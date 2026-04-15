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
import logging
import signal
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, time as dt_time
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("algoict.main")


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

# Intelligence layers — may not exist yet
_SWC_RUN = _try_import("sentiment.swc_engine", "run_premarket_scan")
_GEX_RUN = _try_import("gamma.gex_engine", "run_premarket_scan")
VPINCalculator = _try_import("toxicity.vpin_calculator", "VPINCalculator")
_POST_MORTEM = _try_import("agents.post_mortem", "analyze_loss")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLLING_1MIN_BARS = 5000        # Keep ~3 days of 1-min data in memory
PREMARKET_HOUR = 6              # 6:00 AM CT — SWC + GEX pre-market scan
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

    # SWC re-scan flags (prevent double-trigger within the same day)
    swc_london_rescan_done: bool = False
    swc_nyam_rescan_done: bool = False

    # Intelligence snapshots
    swc_snapshot: Optional[dict] = None
    gex_snapshot: Optional[dict] = None

    # Open position tracking — {order_id: {...}}
    open_positions: dict = None

    def __post_init__(self):
        if self.bars_1min is None:
            self.bars_1min = pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"]
            )
        if self.last_completed_tf_ts is None:
            self.last_completed_tf_ts = {}
        if self.open_positions is None:
            self.open_positions = {}


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
    vpin: Optional[Any] = None


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


def _init_components(mode: str) -> Components:
    """
    Construct every component. Required modules crash on failure; optional
    modules (Supabase, Telegram, VPIN) degrade to None.
    """
    logger.info("Initializing components (mode=%s)...", mode)

    # ── Broker ────────────────────────────────────────────────────────
    broker = TopstepXClient()

    # ── Risk + timeframes ─────────────────────────────────────────────
    risk = RiskManager()
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

    # ── Optional: VPIN calculator ─────────────────────────────────────
    vpin = None
    if VPINCalculator is not None:
        try:
            vpin = VPINCalculator(num_buckets=50)
            logger.info("VPIN calculator ready")
        except Exception as exc:
            logger.warning("VPIN unavailable: %s", exc)

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
    )

    # Stash the state_ref on components so run() can wire it up
    components._state_ref = state_ref  # type: ignore[attr-defined]
    return components


# ---------------------------------------------------------------------------
# Pre-market scan
# ---------------------------------------------------------------------------

async def _run_premarket_scan(components: Components, state: EngineState) -> None:
    """
    Run SWC and GEX scans at 06:00 CT. Apply results to RiskManager.

    Both modules are optional and independently fail-safe.
    """
    logger.info("=" * 60)
    logger.info("  PRE-MARKET SCAN (%s)", datetime.now().strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 60)

    # ── SWC (sentiment) ───────────────────────────────────────────────
    if _SWC_RUN is not None:
        try:
            swc = await _maybe_await(_SWC_RUN())
            state.swc_snapshot = swc
            if isinstance(swc, dict):
                min_conf_adj = int(swc.get("min_confluence_adj", 0))
                pos_mult = float(swc.get("position_multiplier", 1.0))
                components.risk.set_swc_overrides(min_conf_adj, pos_mult)
                logger.info("SWC applied: adj=+%d mult=%.2f", min_conf_adj, pos_mult)
        except Exception as exc:
            logger.warning("SWC pre-market scan failed: %s", exc)
    else:
        logger.info("SWC module not available — skipping sentiment scan")

    # ── GEX (gamma) ───────────────────────────────────────────────────
    if _GEX_RUN is not None:
        try:
            gex = await _maybe_await(_GEX_RUN())
            state.gex_snapshot = gex
            logger.info("GEX snapshot captured")
        except Exception as exc:
            logger.warning("GEX pre-market scan failed: %s", exc)
    else:
        logger.info("GEX module not available — skipping gamma scan")

    # Alert
    if components.telegram is not None:
        try:
            components.telegram.send_heartbeat_alert("OK")
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

    old_mood = state.swc_snapshot.get("mood") if state.swc_snapshot else None

    try:
        swc = await _maybe_await(_SWC_RUN())

        if not isinstance(swc, dict):
            logger.warning("SWC re-scan [%s CT] returned unexpected type — skipping", time_str)
            return

        new_mood = swc.get("mood", "unknown")
        new_adj  = int(swc.get("min_confluence_adj", 0))
        new_mult = float(swc.get("position_multiplier", 1.0))

        components.risk.set_swc_overrides(new_adj, new_mult)
        state.swc_snapshot = swc

        if old_mood is not None and new_mood != old_mood:
            logger.info(
                "SWC re-scan [%s CT]: mood changed %s \u2192 %s",
                time_str, old_mood, new_mood,
            )
            if components.telegram is not None:
                try:
                    components.telegram.send_emergency_alert(
                        f"SWC re-scan [{time_str} CT]: mood changed {old_mood} \u2192 {new_mood}"
                        f"\nMin conf: +{new_adj} | Pos mult: {new_mult:.2f}"
                    )
                except Exception as exc:
                    logger.error("Failed to send SWC rescan Telegram alert: %s", exc)
        else:
            shown_mood = new_mood if old_mood is None else old_mood
            logger.info("SWC re-scan [%s CT]: mood unchanged (%s)", time_str, shown_mood)

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
            components.detectors["fvg"].update_mitigation(float(df_5min.iloc[-1]["close"]))
            components.detectors["ob"].update_mitigation(df_5min)
        except Exception as exc:
            logger.warning("5min detector update failed: %s", exc)
        state.last_completed_tf_ts["5min"] = last_5_ts
        updated["5min"] = True

    if last_15_ts is not None and last_15_ts != state.last_completed_tf_ts.get("15min"):
        try:
            components.detectors["structure"].update(df_15min, "15min")
        except Exception as exc:
            logger.warning("15min structure update failed: %s", exc)
        state.last_completed_tf_ts["15min"] = last_15_ts
        updated["15min"] = True

    return updated


# ---------------------------------------------------------------------------
# Signal execution
# ---------------------------------------------------------------------------

async def _execute_signal(
    signal,
    components: Components,
    state: EngineState,
) -> None:
    """Submit entry + stop + target orders, log, and alert."""
    logger.info("EXECUTING signal: %s", signal)

    broker = components.broker
    side = "buy" if signal.direction == "long" else "sell"
    exit_side = "sell" if side == "buy" else "buy"

    try:
        entry_order = await broker.submit_market_order(
            symbol=signal.symbol,
            side=side,
            contracts=signal.contracts,
        )
    except Exception as exc:
        logger.error("Entry order failed: %s", exc)
        return

    try:
        stop_order = await broker.submit_stop_order(
            symbol=signal.symbol,
            side=exit_side,
            contracts=signal.contracts,
            stop_price=signal.stop_price,
        )
    except Exception as exc:
        logger.error("Stop order failed: %s", exc)
        stop_order = None

    try:
        target_order = await broker.submit_limit_order(
            symbol=signal.symbol,
            side=exit_side,
            contracts=signal.contracts,
            limit_price=signal.target_price,
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
    }

    # Log to Supabase
    if components.supabase is not None:
        try:
            components.supabase.write_signal({
                "timestamp": str(signal.timestamp),
                "symbol": signal.symbol,
                "signal_type": signal.direction,
                "price": signal.entry_price,
                "confluence_score": signal.confluence_score,
                **signal.confluence_breakdown,
            })
        except Exception as exc:
            logger.warning("Supabase signal write failed: %s", exc)

    # Telegram alert
    if components.telegram is not None:
        try:
            components.telegram.send_trade_alert(
                symbol=signal.symbol,
                side=side.upper(),
                contracts=signal.contracts,
                entry_price=signal.entry_price,
                confluence_score=signal.confluence_score,
            )
        except Exception as exc:
            logger.warning("Telegram alert failed: %s", exc)


# ---------------------------------------------------------------------------
# Trading loop — called on every new 1-min bar
# ---------------------------------------------------------------------------

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

        # ── 3. VPIN update ────────────────────────────────────────────
        if components.vpin is not None:
            try:
                pass   # VPIN operates on volume buckets, not raw bars — wired separately
            except Exception as exc:
                logger.debug("VPIN update failed: %s", exc)

        ts = state.bars_1min.index[-1]

        # ── 4. Hard close ─────────────────────────────────────────────
        if (not state.hard_close_done
                and ts.hour == HARD_CLOSE_HOUR
                and ts.minute >= HARD_CLOSE_MIN):
            logger.warning("HARD CLOSE reached at %s — flattening all", ts)
            await _flatten_all(components, state, reason="hard_close")
            state.hard_close_done = True
            return

        if state.hard_close_done:
            return

        # ── 5. Strategy evaluation ────────────────────────────────────
        bars = state.bars_1min
        if len(bars) < 50:
            return  # warm-up

        try:
            df_5min = components.tf_manager.aggregate(bars, "5min")
            df_15min = components.tf_manager.aggregate(bars, "15min")
        except Exception as exc:
            logger.debug("TF aggregation failed in strategy eval: %s", exc)
            return

        # NY AM Reversal (5min entry)
        try:
            signal = components.ny_am_strategy.evaluate(df_5min, df_15min)
            if signal is not None:
                allowed, reason = components.risk.can_trade()
                if allowed:
                    await _execute_signal(signal, components, state)
                else:
                    logger.info("NY AM signal suppressed: %s", reason)
        except Exception as exc:
            logger.exception("NY AM strategy raised: %s", exc)

        # Silver Bullet (1min entry)
        try:
            signal = components.silver_bullet_strategy.evaluate(bars, df_5min)
            if signal is not None:
                allowed, reason = components.risk.can_trade()
                if allowed:
                    await _execute_signal(signal, components, state)
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
) -> None:
    """Close every open position via the broker."""
    logger.warning("FLATTEN ALL triggered: %s", reason)
    try:
        await components.broker.flatten_all()
    except Exception as exc:
        logger.error("Broker flatten failed: %s", exc)
    state.open_positions.clear()
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
            components.telegram.send_daily_summary(
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
    state.swc_london_rescan_done = False
    state.swc_nyam_rescan_done = False


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
# Main entry point
# ---------------------------------------------------------------------------

async def run(mode: str = "paper") -> None:
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
        components = _init_components(mode)
    except Exception as exc:
        logger.critical("Failed to initialize components: %s", exc, exc_info=True)
        return

    state = EngineState(mode=mode)
    components._state_ref["bars_1min"] = state.bars_1min  # type: ignore[attr-defined]

    # ── 2. Connect broker ─────────────────────────────────────────────
    try:
        await components.broker.connect()
    except Exception as exc:
        logger.critical("Broker connect failed: %s", exc, exc_info=True)
        return

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

    # ── 4. Subscribe to 1-min bars ────────────────────────────────────
    def _bar_callback(bar: dict):
        """Schedule async handling on the event loop."""
        asyncio.create_task(_on_new_bar(bar, components, state))

    components.broker.subscribe_bars(state.symbol, _bar_callback)
    logger.info("Subscribed to %s 1-min bars", state.symbol)

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
            now = datetime.now()
            today = now.date()

            # New day detection
            if state.current_session_date != today:
                state.current_session_date = today
                _reset_for_new_day(components, state)

            # Pre-market scan at 06:00 CT (run once per day)
            if not state.premarket_done and now.hour >= PREMARKET_HOUR:
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
                    and now.hour >= HARD_CLOSE_HOUR
                    and now.minute >= HARD_CLOSE_MIN):
                await _flatten_all(components, state, reason="daily_hard_close")
                state.hard_close_done = True
                await _send_daily_summary(components, state)

            await asyncio.sleep(10)

    except asyncio.CancelledError:
        logger.info("Main loop cancelled")
    except Exception as exc:
        logger.critical("Unhandled exception in main loop: %s", exc, exc_info=True)
        await _flatten_all(components, state, reason="unhandled_exception")

    # ── 6. Graceful shutdown ──────────────────────────────────────────
    logger.info("Shutting down...")

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


def main() -> int:
    args = _parse_args()

    if args.mode == "live":
        if not _confirm_live_mode():
            print("Live mode aborted.")
            return 1

    try:
        asyncio.run(run(mode=args.mode))
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
