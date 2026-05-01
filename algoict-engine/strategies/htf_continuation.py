"""
strategies/htf_continuation.py
================================
ICT Daily Bias Continuation — second strategy for AlgoICT.

Designed 2026-04-30 to complement Silver Bullet by capturing the OPPOSITE
edge type. SB is a mean-reversion play (sweep + reversal). This strategy
is a CONTINUATION play (HTF bias + pullback into structure).

Setup (ICT canonical)
---------------------
1. Daily bias is bullish OR bearish (NOT neutral).
   Source: HTFBiasDetector.daily_bias (NOT weekly — user chose loose mode).

2. Price is in the institutional zone:
   - Long  setups: price in DISCOUNT  (< 50% of daily range)
   - Short setups: price in PREMIUM  (> 50% of daily range)
   ICT principle: "institutions buy at discount, sell at premium".

3. Inside an active kill zone (London / NY AM / NY PM).

4. A 5-min Order Block (preferred) or FVG exists in the bias direction,
   unmitigated, with proximal level near current price.

5. Pullback complete: current_price within proximity_pts of OB.proximal
   (or FVG.top for long / FVG.bottom for short).

Entry / Stop / Target
---------------------
Long:
  entry  = OB.high + 1 tick                     (or FVG.top + 1 tick)
  stop   = (last 5min swing_low - 1 tick)       capped to [MIN, MAX] width
  target = nearest unswept BSL/PDH/PWH/equal_highs above entry, ≥10pts

Short (mirror):
  entry  = OB.low  - 1 tick
  stop   = (last 5min swing_high + 1 tick)      capped to [MIN, MAX] width
  target = nearest unswept SSL/PDL/PWL/equal_lows below entry, ≥10pts

Stop sizing:
  - Default: structural (5min swing).
  - MIN 15pt floor: avoid stop-outs by tick-noise on tight OBs.
  - MAX 80pt ceiling: cap risk so 2R remains intraday-achievable.
  - Position sizer (`risk/position_sizer.py`) computes contracts from
    risk_$ + stop_pts (shared $250 budget with SB).

Trade management (live + backtest)
----------------------------------
  - At 1R: move stop to BE + 1 tick (extra tick of safety).
  - At 2R: start trailing the last 5min swing (same as SB).
  - Backtester reads `config.TRADE_MANAGEMENT` for parity.

Why this complements Silver Bullet
----------------------------------
SB requires: sweep AGAINST bias + 1min FVG + 5min MSS/BOS + bullish bias
             from sweep direction (NOT from HTF).
HTF Cont:    Daily bias (NOT from sweep) + pullback into 5min OB/FVG +
             discount/premium filter.

In CHOP markets: SB fires (sweeps + reversals), HTF Cont rarely (no clear bias).
In TREND markets: HTF Cont fires (pullback in bias), SB rarely (no clean sweeps).
Mutually exclusive ~80% of trading time → low correlation → diversifies P&L.

Defenses kept (shared with SB)
------------------------------
  - News blackout (NEWS_BLACKOUT_*) — Fix #1
  - Same-setup cooldown (HTF_CONT_SAME_SETUP_COOLDOWN_MIN) — Fix #3 analog
  - Tighter kill_switch (KILL_SWITCH_SAME_SETUP_LOSSES) — Fix #4 (shared)
  - VPIN shield (vpin_halted via risk_manager) — global
  - MLL zones (warning/caution/stop) — global
  - Hard close 15:00 CT — global
  - Past-cancel-time (last 10 min of KZ) — internal

Defenses NOT applicable
-----------------------
  - Sweep close-back invalidation (no sweep involved in setup)
  - 5min struct counter-event invalidator (no struct event required)
  - FVG quality filter (we accept any unmitigated 5min OB/FVG; the
    structural significance comes from being a 5min OB, not from width)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Callable

import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from risk.position_sizer import calculate_position
from timeframes.htf_bias import BiasResult
from strategies.silver_bullet import Signal  # reuse the dataclass

logger = logging.getLogger(__name__)


# Minutes before the end of a kill zone in which we refuse new entries.
# Mirrors SB's _CANCEL_MINUTES_BEFORE_END.
_CANCEL_MINUTES_BEFORE_END = 10


def _ts_hm(ts) -> str:
    """Format a bar timestamp as HH:MM for EVAL log lines."""
    try:
        return ts.strftime("%H:%M")
    except AttributeError:
        return str(ts)


class HTFContinuationStrategy:
    """ICT Daily Bias Continuation — pullback into 5-min OB/FVG entry."""

    # 2026-05-01 — HTF Continuation does NOT use ICT kill zones. KZ filter
    # is for mean-reversion (Silver Bullet). Continuation is a Daily Bias
    # play that can fire on ANY pullback during RTH. Diagnostic on Jan 2024
    # showed 67% of all rejects were `outside_kz` — removing the gate gives
    # us ~3x more eligible bars while preserving structural filters
    # (premium/discount, 5min OB, framework, etc).
    KILL_ZONES = ("rth",)         # virtual single zone covering RTH
    MAX_TRADES_PER_ZONE = 5       # max 5 trades/day total (was 1/KZ × 3 = 3)
    KILL_ZONE = "rth"
    # ENTRY_TF = "5min" because the strategy's setup is 5-min OB / FVG.
    # The backtester only runs detectors on `entry_tf`; if we set this to
    # "1min" the OB/FVG detectors never run on 5-min and `get_active(
    # timeframe="5min")` returns []. evaluate() then fires zero signals.
    # First smoke 2024 caught this — see commit 1c0dc58 + investigation.
    ENTRY_TF = "5min"
    CONTEXT_TF = "15min"
    SYMBOL = "MNQ"

    # Trading window — the bot opens for new entries from this hour:minute
    # CT (Globex re-open after CME break) and stops new entries
    # CANCEL_BEFORE_HARD_CLOSE_MIN before HARD_CLOSE_HOUR:HARD_CLOSE_MINUTE
    # (config). Effectively 17:00 CT → 14:50 CT next day = ~22h trading.
    RTH_START_HOUR = 17           # 17:00 CT (Globex re-open)
    RTH_START_MIN = 0
    CANCEL_BEFORE_HARD_CLOSE_MIN = 10
    MIN_FRAMEWORK_PTS = 10.0

    # 2026-04-30 stop sizing (per design discussion):
    #   MIN 15pt — avoid wick-stop-outs on thin OBs
    #   MAX 80pt — keep 2R intraday-achievable
    STOP_MIN_PTS = 15.0
    STOP_MAX_PTS = 80.0

    # How close (in MNQ pts) current price must be to OB/FVG proximal to
    # consider the pullback complete. Loose enough to catch wicks that
    # touch the proximal but close just above it.
    PROXIMITY_PTS = 5.0

    # Liquidity types for target selection (mirrors SB).
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
        detectors      : dict — populated detector instances + 'tracked_levels'.
                         Required keys: 'ob', 'fvg', 'swing_context',
                         'tracked_levels'. Optional: 'confluence'.
        risk_manager   : RiskManager — daily P&L state + can_trade_in_kz +
                         position_multiplier + get_current_risk.
        session_manager: SessionManager — kill zone checks.
        htf_bias_fn    : callable(price) -> BiasResult — REQUIRED to be the
                         dynamic bias function (NOT the static stub) for
                         this strategy to work as designed. The static
                         stub always returns bullish, which would force
                         this strategy to long-only every bar.
        """
        self.detectors = detectors
        self.risk = risk_manager
        self.session = session_manager
        self.htf_bias_fn = htf_bias_fn

        self.trades_today: int = 0
        self._trades_by_zone: dict[str, int] = {z: 0 for z in self.KILL_ZONES}
        self._last_evaluated_bar_ts: Optional[pd.Timestamp] = None
        self._last_active_zone: Optional[str] = None

        # Same-setup cooldown state — armed when a trade closes at a loss.
        # If a subsequent setup tries to fire at a similar entry within the
        # cooldown window AND in the same KZ → reject.
        self._last_stopped_entry_price: Optional[float] = None
        self._last_stopped_ts: Optional[pd.Timestamp] = None
        self._last_stopped_kz: str = ""

        # Phantom-cleanup cooldown (mirrors SB pattern, defensive).
        self._phantom_cooldown_until: Optional[pd.Timestamp] = None

        # Diagnostic surface for main.py to inspect why we rejected.
        self.last_rejection: Optional[dict] = None

        # 2026-05-01 diagnostic — count each reject reason across the run.
        # Dumped at end of backtest to identify which gate filters most.
        from collections import Counter
        self.reject_counters: Counter = Counter()

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _set_rejection(
        self,
        ts,
        reason: str,
        kill_zone: str,
        is_near_miss: bool = False,
        **details,
    ) -> None:
        """Stash rejection context for observers (main.py, tests)."""
        self.last_rejection = {
            "reason": reason,
            "ts": ts,
            "kill_zone": kill_zone,
            "is_near_miss": is_near_miss,
            "details": details,
        }
        # 2026-05-01 — also bump diagnostic counter
        self.reject_counters[reason] += 1

    @staticmethod
    def _bias_to_direction(daily_bias: str) -> Optional[str]:
        """Map daily_bias to trade direction. Neutral → None (skip)."""
        if daily_bias == "bullish":
            return "long"
        if daily_bias == "bearish":
            return "short"
        return None

    @staticmethod
    def _zone_aligned(direction: str, premium_discount: str) -> bool:
        """ICT institutional rule: longs in discount, shorts in premium.

        2026-05-01 — RELAXED to also accept equilibrium (35-65% mid-band).
        Diagnostic on Jan 2024 showed zone_mismatch was ~50% of in-KZ
        rejects with strict version. For a continuation play (not
        reversal), equilibrium is still actionable when daily_bias is
        clear — the entry point is the OB pullback, not extreme zone
        institutional anchoring (that's mean-reversion logic).
        """
        if direction == "long":
            return premium_discount in ("discount", "equilibrium")
        if direction == "short":
            return premium_discount in ("premium", "equilibrium")
        return False

    def _find_entry_block(
        self,
        direction: str,
        current_price: float,
    ) -> tuple[Optional[object], str]:
        """Find nearest 5-min OB or FVG in trade direction (proximal ≤ price for
        long, proximal ≥ price for short).

        Strategy:
          1. Try 5-min OB first (preferred — institutional footprint).
          2. Fallback to 5-min FVG if no OB available.

        Returns (block, kind) where kind is 'ob' | 'fvg' | '' if nothing found.
        The block has a `.proximal` attribute (OB) or `.top`/`.bottom`/`direction`
        (FVG) — caller must handle both shapes.
        """
        bias_dir = "bullish" if direction == "long" else "bearish"

        # 5-min OB first. We do NOT pre-filter by directional position
        # (proximal vs price); the caller (`evaluate`) classifies whether
        # the pullback is incomplete (price too far above proximal) or
        # past_proximal (price already went through the block) so we get
        # informative reject reasons instead of a generic "no_block".
        ob_det = self.detectors.get("ob")
        if ob_det is not None:
            obs = ob_det.get_active(timeframe="5min", direction=bias_dir)
            if obs:
                nearest = min(obs, key=lambda ob: abs(ob.proximal - current_price))
                return nearest, "ob"

        # FVG fallback (no OB available).
        fvg_det = self.detectors.get("fvg")
        if fvg_det is not None:
            fvgs = fvg_det.get_active(timeframe="5min", direction=bias_dir)
            if fvgs:
                # Pick nearest proximal: top for long, bottom for short.
                if direction == "long":
                    nearest = min(fvgs, key=lambda f: abs(f.top - current_price))
                else:
                    nearest = min(fvgs, key=lambda f: abs(f.bottom - current_price))
                return nearest, "fvg"

        return None, ""

    def _block_proximal(self, block, kind: str, direction: str) -> float:
        """Extract proximal price from OB or FVG."""
        if kind == "ob":
            return float(block.proximal)
        if kind == "fvg":
            return float(block.top if direction == "long" else block.bottom)
        raise ValueError(f"unknown block kind: {kind}")

    def _find_stop_price(
        self,
        direction: str,
        entry_price: float,
        block,
        kind: str,
    ) -> tuple[float, float]:
        """Compute stop price per the spec:
            structural = last 5min swing low/high - 1 tick
            capped to [STOP_MIN_PTS, STOP_MAX_PTS] from entry

        Returns (stop_price, stop_points).
        """
        tick = float(getattr(config, "MNQ_TICK_SIZE", 0.25))
        swing_det = self.detectors.get("swing_context")
        structural_stop: Optional[float] = None
        if swing_det is not None:
            try:
                if direction == "long":
                    sp = swing_det.get_latest_swing_low()
                    if sp is not None and sp.price < entry_price:
                        structural_stop = float(sp.price) - tick
                else:
                    sp = swing_det.get_latest_swing_high()
                    if sp is not None and sp.price > entry_price:
                        structural_stop = float(sp.price) + tick
            except Exception as exc:
                logger.debug("swing stop lookup failed: %s", exc)

        # Fallback if no swing available: use OB/FVG distal (other side of
        # the block) - 1 tick. This is the loosest reasonable structural stop.
        if structural_stop is None:
            if kind == "ob":
                structural_stop = (
                    float(block.distal) - tick if direction == "long"
                    else float(block.distal) + tick
                )
            elif kind == "fvg":
                # FVG distal = bottom for long (other side of gap), top for short
                structural_stop = (
                    float(block.bottom) - tick if direction == "long"
                    else float(block.top) + tick
                )
            else:
                # Should never reach — _find_entry_block always returns valid kind
                structural_stop = (
                    entry_price - self.STOP_MIN_PTS if direction == "long"
                    else entry_price + self.STOP_MIN_PTS
                )

        # Apply MIN/MAX caps relative to entry.
        raw_distance = abs(entry_price - structural_stop)
        if raw_distance < self.STOP_MIN_PTS:
            # Push stop further to enforce floor.
            stop_price = (
                entry_price - self.STOP_MIN_PTS if direction == "long"
                else entry_price + self.STOP_MIN_PTS
            )
        elif raw_distance > self.STOP_MAX_PTS:
            # Cap stop closer to enforce ceiling.
            stop_price = (
                entry_price - self.STOP_MAX_PTS if direction == "long"
                else entry_price + self.STOP_MAX_PTS
            )
        else:
            stop_price = structural_stop

        stop_points = abs(entry_price - stop_price)
        return float(stop_price), float(stop_points)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def evaluate(
        self,
        candles_1min: pd.DataFrame,
        candles_5min: pd.DataFrame,
    ) -> Optional[Signal]:
        """Run a HTF Continuation evaluation on the latest 1-min candle.

        Returns a Signal on fire, None on reject. Mirrors SB's contract.
        """

        # ── 1. Pre-conditions ──────────────────────────────────────────
        if candles_1min.empty or candles_5min.empty:
            return None

        ts = candles_1min.index[-1]
        last_close = float(candles_1min.iloc[-1]["close"])

        # Per-bar dedup — strategy is idempotent within a bar.
        if ts == self._last_evaluated_bar_ts:
            self.reject_counters["per_bar_dedup"] += 1
            return None

        # Phantom cooldown (defensive — main.py may call record_phantom_cleanup
        # if a placed limit never fills).
        if (
            self._phantom_cooldown_until is not None
            and ts < self._phantom_cooldown_until
        ):
            self._set_rejection(
                ts, "phantom_cooldown", "n/a", is_near_miss=False,
                cooldown_until=str(self._phantom_cooldown_until),
            )
            return None

        # ── 2. RTH window check (NO kill zone filter for continuation) ─
        # Active when: time >= RTH_START (17:00 CT Globex re-open) OR
        #              time < hard_close_hour:hard_close_min (next morning).
        # Inactive only during the CME maintenance break 15:00-17:00 CT.
        ts_total_min = ts.hour * 60 + ts.minute
        rth_start_total = self.RTH_START_HOUR * 60 + self.RTH_START_MIN
        hard_close_total = (
            config.cfg("HARD_CLOSE_HOUR", 15) * 60
            + config.cfg("HARD_CLOSE_MINUTE", 0)
        )
        # In window if (>= rth_start) OR (< hard_close).
        # Both conditions allow overnight (17:00→23:59 + 00:00→hard_close).
        in_window = ts_total_min >= rth_start_total or ts_total_min < hard_close_total
        if not in_window:
            self.reject_counters["outside_window"] += 1
            return None
        active_zone = "rth"

        # ── 3. News blackout (Fix #1, shared with SB) ──────────────────
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
                        "EVAL htf_continuation [%s]: signal=reject, "
                        "reason=news_blackout (%s @%s, risk=%s)",
                        _ts_hm(ts), blk_event.name,
                        blk_event.time_ct, blk_event.risk,
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

        # ── 4. Past cancel time (last N min before hard close) ────────
        # Stop new entries CANCEL_BEFORE_HARD_CLOSE_MIN before hard close
        # so we don't open trades that immediately get flattened.
        cancel_total_min = hard_close_total - self.CANCEL_BEFORE_HARD_CLOSE_MIN
        # Only relevant if we're in the morning (before hard close), not
        # in the evening (after RTH start, before midnight).
        if ts_total_min < hard_close_total and ts_total_min >= cancel_total_min:
            self.reject_counters["past_cancel_time"] += 1
            return None

        # ── 5. Hard close + risk gates (shared with SB via risk_manager) ──
        if self.risk.check_hard_close(ts):
            self.reject_counters["past_hard_close"] += 1
            return None

        if hasattr(self.risk, "can_trade_in_kz"):
            allowed, reason = self.risk.can_trade_in_kz(active_zone)
        else:
            allowed, reason = self.risk.can_trade()
        if not allowed:
            logger.info(
                "EVAL htf_continuation [%s]: signal=reject, reason=risk_blocked (%s)",
                _ts_hm(ts), reason,
            )
            self._set_rejection(
                ts, "risk_blocked", active_zone, is_near_miss=False,
                reason_detail=reason,
            )
            return None

        # ── 6. Per-zone trade cap ──────────────────────────────────────
        if self._trades_by_zone.get(active_zone, 0) >= self.MAX_TRADES_PER_ZONE:
            self._set_rejection(
                ts, "max_trades_per_zone", active_zone, is_near_miss=False,
                trades_in_zone=self._trades_by_zone.get(active_zone, 0),
            )
            return None

        # ── 7. Daily bias (THE primary filter) ─────────────────────────
        bias = self.htf_bias_fn(last_close) if self.htf_bias_fn else None
        if bias is None:
            self._set_rejection(
                ts, "no_bias_data", active_zone, is_near_miss=False,
            )
            return None
        daily_bias = getattr(bias, "daily_bias", "neutral")
        direction = self._bias_to_direction(daily_bias)
        if direction is None:
            logger.info(
                "EVAL htf_continuation [%s]: signal=reject, reason=neutral_bias",
                _ts_hm(ts),
            )
            self._set_rejection(
                ts, "neutral_bias", active_zone, is_near_miss=False,
                daily_bias=daily_bias,
            )
            return None

        # ── 8. Premium/Discount filter (institutional zone) ────────────
        premium_discount = getattr(bias, "premium_discount", "equilibrium")
        if not self._zone_aligned(direction, premium_discount):
            logger.info(
                "EVAL htf_continuation [%s]: signal=reject, "
                "reason=zone_mismatch (dir=%s, zone=%s, expected=%s)",
                _ts_hm(ts), direction, premium_discount,
                "discount" if direction == "long" else "premium",
            )
            self._set_rejection(
                ts, "zone_mismatch", active_zone, is_near_miss=True,
                direction=direction,
                premium_discount=premium_discount,
                daily_bias=daily_bias,
            )
            return None

        # ── 9. Find 5-min OB or FVG in bias direction ──────────────────
        block, kind = self._find_entry_block(direction, last_close)
        if block is None:
            self._set_rejection(
                ts, "no_5min_block", active_zone, is_near_miss=True,
                direction=direction,
            )
            return None

        proximal = self._block_proximal(block, kind, direction)

        # ── 10. Pullback proximity check ───────────────────────────────
        # 2026-05-01 — Use bar.low/high (intra-bar wick) instead of close.
        # Diagnostic showed past_proximal hits 497 times/Jan when we check
        # close-only. ICT canonical: limit at proximal+1tick fills as soon
        # as price wicks down to the OB; we shouldn't reject just because
        # the bar closed back above proximal.
        last_bar = candles_5min.iloc[-1]
        last_low = float(last_bar["low"])
        last_high = float(last_bar["high"])
        # For LONG (bullish OB, proximal=top): we want bar.low to come
        #   close to proximal from above, OR slightly past it (wick fill).
        # For SHORT (bearish OB, proximal=bottom): bar.high comes close
        #   from below.
        if direction == "long":
            # distance_to_proximal: how far ABOVE proximal the bar's low is.
            # 0 = touched, negative = wicked into OB, positive = above.
            distance_to_proximal = last_low - proximal
        else:
            distance_to_proximal = proximal - last_high

        if distance_to_proximal > self.PROXIMITY_PTS:
            # Pullback hasn't completed yet — bar didn't approach proximal.
            self._set_rejection(
                ts, "pullback_incomplete", active_zone, is_near_miss=True,
                direction=direction,
                proximal=proximal,
                last_low=last_low, last_high=last_high,
                distance=distance_to_proximal,
            )
            return None
        # Past proximal: bar wicked DEEP into OB (more than PROXIMITY past).
        # That likely broke through the OB, invalidating the setup.
        if distance_to_proximal < -self.PROXIMITY_PTS:
            self._set_rejection(
                ts, "past_proximal", active_zone, is_near_miss=True,
                direction=direction,
                proximal=proximal,
                last_low=last_low, last_high=last_high,
                distance=distance_to_proximal,
            )
            return None
        # In sweet spot: bar's low/high touched within ±PROXIMITY of
        # proximal. Fire the limit.

        # ── 11. Entry / Stop ───────────────────────────────────────────
        tick = float(getattr(config, "MNQ_TICK_SIZE", 0.25))
        if direction == "long":
            entry_price = proximal + tick
        else:
            entry_price = proximal - tick

        stop_price, stop_points = self._find_stop_price(
            direction, entry_price, block, kind,
        )
        if stop_points <= 0:
            # Defensive — should never happen with caps in place
            self._set_rejection(
                ts, "invalid_stop", active_zone, is_near_miss=False,
                entry=entry_price, stop=stop_price,
            )
            return None

        # ── 12. Same-setup cooldown (Fix #3 analog) ────────────────────
        if (
            self._last_stopped_entry_price is not None
            and self._last_stopped_kz == active_zone
            and self._last_stopped_ts is not None
        ):
            try:
                cooldown_min = config.cfg(
                    "HTF_CONT_SAME_SETUP_COOLDOWN_MIN",
                    config.cfg("SB_SAME_SETUP_COOLDOWN_MIN", 30),
                )
                price_tol = config.cfg(
                    "HTF_CONT_SAME_SETUP_PRICE_TOL_PTS",
                    config.cfg("SB_SAME_SETUP_PRICE_TOL_PTS", 5.0),
                )
                age_s = (ts - self._last_stopped_ts).total_seconds()
                price_diff = abs(entry_price - self._last_stopped_entry_price)
                if age_s <= cooldown_min * 60 and price_diff <= price_tol:
                    logger.info(
                        "EVAL htf_continuation [%s]: signal=reject, "
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

        # ── 13. Target: nearest unswept liquidity ≥ 10pt framework ─────
        tracked_levels = self.detectors.get("tracked_levels", [])
        target_types = (
            self._LONG_TARGET_TYPES if direction == "long"
            else self._SHORT_TARGET_TYPES
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
            self._set_rejection(
                ts, "no_liquidity_target", active_zone, is_near_miss=True,
                direction=direction, entry_price=entry_price,
                stop_price=stop_price,
            )
            return None
        target = min(
            candidate_targets,
            key=lambda lvl: abs(lvl.price - entry_price),
        )
        target_price = float(target.price)
        framework_pts = abs(target_price - entry_price)
        if framework_pts < self.MIN_FRAMEWORK_PTS:
            self._set_rejection(
                ts, "framework_lt_10pts", active_zone, is_near_miss=True,
                direction=direction, entry_price=entry_price,
                target_type=target.type, target_price=target_price,
                framework_pts=framework_pts,
                min_framework_pts=self.MIN_FRAMEWORK_PTS,
            )
            return None

        # ── 14. Position size (shared $250 budget via risk_manager) ────
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

        # ── 15. Confluence scoring (informational, no hard gate) ───────
        confluence_score = 0
        confluence_breakdown: dict = {}
        confluence_reasons: list = []
        try:
            scorer = self.detectors.get("confluence")
            if scorer is not None:
                conf = scorer.score(
                    direction=direction,
                    entry_price=entry_price,
                    target_price=target_price,
                    sweep=None,                        # not a sweep-based setup
                    fvgs=[block] if kind == "fvg" else [],
                    obs=[block] if kind == "ob" else [],
                    structure_event=None,              # not a struct-based setup
                    displacement=None,
                    kill_zone=True,
                    htf_bias=bias,
                    key_levels=tracked_levels,
                )
                confluence_score = conf.total_score
                confluence_breakdown = dict(conf.breakdown)
                confluence_reasons = list(conf.reasons)
        except Exception as exc:
            logger.debug("Confluence scoring failed: %s", exc)

        # ── 16. Build signal ───────────────────────────────────────────
        signal = Signal(
            strategy="htf_continuation",
            symbol=self.SYMBOL,
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            contracts=contracts,
            confluence_score=confluence_score,
            confluence_breakdown=confluence_breakdown,
            confluence_reasons=confluence_reasons,
            timestamp=ts,
            kill_zone=active_zone,
        )
        self._last_evaluated_bar_ts = ts
        self._trades_by_zone[active_zone] = (
            self._trades_by_zone.get(active_zone, 0) + 1
        )
        self.trades_today += 1

        logger.info(
            "EVAL htf_continuation [%s]: signal=fire | dir=%s entry=%.2f "
            "stop=%.2f target=%s@%.2f stop_pts=%.1f framework=%.1fpts "
            "block=%s contracts=%d daily_bias=%s zone=%s",
            _ts_hm(ts), direction, entry_price, stop_price,
            target.type, target_price, stop_points, framework_pts,
            kind, contracts, daily_bias, premium_discount,
        )
        return signal

    # ------------------------------------------------------------------ #
    # Lifecycle (mirrors SB)                                               #
    # ------------------------------------------------------------------ #

    def rollback_last_evaluated_bar(self, ts) -> None:
        """Clear the per-bar dedup if the caller invalidates the eval."""
        if self._last_evaluated_bar_ts == ts:
            self._last_evaluated_bar_ts = None

    def record_phantom_cleanup(self, ts, cooldown_minutes: int = 5) -> None:
        """Arm the phantom-cleanup cooldown after a never-filled signal
        is cleaned up. Mirrors SB.record_phantom_cleanup.
        """
        try:
            self._phantom_cooldown_until = ts + pd.Timedelta(
                minutes=cooldown_minutes,
            )
            logger.info(
                "htf_continuation: phantom cooldown ARMED until %s",
                _ts_hm(self._phantom_cooldown_until),
            )
        except Exception as exc:
            logger.debug("record_phantom_cleanup failed: %s", exc)

    def notify_trade_closed(self, trade: dict) -> None:
        """Record last stopout for the same-setup cooldown gate.

        Called from main._on_trade_closed after broker confirms close.
        Track only LOSING trades — winners can be re-attempted.
        """
        try:
            pnl = float(trade.get("pnl") or 0)
            if pnl >= 0:
                return
            self._last_stopped_entry_price = float(
                trade.get("entry_price") or 0,
            ) or None
            try:
                self._last_stopped_ts = pd.Timestamp(trade.get("exit_time"))
            except Exception:
                self._last_stopped_ts = None
            self._last_stopped_kz = str(trade.get("kill_zone") or "")
            logger.info(
                "htf_continuation: same-setup cooldown ARMED — last stopout "
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
