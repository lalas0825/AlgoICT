"""
main.py
=======
AlgoICT — master orchestrator.

This is the production entry point. It wires together every module we've built
so far and runs the trading loop end-to-end.

Layered architecture
--------------------
    1. Config + logging          (config.py)
    2. Brokers                   (brokers/topstepx.py)
    3. Data bus                  (db/supabase_client.py)
    4. Heartbeat                 (core/heartbeat.py)
    5. Alerts                    (alerts/telegram_bot.py)
    6. Timeframes + HTF bias     (timeframes/)
    7. ICT detectors             (detectors/)
    8. Risk manager              (risk/risk_manager.py)
    9. Strategies                (strategies/)
   10. Pre-market SWC / GEX      (sentiment/, gamma/)        — optional
   11. Real-time VPIN shield     (toxicity/)                  — optional
   12. Post-mortem               (agents/post_mortem.py)      — optional

Usage
-----
    python main.py --mode paper     # Practice Account (TopstepX paper)
    python main.py --mode live      # Combine — requires y/N confirmation

Graceful degradation
--------------------
Modules that don't exist yet (SWC, GEX, VPIN, post_mortem) are set to None.
The loop skips any None module. The core loop (brokers + ICT + strategies +
risk) is always required.

Error handling
--------------
- Module import failures      -> warning, set module to None, continue
- WS disconnect               -> TopstepX auto-reconnect with backoff
- Heartbeat failure           -> emergency_flatten triggered
- Strategy exception          -> log + continue (don't crash the loop)
- Unhandled exception in loop -> flatten + close + exit
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import logging
import os
import signal
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, time as dt_time
from zoneinfo import ZoneInfo

_CT = ZoneInfo("US/Central")
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

# Ensure engine root is importable
ENGINE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_ROOT))

import config  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_FILE = Path(__file__).resolve().parent / "engine.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),                          # stdout
        logging.FileHandler(_LOG_FILE, encoding="utf-8"), # persistent
    ],
)
logger = logging.getLogger("algoict.main")

# Surface strategy reject reasons at INFO level — otherwise the DEBUG
# logs inside NY AM / Silver Bullet are invisible and we can't tell why
# signals aren't firing (bias neutral? no FVG? no swept level? etc.)
logging.getLogger("strategies.ny_am_reversal").setLevel(logging.DEBUG)
logging.getLogger("strategies.silver_bullet").setLevel(logging.DEBUG)

# Persistence file for "SWC daily mood already sent today" — survives restarts
_SWC_SENT_FILE = Path(__file__).resolve().parent / ".swc_mood_sent.txt"


def _swc_mood_sent_date() -> Optional[str]:
    """Return the ISO date ('YYYY-MM-DD') of the last SWC mood send, or None."""
    try:
        if _SWC_SENT_FILE.exists():
            return _SWC_SENT_FILE.read_text(encoding="utf-8").strip() or None
    except Exception:
        pass
    return None


def _mark_swc_mood_sent(date_str: str) -> None:
    """Persist the ISO date so we don't resend today's mood on restart."""
    try:
        _SWC_SENT_FILE.write_text(date_str, encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not persist SWC-sent marker: %s", exc)


# ---------------------------------------------------------------------------
# Optional module loading — graceful degradation
# ---------------------------------------------------------------------------

def _try_import(path: str, attr: str) -> Any:
    """Import attr from path, return None if import fails."""
    try:
        mod = __import__(path, fromlist=[attr])
        return getattr(mod, attr)
    except Exception as exc:
        logger.warning("Module %s.%s not available: %s", path, attr, exc)
        return None


# Required modules — crash if missing
from brokers.topstepx import TopstepXClient  # noqa: E402
from risk.risk_manager import RiskManager  # noqa: E402
from timeframes.tf_manager import TimeframeManager  # noqa: E402
from timeframes.session_manager import SessionManager  # noqa: E402
from timeframes.htf_bias import HTFBiasDetector  # noqa: E402
from detectors.swing_points import SwingPointDetector  # noqa: E402
from detectors.market_structure import MarketStructureDetector  # noqa: E402
from detectors.fair_value_gap import FairValueGapDetector  # noqa: E402
from detectors.order_block import OrderBlockDetector  # noqa: E402
from detectors.liquidity import LiquidityDetector  # noqa: E402
from detectors.displacement import DisplacementDetector  # noqa: E402
from detectors.confluence import ConfluenceScorer  # noqa: E402
from strategies.ny_am_reversal import NYAMReversalStrategy  # noqa: E402
from strategies.silver_bullet import SilverBulletStrategy  # noqa: E402

# Optional modules — set to None if missing
SupabaseClient = _try_import("db.supabase_client", "SupabaseClient")
TelegramBot = _try_import("alerts.telegram_bot", "TelegramBot")
start_heartbeat = _try_import("core.heartbeat", "start_heartbeat")
BotStateSync = _try_import("core.state_sync", "BotStateSync")

# Intelligence layers — may not exist yet
_SWC_RUN = _try_import("sentiment.swc_engine", "run_premarket_scan")
_GEX_ENGINE = _try_import("gamma.gex_engine", "GEXEngine")
_GEX_SCORE = _try_import("gamma.gex_confluence", "score_gex_alignment")
VPINEngine = _try_import("toxicity.vpin_engine", "VPINEngine")
_VPIN_SCORE = _try_import("toxicity.vpin_confluence", "score")
PostMortemAgent = _try_import("agents.post_mortem", "PostMortemAgent")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLLING_1MIN_BARS = 12000       # Keep ~8 Globex days of 1-min data in memory
                                # Gives headroom above WARMUP_BARS so no trim
                                # happens during a session.
WARMUP_BARS = 10000             # Historical bars to preload before WS starts.
MIN_WARMUP_BARS_FOR_TRADING = 1000   # Hard gate: below this, block trades.
                                     # ~1 full session; less leaves swing /
                                     # structure / FVG detectors too thin
                                     # to produce reliable signals.
                                # 10000 1-min bars ≈ 7 Globex trading days ≈
                                # 1.5 completed weekly bars + 7 daily bars.
                                # Probed API cap is 20000+, so 10000 is safe.
                                # More HTF context → better weekly/daily bias
                                # and stronger swing/FVG/OB detection.
WARMUP_LOOKBACK_DAYS = 21       # Covers 3 weeks to span weekends/holidays
                                # when building the 10000-bar request window.
PREMARKET_HOUR = 6              # 6:00 AM CT — SWC + GEX pre-market scan
VPIN_WARN_THRESHOLD = 0.55      # log warning above this
VPIN_EXTREME_THRESHOLD = 0.70   # flatten everything above this
HARD_CLOSE_HOUR = config.HARD_CLOSE_HOUR
HARD_CLOSE_MIN = config.HARD_CLOSE_MINUTE

# SWC re-scan schedule — 15 min before each Kill Zone opens
SWC_LONDON_HOUR = 0             # 00:45 CT — before London KZ (01:00 CT)
SWC_LONDON_MIN  = 45
SWC_NY_AM_HOUR  = 8             # 08:15 CT — before NY AM KZ (08:30 CT)
SWC_NY_AM_MIN   = 15


# ---------------------------------------------------------------------------
# State container
# ---------------------------------------------------------------------------

@dataclass
class EngineState:
    """Shared mutable state passed into the trading loop."""

    mode: str                           # 'paper' | 'live'
    symbol: str = "MNQ"

    # 1-min rolling bar buffer (DatetimeIndex, OHLCV columns, US/Central)
    bars_1min: pd.DataFrame = None

    # Last aggregated TF timestamps (so we only "update detectors on completion")
    last_completed_tf_ts: dict = None

    # Daily session tracking
    current_session_date: Optional[Any] = None
    premarket_done: bool = False
    hard_close_done: bool = False
    daily_summary_sent: bool = False
    swc_mood_sent_today: bool = False

    # SWC re-scan flags (prevent double-trigger within the same day)
    swc_london_rescan_done: bool = False
    swc_nyam_rescan_done: bool = False

    # Intelligence snapshots
    swc_snapshot: Optional[Any] = None     # DailyMoodReport
    gex_snapshot: Optional[Any] = None     # GEXOverlay
    vpin_status: Optional[Any] = None      # latest VPINStatus

    # Open position tracking — {order_id: {...}}
    open_positions: dict = None

    # Dedup: signal IDs already executed this day — prevents same bar firing twice
    executed_signals: set = None

    # Bar-level dedup: last bar timestamp dispatched to _on_new_bar
    last_dispatched_bar_ts: Optional[Any] = None

    # Cross-bar guard: timestamp of a signal currently being executed
    # Prevents re-fire on the next bar while broker call is in-flight
    pending_signal_ts: Optional[Any] = None

    # Warm-up gate: True once enough historical bars are loaded for every
    # detector to produce non-degraded output. Trades are blocked until
    # this flips. Set in run() after _warmup_historical_bars() returns,
    # validated against MIN_WARMUP_BARS_FOR_TRADING. Prevents the silent-
    # failure path where a broker fetch failure leaves the buffer empty
    # and signals fire on stub/neutral detector state.
    warmup_complete: bool = False

    # True while a reconcile task is in flight. Prevents duplicate
    # spawns when multiple 1-min bars arrive within the same ts.minute%5
    # window (burst / replay after a WS hiccup).
    reconcile_inflight: bool = False

    # Trailing stop Telegram throttle — only alert if delta > threshold
    # OR more than TRAILING_ALERT_MIN_INTERVAL seconds have passed.
    last_trailing_alert_time: Optional[datetime] = None

    def __post_init__(self):
        if self.bars_1min is None:
            self.bars_1min = pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"]
            )
        if self.last_completed_tf_ts is None:
            self.last_completed_tf_ts = {}
        if self.open_positions is None:
            self.open_positions = {}
        if self.executed_signals is None:
            self.executed_signals = set()


# ---------------------------------------------------------------------------
# Component bundle
# ---------------------------------------------------------------------------

@dataclass
class Components:
    """Bag of initialized components. Any field can be None if unavailable."""

    broker: TopstepXClient
    risk: RiskManager
    tf_manager: TimeframeManager
    session: SessionManager
    htf_bias: HTFBiasDetector

    detectors: dict

    ny_am_strategy: NYAMReversalStrategy
    silver_bullet_strategy: SilverBulletStrategy

    supabase: Optional[Any] = None
    telegram: Optional[Any] = None
    vpin: Optional[Any] = None            # VPINEngine
    gex_engine: Optional[Any] = None      # GEXEngine
    post_mortem: Optional[Any] = None     # PostMortemAgent


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def _init_detectors(risk: RiskManager) -> dict:
    """Build the detectors dict required by strategies."""
    structure = MarketStructureDetector()
    swing = SwingPointDetector()
    fvg = FairValueGapDetector()
    ob = OrderBlockDetector()
    liquidity = LiquidityDetector()
    displacement = DisplacementDetector()
    confluence = ConfluenceScorer()

    return {
        "swing": swing,
        "structure": structure,
        "fvg": fvg,
        "ob": ob,
        "liquidity": liquidity,
        "displacement": displacement,
        "confluence": confluence,
        "tracked_levels": [],   # populated by engine as PDH/PDL/equals are swept
    }


def _init_components(
    mode: str,
    topstep_mode: bool = True,
    mll_warning_pct: float = 0.40,
    mll_caution_pct: float = 0.60,
    mll_stop_pct: float = 0.85,
) -> Components:
    """
    Construct every component. Required modules crash on failure; optional
    modules (Supabase, Telegram, VPIN) degrade to None.
    """
    logger.info("Initializing components (mode=%s)...", mode)

    # ── Broker ────────────────────────────────────────────────────────
    broker = TopstepXClient()

    # ── Risk + timeframes ─────────────────────────────────────────────
    risk = RiskManager()
    if topstep_mode:
        risk.enable_topstep_mode(
            warning_pct=mll_warning_pct,
            caution_pct=mll_caution_pct,
            stop_pct=mll_stop_pct,
        )
        logger.info(
            "Topstep MLL protection ON: warn=$%.0f @ %.0f%%, caution=$%.0f @ %.0f%%, stop=$%.0f @ %.0f%%",
            config.TOPSTEP_MLL * mll_warning_pct, mll_warning_pct * 100,
            config.TOPSTEP_MLL * mll_caution_pct, mll_caution_pct * 100,
            config.TOPSTEP_MLL * mll_stop_pct,    mll_stop_pct * 100,
        )
    else:
        logger.warning(
            "Topstep MLL protection DISABLED via --no-topstep — trading with RAW risk rules only"
        )
    tf_manager = TimeframeManager()
    session = SessionManager()
    htf_bias_det = HTFBiasDetector()

    # ── Detectors ─────────────────────────────────────────────────────
    detectors = _init_detectors(risk)

    # ── HTF bias closure (strategies call htf_bias_fn(price)) ─────────
    def _make_htf_bias_fn(tf_mgr: TimeframeManager, state_ref: dict) -> Callable:
        def _fn(price: float):
            bars = state_ref.get("bars_1min")
            if bars is None or len(bars) < 50:
                from timeframes.htf_bias import BiasResult
                return BiasResult(
                    direction="neutral",
                    premium_discount="",
                    htf_levels={},
                    confidence="low",
                    weekly_bias="neutral",
                    daily_bias="neutral",
                )
            try:
                df_daily = tf_mgr.aggregate(bars, "D")
                df_weekly = tf_mgr.aggregate(bars, "W")
                return htf_bias_det.determine_bias(df_daily, df_weekly, price)
            except Exception as exc:
                logger.warning("htf_bias_fn failed: %s", exc)
                from timeframes.htf_bias import BiasResult
                return BiasResult(
                    direction="neutral",
                    premium_discount="",
                    htf_levels={},
                    confidence="low",
                    weekly_bias="neutral",
                    daily_bias="neutral",
                )
        return _fn

    # state_ref is populated later in run(); for now pass an empty dict
    state_ref: dict = {}
    htf_bias_fn = _make_htf_bias_fn(tf_manager, state_ref)

    # ── Strategies ────────────────────────────────────────────────────
    ny_am = NYAMReversalStrategy(
        detectors=detectors,
        risk_manager=risk,
        session_manager=session,
        htf_bias_fn=htf_bias_fn,
    )
    silver_bullet = SilverBulletStrategy(
        detectors=detectors,
        risk_manager=risk,
        session_manager=session,
        htf_bias_fn=htf_bias_fn,
    )

    # ── Optional: Supabase ────────────────────────────────────────────
    supabase = None
    if SupabaseClient is not None:
        try:
            supabase = SupabaseClient()
            logger.info("Supabase client ready")
        except Exception as exc:
            logger.warning("Supabase unavailable: %s", exc)

    # ── Optional: Telegram ────────────────────────────────────────────
    telegram = None
    if TelegramBot is not None:
        try:
            telegram = TelegramBot()
            logger.info("Telegram bot ready")
        except Exception as exc:
            logger.warning("Telegram unavailable: %s", exc)

    # ── Optional: VPIN engine (shield-enabled) ────────────────────────
    vpin = None
    if VPINEngine is not None:
        try:
            vpin = VPINEngine(
                risk_manager=risk,
                telegram_bot=telegram,
                bucket_size=1000,
                num_buckets=50,
            )
            logger.info("VPIN engine ready (shield-enabled)")
        except Exception as exc:
            logger.warning("VPIN unavailable: %s", exc)

    # ── Optional: GEX engine ──────────────────────────────────────────
    gex_engine = None
    if _GEX_ENGINE is not None:
        try:
            gex_engine = _GEX_ENGINE()  # options_loader=None → skips gracefully
            logger.info("GEX engine ready (options_loader=None, will skip if no data)")
        except Exception as exc:
            logger.warning("GEX unavailable: %s", exc)

    # ── Optional: Post-Mortem agent ───────────────────────────────────
    post_mortem = None
    if PostMortemAgent is not None:
        try:
            post_mortem = PostMortemAgent(
                supabase_client=supabase,
                telegram_bot=telegram,
            )
            logger.info("PostMortemAgent ready")
        except Exception as exc:
            logger.warning("PostMortemAgent unavailable: %s", exc)

    components = Components(
        broker=broker,
        risk=risk,
        tf_manager=tf_manager,
        session=session,
        htf_bias=htf_bias_det,
        detectors=detectors,
        ny_am_strategy=ny_am,
        silver_bullet_strategy=silver_bullet,
        supabase=supabase,
        telegram=telegram,
        vpin=vpin,
        gex_engine=gex_engine,
        post_mortem=post_mortem,
    )

    # Stash the state_ref on components so run() can wire it up
    components._state_ref = state_ref  # type: ignore[attr-defined]
    return components


# ---------------------------------------------------------------------------
# Pre-market scan
# ---------------------------------------------------------------------------

async def _run_premarket_scan(components: Components, state: EngineState) -> None:
    """
    Run SWC and GEX scans at 06:00 CT. Apply results to RiskManager,
    broadcast briefings to Telegram.

    Both modules are optional and independently fail-safe:
      - If SWC fails → log warning, keep default min_confluence
      - If GEX has no options data → skip cleanly, 0 bonus confluence
    """
    logger.info("=" * 60)
    logger.info("  PRE-MARKET SCAN (%s)", datetime.now().strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 60)

    # ── SWC (sentiment) ───────────────────────────────────────────────
    if _SWC_RUN is not None:
        try:
            report = await _maybe_await(_SWC_RUN())
            state.swc_snapshot = report

            # DailyMoodReport has min_confluence_override + position_size_multiplier
            min_conf = int(getattr(report, "min_confluence_override",
                                   config.MIN_CONFLUENCE))
            pos_mult = float(getattr(report, "position_size_multiplier", 1.0))
            min_conf_adj = max(0, min_conf - config.MIN_CONFLUENCE)
            components.risk.set_swc_overrides(min_conf_adj, pos_mult)

            summary = getattr(report, "one_line_summary", "mood report generated")
            logger.info(
                "SWC applied: min_conf=%d (+%d) pos_mult=%.2f — %s",
                min_conf, min_conf_adj, pos_mult, summary,
            )

            # Send SWC mood ONCE per trading day (survives restarts via marker file)
            today_iso = datetime.now(_CT).strftime("%Y-%m-%d")
            if state.swc_mood_sent_today or _swc_mood_sent_date() == today_iso:
                state.swc_mood_sent_today = True
                logger.info("SWC mood already sent today (%s) — skipping", today_iso)
            elif components.telegram is not None:
                try:
                    mood_label = str(getattr(report, "mood", "Unknown")).title()
                    await components.telegram.send_daily_mood(
                        date_str=today_iso,
                        mood=mood_label,
                        min_confluence=min_conf,
                        position_size_pct=pos_mult,
                        summary=summary,
                    )
                    state.swc_mood_sent_today = True
                    _mark_swc_mood_sent(today_iso)
                except Exception as tx_exc:
                    logger.debug("SWC Telegram briefing failed: %s", tx_exc)
        except Exception as exc:
            logger.warning("SWC pre-market scan failed: %s — using defaults", exc)
    else:
        logger.info("SWC module not available — skipping sentiment scan")

    # ── GEX (gamma) ───────────────────────────────────────────────────
    if components.gex_engine is not None:
        try:
            # Derive spot from the last 1-min bar if we already have warm-up data
            spot = None
            if not state.bars_1min.empty:
                spot = float(state.bars_1min["close"].iloc[-1])
            overlay = components.gex_engine.run_premarket_scan(spot_price=spot)
            state.gex_snapshot = overlay

            if getattr(overlay, "is_valid", False):
                logger.info(
                    "GEX: regime=%s call_wall=%.0f put_wall=%.0f flip=%.0f",
                    overlay.regime, overlay.call_wall,
                    overlay.put_wall, overlay.gamma_flip,
                )
                if components.telegram is not None:
                    try:
                        msg = (
                            f"GEX Pre-Market\n"
                            f"Regime    : {overlay.regime}\n"
                            f"Call wall : {overlay.call_wall:.0f}\n"
                            f"Put wall  : {overlay.put_wall:.0f}\n"
                            f"Gamma flip: {overlay.gamma_flip:.0f}"
                        )
                        await components.telegram.send_emergency_alert(msg)
                    except Exception as tx_exc:
                        logger.debug("GEX Telegram briefing failed: %s", tx_exc)
            else:
                logger.info("GEX: no options data, skipping (0 bonus confluence)")
        except Exception as exc:
            logger.warning("GEX pre-market scan failed: %s — skipping", exc)
    else:
        logger.info("GEX module not available — skipping gamma scan")

    # ── Seed tracked_levels with PDH/PDL/PWH/PWL ──────────────────────
    # The NY AM strategy needs swept liquidity levels to fire — without
    # this seed, `tracked_levels` stays [] forever and every kill-zone
    # evaluation rejects on "no aligned liquidity sweep".
    try:
        if not state.bars_1min.empty:
            tf_mgr = components.tf_manager
            df_daily = tf_mgr.aggregate(state.bars_1min, "D")
            df_weekly = tf_mgr.aggregate(state.bars_1min, "W")
            levels = components.detectors["liquidity"].build_key_levels(
                df_daily=df_daily, df_weekly=df_weekly,
            )
            components.detectors["tracked_levels"] = levels
            logger.info(
                "tracked_levels seeded: %d levels (%s)",
                len(levels),
                ", ".join(f"{lvl.type}@{lvl.price:.2f}" for lvl in levels),
            )
        else:
            logger.warning("tracked_levels: no bars yet, skipping seed")
    except Exception as exc:
        logger.warning("tracked_levels seed failed: %s", exc)

    # Heartbeat alert at end of scan
    if components.telegram is not None:
        try:
            await components.telegram.send_heartbeat_alert("OK")
        except Exception:
            pass

    state.premarket_done = True


async def _run_swc_rescan(
    components: "Components",
    state: "EngineState",
    time_str: str,
) -> None:
    """
    Re-run SWC scan before a Kill Zone opens.

    Calls run_premarket_scan() (same function as the boot scan), updates
    state.swc_snapshot and RiskManager overrides, then logs and optionally
    alerts Telegram depending on whether the mood changed.

    On API failure: logs ERROR and retains the previous snapshot unchanged.

    Parameters
    ----------
    time_str : "00:45" | "08:15"  — used in log messages.
    """
    if _SWC_RUN is None:
        return

    old_mood = getattr(state.swc_snapshot, "market_mood", None)
    old_mood_val = getattr(old_mood, "value", str(old_mood)) if old_mood else None

    try:
        report = await _maybe_await(_SWC_RUN())

        if report is None:
            logger.warning("SWC re-scan [%s CT] returned None — skipping", time_str)
            return

        # DailyMoodReport dataclass
        new_mood_val = getattr(report.market_mood, "value", str(report.market_mood))
        min_conf = int(getattr(report, "min_confluence_override", config.MIN_CONFLUENCE))
        pos_mult = float(getattr(report, "position_size_multiplier", 1.0))
        min_conf_adj = max(0, min_conf - config.MIN_CONFLUENCE)

        components.risk.set_swc_overrides(min_conf_adj, pos_mult)
        state.swc_snapshot = report

        if old_mood_val is not None and new_mood_val != old_mood_val:
            logger.info(
                "SWC re-scan [%s CT]: mood changed %s -> %s (min_conf=%d, pos_mult=%.2f)",
                time_str, old_mood_val, new_mood_val, min_conf, pos_mult,
            )
            if components.telegram is not None:
                try:
                    await components.telegram.send_daily_mood(
                        date_str=datetime.now(_CT).strftime("%Y-%m-%d"),
                        mood=new_mood_val.title(),
                        min_confluence=min_conf,
                        position_size_pct=pos_mult,
                        summary=f"Re-scan at {time_str} CT: mood changed from {old_mood_val}",
                    )
                except Exception as exc:
                    logger.error("Failed to send SWC rescan Telegram alert: %s", exc)
        else:
            logger.info("SWC re-scan [%s CT]: mood unchanged (%s)", time_str, new_mood_val)

    except Exception as exc:
        logger.error(
            "SWC re-scan [%s CT] failed: %s — keeping previous mood", time_str, exc
        )


async def _maybe_await(result):
    """Helper: await the result if it's a coroutine, else return it."""
    if asyncio.iscoroutine(result):
        return await result
    return result


# ---------------------------------------------------------------------------
# Warm-up: preload historical bars so detectors have context on WS tick #1
# ---------------------------------------------------------------------------

async def _warmup_historical_bars(
    components: "Components",
    state: "EngineState",
    bars_wanted: int = WARMUP_BARS,
    lookback_days: int = WARMUP_LOOKBACK_DAYS,
) -> int:
    """
    Fetch recent 1-min bars from the broker and seed the rolling buffer.

    Without this the first N WebSocket bars arrive into an empty detector
    state — no swing points, no FVGs, no structure — and the bot is blind
    until enough bars accumulate. Pre-loading the last session gives the
    detectors real context before live trading begins.

    Returns the number of bars seeded (0 on any failure — warm-up is
    best-effort and must not block start-up).
    """
    broker = components.broker
    if not hasattr(broker, "get_historical_bars") or not hasattr(broker, "lookup_contract"):
        logger.warning("Broker does not support historical bars — skipping warm-up")
        return 0

    try:
        contract = await broker.lookup_contract(state.symbol, live=False)
        if contract is None:
            logger.warning("Warm-up: contract %s not found", state.symbol)
            return 0

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        bars = await broker.get_historical_bars(
            contract_id=contract["id"],
            start=start,
            end=end,
            unit=2,
            unit_number=1,
            limit=bars_wanted,
        )
    except Exception as exc:
        logger.warning("Warm-up fetch failed: %s", exc)
        return 0

    if not bars:
        logger.warning("Warm-up: 0 bars returned")
        return 0

    # Keep only the tail we actually want
    if len(bars) > bars_wanted:
        bars = bars[-bars_wanted:]

    # Seed the rolling buffer using the same append path the WS callback
    # uses, so timezone conversion + schema stays consistent.
    for bar in bars:
        _append_bar(state, bar)

    # Update strategy's HTF state cache so that `run()` sees the history
    components._state_ref["bars_1min"] = state.bars_1min  # type: ignore[attr-defined]

    # Run detector update once so swing/structure/FVG/OB are primed
    try:
        _update_detectors(components, state)
    except Exception as exc:
        logger.warning("Warm-up detector priming failed: %s", exc)

    logger.info(
        "Warm-up complete: %d bars seeded (%s -> %s)",
        len(state.bars_1min),
        state.bars_1min.index[0],
        state.bars_1min.index[-1],
    )

    # Backfill market_data so the dashboard chart has history immediately.
    # Runs off the event loop to avoid stalling _on_new_bar / main loop for
    # the duration of the backfill. Uses batch upsert (1000 rows per
    # request) — ~10s for 10 000 bars vs ~15 min serially.
    if components.supabase is not None:
        df = state.bars_1min
        payload = [
            {
                "symbol": state.symbol,
                "timeframe": "1m",
                "timestamp": ts_idx.isoformat(),
                "open": float(df.loc[ts_idx, "open"]),
                "high": float(df.loc[ts_idx, "high"]),
                "low": float(df.loc[ts_idx, "low"]),
                "close": float(df.loc[ts_idx, "close"]),
                "volume": int(df.loc[ts_idx, "volume"]),
                "vpin_level": None,
            }
            for ts_idx in df.index
        ]

        async def _backfill():
            written = await asyncio.to_thread(
                components.supabase.write_market_data_batch, payload,
            )
            logger.info("Warm-up: %d/%d bars written to market_data", written, len(payload))

        asyncio.create_task(_backfill())

    return len(state.bars_1min)


# ---------------------------------------------------------------------------
# Bar handling + detector updates
# ---------------------------------------------------------------------------

def _append_bar(state: EngineState, bar: dict) -> None:
    """Append a 1-min bar to the rolling buffer (trim to ROLLING_1MIN_BARS)."""
    ts = bar["timestamp"]
    if not isinstance(ts, pd.Timestamp):
        ts = pd.Timestamp(ts)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    ts_ct = ts.tz_convert("US/Central")

    row = pd.DataFrame(
        [{
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
        }],
        index=pd.DatetimeIndex([ts_ct], name="timestamp"),
    )

    state.bars_1min = pd.concat([state.bars_1min, row])
    # Drop duplicates (in case WS replays) and trim
    state.bars_1min = state.bars_1min[~state.bars_1min.index.duplicated(keep="last")]
    if len(state.bars_1min) > ROLLING_1MIN_BARS:
        state.bars_1min = state.bars_1min.iloc[-ROLLING_1MIN_BARS:]


def _update_detectors(
    components: Components,
    state: EngineState,
) -> dict:
    """
    Re-aggregate timeframes and run detector updates on completed TFs only.

    Returns a dict of which TFs were updated this tick.
    """
    tf_mgr = components.tf_manager
    tf_mgr.clear_cache()  # invalidate cache because we appended a new bar
    bars = state.bars_1min

    updated: dict = {}
    if len(bars) < 20:
        return updated   # warm-up period

    try:
        df_5min = tf_mgr.aggregate(bars, "5min")
        df_15min = tf_mgr.aggregate(bars, "15min")
    except Exception as exc:
        logger.debug("TF aggregation failed: %s", exc)
        return updated

    # ── Only re-run detectors if the last bar of a TF is new ──────────
    last_5_ts = df_5min.index[-1] if not df_5min.empty else None
    last_15_ts = df_15min.index[-1] if not df_15min.empty else None

    if last_5_ts is not None and last_5_ts != state.last_completed_tf_ts.get("5min"):
        try:
            components.detectors["swing"].detect(df_5min, "5min")
            components.detectors["fvg"].detect(df_5min, "5min")
            components.detectors["ob"].detect(df_5min, "5min")
            components.detectors["displacement"].detect(df_5min, timeframe="5min")
            # Compute candle body + ATR for IFVG displacement gate
            last_5 = df_5min.iloc[-1]
            _close_5 = float(last_5["close"])
            _body_5 = abs(float(last_5["close"]) - float(last_5["open"]))
            _atr_5 = None
            if len(df_5min) >= 15:
                import numpy as np
                _highs = df_5min["high"].values[-14:]
                _lows = df_5min["low"].values[-14:]
                _closes = df_5min["close"].values[-15:-1]
                _tr = np.maximum(
                    _highs - _lows,
                    np.maximum(
                        np.abs(_highs - _closes),
                        np.abs(_lows - _closes),
                    ),
                )
                _atr_5 = float(_tr.mean())
            components.detectors["fvg"].update_mitigation(
                _close_5, candle_body=_body_5, atr_14=_atr_5,
            )
            components.detectors["ob"].update_mitigation(df_5min)

            # ── Liquidity: check sweeps on the just-closed 5min candle ──
            # `tracked_levels` is seeded in _run_premarket_scan with PDH/PDL/PWH/PWL.
            # Without this call, the NY AM strategy never sees a swept level
            # and rejects every bar silently — the cause of 0 signals for 2 days.
            tracked = components.detectors.get("tracked_levels", [])
            if tracked:
                newly_swept = components.detectors["liquidity"].check_sweep(
                    df_5min.iloc[-1], tracked,
                )
                if newly_swept:
                    logger.info(
                        "LIQUIDITY SWEEP on 5min [%s]: %s",
                        last_5_ts,
                        ", ".join(f"{lvl.type}@{lvl.price:.2f}" for lvl in newly_swept),
                    )
        except Exception as exc:
            logger.warning("5min detector update failed: %s", exc)
        state.last_completed_tf_ts["5min"] = last_5_ts
        updated["5min"] = True

    if last_15_ts is not None and last_15_ts != state.last_completed_tf_ts.get("15min"):
        try:
            # Prime swings on 15min before feeding them to the structure
            # detector — MarketStructureDetector.update() walks the swing
            # point list to confirm BOS/CHoCH against the context TF.
            swing = components.detectors["swing"]
            swing.detect(df_15min, "15min")
            components.detectors["structure"].update(df_15min, swing, "15min")
        except Exception as exc:
            logger.warning("15min structure update failed: %s", exc)
        state.last_completed_tf_ts["15min"] = last_15_ts
        updated["15min"] = True

    return updated


def _log_bar_snapshot(components: Components, state: EngineState, ts) -> None:
    """
    Emit one INFO line per 1-min bar with the full detector/strategy context.

    Without this, the log shows only WS bars + heartbeat and we can't tell
    if detectors ran, if tracked_levels is populated, or why signals never fire.
    """
    try:
        bars = state.bars_1min
        close = float(bars.iloc[-1]["close"]) if len(bars) else 0.0

        # Session context
        in_rth = 8 <= ts.hour < 15 or (ts.hour == 8 and ts.minute >= 30)
        sess = components.session
        kz = "none"
        for zone in ("london", "london_silver_bullet", "ny_am", "silver_bullet", "ny_pm"):
            if sess.is_kill_zone(ts, zone):
                kz = zone
                break

        # Detector counts (safe best-effort getters)
        det = components.detectors
        all_swings = getattr(det["swing"], "swing_points", [])
        sw_count = sum(1 for sp in all_swings if getattr(sp, "timeframe", "") == "5min")
        fvg_active = det["fvg"].get_active(timeframe="5min")
        fvg_count = len(fvg_active)
        ifvg_count = len(det["fvg"].get_active_ifvgs(timeframe="5min"))
        ob_count = len(det["ob"].get_active(timeframe="5min"))
        struct_events = det["structure"].get_events(timeframe="15min")
        struct_count = len(struct_events)
        tracked = det.get("tracked_levels", [])
        liq_total = len(tracked)
        liq_swept = sum(1 for lvl in tracked if getattr(lvl, "swept", False))

        # ── FVG top-3 (all tf + directions, closest midpoint) ─────────────
        all_fvgs = det["fvg"].get_active()
        all_fvgs.sort(key=lambda f: abs((f.top + f.bottom) / 2 - close))
        fvg_top3_str = ", ".join(
            f"{f.bottom:.0f}-{f.top:.0f} {f.direction[:4]} {f.timeframe} "
            f"{((f.top + f.bottom) / 2 - close):+.0f}pts"
            for f in all_fvgs[:3]
        ) or "none"

        # ── IFVG top-3 ────────────────────────────────────────────────────
        all_ifvgs = det["fvg"].get_active_ifvgs()
        all_ifvgs.sort(key=lambda f: abs((f.top + f.bottom) / 2 - close))
        ifvg_top3_str = ", ".join(
            f"{f.bottom:.0f}-{f.top:.0f} {f.direction[:4]} {f.timeframe} "
            f"{((f.top + f.bottom) / 2 - close):+.0f}pts"
            for f in all_ifvgs[:3]
        ) or "none"

        # ── OB top-3 (closest midpoint high+low / 2) ──────────────────────
        all_obs = det["ob"].get_active()
        all_obs.sort(key=lambda o: abs((o.high + o.low) / 2 - close))
        ob_top3_str = ", ".join(
            f"{o.low:.0f}-{o.high:.0f} {o.direction[:4]} {o.timeframe} "
            f"{((o.high + o.low) / 2 - close):+.0f}pts"
            for o in all_obs[:3]
        ) or "none"

        # ── Tracked levels with swept state ───────────────────────────────
        levels_str = ", ".join(
            f"{lvl.type}@{lvl.price:.0f} {'SWEPT' if getattr(lvl, 'swept', False) else 'active'}"
            for lvl in tracked
        ) or "none"

        # ── Equal highs / equal lows from tracked_levels ──────────────────
        eql_prices = [lvl.price for lvl in tracked if getattr(lvl, "type", "") == "equal_lows"]
        eqh_prices = [lvl.price for lvl in tracked if getattr(lvl, "type", "") == "equal_highs"]
        eql_str = "[" + ", ".join(f"{p:.0f}" for p in eql_prices) + "]"
        eqh_str = "[" + ", ".join(f"{p:.0f}" for p in eqh_prices) + "]"

        # ── Structure: last 3 events (all tf) ─────────────────────────────
        all_struct = det["structure"].get_events()
        all_struct_sorted = sorted(all_struct, key=lambda e: e.timestamp)[-3:]
        struct_last3_str = ", ".join(
            f"{e.type} {e.direction[:4]} {e.timestamp.strftime('%H:%M')}CT"
            for e in all_struct_sorted
        ) or "none"

        # ── Last displacement (5min, any direction) ────────────────────────
        recent_disps = det["displacement"].get_recent(n=1, timeframe="5min")
        if recent_disps:
            d = recent_disps[0]
            disp_str = (
                f"{d.direction[:4]} mag={d.magnitude:.0f}pts "
                f"{d.timestamp.strftime('%H:%M')}CT"
            )
        else:
            disp_str = "none"

        vpin_val = getattr(state.vpin_status, "vpin", None) if state.vpin_status else None
        vpin_str = f"{vpin_val:.3f}" if vpin_val is not None else "—"

        # HTF bias (swing-based). Cheap to recompute per bar — ~7 daily + 2-3
        # weekly bars only. Lets us see live bias evolution in the log.
        bias_str = "n/a"
        fvg_5m_dir = 0
        try:
            tf_mgr = components.tf_manager
            df_daily = tf_mgr.aggregate(bars, "D")
            df_weekly = tf_mgr.aggregate(bars, "W")
            bias = components.htf_bias.determine_bias(df_daily, df_weekly, close)
            bias_str = (
                f"{bias.direction}({bias.premium_discount}) "
                f"d={bias.daily_bias} w={bias.weekly_bias}"
            )
            bias_dir = bias.direction  # 'bullish' | 'bearish'
            fvg_5m_dir = len(det["fvg"].get_active(timeframe="5min", direction=bias_dir))
        except Exception as bexc:
            logger.debug("bar-snapshot bias compute failed: %s", bexc)

        ts_str = ts.strftime("%H:%M")
        rth_str = "Y" if in_rth else "N"
        logger.info(
            "BAR [%s CT] close=%.2f rth=%s kz=%s | sw=%d fvg=%d(5m_dir=%d) ifvg=%d ob=%d struct=%d liq=%d(swept=%d) | VPIN=%s | bias=%s",
            ts_str, close, rth_str, kz,
            sw_count, fvg_count, fvg_5m_dir, ifvg_count, ob_count, struct_count, liq_total, liq_swept,
            vpin_str, bias_str,
        )
        logger.info(
            "  fvg_top3=[%s] | ifvg_top3=[%s]",
            fvg_top3_str, ifvg_top3_str,
        )
        logger.info(
            "  ob_top3=[%s]",
            ob_top3_str,
        )
        logger.info(
            "  levels=[%s] | eql=%s eqh=%s",
            levels_str, eql_str, eqh_str,
        )
        logger.info(
            "  struct_last3=[%s] | last_disp=%s",
            struct_last3_str, disp_str,
        )
    except Exception as exc:
        logger.debug("bar-snapshot log failed: %s", exc)


# ---------------------------------------------------------------------------
# Signal execution
# ---------------------------------------------------------------------------

def _snap(price: float, tick: float = config.MNQ_TICK_SIZE) -> float:
    """Round price to the nearest tick increment (e.g. 0.25 for MNQ).

    TopstepX rejects limit/stop orders whose price is not an exact multiple
    of the contract tick size (errorCode=2). All prices sent to the broker
    must pass through this before submission.
    """
    return round(round(price / tick) * tick, 10)


async def _execute_signal(
    signal,
    components: Components,
    state: EngineState,
) -> None:
    """Submit entry + stop + target orders, log, and alert."""
    # Warm-up gate: block trade submission until enough bars have loaded
    # for detectors to produce non-degraded output. Prevents the silent-
    # failure path where _warmup_historical_bars() returned 0 (broker
    # fetch failure) and early WS ticks drove trades on cold state.
    if not state.warmup_complete:
        buffer_len = len(state.bars_1min)
        if buffer_len >= MIN_WARMUP_BARS_FOR_TRADING:
            state.warmup_complete = True
            logger.info(
                "Warm-up gate lifted via WS buffer: %d bars accumulated",
                buffer_len,
            )
        else:
            logger.info(
                "Signal %s %s blocked — warm-up incomplete (%d/%d bars)",
                signal.strategy, signal.direction,
                buffer_len, MIN_WARMUP_BARS_FOR_TRADING,
            )
            return

    # signal_id must be stable across duplicate deliveries of the SAME
    # setup but unique across distinct setups. Previously it was just
    # `{strategy}_{direction}_{timestamp}` — two distinct setups at the
    # same bar/strategy/direction (e.g., two separate OBs both qualifying
    # on the same 5-min bar) would collide and the second would silently
    # be blocked as a "duplicate". Entry price is the natural per-setup
    # differentiator (stop/target derive from it). Rounded to 2 dp so
    # float noise between re-deliveries doesn't create phantom IDs.
    signal_id = (
        f"{signal.strategy}_{signal.direction}_{signal.timestamp}_"
        f"{float(signal.entry_price):.2f}"
    )
    if signal_id in state.executed_signals:
        logger.info("Signal %s already executed this bar — skipping duplicate", signal_id)
        return
    state.executed_signals.add(signal_id)

    logger.info("EXECUTING signal: %s", signal)

    broker = components.broker
    side = "buy" if signal.direction == "long" else "sell"
    exit_side = "sell" if side == "buy" else "buy"

    # Use a limit order at the OB proximal edge (signal.entry_price) so the
    # fill occurs at the ICT-intended level, not wherever the market happens
    # to be at order submission. The proximity gate in the strategy already
    # ensures price is within OB_PROXIMITY_TOLERANCE pts of this level, so
    # the limit will fill immediately or on the first tick back to the OB.
    # reference_price guards against pre-submission deviation > 2%.
    _ref_close = (
        float(state.bars_1min["close"].iloc[-1])
        if not state.bars_1min.empty else None
    )
    try:
        entry_order = await broker.submit_limit_order(
            symbol=signal.symbol,
            side=side,
            contracts=signal.contracts,
            limit_price=_snap(float(signal.entry_price)),
            reference_price=_ref_close,
        )
    except Exception as exc:
        logger.error("Entry order failed: %s", exc)
        return

    # Guard against broker-level rejection / non-fill. `_submit_order` in
    # brokers/topstepx.py can return OrderResult(status="rejected") WITHOUT
    # raising when the API replies success=False (audit finding, 2026-04-17).
    # The previous code path then happily submitted stop + target for a
    # position that never opened AND advanced the per-zone counter via
    # notify_trade_executed — consuming the KZ budget for zero real trades.
    #
    # Treat anything that isn't an active fill as a hard failure: abort the
    # signal, do NOT submit stop/target, do NOT advance counters. The
    # executed_signals guard above already blocks a retry on the same bar.
    # Resolve strategy instance up front — needed for both the reject-path
    # rollback and the happy-path notify_trade_executed below.
    strat_name = getattr(signal, "strategy", "")
    strat = None
    if strat_name == "ny_am_reversal":
        strat = getattr(components, "ny_am_strategy", None)
    elif strat_name == "silver_bullet":
        strat = getattr(components, "silver_bullet_strategy", None)

    entry_status = (entry_order.status or "").lower() if entry_order else ""
    fill_confirmed = entry_status in ("filled", "submitted", "working")
    if not entry_order or not fill_confirmed:
        logger.warning(
            "Entry order NOT confirmed (status=%s message=%r) — aborting "
            "stop/target submission and rolling back zone counter reservation",
            entry_status or "<none>", getattr(entry_order, "message", ""),
        )
        # Release the executed_signals slot so a later bar with the same
        # signal_id can retry cleanly. Also clear the strategy's
        # _last_evaluated_bar_ts so evaluate() doesn't short-circuit on
        # the next delivery of THIS same bar (meta-audit: without this,
        # executed_signals rollback was a no-op because Layer-1 dedup in
        # strategy.evaluate() still blocked the bar).
        state.executed_signals.discard(signal_id)
        if strat is not None and hasattr(strat, "rollback_last_evaluated_bar"):
            try:
                strat.rollback_last_evaluated_bar(signal.timestamp)
            except Exception as exc:
                logger.debug("rollback_last_evaluated_bar failed: %s", exc)
        return

    # Entry is either already filled or working (market order pending fill).
    # NOTE: "submitted"/"working" is not yet a confirmed fill — we advance
    # counters optimistically because TopstepX fills market orders within
    # milliseconds and the alternative (waiting for a fill callback) would
    # block the bar-tick path. If the market order somehow rejects AFTER
    # submission (rare), the position-reconciliation pass should surface
    # the discrepancy. (Follow-up: wire a fill-confirmation callback.)
    if strat is not None and hasattr(strat, "notify_trade_executed"):
        try:
            strat.notify_trade_executed(signal)
        except Exception as exc:
            logger.warning("notify_trade_executed failed: %s", exc)

    try:
        stop_order = await broker.submit_stop_order(
            symbol=signal.symbol,
            side=exit_side,
            contracts=signal.contracts,
            stop_price=_snap(signal.stop_price),
        )
    except Exception as exc:
        logger.error("Stop order failed: %s", exc)
        stop_order = None

    # Resolve effective fill price: prefer broker-reported fill, fall back to
    # latest bar close.  Market orders are async — the broker returns status=
    # submitted before the fill lands, so filled_price is usually None here.
    # Using the latest close is an acceptable proxy for the spread correction.
    effective_fill = entry_order.filled_price
    if effective_fill is None and not state.bars_1min.empty:
        effective_fill = float(state.bars_1min["close"].iloc[-1])

    # Recalculate target if it would be invalid at the current price.
    # For longs  a Limit SELL must be ABOVE the market → target > effective_fill.
    # For shorts a Limit BUY  must be BELOW the market → target < effective_fill.
    target_pts = signal.target_price - signal.entry_price   # signed offset
    adjusted_target = signal.target_price
    if effective_fill is not None:
        candidate = effective_fill + target_pts
        is_invalid = (
            (signal.direction == "long"  and signal.target_price <= effective_fill) or
            (signal.direction == "short" and signal.target_price >= effective_fill)
        )
        if is_invalid:
            adjusted_target = candidate
            logger.warning(
                "Target price %.2f invalid vs fill %.2f — adjusted to %.2f (%.1f pts offset preserved)",
                signal.target_price, effective_fill, adjusted_target, target_pts,
            )

    try:
        # Pass reference_price so the broker client rejects any target that
        # would fall outside the allowed deviation band BEFORE a round-trip
        # to TopstepX (which would silently reject with errorCode=2
        # "Invalid price outside allowed range" as it did 6× on 2026-04-17).
        target_order = await broker.submit_limit_order(
            symbol=signal.symbol,
            side=exit_side,
            contracts=signal.contracts,
            limit_price=_snap(adjusted_target),
            reference_price=effective_fill,
        )
    except Exception as exc:
        logger.error("Target order failed: %s", exc)
        target_order = None

    # Track the position
    state.open_positions[entry_order.order_id] = {
        "signal": signal,
        "entry_order": entry_order,
        "stop_order": stop_order,
        "target_order": target_order,
        "opened_at": datetime.now(timezone.utc),
        "current_stop_price": float(signal.stop_price),
    }

    # Log to Supabase. Only fields KNOWN to exist in the `signals` table
    # schema are sent. Previously the code spread **signal.confluence_breakdown
    # which blew up the whole insert whenever the scorer added a new key
    # (e.g. htf_bias_aligned) without a matching DB migration — PGRST204
    # swallowed the trade log. Breakdown is kept out of DB until a JSONB
    # migration lands; the raw score is still persisted.
    if components.supabase is not None:
        try:
            components.supabase.write_signal({
                "timestamp": str(signal.timestamp),
                "symbol": signal.symbol,
                "signal_type": signal.direction,
                "price": signal.entry_price,
                "confluence_score": signal.confluence_score,
            })
        except Exception as exc:
            logger.warning("Supabase signal write failed: %s", exc)

    # Telegram — rich signal fired alert
    if components.telegram is not None:
        try:
            vs = state.vpin_status
            vpin_val  = getattr(vs, "vpin",  None) if vs else None
            vpin_zone = getattr(vs, "label", "unknown") if vs else "unknown"
            swc_mood  = getattr(state.swc_snapshot, "mood", None) if state.swc_snapshot else None
            gex_ok    = state.gex_snapshot is not None
            gex_status = "active" if gex_ok else "no data"
            size_pct  = getattr(components.risk, "position_multiplier", 1.0)

            # HTF bias — recompute from latest bars (same as _log_bar_snapshot)
            htf_daily = htf_weekly = "n/a"
            try:
                bars = state.bars_1min
                if not bars.empty:
                    tf_mgr = components.tf_manager
                    df_d = tf_mgr.aggregate(bars, "D")
                    df_w = tf_mgr.aggregate(bars, "W")
                    bias = components.htf_bias.determine_bias(df_d, df_w, signal.entry_price)
                    htf_daily  = getattr(bias, "daily_bias",  "n/a")
                    htf_weekly = getattr(bias, "weekly_bias", "n/a")
            except Exception:
                pass

            await components.telegram.send_signal_fired(
                signal=signal,
                vpin_value=vpin_val,
                vpin_zone=vpin_zone,
                swc_mood=swc_mood,
                gex_status=gex_status,
                htf_daily=htf_daily,
                htf_weekly=htf_weekly,
                size_pct=size_pct,
            )
        except Exception as exc:
            logger.warning("Telegram signal fired alert failed: %s", exc)

    # Telegram — trade opened (fill confirmation)
    if components.telegram is not None:
        try:
            fill = entry_order.filled_price or signal.entry_price
            await components.telegram.send_trade_opened(
                symbol=signal.symbol,
                direction=signal.direction,
                contracts=signal.contracts,
                fill_price=fill,
            )
        except Exception as exc:
            logger.warning("Telegram trade opened alert failed: %s", exc)


# ---------------------------------------------------------------------------
# Trading loop — called on every new 1-min bar
# ---------------------------------------------------------------------------

async def _update_vpin(
    components: Components,
    state: EngineState,
    bar: dict,
) -> None:
    """
    Feed the freshly-arrived bar into the VPIN engine. If the shield
    returns an action with should_flatten (VPIN > 0.70) we stop all
    trading and alert Telegram. Warning threshold (> 0.55) is logged.
    """
    if components.vpin is None:
        return

    try:
        # Build a pandas Series matching what VPINEngine expects
        ts = bar.get("timestamp")
        if ts is None and not state.bars_1min.empty:
            ts = state.bars_1min.index[-1]
        bar_series = pd.Series(
            {
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
            },
            name=ts,
        )
        # ── Read halt state BEFORE on_new_bar so we can detect both transitions ──
        # check_deactivate() runs inside on_new_bar (sync). If VPIN normalises
        # this bar, shield.is_halted flips False inside that call. We need the
        # pre-bar snapshot to identify True → False after the call.
        was_halted = components.vpin._shield.is_halted  # type: ignore[attr-defined]

        components.vpin.on_new_bar(bar_series)
        status = components.vpin.get_status()
        state.vpin_status = status

        if status.vpin is not None:
            is_halted_now = components.vpin._shield.is_halted  # type: ignore[attr-defined]

            # ── True → False: VPIN just normalised this bar ────────────────
            if was_halted and not is_halted_now:
                logger.critical(
                    "VPIN NORMALIZED: %.3f — trading resumed", status.vpin,
                )
                tg = getattr(components, "telegram", None)
                if tg is not None:
                    try:
                        await tg.send_vpin_alert(
                            vpin=status.vpin,
                            toxicity_level="normalized",
                        )
                    except Exception as tg_exc:
                        logger.error("Failed to send VPIN normalized alert: %s", tg_exc)

            # ── False → True: VPIN just went extreme this bar ──────────────
            elif status.vpin >= VPIN_EXTREME_THRESHOLD:
                if not was_halted:
                    # Fire once — execute_flatten sends Telegram + activates halt
                    logger.critical(
                        "VPIN EXTREME: %.3f — flattening all positions", status.vpin,
                    )
                    try:
                        await components.vpin._shield.execute_flatten(  # type: ignore[attr-defined]
                            reason=f"VPIN extreme {status.vpin:.3f}"
                        )
                    except Exception as flat_exc:
                        logger.error("Shield flatten failed: %s", flat_exc)
                    # Flatten open broker positions once on activation.
                    await _flatten_all(components, state, reason="vpin_extreme", emergency=False)
                # else: already halted — shield is holding; no repeated alert/flatten

            elif status.vpin >= VPIN_WARN_THRESHOLD:
                logger.warning(
                    "VPIN HIGH: %.3f (%s)", status.vpin, status.label,
                )
    except Exception as exc:
        logger.debug("VPIN update failed: %s", exc)


def _update_edge_state(components: Components, state: EngineState) -> None:
    """
    Compute the current SWC/GEX/VPIN alignment flags and push them into
    the ConfluenceScorer. Strategies don't need to know — the scorer
    will OR-merge these flags with any explicit kwargs on `score()`.
    """
    scorer = components.detectors.get("confluence")
    if scorer is None or not hasattr(scorer, "set_edge_state"):
        return

    # ── SWC ───────────────────────────────────────────────────────────
    # We treat "sentiment aligned" as: min_confluence_override <= default
    # AND position_size_multiplier >= 1.0 (i.e. the day is neutral or
    # positively rated). Genuine news risk lowers pos_mult below 1.0.
    swc_aligned = False
    swc = state.swc_snapshot
    if swc is not None:
        try:
            pos_mult = float(getattr(swc, "position_size_multiplier", 1.0))
            min_override = int(getattr(swc, "min_confluence_override",
                                       config.MIN_CONFLUENCE))
            swc_aligned = (pos_mult >= 1.0) and (min_override <= config.MIN_CONFLUENCE)
        except Exception:
            swc_aligned = False

    # ── GEX ───────────────────────────────────────────────────────────
    # Use the raw is_valid flag as the "regime aligned" signal. True wall
    # alignment depends on the concrete entry price and direction of a
    # pending signal — strategies can still pass that explicitly.
    gex_regime_aligned = False
    gex = state.gex_snapshot
    if gex is not None and getattr(gex, "is_valid", False):
        gex_regime_aligned = True

    # ── VPIN ──────────────────────────────────────────────────────────
    # "Quality session" = VPIN in the healthy elevated band (>= 0.45 and
    # below the high threshold). "Validated sweep" is kept False here; a
    # richer version would track recent liquidity sweeps and their VPIN.
    vpin_quality_session = False
    vpin_status = state.vpin_status
    if vpin_status is not None and vpin_status.vpin is not None:
        v = vpin_status.vpin
        vpin_quality_session = (0.45 <= v < VPIN_WARN_THRESHOLD)

    scorer.set_edge_state(
        swc_sentiment_aligned=swc_aligned,
        gex_wall_aligned=False,          # needs entry price context
        gex_regime_aligned=gex_regime_aligned,
        vpin_validated_sweep=False,      # needs sweep detector hook
        vpin_quality_session=vpin_quality_session,
    )


async def _on_broker_fill(
    order_data: dict,
    components: "Components",
    state: "EngineState",
) -> None:
    """
    Called by the broker's fill callback (user hub GatewayUserOrder status=2).

    Matches the filled order ID against every open position's stop_order and
    target_order. On a match:
      - Computes realised P&L
      - Builds the trade dict expected by _on_trade_closed()
      - Calls _on_trade_closed() (risk accounting + Supabase + Telegram + post-mortem)
      - Cancels the surviving counter-order (target if stop hit; stop if target hit)
      - Removes the position from state.open_positions

    Unknown order IDs are silently ignored (already-closed positions or
    broker-initiated flattens handled elsewhere).
    """
    order_id = str(order_data.get("orderId") or order_data.get("id") or "")
    fill_price_raw = (
        order_data.get("filledPrice")
        or order_data.get("avgPrice")
        or order_data.get("price")
    )
    if not order_id or fill_price_raw is None:
        logger.warning("Fill event missing orderId or filledPrice: %s", order_data)
        return

    fill_price = float(fill_price_raw)

    for pos_key, pos in list(state.open_positions.items()):
        stop_order = pos.get("stop_order")
        target_order = pos.get("target_order")
        stop_id = str(stop_order.order_id) if stop_order else ""
        target_id = str(target_order.order_id) if target_order else ""

        is_stop = bool(stop_id and stop_id == order_id)
        is_target = bool(target_id and target_id == order_id)
        if not is_stop and not is_target:
            continue

        signal = pos["signal"]
        entry_price = float(signal.entry_price)
        contracts = int(signal.contracts)
        direction = signal.direction
        opened_at = pos.get("opened_at")
        current_stop = pos.get("current_stop_price", float(signal.stop_price))
        stop_points = abs(current_stop - entry_price)

        if direction == "long":
            pnl = (fill_price - entry_price) * contracts * config.MNQ_POINT_VALUE
        else:
            pnl = (entry_price - fill_price) * contracts * config.MNQ_POINT_VALUE

        reason = "trailing_stop" if is_stop else "target"

        trade_dict = {
            "id": pos_key,
            "strategy": signal.strategy,
            "direction": direction,
            "symbol": signal.symbol,
            "entry_price": entry_price,
            "exit_price": fill_price,
            "entry_time": str(opened_at) if opened_at else "",
            "exit_time": str(datetime.now(timezone.utc)),
            "pnl": pnl,
            "confluence_score": getattr(signal, "confluence_score", 0),
            "ict_concepts": list(
                getattr(signal, "confluence_breakdown", {}).keys()
            ),
            "kill_zone": getattr(signal, "kill_zone", ""),
            "stop_points": stop_points,
            "contracts": contracts,
            "reason": reason,
        }

        logger.info(
            "TRADE CLOSED: %s %s %dx @ %.2f | P&L: $%.2f | Reason: %s",
            direction, signal.symbol, contracts, fill_price, pnl, reason,
        )

        await _on_trade_closed(components, state, trade_dict)
        del state.open_positions[pos_key]

        # Cancel the surviving counter-order
        try:
            if is_stop and target_order:
                await components.broker.cancel_order(str(target_order.order_id))
                logger.info(
                    "Cancelled target order %s after stop fill", target_order.order_id
                )
            elif is_target and stop_order:
                await components.broker.cancel_order(str(stop_order.order_id))
                logger.info(
                    "Cancelled stop order %s after target fill", stop_order.order_id
                )
        except Exception as exc:
            logger.warning("Counter-order cancel failed: %s", exc)

        return  # position found and processed — stop iterating

    logger.debug(
        "Fill for order %s not matched to any open position (already closed?)",
        order_id,
    )


async def _on_trade_closed(
    components: Components,
    state: EngineState,
    trade: dict,
) -> None:
    """
    Record a realized trade. Must be called from the fill/close path
    (currently not auto-wired — the WS fill stream is the pending piece).

    Responsibilities:
      1. risk.record_trade(pnl) so daily limits update
      2. Write to Supabase `trades` table if available
      3. If pnl < 0 → run PostMortemAgent.analyze_loss, save + alert

    `trade` dict shape (matches PostMortemAgent expectations):
        {id, strategy, direction, entry_price, exit_price,
         entry_time, exit_time, pnl, confluence_score,
         ict_concepts, kill_zone, stop_points, contracts}
    """
    pnl = float(trade.get("pnl", 0.0))

    # 1. risk accounting
    try:
        components.risk.record_trade(pnl)
    except Exception as exc:
        logger.warning("risk.record_trade failed: %s", exc)

    # 2. supabase persistence
    if components.supabase is not None:
        try:
            components.supabase.write_trade(trade)
        except Exception as exc:
            logger.warning("Supabase trade write failed: %s", exc)

    # 3. Telegram WIN/LOSS alert
    if components.telegram is not None:
        try:
            await components.telegram.send_trade_closed(
                symbol=trade.get("symbol", "MNQ"),
                pnl=pnl,
                reason=trade.get("reason", "stop"),
                close_price=float(trade.get("exit_price", 0.0)),
            )
        except Exception as exc:
            logger.warning("Telegram trade closed alert failed: %s", exc)

    # 5. post-mortem on losses
    if pnl < 0 and components.post_mortem is not None:
        try:
            market_ctx = {
                "weekly_bias": None,
                "daily_bias": None,
                "structure_15min": None,
                "swc": state.swc_snapshot,
                "gex": state.gex_snapshot,
                "vpin": getattr(state.vpin_status, "vpin", None),
            }
            # analyze_loss is sync; run it on a thread so the event loop
            # is not blocked by the Claude API call.
            await asyncio.to_thread(
                components.post_mortem.analyze_loss,
                trade,
                market_ctx,
            )
        except Exception as exc:
            logger.error("Post-mortem analysis failed: %s", exc)


# Throttle constants for trailing-stop Telegram alerts
_TRAILING_ALERT_MIN_PTS = 5.0       # only alert if delta >= this many points
_TRAILING_ALERT_MIN_INTERVAL_S = 300  # or if >= 5 min since last alert


async def _poll_position_status(components: Components, state: EngineState) -> None:
    """Fallback fill detection when the User hub is unavailable.

    Polls broker positions every bar. If a locally-tracked position is no
    longer reported by get_positions(), the exit is inferred from the latest
    close price and routed through _on_broker_fill so all accounting
    (risk, Supabase, Telegram, post-mortem) fires exactly once.

    Called from _on_new_bar() whenever user_hub_alive is False.
    """
    if not state.open_positions:
        return
    try:
        broker_positions = await components.broker.get_positions()
    except Exception:
        return  # silent — don't disrupt bar loop on poll failure

    def _root(sym: str) -> str:
        if not sym:
            return ""
        s = str(sym).upper()
        if s.startswith("CON.F.") and "." in s:
            parts = s.split(".")
            if len(parts) >= 4:
                return parts[3]
        return s

    broker_symbols = {
        _root(getattr(p, "symbol", ""))
        for p in broker_positions
        if getattr(p, "contracts", 0) != 0
    } - {""}

    last_close = (
        float(state.bars_1min["close"].iloc[-1])
        if not state.bars_1min.empty else None
    )

    for pos_key, pos in list(state.open_positions.items()):
        signal = pos.get("signal")
        if signal is None:
            continue
        if _root(signal.symbol) in broker_symbols:
            continue  # still open — nothing to do

        # Position is flat at broker. Infer exit from last close price.
        if last_close is None:
            continue

        direction = signal.direction
        current_stop = pos.get("current_stop_price", float(signal.stop_price))
        target_price = float(getattr(signal, "target_price", 0) or 0)

        # Heuristic: if price is within 2 pts of stop → stop fill; else target.
        if direction == "long":
            is_stop = last_close <= current_stop + 2.0
        else:
            is_stop = last_close >= current_stop - 2.0

        stop_order = pos.get("stop_order")
        target_order = pos.get("target_order")

        if is_stop and stop_order:
            inferred_id = str(stop_order.order_id)
            exit_price = _snap(current_stop)
        elif not is_stop and target_order and target_price:
            inferred_id = str(target_order.order_id)
            exit_price = _snap(target_price)
        else:
            inferred_id = pos_key
            exit_price = _snap(last_close)

        logger.info(
            "POLL: %s closed at broker — inferred exit %.2f (%s)",
            _root(signal.symbol), exit_price, "stop" if is_stop else "target",
        )
        synthetic_fill = {"orderId": inferred_id, "filledPrice": exit_price}
        await _on_broker_fill(synthetic_fill, components, state)


async def _reconcile_positions(components: Components, state: EngineState) -> None:
    """Compare broker-reported open positions with local state.open_positions.

    Runs every 5 minutes during active trading.

    - GHOST: broker has a position we don't track → log warning + attempt
      flatten so we don't carry an unmanaged position.
    - ORPHAN: we track a position the broker says is flat → cancel any
      pending stop/target orders for it, remove from local state, and log
      the resolution. Does NOT call _on_trade_closed (no confirmed P&L).
    """
    if components.broker is None:
        return
    try:
        broker_positions = await components.broker.get_positions()
    except Exception as exc:
        logger.debug("Reconcile: get_positions failed: %s", exc)
        return

    # Normalize both sides to a root-symbol set. Broker can return either
    # the short name ("MNQ") or the full TopstepX contract id
    # ("CON.F.US.MNQ.M26"); local state always stores signal.symbol ("MNQ").
    def _root(sym: str) -> str:
        if not sym:
            return ""
        s = str(sym).upper()
        if s.startswith("CON.F.") and "." in s:
            parts = s.split(".")
            if len(parts) >= 4:
                return parts[3]
        return s

    broker_symbols = {_root(getattr(p, "symbol", "")) for p in broker_positions
                      if getattr(p, "contracts", 0) != 0} - {""}
    local_symbols = {
        _root((pos.get("signal") and pos["signal"].symbol) or "")
        for pos in state.open_positions.values()
    } - {""}

    ghosts = broker_symbols - local_symbols
    orphans = local_symbols - broker_symbols

    if ghosts:
        logger.warning(
            "Position reconcile: GHOST at broker (not in local state): %s — "
            "attempting flatten",
            sorted(ghosts),
        )
        try:
            await components.broker.flatten_all()
        except Exception as exc:
            logger.warning("Reconcile: flatten_all for ghost failed: %s", exc)

    if orphans:
        logger.warning(
            "Position reconcile: ORPHAN in local state (not at broker): %s",
            sorted(orphans),
        )
        # Cancel all pending stop/target orders for each orphaned position
        # then remove from local state. We do NOT record a P&L event because
        # the position was never confirmed at the broker.
        orphan_keys = [
            key for key, pos in state.open_positions.items()
            if _root((pos.get("signal") and pos["signal"].symbol) or "") in orphans
        ]
        for key in orphan_keys:
            pos = state.open_positions.pop(key, None)
            if pos is None:
                continue
            for order_field in ("stop_order", "target_order"):
                order = pos.get(order_field)
                oid = getattr(order, "order_id", None) if order else None
                if oid:
                    try:
                        await components.broker.cancel_order(oid)
                    except Exception as exc:
                        logger.debug(
                            "Reconcile: cancel %s order %s failed: %s",
                            order_field, oid, exc,
                        )
            sym = (pos.get("signal") and pos["signal"].symbol) or key
            logger.info(
                "ORPHAN resolved: removed local position %s, cancelled pending orders",
                sym,
            )


async def _manage_open_positions(
    components: Components,
    state: EngineState,
) -> None:
    """
    Trail the protective stop to the most recent 5min swing low (long) or
    swing high (short) for every open position.

    Mirrors backtester._update_trailing_stop exactly:
      - Same swing source: components.detectors["swing"] (5min + 15min)
      - Same tighten-only logic: LONG new_stop > current_stop;
        SHORT new_stop < current_stop
      - On improvement: cancel old stop order, place new stop order

    Race condition handling: if cancel_order fails the old stop may already
    have been executed (position closed), so we log a warning and skip the
    replace to avoid double-cancelling a filled order.
    """
    swing = components.detectors.get("swing")
    if swing is None or not state.open_positions:
        return

    broker = components.broker

    for pos in list(state.open_positions.values()):
        signal = pos["signal"]
        direction = signal.direction
        symbol = signal.symbol
        contracts = signal.contracts
        current_stop = pos.get("current_stop_price", float(signal.stop_price))

        if direction == "long":
            sp = swing.get_latest_swing_low()
            if sp is None or sp.price <= current_stop:
                continue
            new_stop = sp.price
        else:
            sp = swing.get_latest_swing_high()
            if sp is None or sp.price >= current_stop:
                continue
            new_stop = sp.price

        old_stop_order = pos.get("stop_order")
        old_order_id = old_stop_order.order_id if old_stop_order else None

        if old_order_id:
            try:
                await broker.cancel_order(old_order_id)
            except Exception as exc:
                logger.warning(
                    "TRAILING STOP: cancel order %s failed (may already be filled): %s",
                    old_order_id, exc,
                )
                continue  # stop may be executed — do not replace

        exit_side = "sell" if direction == "long" else "buy"
        try:
            new_stop_order = await broker.submit_stop_order(
                symbol=symbol,
                side=exit_side,
                contracts=contracts,
                stop_price=_snap(new_stop),
            )
        except Exception as exc:
            logger.error("TRAILING STOP: failed to submit new stop: %s", exc)
            continue

        diff = new_stop - current_stop if direction == "long" else current_stop - new_stop
        logger.info(
            "TRAILING STOP updated: %s %s stop %.2f → %.2f (+%.1f pts)",
            direction, symbol, current_stop, new_stop, diff,
        )
        pos["stop_order"] = new_stop_order
        pos["current_stop_price"] = new_stop

        # Telegram alert — throttled: only send if delta >= threshold OR
        # enough time has passed since last alert (avoids spam on fast moves).
        if components.telegram is not None:
            now = datetime.now(timezone.utc)
            last = state.last_trailing_alert_time
            time_ok = (last is None or
                       (now - last).total_seconds() >= _TRAILING_ALERT_MIN_INTERVAL_S)
            if diff >= _TRAILING_ALERT_MIN_PTS or time_ok:
                try:
                    await components.telegram.send_trailing_stop_update(
                        symbol=symbol,
                        direction=direction,
                        old_stop=current_stop,
                        new_stop=new_stop,
                    )
                    state.last_trailing_alert_time = now
                except Exception as exc:
                    logger.debug("Trailing stop Telegram alert failed: %s", exc)


async def _on_new_bar(
    bar: dict,
    components: Components,
    state: EngineState,
) -> None:
    """
    Main per-bar handler. Called from the WebSocket callback.

    Pipeline:
      1. Append bar
      2. Update detectors (on completed TFs only)
      3. VPIN update (if available)
      4. Hard-close check (3:00 PM CT -> flatten)
      5. Evaluate strategies -> submit signals
    """
    try:
        _append_bar(state, bar)

        # Update state_ref so htf_bias_fn sees current bars
        components._state_ref["bars_1min"] = state.bars_1min  # type: ignore[attr-defined]

        # ── 2. Detector updates ───────────────────────────────────────
        _update_detectors(components, state)

        # ── 3. VPIN update + shield ───────────────────────────────────
        # Drives the toxicity pipeline end-to-end (bucketizer → BVC →
        # VPINCalculator → ShieldManager). extreme → flatten + alert.
        await _update_vpin(components, state, bar)

        # ── 3b. Publish live edge state to the confluence scorer ──────
        _update_edge_state(components, state)

        ts = state.bars_1min.index[-1]

        # ── 3c. Persist bar to Supabase market_data (fire and forget) ─
        if components.supabase is not None:
            vpin_val: Optional[float] = None
            vs = state.vpin_status
            if vs is not None and vs.vpin is not None:
                vpin_val = float(vs.vpin)
            asyncio.create_task(asyncio.to_thread(
                components.supabase.write_market_data,
                {
                    "symbol": state.symbol,
                    "timeframe": "1m",
                    "timestamp": ts.isoformat(),
                    "open": float(bar["open"]),
                    "high": float(bar["high"]),
                    "low": float(bar["low"]),
                    "close": float(bar["close"]),
                    "volume": int(bar.get("volume", 0)),
                    "vpin_level": vpin_val,
                },
            ))

        # ── 3d. Bar-level visibility log (detector + session snapshot) ─
        _log_bar_snapshot(components, state, ts)

        # ── 3e. Reconcile broker positions with local state (every 5 min) ─
        # Catches ghost positions (broker says open, we don't track) and
        # orphaned tracking (we think open, broker says flat). Either
        # indicates a prior bug path or network partition. Logged at
        # WARNING so Telegram surfaces via the alert hook.
        #
        # Fire-and-forget: the broker HTTP call can take hundreds of ms
        # and must NOT block the bar loop (which still has to process
        # hard-close, VPIN halts, and strategy eval). Dedup across a
        # single 1-min window via state.reconcile_inflight — multiple
        # bars arriving in the same minute won't spawn duplicate tasks.
        if ts.minute % 5 == 0 and not getattr(state, "reconcile_inflight", False):
            state.reconcile_inflight = True
            async def _reconcile_wrapped():
                try:
                    await _reconcile_positions(components, state)
                except Exception as exc:
                    logger.debug("Reconcile failed (non-fatal): %s", exc)
                finally:
                    state.reconcile_inflight = False
            asyncio.create_task(_reconcile_wrapped())

        # ── 4. Hard close ─────────────────────────────────────────────
        if (not state.hard_close_done
                and (ts.hour > HARD_CLOSE_HOUR
                     or (ts.hour == HARD_CLOSE_HOUR and ts.minute >= HARD_CLOSE_MIN))):
            logger.warning("HARD CLOSE reached at %s CT — flattening all", ts)
            await _flatten_all(components, state, reason="hard_close")
            state.hard_close_done = True
            return

        if state.hard_close_done:
            return

        # ── 4b. Trade management (trailing stop / partials) ──────────
        if state.open_positions:
            mode = getattr(config, "TRADE_MANAGEMENT", "fixed")
            if mode == "trailing":
                await _manage_open_positions(components, state)
            elif mode == "partials_be":
                # NOT YET IMPLEMENTED in live (backtester has it). If
                # someone flips config to partials_be, shout loudly every
                # bar rather than silently fall through to fixed SL/TP —
                # that would leave the user thinking they're running
                # partials-and-BE while the bot just passively waits for
                # stop or target. Meta-audit 2026-04-17.
                if not getattr(state, "_partials_be_warned", False):
                    logger.error(
                        "config.TRADE_MANAGEMENT='partials_be' is NOT implemented "
                        "in the live engine (only in backtest). The bracket will "
                        "behave as 'fixed' (full size to SL or TP). Either "
                        "implement partials_be in main._manage_open_positions "
                        "or switch config.TRADE_MANAGEMENT back to 'trailing' "
                        "or 'fixed'."
                    )
                    state._partials_be_warned = True  # type: ignore[attr-defined]
            # mode == "fixed": nothing to do — bracket runs to SL/TP

        # ── 4c. Position-status polling (User hub fallback) ───────────
        # When the User hub is unavailable (paper-account SubscribeAccounts
        # failure after 3 retries), we poll get_positions() every bar to
        # detect fills. This is less latent than the 5-min reconcile and
        # routes inferred closes through _on_broker_fill so risk accounting,
        # Supabase, Telegram, and post-mortem all fire correctly.
        if (state.open_positions
                and components.broker is not None
                and not getattr(components.broker, "user_hub_alive", True)):
            await _poll_position_status(components, state)

        # ── 5. Strategy evaluation ────────────────────────────────────
        bars = state.bars_1min
        if len(bars) < 50:
            return  # warm-up

        try:
            # Aggregate first (also updates tf_manager._last_1min_ts). Then
            # fetch the COMPLETED subset — drops any tail bar whose window
            # hasn't elapsed yet based on the latest 1-min timestamp. Without
            # this guard, strategies previously saw a forming 5-min or 15-min
            # bar as if it were closed (look-ahead risk).
            components.tf_manager.aggregate(bars, "5min")
            components.tf_manager.aggregate(bars, "15min")
            df_5min = components.tf_manager.get_completed_bars("5min")
            df_15min = components.tf_manager.get_completed_bars("15min")
            if df_5min is None or df_15min is None:
                return
        except Exception as exc:
            logger.debug("TF aggregation failed in strategy eval: %s", exc)
            return

        sess = components.session

        # NY AM Reversal — evaluates in london + ny_am windows
        try:
            signal = components.ny_am_strategy.evaluate(df_5min, df_15min)
            ny_zones = getattr(components.ny_am_strategy, "KILL_ZONES", ("ny_am",))
            if any(sess.is_kill_zone(ts, z) for z in ny_zones):
                logger.info(
                    "EVAL ny_am [%s]: signal=%s",
                    ts.strftime("%H:%M"),
                    "FIRE" if signal else "reject",
                )
            if signal is not None:
                allowed, reason = components.risk.can_trade()
                if allowed:
                    if state.pending_signal_ts is not None:
                        logger.info("NY AM signal suppressed: pending execution at %s", state.pending_signal_ts)
                    else:
                        state.pending_signal_ts = signal.timestamp
                        try:
                            await _execute_signal(signal, components, state)
                        finally:
                            state.pending_signal_ts = None
                else:
                    logger.info("NY AM signal suppressed: %s", reason)
        except Exception as exc:
            logger.exception("NY AM strategy raised: %s", exc)

        # Silver Bullet — evaluates in london_silver_bullet + silver_bullet windows
        try:
            signal = components.silver_bullet_strategy.evaluate(bars, df_5min)
            sb_zones = getattr(components.silver_bullet_strategy, "KILL_ZONES", ("silver_bullet",))
            if any(sess.is_kill_zone(ts, z) for z in sb_zones):
                logger.info(
                    "EVAL silver_bullet [%s]: signal=%s",
                    ts.strftime("%H:%M"),
                    "FIRE" if signal else "reject",
                )
            if signal is not None:
                allowed, reason = components.risk.can_trade()
                if allowed:
                    if state.pending_signal_ts is not None:
                        logger.info("Silver Bullet signal suppressed: pending execution at %s", state.pending_signal_ts)
                    else:
                        state.pending_signal_ts = signal.timestamp
                        try:
                            await _execute_signal(signal, components, state)
                        finally:
                            state.pending_signal_ts = None
                else:
                    logger.info("Silver Bullet signal suppressed: %s", reason)
        except Exception as exc:
            logger.exception("Silver Bullet strategy raised: %s", exc)

    except Exception as exc:
        logger.exception("Unhandled error in _on_new_bar: %s", exc)


# ---------------------------------------------------------------------------
# Flatten + daily summary
# ---------------------------------------------------------------------------

async def _flatten_all(
    components: Components,
    state: EngineState,
    reason: str,
    emergency: bool = False,
) -> None:
    """
    Close every open position via the broker.

    Parameters
    ----------
    emergency : bool
        When True, activates the kill switch via ``risk.emergency_flatten()``
        (logs CRITICAL).  Use for real failures: unhandled exceptions, VPIN
        extreme events, heartbeat loss.  Routine session closes (hard_close,
        daily_hard_close) should pass ``emergency=False`` — the
        ``state.hard_close_done`` flag already prevents new trades.
    """
    logger.warning("FLATTEN ALL triggered: %s", reason)

    # ── Capture + synthesize _on_trade_closed for every open position ──
    # broker.flatten_all() submits fresh market orders whose order_ids do
    # NOT match the tracked stop/target, so _on_broker_fill() would never
    # match them — that path was silently losing P&L accounting on every
    # VPIN-extreme / hard-close / signalr-exhausted / unhandled-exception
    # flatten. Meta-audit 2026-04-17. Now we:
    #   1. Cancel the tracked stop+target brackets FIRST (prevents them
    #      from firing after the flatten market order closes the position)
    #   2. Capture each position's details for trade_dict synthesis
    #   3. Call broker.flatten_all()
    #   4. Synthesize a trade_dict using last 1-min close as exit proxy
    #      (market flatten fills within a tick; exact fill price isn't
    #      available from broker.flatten_all today — a future refactor
    #      can wait for fill callbacks, but synthesising here is strictly
    #      better than the prior silent P&L loss)
    #   5. Call _on_trade_closed per position (risk.record_trade + Supabase
    #      trade row + Telegram exit alert + post-mortem if loss)
    captured: list[dict] = []
    for pos_key, pos in list(state.open_positions.items()):
        signal = pos.get("signal")
        if signal is None:
            continue

        # Pre-cancel bracket to prevent post-flatten ghost fills
        for order_attr in ("stop_order", "target_order"):
            ord_obj = pos.get(order_attr)
            if ord_obj is not None:
                try:
                    await components.broker.cancel_order(str(ord_obj.order_id))
                except Exception as exc:
                    logger.debug(
                        "Pre-flatten cancel of %s %s failed (continuing): %s",
                        order_attr, ord_obj.order_id, exc,
                    )

        captured.append({
            "pos_key": pos_key,
            "signal": signal,
            "opened_at": pos.get("opened_at"),
            "current_stop_price": pos.get("current_stop_price"),
        })

    try:
        await components.broker.flatten_all()
    except Exception as exc:
        logger.error("Broker flatten failed: %s", exc)

    # Resolve an exit price once for all positions — last completed 1-min
    # close is the best available proxy when broker.flatten_all doesn't
    # return per-fill prices.
    exit_price_proxy: Optional[float] = None
    try:
        if not state.bars_1min.empty:
            exit_price_proxy = float(state.bars_1min["close"].iloc[-1])
    except Exception:
        exit_price_proxy = None

    for cap in captured:
        signal = cap["signal"]
        entry_price = float(signal.entry_price)
        contracts = int(signal.contracts)
        direction = signal.direction
        exit_price = exit_price_proxy if exit_price_proxy is not None else entry_price
        if direction == "long":
            pnl = (exit_price - entry_price) * contracts * config.MNQ_POINT_VALUE
        else:
            pnl = (entry_price - exit_price) * contracts * config.MNQ_POINT_VALUE
        current_stop = cap["current_stop_price"] if cap["current_stop_price"] is not None else float(signal.stop_price)
        stop_points = abs(current_stop - entry_price)

        trade_dict = {
            "id": cap["pos_key"],
            "strategy": signal.strategy,
            "direction": direction,
            "symbol": signal.symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_time": str(cap["opened_at"]) if cap["opened_at"] else "",
            "exit_time": str(datetime.now(timezone.utc)),
            "pnl": pnl,
            "confluence_score": getattr(signal, "confluence_score", 0),
            "ict_concepts": list(getattr(signal, "confluence_breakdown", {}).keys()),
            "kill_zone": getattr(signal, "kill_zone", ""),
            "stop_points": stop_points,
            "contracts": contracts,
            "reason": f"flatten:{reason}",
            "exit_price_is_proxy": exit_price_proxy is not None and exit_price_proxy != entry_price,
        }
        logger.info(
            "TRADE CLOSED (flatten): %s %s %dx @ %.2f | P&L: $%.2f | reason=flatten:%s",
            direction, signal.symbol, contracts, exit_price, pnl, reason,
        )
        try:
            await _on_trade_closed(components, state, trade_dict)
        except Exception as exc:
            logger.error("_on_trade_closed raised during flatten: %s", exc)

    state.open_positions.clear()
    if emergency:
        components.risk.emergency_flatten()


async def _send_daily_summary(components: Components, state: EngineState) -> None:
    """Push end-of-day summary to Telegram + Supabase."""
    if state.daily_summary_sent:
        return
    state.daily_summary_sent = True

    risk = components.risk
    trades_count = risk.trades_today
    wins = 0  # Would need to track win/loss per trade
    losses = 0
    total_pnl = risk.daily_pnl

    date_str = datetime.now().strftime("%Y-%m-%d")

    if components.telegram is not None:
        try:
            await components.telegram.send_daily_summary(
                date_str=date_str,
                trades_count=trades_count,
                wins=wins,
                losses=losses,
                total_pnl=total_pnl,
            )
        except Exception as exc:
            logger.warning("Daily summary Telegram failed: %s", exc)

    if components.supabase is not None:
        try:
            components.supabase.write_daily_performance({
                "date": date_str,
                "trades_count": trades_count,
                "wins": wins,
                "losses": losses,
                "total_pnl": total_pnl,
                "max_drawdown": 0.0,
                "sharpe": 0.0,
            })
        except Exception as exc:
            logger.warning("Daily summary Supabase write failed: %s", exc)


def _reset_for_new_day(components: Components, state: EngineState) -> None:
    """Reset all daily state at the start of a new trading session."""
    logger.info("=" * 60)
    logger.info("  NEW TRADING DAY: %s", datetime.now().strftime("%Y-%m-%d"))
    logger.info("=" * 60)

    components.risk.reset_daily()
    components.ny_am_strategy.reset_daily()
    components.silver_bullet_strategy.reset_daily()
    components.detectors["tracked_levels"] = []
    state.premarket_done = False
    state.hard_close_done = False
    state.daily_summary_sent = False
    state.swc_mood_sent_today = False
    state.swc_london_rescan_done = False
    state.swc_nyam_rescan_done = False
    state.executed_signals = set()
    state.pending_signal_ts = None

    # ── Seed tracked_levels immediately so London KZ (01:00-04:00 CT)
    # has PDH/PDL/PWH/PWL available before pre-market runs at 06:00 CT.
    # Pre-market will re-seed with fresher data later.
    try:
        bars = state.bars_1min
        if bars is not None and not bars.empty:
            tf_mgr = components.tf_manager
            df_daily = tf_mgr.aggregate(bars, "D")
            df_weekly = tf_mgr.aggregate(bars, "W")
            levels = components.detectors["liquidity"].build_key_levels(
                df_daily=df_daily, df_weekly=df_weekly,
            )
            components.detectors["tracked_levels"] = levels
            logger.info(
                "tracked_levels seeded on daily reset: %d levels (%s)",
                len(levels),
                ", ".join(f"{lvl.type}@{lvl.price:.2f}" for lvl in levels),
            )
        else:
            logger.warning("tracked_levels: no warm-up bars yet, deferring to pre-market")
    except Exception as exc:
        logger.warning("tracked_levels daily-reset seed failed: %s", exc)


# ---------------------------------------------------------------------------
# Heartbeat integration
# ---------------------------------------------------------------------------

class _RiskManagerAsyncAdapter:
    """
    Adapter that gives RiskManager the async emergency_flatten(reason=...)
    signature expected by core/heartbeat.py.
    """
    def __init__(self, risk: RiskManager, broker: TopstepXClient):
        self._risk = risk
        self._broker = broker

    async def emergency_flatten(self, reason: str = "") -> None:
        logger.critical("Async emergency flatten: %s", reason)
        try:
            await self._broker.flatten_all()
        except Exception as exc:
            logger.error("Broker flatten in emergency failed: %s", exc)
        self._risk.emergency_flatten()


# ---------------------------------------------------------------------------
# Dashboard state snapshot
# ---------------------------------------------------------------------------

def _make_state_snapshot(components: "Components", state: "EngineState") -> dict:
    """
    Build the full bot_state payload that BotStateSync pushes to Supabase
    every 5 seconds. The dashboard reads this to show live P&L, VPIN, etc.
    """
    risk = components.risk
    vpin_status = state.vpin_status  # VPINStatus object or None
    vpin_val = (vpin_status.vpin if vpin_status is not None and vpin_status.vpin is not None else 0.0)
    tox_label = (vpin_status.label if vpin_status is not None and hasattr(vpin_status, "label") else "calm")

    snap: dict = {
        "is_running": True,
        "vpin": vpin_val,
        "toxicity_level": tox_label,
        "shield_active": risk.vpin_halted,
        "trades_today": risk.trades_today,
        "pnl_today": risk.daily_pnl,
        "position_count": len(state.open_positions),
    }

    # ── SWC mood (from pre-market scan) ──────────────────────────────
    # Without this, bot_state stays at the startup defaults
    # ("choppy", 0, "Engine starting…") and the dashboard never sees the
    # real mood that Claude + Finnhub produced.
    swc = state.swc_snapshot
    if swc is not None:
        mood_val = getattr(swc.market_mood, "value", None) or str(swc.market_mood)
        conf_map = {"low": 25, "medium": 50, "high": 75}
        snap["swc_mood"] = mood_val
        snap["swc_confidence"] = conf_map.get(
            str(swc.confidence).lower(), 50,
        ) / 100.0   # bot_state stores 0-1 per CHECK constraint on the column
        snap["swc_summary"] = swc.one_line_summary or ""

    # ── GEX overlay (from pre-market scan) ───────────────────────────
    gex = state.gex_snapshot
    if gex is not None and getattr(gex, "is_valid", False):
        regime = getattr(gex, "regime", "unknown")
        snap["gex_regime"] = regime if regime in (
            "positive", "negative", "flip", "unknown"
        ) else "unknown"
        snap["gex_call_wall"] = float(getattr(gex, "call_wall", 0.0) or 0.0)
        snap["gex_put_wall"] = float(getattr(gex, "put_wall", 0.0) or 0.0)
        snap["gex_flip_point"] = float(getattr(gex, "gamma_flip", 0.0) or 0.0)

    # Last signal (most recent bar timestamp as a human-readable hint)
    if not state.bars_1min.empty:
        last_ts = state.bars_1min.index[-1]
        snap["last_signal"] = (
            f"Last bar: {last_ts.strftime('%H:%M CT')} | "
            f"Bars loaded: {len(state.bars_1min)}"
        )

    # ── Detector overlay (Phase 2 of chart integration, migration 0003) ──
    # Everything below lands in JSONB / scalar columns for the dashboard
    # chart page. Computed best-effort: any sub-block that raises is
    # logged at debug and skipped so the simpler scalar payload still
    # ships. Keep this block cheap — it runs every 5s.
    try:
        _populate_detector_overlay(snap, components, state)
    except Exception as exc:
        logger.debug("detector overlay snapshot failed: %s", exc)

    return snap


def _populate_detector_overlay(
    snap: dict,
    components: "Components",
    state: "EngineState",
) -> None:
    """Populate the bot_state overlay columns added in migration 0003."""
    det = components.detectors or {}
    risk = components.risk

    if state.bars_1min.empty:
        last_close = None
        last_ts = None
    else:
        last_close = float(state.bars_1min["close"].iloc[-1])
        last_ts = state.bars_1min.index[-1]

    # ── FVG / IFVG / OB top-3 nearest (by midpoint distance to close) ──
    def _zone_row(z, *, is_ifvg: bool) -> dict:
        return {
            "price_low":  float(z.bottom),
            "price_high": float(z.top),
            "direction":  z.direction,
            "tf":         z.timeframe,
            "is_ifvg":    bool(is_ifvg or getattr(z, "is_ifvg", False)),
            "midpoint":   float(z.midpoint),
            "ts":         str(getattr(z, "timestamp", "")),
        }

    fvg_det = det.get("fvg")
    if fvg_det is not None and last_close is not None:
        try:
            fvgs = fvg_det.get_active(timeframe="5min")
            fvgs_sorted = sorted(
                fvgs, key=lambda f: abs(f.midpoint - last_close),
            )[:3]
            snap["fvg_top3"] = [_zone_row(f, is_ifvg=False) for f in fvgs_sorted]

            ifvgs = fvg_det.get_active_ifvgs(timeframe="5min")
            ifvgs_sorted = sorted(
                ifvgs, key=lambda f: abs(f.midpoint - last_close),
            )[:3]
            snap["ifvg_top3"] = [_zone_row(f, is_ifvg=True) for f in ifvgs_sorted]
        except Exception as exc:
            logger.debug("fvg/ifvg snapshot: %s", exc)

    ob_det = det.get("ob")
    if ob_det is not None and last_close is not None:
        try:
            obs = ob_det.get_active(timeframe="5min")
            obs_sorted = sorted(
                obs,
                key=lambda o: abs(((o.high + o.low) / 2.0) - last_close),
            )[:3]
            snap["ob_top3"] = [
                {
                    "price_low":  float(o.low),
                    "price_high": float(o.high),
                    "direction":  o.direction,
                    "tf":         o.timeframe,
                    "ts":         str(getattr(o, "timestamp", "")),
                }
                for o in obs_sorted
            ]
        except Exception as exc:
            logger.debug("ob snapshot: %s", exc)

    # ── Tracked levels (PDH/PDL/PWH/PWL/BSL/SSL/EQH/EQL) ──
    try:
        tracked = det.get("tracked_levels") or []
        snap["tracked_levels"] = [
            {
                "price":  float(getattr(lvl, "price", 0.0)),
                "type":   str(getattr(lvl, "type", "")),
                "swept":  bool(getattr(lvl, "swept", False)),
                "ts":     str(getattr(lvl, "timestamp", "")),
            }
            for lvl in tracked[:16]   # cap payload size — dashboard shows top 8-12
        ]
    except Exception as exc:
        logger.debug("tracked_levels snapshot: %s", exc)

    # ── Structure events (last 3 on 15-min TF) ──
    struct_det = det.get("structure")
    if struct_det is not None:
        try:
            events = struct_det.get_events(timeframe="15min") or []
            snap["struct_last3"] = [
                {
                    "type":      str(getattr(ev, "event_type", "")),
                    "direction": str(getattr(ev, "direction", "")),
                    "price":     float(getattr(ev, "price", 0.0)),
                    "ts":        str(getattr(ev, "timestamp", "")),
                }
                for ev in events[-3:][::-1]     # most recent first
            ]
        except Exception as exc:
            logger.debug("struct snapshot: %s", exc)

    # ── Last displacement on entry TF ──
    disp_det = det.get("displacement")
    if disp_det is not None:
        try:
            recent = disp_det.get_recent(n=1, timeframe="5min")
            if recent:
                d = recent[0]
                snap["last_displacement"] = {
                    "direction": str(getattr(d, "direction", "")),
                    "points":    float(getattr(d, "magnitude", 0.0)),
                    "ts":        str(getattr(d, "timestamp", "")),
                }
        except Exception as exc:
            logger.debug("displacement snapshot: %s", exc)

    # ── HTF bias + premium/discount ──
    try:
        # The bias closure is stored on the strategies (identical for both);
        # reuse it so we don't re-implement the lookahead-safe cutoff logic.
        bias_fn = None
        strat = getattr(components, "ny_am_strategy", None) or \
                getattr(components, "silver_bullet_strategy", None)
        if strat is not None:
            bias_fn = getattr(strat, "htf_bias_fn", None)
        bias = bias_fn(last_close) if (bias_fn and last_close is not None) else None
        if bias is not None:
            snap["bias_direction"] = getattr(bias, "direction", "neutral") or "neutral"
            snap["bias_zone"] = getattr(bias, "premium_discount", "") or ""
            snap["daily_bias"] = getattr(bias, "daily_bias", "neutral") or "neutral"
            snap["weekly_bias"] = getattr(bias, "weekly_bias", "neutral") or "neutral"
    except Exception as exc:
        logger.debug("bias snapshot: %s", exc)

    # ── Active kill zone ──
    try:
        session = components.session
        if session is not None and last_ts is not None:
            for kz in ("london", "london_silver_bullet", "silver_bullet", "ny_am", "ny_pm"):
                if session.is_kill_zone(last_ts, kz):
                    snap["active_kz"] = kz
                    break
            else:
                snap["active_kz"] = ""
    except Exception as exc:
        logger.debug("active_kz snapshot: %s", exc)

    # ── MLL zone + min confluence ──
    try:
        snap["mll_zone"] = getattr(risk, "_mll_zone", "normal") or "normal"
    except Exception:
        pass
    try:
        snap["min_confluence"] = int(risk.effective_min_confluence)
    except Exception:
        pass

    # ── Bot status ──
    # `halted` if VPIN halt active; `error` is reserved for future
    # exception-recovery paths; default running while the process is up.
    try:
        if getattr(risk, "vpin_halted", False):
            snap["bot_status"] = "halted"
        else:
            snap["bot_status"] = "running"
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(
    mode: str = "paper",
    topstep_mode: bool = True,
    mll_warning_pct: float = 0.40,
    mll_caution_pct: float = 0.60,
    mll_stop_pct: float = 0.85,
) -> None:
    """
    Main orchestrator coroutine.

    Phases:
      0. init
      1. connect broker + start heartbeat
      2. pre-market scan (06:00 CT)
      3. subscribe to 1-min bars + run trading loop
      4. hard close 3:00 PM CT -> flatten + daily summary
      5. wait for next day (or shutdown)
    """
    logger.info("=" * 60)
    logger.info("  AlgoICT Engine Starting (mode=%s)", mode)
    logger.info("=" * 60)

    # ── 1. Initialize components ──────────────────────────────────────
    try:
        components = _init_components(
            mode,
            topstep_mode=topstep_mode,
            mll_warning_pct=mll_warning_pct,
            mll_caution_pct=mll_caution_pct,
            mll_stop_pct=mll_stop_pct,
        )
    except Exception as exc:
        logger.critical("Failed to initialize components: %s", exc, exc_info=True)
        return

    state = EngineState(mode=mode)
    components._state_ref["bars_1min"] = state.bars_1min  # type: ignore[attr-defined]

    # ── 2a. Register bar callback BEFORE connect so _on_open subscribes ─
    def _bar_callback(bar: dict):
        """Schedule async handling on the event loop."""
        # Deduplicate: TopstepX delivers the same bar via 3 contract-ID streams.
        # All 3 share the same timestamp — skip if already dispatched this bar.
        bar_ts = bar.get("timestamp")
        if bar_ts == state.last_dispatched_bar_ts:
            return
        state.last_dispatched_bar_ts = bar_ts
        asyncio.create_task(_on_new_bar(bar, components, state))

    components.broker.subscribe_bars(state.symbol, _bar_callback)
    logger.info("Registered bar callback for %s", state.symbol)

    # Register emergency-flatten hook: when SignalR exhausts all reconnect
    # retries we lose the price feed entirely — stops can't be monitored,
    # VPIN halts can't fire, hard-close can't flatten. Anything open at
    # that moment is uncovered risk. flatten_all now runs BEFORE the
    # TopstepXConnectionError propagates out of the listener task.
    if hasattr(components.broker, "set_on_ws_exhausted"):
        async def _ws_exhausted_flatten() -> None:
            logger.critical(
                "SignalR feed permanently lost — emergency flatten before engine exits"
            )
            await _flatten_all(components, state, reason="signalr_exhausted", emergency=True)
        components.broker.set_on_ws_exhausted(_ws_exhausted_flatten)

    # Register fill callback — routes broker order fills to _on_trade_closed().
    # Must be set before broker.connect() so the user hub task picks it up.
    if hasattr(components.broker, "set_fill_callback"):
        async def _fill_cb(order_data: dict) -> None:
            await _on_broker_fill(order_data, components, state)
        components.broker.set_fill_callback(_fill_cb)
        logger.info("Registered broker fill callback")

    # ── 2b. Connect broker (starts SignalR with symbols already registered) ─
    try:
        await components.broker.connect()
    except Exception as exc:
        logger.critical("Broker connect failed: %s", exc, exc_info=True)
        return

    # ── 2c. Reset bot_state to clear stale values from prior runs ──────
    if components.supabase is not None:
        try:
            components.supabase.update_bot_state({
                "is_running": True,
                "vpin": 0.0,
                "toxicity_level": "calm",
                "shield_active": False,
                "trades_today": 0,
                "pnl_today": 0.0,
                "daily_high_pnl": 0.0,
                "position_count": 0,
                "wins_today": 0,
                "losses_today": 0,
                "swc_mood": "choppy",
                "swc_confidence": 0.0,
                "swc_summary": "Engine starting…",
                "gex_regime": "unknown",
                "gex_call_wall": None,
                "gex_put_wall": None,
                "gex_flip_point": None,
                "last_signal": "Warming up…",
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            })
            logger.info("bot_state reset — stale values cleared")
        except Exception as exc:
            logger.warning("bot_state reset failed: %s", exc)

    # ── 3. Start heartbeat (if available + Supabase present) ──────────
    heartbeat_task: Optional[asyncio.Task] = None
    if start_heartbeat is not None and components.supabase is not None:
        try:
            adapter = _RiskManagerAsyncAdapter(components.risk, components.broker)
            heartbeat_task = asyncio.create_task(
                start_heartbeat(components.supabase, adapter)
            )
            logger.info("Heartbeat started")
        except Exception as exc:
            logger.warning("Heartbeat start failed: %s", exc)

    # ── 3b. Start BotStateSync — full dashboard state every 5s ────────
    state_sync: Optional[Any] = None
    state_sync_task: Optional[asyncio.Task] = None
    if BotStateSync is not None and components.supabase is not None:
        try:
            state_sync = BotStateSync(
                client=components.supabase,
                state_provider=lambda: _make_state_snapshot(components, state),
                interval_s=5.0,
            )
            state_sync_task = asyncio.create_task(state_sync.start())
            logger.info("BotStateSync started — dashboard will show RUNNING")
        except Exception as exc:
            logger.warning("BotStateSync start failed: %s", exc)

    # ── 4. Warm-up: preload historical bars so detectors start primed ─
    seeded = await _warmup_historical_bars(components, state)
    if seeded >= MIN_WARMUP_BARS_FOR_TRADING:
        state.warmup_complete = True
        logger.info(
            "Warm-up complete: %d bars loaded (>= %d required) — trading enabled",
            seeded, MIN_WARMUP_BARS_FOR_TRADING,
        )
    elif seeded == 0:
        logger.warning(
            "Running with cold detectors — first %d WS bars will be "
            "used to build context before strategies can fire",
            ROLLING_1MIN_BARS // 50,
        )
    else:
        logger.warning(
            "Partial warm-up: %d bars loaded (need %d) — trading BLOCKED "
            "until enough bars flow in from WS",
            seeded, MIN_WARMUP_BARS_FOR_TRADING,
        )

    # ── 5. Main daily loop ────────────────────────────────────────────
    shutdown = False

    def _request_shutdown(*_):
        nonlocal shutdown
        logger.warning("Shutdown requested")
        shutdown = True

    # Register graceful shutdown on SIGINT (best effort — Windows signal support is limited)
    try:
        signal.signal(signal.SIGINT, _request_shutdown)
    except Exception:
        pass

    try:
        while not shutdown:
            now = datetime.now(_CT)   # always CT — avoids machine-tz drift
            today = now.date()

            # New day detection
            if state.current_session_date != today:
                state.current_session_date = today
                _reset_for_new_day(components, state)
                # If the engine starts (or restarts) after hard-close time with
                # no tracked open positions, skip the routine end-of-day flatten.
                # Without this, a cold start at 7 PM would immediately fire
                # "FLATTEN ALL: daily_hard_close" against an account with nothing
                # open — generating a spurious 404 and misleading CRITICAL log.
                if (
                    not state.open_positions
                    and (
                        now.hour > HARD_CLOSE_HOUR
                        or (now.hour == HARD_CLOSE_HOUR and now.minute >= HARD_CLOSE_MIN)
                    )
                ):
                    logger.info(
                        "Engine started post-market (%02d:%02d CT) with no open "
                        "positions — skipping hard-close flatten",
                        now.hour, now.minute,
                    )
                    state.hard_close_done = True

            # Pre-market scan — runs once per day. Fires on startup and on
            # daily reset. Finnhub + Alpha Vantage + Claude all return valid
            # data at any hour, so there's no reason to wait until 06:00 CT.
            # (The PREMARKET_HOUR constant is kept only for documentation.)
            if not state.premarket_done:
                await _run_premarket_scan(components, state)

            # SWC re-scan at 00:45 CT — before London Kill Zone (01:00 CT)
            if (not state.swc_london_rescan_done
                    and now.hour == SWC_LONDON_HOUR
                    and now.minute >= SWC_LONDON_MIN):
                await _run_swc_rescan(components, state, "00:45")
                state.swc_london_rescan_done = True

            # SWC re-scan at 08:15 CT — before NY AM Kill Zone (08:30 CT)
            if (not state.swc_nyam_rescan_done
                    and now.hour == SWC_NY_AM_HOUR
                    and now.minute >= SWC_NY_AM_MIN):
                await _run_swc_rescan(components, state, "08:15")
                state.swc_nyam_rescan_done = True

            # Hard close check (in addition to the per-bar check)
            if (not state.hard_close_done
                    and (now.hour > HARD_CLOSE_HOUR
                         or (now.hour == HARD_CLOSE_HOUR
                             and now.minute >= HARD_CLOSE_MIN))):
                await _flatten_all(components, state, reason="daily_hard_close")
                state.hard_close_done = True
                await _send_daily_summary(components, state)

            await asyncio.sleep(10)

    except asyncio.CancelledError:
        logger.info("Main loop cancelled")
    except Exception as exc:
        logger.critical("Unhandled exception in main loop: %s", exc, exc_info=True)
        await _flatten_all(components, state, reason="unhandled_exception", emergency=True)

    # ── 6. Graceful shutdown ──────────────────────────────────────────
    logger.info("Shutting down...")

    # Mark bot offline in dashboard before tearing down
    if components.supabase is not None:
        try:
            components.supabase.update_bot_state({
                "is_running": False,
                "shield_active": False,
                "position_count": 0,
            })
        except Exception as exc:
            logger.warning("Failed to mark bot offline: %s", exc)

    if state_sync is not None:
        await state_sync.stop()
    if state_sync_task is not None:
        try:
            await state_sync_task
        except asyncio.CancelledError:
            pass

    if heartbeat_task is not None:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

    try:
        await components.broker.close()
    except Exception as exc:
        logger.warning("Broker close raised: %s", exc)

    logger.info("AlgoICT engine stopped cleanly")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="algoict",
        description="AlgoICT — ICT/SWC/GEX/VPIN trading engine",
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode: paper (Practice Account) or live (Combine)",
    )
    # MLL protection flags (default ON for both paper and live — the whole
    # point of paper is to simulate Combine rules). Thresholds default to
    # M17b validated values (Combine rolling pass rate 19/20 = 95%).
    parser.add_argument(
        "--no-topstep",
        action="store_true",
        help="Disable Topstep MLL-aware risk protection (NOT recommended — "
             "default is ON for both paper and live).",
    )
    parser.add_argument(
        "--mll-warning-pct",
        type=float,
        default=0.40,
        help="MLL warning zone threshold (fraction of MLL). -25%% size + "
             "min_confluence +1 when DD >= this. Default 0.40 = $800.",
    )
    parser.add_argument(
        "--mll-caution-pct",
        type=float,
        default=0.60,
        help="MLL caution zone threshold. -50%% size + min_confluence +2 "
             "when DD >= this. Default 0.60 = $1,200 (validated 2026-04-17).",
    )
    parser.add_argument(
        "--mll-stop-pct",
        type=float,
        default=0.85,
        help="MLL stop zone threshold. No new trades when DD >= this. "
             "Default 0.85 = $1,700 (validated 2026-04-17).",
    )
    return parser.parse_args()


def _confirm_live_mode() -> bool:
    """Interactive confirmation gate for live Combine trading."""
    print()
    print("=" * 60)
    print("  !!! LIVE MODE — Topstep Combine !!!")
    print("=" * 60)
    print("You are about to trade with real Combine capital.")
    print("Risk rules: $250/trade, $750 kill switch, $1,500 cap, 3pm hard close.")
    print("Topstep rules: $2K MLL (trailing), $1K DLL, $3K profit target.")
    print()
    answer = input("Type 'YES I CONFIRM' to proceed, anything else to abort: ").strip()
    return answer == "YES I CONFIRM"


# ---------------------------------------------------------------------------
# Single-instance lock (cross-process dedup defense)
# ---------------------------------------------------------------------------
#
# On 2026-04-17 three zombie engine instances ran overnight (startup banners
# 22:31 / 22:53 / 23:01 CT 2026-04-16). At 04:31 CT Friday a single London
# ny_am signal fired 6 Market BUY orders — each instance independently
# passed its per-process dedup (EngineState.executed_signals,
# Strategy._last_evaluated_bar_ts) and submitted orders. In-process dedup
# is necessary but not sufficient; concurrent processes must be prevented
# at startup, before any component initialises.
#
# Cross-host distributed lock is NOT needed — the engine runs on one Windows
# box. A PID file with liveness check is enough.

_LOCK_PATH = Path(__file__).resolve().parent / ".engine.lock"


def _is_pid_alive(pid: int) -> bool:
    """Return True if a process with this PID is currently running.

    Uses os.kill(pid, 0): zero signal, no-op if process exists, raises
    ProcessLookupError if not. On Windows os.kill with signal 0 works the
    same way for querying existence.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        # ProcessLookupError: definitely dead.
        # OSError (PermissionError in particular on Windows): process exists
        # but belongs to another user / is protected. Treat as alive to be
        # safe — we'd rather fail-closed than fire duplicate orders.
        import errno
        if isinstance(sys.exc_info()[1], PermissionError):
            return True
        exc = sys.exc_info()[1]
        if hasattr(exc, "errno") and exc.errno == errno.EPERM:
            return True
        return False


def _release_engine_lock() -> None:
    """Remove the lock file if we own it. Safe to call multiple times."""
    try:
        if not _LOCK_PATH.exists():
            return
        try:
            stored_pid = int(_LOCK_PATH.read_text().strip())
        except (ValueError, OSError):
            stored_pid = -1
        if stored_pid == os.getpid():
            _LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        # Never let cleanup crash the shutdown path.
        pass


def _acquire_engine_lock() -> bool:
    """Refuse to start if another engine instance is already running.

    Returns True on success (lock acquired), False if another live instance
    owns the lock. Registers atexit + signal handlers so the lock is
    released on normal exit, Ctrl-C, or SIGTERM.
    """
    if _LOCK_PATH.exists():
        try:
            stored_pid = int(_LOCK_PATH.read_text().strip())
        except (ValueError, OSError):
            stored_pid = -1
        if stored_pid > 0 and stored_pid != os.getpid() and _is_pid_alive(stored_pid):
            print(
                f"[FATAL] Another AlgoICT engine is already running "
                f"(PID {stored_pid}). Kill it first:\n"
                f"         taskkill /F /PID {stored_pid}\n"
                f"         (or delete {_LOCK_PATH} if you are sure no other "
                f"instance is alive)",
                file=sys.stderr,
            )
            return False
        # Stale lock — previous process exited without cleanup. Reclaim.
        try:
            _LOCK_PATH.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        _LOCK_PATH.write_text(str(os.getpid()))
    except OSError as exc:
        print(f"[FATAL] Cannot write lock file {_LOCK_PATH}: {exc}", file=sys.stderr)
        return False

    atexit.register(_release_engine_lock)

    def _signal_release(signum, _frame):
        _release_engine_lock()
        # Propagate the default behavior for the signal.
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    # SIGTERM on POSIX / taskkill triggers it on Windows for most cases;
    # SIGINT covers Ctrl-C. SIGBREAK on Windows covers Ctrl-Break.
    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _signal_release)
            except (ValueError, OSError):
                # Some signals aren't settable from non-main threads.
                pass

    return True


def main() -> int:
    args = _parse_args()

    # Validate MLL threshold ordering — zones must be monotonically
    # increasing: warning < caution < stop. Otherwise the zone
    # classifier would produce nonsensical transitions (e.g. a DD
    # that's both "caution" and "warning"). Fail fast at argparse
    # time rather than deep inside RiskManager. Meta-audit 2026-04-17.
    if not (0 <= args.mll_warning_pct < args.mll_caution_pct < args.mll_stop_pct <= 1):
        print(
            f"[FATAL] Invalid MLL thresholds: "
            f"warning={args.mll_warning_pct}, "
            f"caution={args.mll_caution_pct}, "
            f"stop={args.mll_stop_pct}. "
            f"Required: 0 <= warning < caution < stop <= 1",
            file=sys.stderr,
        )
        return 2

    if not _acquire_engine_lock():
        return 1

    if args.mode == "live":
        if not _confirm_live_mode():
            print("Live mode aborted.")
            _release_engine_lock()
            return 1

    try:
        asyncio.run(run(
            mode=args.mode,
            topstep_mode=not args.no_topstep,
            mll_warning_pct=args.mll_warning_pct,
            mll_caution_pct=args.mll_caution_pct,
            mll_stop_pct=args.mll_stop_pct,
        ))
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    finally:
        _release_engine_lock()


if __name__ == "__main__":
    sys.exit(main())
