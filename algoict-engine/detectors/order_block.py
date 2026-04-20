"""
detectors/order_block.py
=========================
ICT Order Block (OB) detection.

Definitions
-----------
Order Block : the last candle moving in the OPPOSITE direction immediately
              before a displacement move (strong impulse that creates a FVG
              or breaks structure).

Bullish OB  : last bearish candle before a bullish displacement
              high = candle.high, low = candle.low

Bearish OB  : last bullish candle before a bearish displacement
              high = candle.high, low = candle.low

Displacement: a candle whose body range ≥ ATR_MULTIPLIER × rolling ATR,
              OR a candle that creates an FVG (3-candle gap).

Validation  : an OB is validated (more significant) when it sits near:
              - a liquidity sweep (swing point just before the OB), AND
              - an FVG in the same direction

Mitigation  : price trades through the full OB (beyond the distal end):
              Bullish OB mitigated when close < ob.low
              Bearish OB mitigated when close > ob.high

All DataFrames must have US/Central DatetimeIndex and OHLCV columns.
"""

import datetime
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from detectors.swing_points import SwingPointDetector
from detectors.fair_value_gap import FairValueGapDetector

logger = logging.getLogger(__name__)

OB_MAX_HISTORY = getattr(config, "OB_MAX_HISTORY", 100)
OB_ATR_MULTIPLIER = getattr(config, "OB_ATR_MULTIPLIER", 1.5)
OB_ATR_PERIOD = getattr(config, "OB_ATR_PERIOD", 14)
OB_MAX_AGE_BARS = getattr(config, "OB_MAX_AGE_BARS", 500)
# How many bars back to look for a nearby sweep
OB_SWEEP_LOOKBACK = getattr(config, "OB_SWEEP_LOOKBACK", 5)
# How many bars forward to look for an FVG after the OB candle
OB_FVG_LOOKFORWARD = getattr(config, "OB_FVG_LOOKFORWARD", 3)


@dataclass
class OrderBlock:
    """Represents a detected ICT Order Block."""

    high: float
    low: float
    direction: str      # 'bullish' | 'bearish'
    timeframe: str
    candle_index: int   # index in the original DataFrame
    timestamp: pd.Timestamp
    validated: bool = False   # True when near sweep + FVG
    mitigated: bool = False

    @property
    def proximal(self) -> float:
        """Nearest edge to price: top for bullish OB, bottom for bearish OB."""
        return self.high if self.direction == "bullish" else self.low

    @property
    def distal(self) -> float:
        """Furthest edge: bottom for bullish OB, top for bearish OB."""
        return self.low if self.direction == "bullish" else self.high

    def __repr__(self) -> str:
        v = "validated" if self.validated else "unvalidated"
        m = "MITIGATED" if self.mitigated else "active"
        return (
            f"OrderBlock({self.direction} [{self.low:.2f}–{self.high:.2f}], "
            f"tf={self.timeframe}, ts={self.timestamp}, {v}, {m})"
        )


class OrderBlockDetector:
    """
    Detects and tracks ICT Order Blocks.

    Usage
    -----
    detector = OrderBlockDetector()
    obs = detector.detect(df_5min, '5min', swing_detector, fvg_detector)
    detector.update_mitigation(df_5min)
    active = detector.get_active()
    """

    def __init__(self):
        self.order_blocks: list[OrderBlock] = []

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def detect(
        self,
        candles: pd.DataFrame,
        timeframe: str,
        swing_points: Optional[SwingPointDetector] = None,
        fvg_detector: Optional[FairValueGapDetector] = None,
    ) -> list[OrderBlock]:
        """
        Scan candles for new Order Blocks.

        An Order Block is the LAST candle in the opposite direction
        immediately before a displacement candle.

        Parameters
        ----------
        candles      : pd.DataFrame — OHLCV with DatetimeIndex
        timeframe    : str
        swing_points : SwingPointDetector, optional — used for validation
        fvg_detector : FairValueGapDetector, optional — used for validation

        Returns
        -------
        list[OrderBlock] — newly detected OBs
        """
        if len(candles) < OB_ATR_PERIOD + 2:
            return []

        existing_keys = {(ob.timestamp, ob.timeframe) for ob in self.order_blocks}
        new_obs: list[OrderBlock] = []

        opens = candles["open"].values
        highs = candles["high"].values
        lows = candles["low"].values
        closes = candles["close"].values
        timestamps = candles.index

        # Rolling ATR (true range simplified)
        atr = self._compute_atr(highs, lows, closes)

        for i in range(1, len(candles)):
            # Check if candle[i] is a displacement candle
            displacement_dir = self._is_displacement(
                opens, closes, i, atr,
            )
            if displacement_dir is None:
                continue

            # Find the last opposite-direction candle before i
            ob_idx = self._find_last_opposite_candle(
                opens, closes, i, displacement_dir,
            )
            if ob_idx is None:
                continue

            ts = timestamps[ob_idx]
            if (ts, timeframe) in existing_keys:
                continue

            ob = OrderBlock(
                high=float(highs[ob_idx]),
                low=float(lows[ob_idx]),
                direction=displacement_dir,
                timeframe=timeframe,
                candle_index=ob_idx,
                timestamp=ts,
            )

            # Validate against sweep + FVG
            ob.validated = self._validate(
                ob, ob_idx, timestamps,
                swing_points, fvg_detector, timeframe,
            )

            new_obs.append(ob)
            existing_keys.add((ts, timeframe))

        self.order_blocks.extend(new_obs)
        if len(self.order_blocks) > OB_MAX_HISTORY:
            self.order_blocks = self.order_blocks[-OB_MAX_HISTORY:]

        logger.debug(
            "detect(%s): found %d new OBs (%d total)",
            timeframe, len(new_obs), len(self.order_blocks),
        )
        return new_obs

    def update_mitigation(self, candles: pd.DataFrame) -> list[OrderBlock]:
        """
        Mark active OBs as mitigated when price trades through their distal end.

        Bullish OB mitigated: close < ob.low
        Bearish OB mitigated: close > ob.high

        Parameters
        ----------
        candles : pd.DataFrame — full OHLCV history (uses last close)

        Returns
        -------
        list[OrderBlock] — OBs newly mitigated
        """
        if candles.empty:
            return []
        current_close = float(candles.iloc[-1]["close"])
        newly_mitigated: list[OrderBlock] = []
        for ob in self.order_blocks:
            if ob.mitigated:
                continue
            if ob.direction == "bullish" and current_close < ob.low:
                ob.mitigated = True
                newly_mitigated.append(ob)
                logger.debug("Bullish OB [%.2f–%.2f] mitigated", ob.low, ob.high)
            elif ob.direction == "bearish" and current_close > ob.high:
                ob.mitigated = True
                newly_mitigated.append(ob)
                logger.debug("Bearish OB [%.2f–%.2f] mitigated", ob.low, ob.high)
        return newly_mitigated

    def get_active(
        self,
        timeframe: Optional[str] = None,
        direction: Optional[str] = None,
        validated_only: bool = False,
    ) -> list[OrderBlock]:
        """
        Return OBs that have NOT been mitigated yet.

        Parameters
        ----------
        timeframe      : str, optional
        direction      : str, optional — 'bullish' | 'bearish'
        validated_only : bool — if True, only return validated OBs

        Returns
        -------
        list[OrderBlock] sorted by timestamp ascending
        """
        active = [ob for ob in self.order_blocks if not ob.mitigated]
        if timeframe is not None:
            active = [ob for ob in active if ob.timeframe == timeframe]
        if direction is not None:
            active = [ob for ob in active if ob.direction == direction]
        if validated_only:
            active = [ob for ob in active if ob.validated]
        return sorted(active, key=lambda ob: ob.timestamp)

    def get_nearest(
        self,
        current_price: float,
        direction: Optional[str] = None,
        timeframe: Optional[str] = None,
        validated_only: bool = False,
    ) -> Optional[OrderBlock]:
        """Return the active OB whose proximal level is nearest to current_price."""
        candidates = self.get_active(
            timeframe=timeframe,
            direction=direction,
            validated_only=validated_only,
        )
        if not candidates:
            return None
        return min(candidates, key=lambda ob: abs(ob.proximal - current_price))

    def invalidate_by_structure(
        self,
        direction: str,
        current_bar_count: int = 0,
    ) -> list[OrderBlock]:
        """Invalidate OBs whose direction is OPPOSITE to a new BOS/CHoCH/MSS,
        but only when the OB is older than 100 entry-TF bars (≈ 8h RTH).

        Fresh OBs (age ≤ 100 bars) are intentionally preserved — a BOS on the
        bar immediately after an OB forms should NOT kill that OB; the level is
        still relevant for a retrace entry.

        Parameters
        ----------
        direction         : 'bullish' | 'bearish' — direction of the new structure event
        current_bar_count : int — current entry-TF bar index (passed by caller)

        Returns
        -------
        list[OrderBlock] — OBs invalidated in this call
        """
        opposite = "bearish" if direction == "bullish" else "bullish"
        invalidated: list[OrderBlock] = []
        for ob in self.order_blocks:
            if not ob.mitigated and ob.direction == opposite:
                age = current_bar_count - ob.candle_index
                if age > 100:
                    ob.mitigated = True
                    invalidated.append(ob)
                    logger.debug(
                        "OB %s [%.2f-%.2f] invalidated by %s structure event (age=%d bars)",
                        ob.direction, ob.low, ob.high, direction, age,
                    )
        return invalidated

    def expire_old(self, current_ts: pd.Timestamp) -> list[OrderBlock]:
        """
        Mark active OBs as mitigated when they are older than OB_MAX_AGE_BARS
        5-min bars (≈ OB_MAX_AGE_BARS × 5 minutes).

        Parameters
        ----------
        current_ts : pd.Timestamp — timestamp of the latest processed bar

        Returns
        -------
        list[OrderBlock] — OBs expired in this call
        """
        max_age = datetime.timedelta(minutes=OB_MAX_AGE_BARS * 5)
        expired: list[OrderBlock] = []
        for ob in self.order_blocks:
            if ob.mitigated:
                continue
            age = current_ts - ob.timestamp
            # strip timezone if needed for comparison
            try:
                if age > max_age:
                    ob.mitigated = True
                    expired.append(ob)
                    logger.debug(
                        "OB %s [%.2f-%.2f] expired (age=%s > %s)",
                        ob.direction, ob.low, ob.high, age, max_age,
                    )
            except TypeError:
                pass  # mixed tz/naive edge case — skip expiry for this OB
        return expired

    def clear(self) -> None:
        """Reset all detected OBs."""
        self.order_blocks.clear()

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_atr(highs, lows, closes, period: int = OB_ATR_PERIOD) -> np.ndarray:
        """Simple ATR using true range; returns per-candle ATR array."""
        n = len(highs)
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        # Simple rolling mean of true range
        atr = np.zeros(n)
        for i in range(n):
            start = max(0, i - period + 1)
            atr[i] = tr[start: i + 1].mean()
        return atr

    @staticmethod
    def _is_displacement(
        opens, closes, i: int, atr: np.ndarray,
    ) -> Optional[str]:
        """
        Returns 'bullish', 'bearish', or None.

        Displacement = candle body ≥ ATR_MULTIPLIER × ATR[i].
        Body of candle[i] = |close[i] - open[i]|
        """
        body = abs(closes[i] - opens[i])
        threshold = OB_ATR_MULTIPLIER * atr[i]

        if body >= threshold:
            if closes[i] > opens[i]:
                return "bullish"
            elif closes[i] < opens[i]:
                return "bearish"

        return None

    @staticmethod
    def _find_last_opposite_candle(
        opens, closes, displacement_idx: int, displacement_dir: str,
    ) -> Optional[int]:
        """
        Walk backwards from displacement_idx - 1 and find the last candle
        whose direction is OPPOSITE to displacement_dir.

        Bullish displacement → look for last bearish candle (close < open)
        Bearish displacement → look for last bullish candle (close > open)

        Termination rules:
          - MATCH opposite   → return index
          - MATCH same-dir   → break (we've entered the impulse leg; the
                               OB must sit immediately before displacement)
          - DOJI (close==open) → continue walking back (indecision bar;
                               not yet in the impulse leg, OB may lie
                               beyond). This preserves OB quality for
                               the typical M-shape / W-shape sequences
                               where one or two balance bars separate
                               the OB from the displacement.

        Rewrite 2026-04-17: the prior chained-elif form had the correct
        semantics for strict directional candles but relied on four
        guarded branches where two were de-facto unreachable if read
        in a cold review. The explicit if-tree below is easier to audit
        and makes doji handling explicit.
        """
        opposite_dir = "bearish" if displacement_dir == "bullish" else "bullish"
        for j in range(displacement_idx - 1, -1, -1):
            is_bullish = closes[j] > opens[j]
            is_bearish = closes[j] < opens[j]
            if opposite_dir == "bearish":
                if is_bearish:
                    return j
                if is_bullish:
                    # same direction as displacement → entered impulse leg
                    break
                # doji → keep walking back
            else:  # opposite_dir == "bullish"
                if is_bullish:
                    return j
                if is_bearish:
                    break
        return None

    @staticmethod
    def _validate(
        ob: OrderBlock,
        ob_idx: int,
        timestamps,
        swing_points: Optional[SwingPointDetector],
        fvg_detector: Optional[FairValueGapDetector],
        timeframe: str,
    ) -> bool:
        """
        Validate OB by checking for nearby sweep + FVG.

        Sweep: a swing point with timestamp within OB_SWEEP_LOOKBACK bars
               before the OB candle.
        FVG:   an active FVG of the same direction with timestamp between
               ob_idx and ob_idx + OB_FVG_LOOKFORWARD.
        """
        has_sweep = False
        has_fvg = False

        if swing_points is not None:
            sweep_start_idx = max(0, ob_idx - OB_SWEEP_LOOKBACK)
            ts_start = timestamps[sweep_start_idx]
            ts_ob = timestamps[ob_idx]
            for sp in swing_points.swing_points:
                if sp.timeframe != timeframe:
                    continue
                if ts_start <= sp.timestamp <= ts_ob:
                    # Bullish OB: sweep below a swing low
                    if ob.direction == "bullish" and sp.type == "low":
                        has_sweep = True
                        break
                    # Bearish OB: sweep above a swing high
                    elif ob.direction == "bearish" and sp.type == "high":
                        has_sweep = True
                        break

        if fvg_detector is not None:
            ts_ob = timestamps[ob_idx]
            fwd_idx = min(len(timestamps) - 1, ob_idx + OB_FVG_LOOKFORWARD)
            ts_fwd = timestamps[fwd_idx]
            for fvg in fvg_detector.fvgs:
                if fvg.timeframe != timeframe:
                    continue
                if fvg.direction == ob.direction and ts_ob <= fvg.timestamp <= ts_fwd:
                    has_fvg = True
                    break

        return has_sweep and has_fvg
