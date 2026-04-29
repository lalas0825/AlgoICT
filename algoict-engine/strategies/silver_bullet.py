"""
strategies/silver_bullet.py
============================
ICT Silver Bullet — pure FVG entry across three daily 60-minute windows.

Rewritten 2026-04-20 against the ICT 2024 Mentorship video. The prior
implementation used an OB-based entry (same as NY AM Reversal) and a
wrong 10:00-11:00 CT window; ICT is explicit that Silver Bullet is
FVG-only and that the AM window is 10:00-11:00 ET = 9:00-10:00 CT.

Setup
-----
1. Time:      inside one of three Silver Bullet kill zones (all in CT):
                - london_silver_bullet  : 02:00-03:00 CT = 03:00-04:00 ET
                - silver_bullet         : 09:00-10:00 CT = 10:00-11:00 ET
                - pm_silver_bullet      : 13:00-14:00 CT = 14:00-15:00 ET
2. FVG:       first bullish or bearish FVG that forms inside the active
              window on the 1-min entry timeframe. Direction of the FVG
              determines trade direction — ICT does NOT require HTF bias
              (section 3.3: "no es necesariamente el bias, predominantemente
              solo tienes que considerar dónde está el próximo nivel de
              atracción de liquidez").
3. Sweep:     a recent liquidity sweep of the opposite-side pool must
              have occurred before the FVG formed (SSL/equal_lows for a
              long, BSL/equal_highs for a short). Section 3.3: "requires
              sweep previo ... si no hay un barrido ... no tenemos una
              operación".
4. Structure: a 5-min MSS or BOS in the FVG direction must exist within
              the recent context (ICT: sweep → MSS with displacement
              creates the FVG).
5. Framework: distance from entry to the next unswept liquidity pool in
              the trade direction must be >= 10 MNQ points (40 ticks) —
              ICT section 8.1: "minimum trade framework should be 10
              points or 40 ticks for index futures".
6. Risk:      $250 risk, max 1 trade per SB window (up to 3 trades per day).
7. Cancel:    no new entries in the last 10 minutes of the active window.

Entry / Stop / Target (ICT canonical)
-------------------------------------
Long (bullish FVG):
  entry  = FVG.top   + 1 tick   (section 2.3: "candle 3 low plus one tick")
  stop   = FVG.stop_reference - 1 tick   (candle 1 low; section 5.1)
  target = nearest unswept BSL/PDH/PWH/equal_highs above entry, >= 10 pts

Short (bearish FVG, mirror):
  entry  = FVG.bottom - 1 tick   (section 2.3)
  stop   = FVG.stop_reference + 1 tick   (candle 1 high)
  target = nearest unswept SSL/PDL/PWL/equal_lows below entry, >= 10 pts

Position sizing uses risk/position_sizer (floor + expand stop).
Position multiplier from risk_manager (SWC/VPIN soft overrides).

The detectors dict must contain populated detector instances:
  detectors = {
      'structure'      : MarketStructureDetector  (with 5min events),
      'fvg'            : FairValueGapDetector    (with 1min FVGs),
      'ob'             : OrderBlockDetector      (with 1min OBs) [optional — not required],
      'displacement'   : DisplacementDetector    (with 1min displacements) [optional],
      'liquidity'      : LiquidityDetector       (instance),
      'confluence'     : ConfluenceScorer        (instance),
      'tracked_levels' : list[LiquidityLevel]    (sweep + target universe),
  }
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Callable
import datetime

import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from risk.position_sizer import calculate_position
from timeframes.htf_bias import BiasResult

logger = logging.getLogger(__name__)


def _ts_hm(ts) -> str:
    """Format a bar timestamp as HH:MM for EVAL log lines."""
    try:
        return ts.strftime("%H:%M")
    except AttributeError:
        return str(ts)


def sb_applicable_score(breakdown: dict) -> tuple[int, int]:
    """
    Compute the SB-applicable sub-score from a ConfluenceResult breakdown.

    Returns (score, max) where:
      score = sum of pts from factors that actually differentiate SB
              setup quality (see config.SB_APPLICABLE_FACTORS)
      max   = the theoretical ceiling (config.SB_APPLICABLE_MAX = 10)

    The full 19-pt score is kept on the Signal/Trade for DB compatibility.
    This sub-score is what we log + send to Telegram so the number is
    interpretable against the SB-specific scale documented in
    SILVER_BULLET_STRATEGY_GUIDE.md §8.
    """
    applicable = config.SB_APPLICABLE_FACTORS
    score = sum(pts for key, pts in breakdown.items() if key in applicable)
    return score, config.SB_APPLICABLE_MAX


# Minutes before the end of a Silver Bullet window in which we refuse to
# open new entries. 10 min aligns with the legacy behavior at 10:50 CT in
# the prior AM-only implementation.
_CANCEL_MINUTES_BEFORE_END = 10


@dataclass
class Signal:
    """Trade signal emitted by a strategy when a setup is found."""

    strategy: str
    symbol: str
    direction: str           # 'long' | 'short'
    entry_price: float
    stop_price: float
    target_price: float
    contracts: int
    confluence_score: int
    confluence_breakdown: dict = field(default_factory=dict)
    confluence_reasons: list = field(default_factory=list)
    timestamp: pd.Timestamp = None
    kill_zone: str = ""

    def __repr__(self) -> str:
        return (
            f"Signal({self.strategy} {self.direction} {self.symbol} "
            f"entry={self.entry_price:.2f} stop={self.stop_price:.2f} "
            f"target={self.target_price:.2f} x{self.contracts} "
            f"score={self.confluence_score} kz={self.kill_zone})"
        )


class SilverBulletStrategy:
    """ICT Silver Bullet — pure FVG entry across three 60-min windows."""

    # v4 "RTH Mode" (2026-04-21): empirical pivot after v3 showed that
    # narrow 60-min SB windows choke trade count and P&L. User decision:
    # trade the full RTH session using the wide KZ definitions (London
    # 01-04 CT, NY AM 08:30-12 CT, NY PM 13:30-15 CT) — ~8h/day coverage.
    # Unlimited trades per zone; rely on config.KILL_SWITCH_LOSSES (3
    # consecutive losses halts the day) + config.DAILY_PROFIT_CAP for
    # risk containment, not an arbitrary per-zone cap.
    KILL_ZONES = ("london", "ny_am", "ny_pm")
    # Effectively unlimited — RiskManager's kill_switch (3 consecutive
    # losses → halt day) is the real guard.
    MAX_TRADES_PER_ZONE = 999
    KILL_ZONE = "ny_am"           # backward-compat (reported when active lookup misses)
    ENTRY_TF = "1min"
    CONTEXT_TF = "5min"
    SYMBOL = "MNQ"
    # ICT MNQ framework minimum (section 8.1). Setups whose nearest liquidity
    # target is less than this distance from entry are rejected.
    MIN_FRAMEWORK_PTS = 10.0
    # v2 hard-filters stay DISABLED (values=0). The v2 versions
    # (MIN_STOP_PTS=8, ENTRY_WAIT_MINUTES=15) were price-dependent and
    # over-filtered low-price years, eliminating the monster winners that
    # carried the edge. RTH coverage + kill-switch-3-losses handles risk
    # at the engine level instead of inside the strategy.
    MIN_STOP_PTS = 0.0            # 0 = disabled
    ENTRY_WAIT_MINUTES = 0        # 0 = disabled
    # Confluence gate stays REMOVED — Q1 2024 confirmed scoring is noise.
    MAX_TRADES = MAX_TRADES_PER_ZONE * 3  # effectively unlimited total

    # Opposite-pool sweep that must precede a long / short setup.
    # 2026-04-27: ICT canonical sweep types expanded to include session
    # highs/lows (AH/AL Asian, LH/LL London, NAH/NAL NY AM, NPH/NPL NY PM).
    # Previously SB only accepted PDH/PDL/PWH/PWL/equal as sweep targets,
    # missing the most temporally-relevant pools — e.g. NY AM typically
    # raids LH or LL before the real move, but those weren't tracked.
    _LONG_SWEEP_TYPES = {
        "SSL", "PDL", "PWL", "equal_lows",
        "AL", "LL", "NAL", "NPL",   # session lows
    }
    _SHORT_SWEEP_TYPES = {
        "BSL", "PDH", "PWH", "equal_highs",
        "AH", "LH", "NAH", "NPH",   # session highs
    }
    # Target pool types in the trade direction.
    _LONG_TARGET_TYPES = {
        "BSL", "PDH", "PWH", "equal_highs",
        "AH", "LH", "NAH", "NPH",
    }
    _SHORT_TARGET_TYPES = {
        "SSL", "PDL", "PWL", "equal_lows",
        "AL", "LL", "NAL", "NPL",
    }

    def __init__(
        self,
        detectors: dict,
        risk_manager,
        session_manager,
        htf_bias_fn: Callable[[float], BiasResult],
    ):
        """
        Parameters
        ----------
        detectors      : dict — populated detector instances + 'tracked_levels'
        risk_manager   : RiskManager — daily P&L state + overrides
        session_manager: SessionManager — kill zone checks
        htf_bias_fn    : callable(price) -> BiasResult — HTF bias (optional;
                         used only for confluence bonus, not as a hard gate)
        """
        self.detectors = detectors
        self.risk = risk_manager
        self.session = session_manager
        self.htf_bias_fn = htf_bias_fn
        self.trades_today: int = 0
        self._trades_by_zone: dict[str, int] = {z: 0 for z in self.KILL_ZONES}
        self._last_evaluated_bar_ts = None
        # Track the last kill zone seen so we can reset the per-session
        # kill switch whenever we enter a DIFFERENT zone. Without this,
        # 3 consecutive losses in London lock NY AM and NY PM out for the
        # rest of the day (confirmed on 56/56 such days in 2024).
        self._last_active_zone: Optional[str] = None
        # Phantom-cleanup cooldown (2026-04-23 fix): after _poll_position_status
        # detects that a placed limit entry NEVER FILLED and cancels all three
        # orders, the underlying FVG/sweep/structure setup is usually STILL
        # valid on the next bar. Without this gate the strategy re-fires the
        # same signal every 1-2 bars, creating a phantom-fire loop that spams
        # Telegram + wastes broker API calls (observed 5 consecutive fires on
        # 2026-04-23 10:36-11:03 CT, all never-filled, all cleaned).
        #
        # Cooldown = 5 bars (5 min). After a cleanup, evaluate() rejects with
        # reason="phantom_cooldown" until this timestamp passes. Reset at
        # daily boundary (see reset_daily()).
        self._phantom_cooldown_until: Optional[pd.Timestamp] = None
        # Diagnostic: most-recent rejection record. main.py consults this
        # after evaluate() returns None to decide whether to push a
        # near-miss Telegram alert. `is_near_miss=True` means the setup
        # was structurally interesting (e.g. FVG present but no sweep yet)
        # — worth surfacing. Routine rejects (outside_kz, max_trades) set
        # `is_near_miss=False` so verbose mode doesn't flood.
        self.last_rejection: Optional[dict] = None

        # 2026-04-29 hardening — same-setup-stopout cooldown state.
        # On a stop-out, record (entry_price, ts, kz). If a subsequent
        # signal in the SAME kz tries to fire at an entry within
        # SB_SAME_SETUP_PRICE_TOL_PTS within SB_SAME_SETUP_COOLDOWN_MIN
        # of the loss → reject. ICT: a stopped-out FVG is invalidated.
        self._last_stopped_entry_price: Optional[float] = None
        self._last_stopped_ts = None
        self._last_stopped_kz: str = ""

    def _set_rejection(
        self,
        ts,
        reason: str,
        kill_zone: str,
        is_near_miss: bool = False,
        **details,
    ) -> None:
        """Internal: stash rejection context for observers (main.py, tests)."""
        self.last_rejection = {
            "reason": reason,
            "ts": ts,
            "kill_zone": kill_zone,
            "is_near_miss": is_near_miss,
            "details": details,
        }

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def evaluate(
        self,
        candles_1min: pd.DataFrame,
        candles_5min: pd.DataFrame,
    ) -> Optional[Signal]:
        """Run a Silver Bullet evaluation on the latest 1-min candle."""

        # ── 1. Pre-conditions ──────────────────────────────────────────
        if candles_1min.empty or candles_5min.empty:
            return None

        ts = candles_1min.index[-1]
        last_close = float(candles_1min.iloc[-1]["close"])

        # Layer-1 dedup: cache only successful fires.
        if ts == self._last_evaluated_bar_ts:
            return None

        # Phantom-cleanup cooldown (2026-04-23 fix): if a recent fire had
        # its limit entry cancelled because price never reached it, block
        # new fires for 5 bars to avoid the re-fire loop where the same
        # FVG/sweep/structure setup keeps re-triggering while price stays
        # out of reach.
        if (
            self._phantom_cooldown_until is not None
            and ts < self._phantom_cooldown_until
        ):
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                "reason=phantom_cooldown (until %s)",
                _ts_hm(ts), _ts_hm(self._phantom_cooldown_until),
            )
            self._set_rejection(
                ts, "phantom_cooldown", "n/a", is_near_miss=False,
                cooldown_until=str(self._phantom_cooldown_until),
            )
            return None

        active_zone = next(
            (kz for kz in self.KILL_ZONES if self.session.is_kill_zone(ts, kz)),
            None,
        )

        # Per-session kill switch: when we enter a NEW kill zone, reset the
        # 3-consecutive-loss counter. Each window (London, NY AM, NY PM)
        # gets its own budget — losing 3 in London does NOT lock NY out.
        # Daily P&L keeps accumulating toward DLL as a separate guard.
        if active_zone is not None and active_zone != self._last_active_zone:
            if self._last_active_zone is not None:
                # Zone change — reset kill switch for the fresh session.
                self.risk.reset_kill_switch_only(
                    reason=f"kz_change {self._last_active_zone}->{active_zone}"
                )
            self._last_active_zone = active_zone

        if active_zone is None:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=outside_kz",
                _ts_hm(ts),
            )
            return None

        # ── 2026-04-29 NEWS BLACKOUT ──────────────────────────────────
        # Block trading around scheduled high-impact events (FOMC, CPI,
        # NFP). Caught 2026-04-29 NY PM: bot took 3 losers (-$331.50)
        # in the post-FOMC whipsaw despite SWC mood explicitly warning.
        if config.cfg("NEWS_BLACKOUT_ENABLED", True):
            try:
                from sentiment.economic_calendar import is_in_news_blackout
                in_blk, blk_event = is_in_news_blackout(
                    ts,
                    before_min=config.cfg("NEWS_BLACKOUT_MIN_BEFORE", 30),
                    after_min=config.cfg("NEWS_BLACKOUT_MIN_AFTER", 60),
                    min_risk=config.cfg("NEWS_BLACKOUT_MIN_RISK", "high"),
                )
                if in_blk and blk_event is not None:
                    logger.info(
                        "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                        "reason=news_blackout (%s @%s, risk=%s)",
                        _ts_hm(ts), blk_event.name, blk_event.time_ct, blk_event.risk,
                    )
                    self._set_rejection(
                        ts, "news_blackout", active_zone, is_near_miss=False,
                        event_name=blk_event.name,
                        event_time=blk_event.time_ct,
                        event_risk=blk_event.risk,
                    )
                    return None
            except Exception as exc:
                logger.debug("News blackout check failed: %s", exc)

        # Dynamic cancel check: last 10 minutes of the active window.
        kz_cfg = config.KILL_ZONES.get(active_zone, {})
        start_h, start_m = kz_cfg.get("start", (0, 0))
        end_h, end_m = kz_cfg.get("end", (0, 0))
        cancel_total_min = end_h * 60 + end_m - _CANCEL_MINUTES_BEFORE_END
        kz_start_total_min = start_h * 60 + start_m
        arm_total_min = kz_start_total_min + self.ENTRY_WAIT_MINUTES
        ts_total_min = ts.hour * 60 + ts.minute
        if ts_total_min >= cancel_total_min:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                "reason=past_cancel_time (zone=%s cancels at %02d:%02d)",
                _ts_hm(ts), active_zone,
                cancel_total_min // 60, cancel_total_min % 60,
            )
            return None

        # Arm-wait gate (disabled by default in v3; ENTRY_WAIT_MINUTES=0).
        # Kept as an optional guard for A/B experiments; set the class
        # constant to >0 to re-enable the early-window quarantine.
        if self.ENTRY_WAIT_MINUTES > 0 and ts_total_min < arm_total_min:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                "reason=pre_arm (zone=%s arms at %02d:%02d)",
                _ts_hm(ts), active_zone,
                arm_total_min // 60, arm_total_min % 60,
            )
            return None

        if self.risk.check_hard_close(ts):
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=past_hard_close",
                _ts_hm(ts),
            )
            return None

        # can_trade_in_kz() combines can_trade() + per-KZ losing-trade cap
        # + ladder-exhausted check. When the ladder or KZ caps are disabled
        # (default), this is identical to can_trade().
        if hasattr(self.risk, "can_trade_in_kz"):
            allowed, reason = self.risk.can_trade_in_kz(active_zone)
        else:
            allowed, reason = self.risk.can_trade()
        if not allowed:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=risk_blocked (%s)",
                _ts_hm(ts), reason,
            )
            # Surface KZ-cap + ladder-exhaustion as near-miss so Telegram
            # verbose mode logs the fact that a KZ's budget just closed.
            if reason.startswith("kz_loss_cap:") or reason == "ladder_exhausted":
                self._set_rejection(
                    ts, reason, active_zone, is_near_miss=True,
                    losses_today=getattr(self.risk, "_losses_today", None),
                    kz_losing_trades=dict(
                        getattr(self.risk, "_kz_losing_trades", {}) or {}
                    ),
                )
            return None

        if self._trades_by_zone.get(active_zone, 0) >= self.MAX_TRADES_PER_ZONE:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=max_trades",
                _ts_hm(ts),
            )
            return None

        # ── 2. Pick the first FVG formed inside this window ────────────
        # Direction is determined BY the FVG, not by HTF bias (ICT rule).
        kz_start_h, kz_start_m = kz_cfg.get("start", (0, 0))
        kz_start = ts.replace(
            hour=kz_start_h, minute=kz_start_m, second=0, microsecond=0,
        )
        all_active_fvgs = self.detectors["fvg"].get_active(timeframe="1min")
        fvgs_in_window = [
            f for f in all_active_fvgs if f.timestamp >= kz_start
        ]
        if not fvgs_in_window:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                "reason=no_valid_setup (no_fvg_in_window, zone=%s)",
                _ts_hm(ts), active_zone,
            )
            self._set_rejection(
                ts, "no_fvg_in_window", active_zone, is_near_miss=True,
                active_fvgs_total=len(all_active_fvgs),
            )
            return None
        # First FVG by timestamp (ICT: "first FVG that forms after open").
        fvg = min(fvgs_in_window, key=lambda f: f.timestamp)
        bias_dir = fvg.direction                    # 'bullish' | 'bearish'
        direction = "long" if bias_dir == "bullish" else "short"

        # ── 3. Sweep validation ────────────────────────────────────────
        # ICT: a sweep of opposite-side liquidity must have occurred
        # BEFORE the FVG. Accept any currently-swept level of the
        # appropriate type — a stronger check would compare timestamps,
        # but LiquidityLevel.timestamp is DETECTED time not SWEPT time,
        # so a simple "was swept" is the best proxy with current state.
        tracked_levels = self.detectors.get("tracked_levels", [])
        sweep_types = (
            self._LONG_SWEEP_TYPES if direction == "long" else self._SHORT_SWEEP_TYPES
        )
        sweeps = [
            lvl for lvl in tracked_levels
            if lvl.swept and lvl.type in sweep_types
        ]
        if not sweeps:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                "reason=no_valid_setup (no_sweep of %s)",
                _ts_hm(ts),
                "SSL/equal_lows" if direction == "long" else "BSL/equal_highs",
            )
            self._set_rejection(
                ts, "no_opposite_sweep", active_zone, is_near_miss=True,
                fvg_direction=bias_dir, fvg_top=float(fvg.top),
                fvg_bottom=float(fvg.bottom),
                expected_sweep_of=(
                    "SSL/equal_lows" if direction == "long"
                    else "BSL/equal_highs"
                ),
            )
            return None

        # ── 2026-04-29 FRESH-SWEEP WINDOW ──────────────────────────────
        # ICT canonical: post-sweep reversal happens within minutes,
        # not hours. After SB_MAX_SWEEP_AGE_MINUTES the sweep is
        # "consumed" — context has shifted, the original liquidity
        # grab is no longer the active narrative. Caught 2026-04-29:
        # NAH swept at 10:10 CT, bot fired SHORTs 3+ hours later
        # (13:32-14:07), all stopped out. Filter by `swept_at` age.
        max_sweep_age_min = config.cfg("SB_MAX_SWEEP_AGE_MINUTES", 60)
        if max_sweep_age_min and max_sweep_age_min > 0:
            fresh_sweeps = []
            for lvl in sweeps:
                swept_at = getattr(lvl, "swept_at", None)
                if swept_at is None:
                    # Pre-2026-04-26 levels lack swept_at — keep them
                    # for backward compat (tests, replay).
                    fresh_sweeps.append(lvl)
                    continue
                try:
                    age_s = (ts - swept_at).total_seconds()
                    if age_s <= max_sweep_age_min * 60:
                        fresh_sweeps.append(lvl)
                except Exception:
                    fresh_sweeps.append(lvl)
            if not fresh_sweeps:
                # Stash the freshest oldness for log clarity.
                oldest = min(
                    (
                        (ts - getattr(lvl, "swept_at", ts)).total_seconds() / 60
                        for lvl in sweeps
                        if getattr(lvl, "swept_at", None) is not None
                    ),
                    default=999,
                )
                logger.info(
                    "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                    "reason=stale_sweep (oldest %.0fmin > %dmin threshold)",
                    _ts_hm(ts), oldest, max_sweep_age_min,
                )
                self._set_rejection(
                    ts, "stale_sweep", active_zone, is_near_miss=True,
                    fvg_direction=bias_dir,
                    sweep_age_min=round(oldest, 1),
                    threshold_min=max_sweep_age_min,
                )
                return None
            sweeps = fresh_sweeps
        sweep = sweeps[-1]

        # ── 4. 5-min structure in FVG direction ────────────────────────
        # Option B (1-min structure) was tested 2026-04-23 Q1 backtest and
        # REJECTED: noise degraded PF 1.80 → 1.37, P&L -44% vs v9 5-min,
        # max DD nearly doubled ($4.3K → $6.9K). 5-min filters false
        # CHoCHs that the eye mentally discards but detector cannot.
        #
        # Session recency filter (Bug A) still applies — only today's
        # events count. The 2026-04-23 NY AM phantom fires happened
        # because stale events from 2026-04-22 19:45 CT were "satisfying"
        # today's structure check. That bug is fixed here.
        session_start = ts.normalize()  # 00:00 CT today
        structure_events = self.detectors["structure"].get_events(timeframe="5min")
        fresh_events = [
            e for e in structure_events
            if e.timestamp >= session_start
        ]
        # 2026-04-24 Bug C4 (revised): keep CHoCH in the aligned gate
        # (the 7-year $673K backtest was run WITH CHoCH; removing it
        # would change the strategy rather than just fix a bug). But
        # the invalidator filter below was only checking MSS/BOS — so
        # a stale CHoCH aligned event was asymmetrically protected from
        # invalidation by opposite CHoCH events. Symmetric fix: include
        # CHoCH in the invalidator too (see below). Strategy behavior
        # is unchanged except that a bear CHoCH followed by a bull
        # CHoCH now correctly invalidates the bear.
        aligned = [
            e for e in fresh_events
            if e.type in ("MSS", "BOS", "CHoCH") and e.direction == bias_dir
        ]
        if not aligned:
            total_stale = len(structure_events) - len(fresh_events)
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                "reason=no_valid_setup (no_5min_struct in %s, %d events total, "
                "%d from today, stale filtered=%d)",
                _ts_hm(ts), bias_dir,
                len(structure_events), len(fresh_events), total_stale,
            )
            self._set_rejection(
                ts, "no_5min_struct", active_zone, is_near_miss=True,
                fvg_direction=bias_dir,
                sweep_type=sweep.type, sweep_price=float(sweep.price),
                structure_events_total=len(structure_events),
                structure_events_today=len(fresh_events),
                structure_events_stale_filtered=total_stale,
            )
            return None
        last_struct = aligned[-1]

        # ── 2026-04-29 FIX #5 — SMART STRUCTURE VALIDATOR ──────────────
        # Two gates that close the "stale bear MSS used during fresh bull
        # context" hole that caused 3 SHORT losers on 2026-04-29 NY PM.
        #
        # Gate A — last_struct must be RECENT (max age):
        #   Default 60min. ICT canonical: structure shift should be the
        #   catalyst for the FVG forming, so they should be tightly
        #   coupled in time. An MSS from 2 hours ago is no longer the
        #   active narrative.
        #
        # Gate B — count opposite events in recent window:
        #   Default 2+ opposite events in last 30min → invalidate.
        #   Distinguishes single-pullback noise (1 counter event = OK)
        #   from real bias flip (2+ counters = bias actually shifted).
        #   This is a SMART version of the disabled Bug G — the original
        #   triggered on ANY single opposite event and over-rejected
        #   valid setups during normal counter-rallies (Q1 2025 v10
        #   collapsed: WR 21%, PF 0.84). Backtest Q1 2025 with this
        #   version BEFORE relying on it in live.
        if config.cfg("SB_STRUCT_INVALIDATOR_ENABLED", True):
            max_age_min = config.cfg("SB_MAX_STRUCT_AGE_MINUTES", 60)
            opp_count_thresh = config.cfg("SB_INVALIDATOR_OPPOSITE_COUNT", 2)
            opp_window_min = config.cfg("SB_INVALIDATOR_WINDOW_MIN", 30)

            # Gate A: aligned event age
            try:
                age_s = (ts - last_struct.timestamp).total_seconds()
            except Exception:
                age_s = 0
            if max_age_min > 0 and age_s > max_age_min * 60:
                logger.info(
                    "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                    "reason=stale_structure (last %s %s @ %s is %.0fmin old, "
                    "max %dmin)",
                    _ts_hm(ts), last_struct.type, bias_dir,
                    _ts_hm(last_struct.timestamp), age_s / 60, max_age_min,
                )
                self._set_rejection(
                    ts, "stale_structure", active_zone, is_near_miss=True,
                    fvg_direction=bias_dir,
                    last_struct_type=last_struct.type,
                    last_struct_age_min=round(age_s / 60, 1),
                    threshold_min=max_age_min,
                )
                return None

            # Gate B: counter-event count in recent window
            opposite_dir = "bullish" if bias_dir == "bearish" else "bearish"
            window_start = ts
            try:
                from datetime import timedelta as _td
                window_start = ts - _td(minutes=opp_window_min)
            except Exception:
                pass
            recent_opposite = [
                e for e in fresh_events
                if e.type in ("MSS", "BOS", "CHoCH")
                and e.direction == opposite_dir
                and e.timestamp > last_struct.timestamp
                and e.timestamp >= window_start
            ]
            if opp_count_thresh > 0 and len(recent_opposite) >= opp_count_thresh:
                most_recent_opp = recent_opposite[-1]
                logger.info(
                    "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                    "reason=structure_invalidated (last %s %s @ %s superseded "
                    "by %d %s events in last %dmin, most recent %s %s @ %s)",
                    _ts_hm(ts), last_struct.type, bias_dir,
                    _ts_hm(last_struct.timestamp),
                    len(recent_opposite), opposite_dir, opp_window_min,
                    most_recent_opp.type, opposite_dir,
                    _ts_hm(most_recent_opp.timestamp),
                )
                self._set_rejection(
                    ts, "structure_invalidated", active_zone, is_near_miss=True,
                    fvg_direction=bias_dir,
                    last_struct_type=last_struct.type,
                    opposite_count=len(recent_opposite),
                    opposite_dir=opposite_dir,
                    window_min=opp_window_min,
                    most_recent_opp_type=most_recent_opp.type,
                    most_recent_opp_ts=_ts_hm(most_recent_opp.timestamp),
                )
                return None

        # ── Bug G structure invalidation — DISABLED for v11 bisect ────
        # 2026-04-25: Q1 2025 v10 backtest (with this gate) collapsed:
        #   WR 21% (gate ≥40%), PF 0.84 (gate ≥1.5), -$3.8K, 5 RESETs.
        # vs V8 historical Q1 average: ~44% WR, PF ~2.0, +$15K profit.
        #
        # Hypothesis: this gate is too aggressive. ICT canonical says a
        # bear MSS is invalidated only when price CLOSES ABOVE the swing
        # high that caused it — not by any subsequent opposite event.
        # My implementation rejects on any bull BOS/CHoCH/MSS posterior
        # to last_struct, killing valid bear setups during normal
        # counter-rallies in choppy markets like Q1 2025.
        #
        # Disabling for the v11 backtest. If WR/PF return to historical
        # ranges, confirms this gate as the regression cause and we
        # refine to the price-level-aware version. If not, look at
        # Bug F backtester or session recency.
        #
        # CONTROL FLAG (kept off in production until ICT-canonical
        # rewrite lands).
        _BUG_G_ENABLED = False
        if _BUG_G_ENABLED:
            opposite_dir = "bullish" if bias_dir == "bearish" else "bearish"
            invalidators = [
                e for e in fresh_events
                if e.type in ("MSS", "BOS", "CHoCH")
                and e.direction == opposite_dir
                and e.timestamp > last_struct.timestamp
            ]
            if invalidators:
                most_recent = invalidators[-1]
                logger.info(
                    "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                    "reason=no_valid_setup (5min_struct_invalidated: last %s "
                    "%s @ %s superseded by %d %s event(s), most recent %s @ %s)",
                    _ts_hm(ts),
                    last_struct.type, bias_dir, _ts_hm(last_struct.timestamp),
                    len(invalidators), opposite_dir,
                    most_recent.type, _ts_hm(most_recent.timestamp),
                )
                self._set_rejection(
                    ts, "5min_struct_invalidated", active_zone, is_near_miss=True,
                    fvg_direction=bias_dir,
                    last_aligned_type=last_struct.type,
                    last_aligned_ts=_ts_hm(last_struct.timestamp),
                    invalidator_count=len(invalidators),
                    most_recent_invalidator_type=most_recent.type,
                    most_recent_invalidator_ts=_ts_hm(most_recent.timestamp),
                )
                return None

        # ── 5. Entry, Stop, Target (ICT canonical) ─────────────────────
        import math
        tick = config.MNQ_TICK_SIZE
        if direction == "long":
            entry_price = float(fvg.top) + tick
            # Stop reference = candle-1 low. If the FVG was constructed
            # without that OHLC context (NaN), fall back to FVG.bottom
            # (distal) — weaker but functional.
            stop_ref = fvg.stop_reference
            if math.isnan(stop_ref):
                stop_ref = float(fvg.bottom)
            stop_price = stop_ref - tick
        else:
            entry_price = float(fvg.bottom) - tick
            stop_ref = fvg.stop_reference
            if math.isnan(stop_ref):
                stop_ref = float(fvg.top)
            stop_price = stop_ref + tick

        stop_points = abs(entry_price - stop_price)
        if stop_points <= 0:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=no_valid_setup (zero_stop)",
                _ts_hm(ts),
            )
            return None

        # ── 2026-04-29 FIX #6 — FVG QUALITY FILTER ─────────────────────
        # ICT canonical: a "true" FVG comes from a strong displacement
        # (candle 2 big body) where candle 1 and candle 3 wicks DON'T
        # consume the gap. A 3pt-wide FVG with a 19pt stop (caught
        # 2026-04-29 NY PM trade #4) has candle 1 with a dominant wick
        # = INDECISION, not displacement. Two guard rails:
        #
        # Gate A — absolute floor: anything <SB_MIN_FVG_WIDTH_PTS is
        #          noise on MNQ tick-level pricing.
        # Gate B — relative ratio: FVG width / stop distance must be
        #          >= SB_MIN_FVG_TO_STOP_RATIO. A tiny gap relative to
        #          a wide stop means the ENTRY zone is shrinkwrap
        #          tight while the RISK zone is wide → tail-risk
        #          loss profile. ICT-aligned setups have proportional
        #          gap+stop relationships.
        if config.cfg("SB_FVG_QUALITY_ENABLED", True):
            fvg_width = abs(float(fvg.top) - float(fvg.bottom))
            min_width = float(config.cfg("SB_MIN_FVG_WIDTH_PTS", 2.0))
            if fvg_width < min_width:
                logger.info(
                    "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                    "reason=fvg_too_narrow (width %.2fpts < %.1fpts min)",
                    _ts_hm(ts), fvg_width, min_width,
                )
                self._set_rejection(
                    ts, "fvg_too_narrow", active_zone, is_near_miss=True,
                    fvg_direction=bias_dir,
                    fvg_width_pts=round(fvg_width, 2),
                    threshold_pts=min_width,
                )
                return None
            min_ratio = float(config.cfg("SB_MIN_FVG_TO_STOP_RATIO", 0.20))
            if stop_points > 0 and min_ratio > 0:
                ratio = fvg_width / stop_points
                if ratio < min_ratio:
                    logger.info(
                        "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                        "reason=fvg_too_narrow_for_stop "
                        "(width %.2fpts / stop %.2fpts = %.3f < %.2f min ratio)",
                        _ts_hm(ts), fvg_width, stop_points, ratio, min_ratio,
                    )
                    self._set_rejection(
                        ts, "fvg_too_narrow_for_stop", active_zone, is_near_miss=True,
                        fvg_direction=bias_dir,
                        fvg_width_pts=round(fvg_width, 2),
                        stop_pts=round(stop_points, 2),
                        ratio=round(ratio, 3),
                        threshold_ratio=min_ratio,
                    )
                    return None

        # ── 2026-04-29 SAME-SETUP STOPOUT COOLDOWN ─────────────────────
        # If the last loss in THIS kz was at a similar entry price within
        # the cooldown window, skip — that FVG just stopped us out and is
        # invalidated. ICT: a stopped-out FVG is broken structure, not a
        # second-chance setup. Caught 2026-04-29 NY PM: trades #2 and #3
        # had IDENTICAL entry/stop (27,199.25 / 27,212.75), 13min apart,
        # both stopped out for -$108 each.
        if (
            self._last_stopped_entry_price is not None
            and self._last_stopped_kz == active_zone
            and self._last_stopped_ts is not None
        ):
            try:
                cooldown_min = config.cfg("SB_SAME_SETUP_COOLDOWN_MIN", 30)
                price_tol = config.cfg("SB_SAME_SETUP_PRICE_TOL_PTS", 5.0)
                age_s = (ts - self._last_stopped_ts).total_seconds()
                price_diff = abs(entry_price - self._last_stopped_entry_price)
                if age_s <= cooldown_min * 60 and price_diff <= price_tol:
                    logger.info(
                        "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                        "reason=same_setup_cooldown (entry %.2f within %.1fpts of "
                        "last stopout %.2f, %.0fmin ago)",
                        _ts_hm(ts), entry_price, price_tol,
                        self._last_stopped_entry_price, age_s / 60,
                    )
                    self._set_rejection(
                        ts, "same_setup_cooldown", active_zone, is_near_miss=True,
                        attempted_entry=entry_price,
                        last_stopped_entry=self._last_stopped_entry_price,
                        price_diff_pts=round(price_diff, 2),
                        cooldown_min=cooldown_min,
                        age_min=round(age_s / 60, 1),
                    )
                    return None
            except Exception as exc:
                logger.debug("Same-setup cooldown check failed: %s", exc)

        # Min-stop gate (disabled by default in v3; MIN_STOP_PTS=0).
        # The v2 absolute 8pt floor was price-dependent and over-filtered
        # low-price years. Kept as an optional guard for A/B experiments.
        if self.MIN_STOP_PTS > 0 and stop_points < self.MIN_STOP_PTS:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                "reason=stop_too_tight (%.1fpts < %.1fpts min)",
                _ts_hm(ts), stop_points, self.MIN_STOP_PTS,
            )
            return None

        # ── 6. Target: nearest unswept liquidity in direction, >= 10pt framework ──
        target_types = (
            self._LONG_TARGET_TYPES if direction == "long" else self._SHORT_TARGET_TYPES
        )
        candidate_targets = []
        for lvl in tracked_levels:
            if lvl.swept or lvl.type not in target_types:
                continue
            if direction == "long" and lvl.price > entry_price:
                candidate_targets.append(lvl)
            elif direction == "short" and lvl.price < entry_price:
                candidate_targets.append(lvl)
        if not candidate_targets:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                "reason=no_valid_setup (no_liquidity_target)",
                _ts_hm(ts),
            )
            self._set_rejection(
                ts, "no_liquidity_target", active_zone, is_near_miss=True,
                direction=direction, entry_price=entry_price,
                stop_price=stop_price, stop_points=stop_points,
            )
            return None
        # Nearest unswept pool in direction.
        target = min(
            candidate_targets,
            key=lambda lvl: abs(lvl.price - entry_price),
        )
        target_price = float(target.price)
        framework_pts = abs(target_price - entry_price)
        if framework_pts < self.MIN_FRAMEWORK_PTS:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, "
                "reason=no_valid_setup (framework %.1fpts < %.1fpts min, "
                "target=%s @ %.2f)",
                _ts_hm(ts), framework_pts, self.MIN_FRAMEWORK_PTS,
                target.type, target_price,
            )
            self._set_rejection(
                ts, "framework_lt_10pts", active_zone, is_near_miss=True,
                direction=direction, entry_price=entry_price,
                target_type=target.type, target_price=target_price,
                framework_pts=framework_pts,
                min_framework_pts=self.MIN_FRAMEWORK_PTS,
            )
            return None

        # ── 7. Position size ───────────────────────────────────────────
        # Risk amount comes from the RiskManager (ladder-aware when enabled,
        # else flat config.RISK_PER_TRADE). When the ladder is exhausted
        # get_current_risk() returns 0 and can_trade_in_kz() has already
        # rejected us above — so we're guaranteed risk_$ > 0 here.
        if hasattr(self.risk, "get_current_risk"):
            risk_dollars = self.risk.get_current_risk()
        else:
            risk_dollars = float(config.RISK_PER_TRADE)
        pos = calculate_position(
            stop_points=stop_points,
            risk=risk_dollars,
            point_value=config.MNQ_POINT_VALUE,
            max_contracts=config.MAX_CONTRACTS,
        )
        contracts = max(1, int(pos.contracts * self.risk.position_multiplier))

        # ── 8. Confluence scoring (soft filter) ────────────────────────
        obs = self.detectors["ob"].get_active(
            timeframe="1min", direction=bias_dir,
        ) if "ob" in self.detectors else []
        displacements = self.detectors["displacement"].get_recent(
            n=5, timeframe="1min", direction=bias_dir,
        ) if "displacement" in self.detectors else []
        bias = self.htf_bias_fn(last_close) if self.htf_bias_fn else None

        conf = self.detectors["confluence"].score(
            direction=direction,
            entry_price=entry_price,
            target_price=target_price,
            sweep=sweep,
            fvgs=fvgs_in_window,
            obs=obs,
            structure_event=last_struct,
            displacement=displacements[0] if displacements else None,
            kill_zone=True,
            htf_bias=bias,
            key_levels=tracked_levels,
        )
        # v2 Fix 1: confluence gate REMOVED. Q1 2024 analysis found that
        # higher scores (6-9) had 0-16% WR while the minimum score (5) had
        # 37.8% WR. The scoring function is actively noise for Silver Bullet.
        # Score is still attached to the Signal for reporting — we just no
        # longer reject on it.

        # ── 9. Build signal ────────────────────────────────────────────
        signal = Signal(
            strategy="silver_bullet",
            symbol=self.SYMBOL,
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            contracts=contracts,
            confluence_score=conf.total_score,
            confluence_breakdown=dict(conf.breakdown),
            confluence_reasons=list(conf.reasons),
            timestamp=ts,
            kill_zone=active_zone,
        )
        self._last_evaluated_bar_ts = ts

        sb_score, sb_max = sb_applicable_score(signal.confluence_breakdown)
        logger.info(
            "EVAL silver_bullet [%s]: confluence=%d/%d (SB applicable: %d/%d), "
            "signal=fire, reason=fired (framework=%.1fpts target=%s@%.2f) | %s",
            _ts_hm(ts), signal.confluence_score, config.MAX_CONFLUENCE,
            sb_score, sb_max,
            framework_pts, target.type, target_price, signal,
        )
        return signal

    def rollback_last_evaluated_bar(self, ts) -> None:
        """Clear ``_last_evaluated_bar_ts`` if it matches ``ts``. See
        strategies/ny_am_reversal.py for the full rationale."""
        if self._last_evaluated_bar_ts == ts:
            self._last_evaluated_bar_ts = None

    def record_phantom_cleanup(self, ts, cooldown_minutes: int = 5) -> None:
        """
        Arm the phantom-cleanup cooldown after a failed-to-fill signal has
        been cleaned from state. Blocks re-firing on the same FVG/sweep/
        structure setup for ``cooldown_minutes`` bars.

        Called from main._poll_position_status CASE 1 (entry never filled)
        right after cancelling the remaining resting orders.

        5-min cooldown chosen because:
          - ICT windows are 60 min, so 5 min = 8% of window (not too tight)
          - Price typically needs 3-5 min to retrace back toward an FVG
            that was approached but not pierced
          - Matches observed phantom-loop cadence (fires every 2 bars;
            5 min blocks the next 2-3 re-fire attempts of same setup)
        """
        import pandas as pd  # local to avoid top-level dep if unused
        self._phantom_cooldown_until = ts + pd.Timedelta(minutes=cooldown_minutes)
        logger.info(
            "silver_bullet: phantom cooldown ARMED — new fires blocked "
            "until %s (ts=%s, +%dmin)",
            self._phantom_cooldown_until, ts, cooldown_minutes,
        )

    def notify_trade_executed(self, signal) -> None:
        """Advance counters only after broker-confirmed entry."""
        zone = getattr(signal, "kill_zone", "") or ""
        if zone in self._trades_by_zone:
            self._trades_by_zone[zone] = self._trades_by_zone[zone] + 1
        self.trades_today += 1

    def notify_trade_closed(self, trade: dict) -> None:
        """
        2026-04-29 — record last stopout for the same-setup cooldown gate.

        Called from main._on_trade_closed after broker confirms the
        trade closed. We track only LOSING trades here — a profitable
        setup is fine to re-attempt; a stopped-out setup is invalidated
        per ICT (broken FVG / consumed liquidity).
        """
        try:
            pnl = float(trade.get("pnl") or 0)
            if pnl >= 0:
                # Winner / scratch — don't arm the cooldown
                return
            self._last_stopped_entry_price = float(
                trade.get("entry_price") or 0
            ) or None
            # exit_time is a string; the strategy compares against
            # incoming bar timestamps (pd.Timestamp). Convert.
            try:
                import pandas as _pd
                self._last_stopped_ts = _pd.Timestamp(trade.get("exit_time"))
            except Exception:
                self._last_stopped_ts = None
            self._last_stopped_kz = str(trade.get("kill_zone") or "")
            logger.info(
                "silver_bullet: same-setup cooldown ARMED — last stopout "
                "@ %.2f in %s at %s",
                self._last_stopped_entry_price or 0.0,
                self._last_stopped_kz or "?",
                self._last_stopped_ts,
            )
        except Exception as exc:
            logger.debug("notify_trade_closed failed: %s", exc)

    def reset_daily(self) -> None:
        """Reset trade counters — call at session start."""
        self.trades_today = 0
        self._trades_by_zone = {z: 0 for z in self.KILL_ZONES}
        self._last_evaluated_bar_ts = None
        self._phantom_cooldown_until = None
