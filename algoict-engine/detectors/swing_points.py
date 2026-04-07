"""
detectors/swing_points.py
==========================
ICT Swing High / Swing Low detection.

Swing High: candle[N].high is strictly greater than the highs of all
    lookback candles on each side (left and right).
Swing Low: candle[N].low is strictly less than the lows of all
    lookback candles on each side.

A swing point is "broken" when a subsequent close crosses through it
(bullish close above a swing high, or bearish close below a swing low).

All DataFrames must have US/Central DatetimeIndex and OHLCV columns.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

logger = logging.getLogger(__name__)


@dataclass
class SwingPoint:
    """Represents a detected ICT swing high or swing low."""

    price: float            # high value for SH, low value for SL
    timestamp: pd.Timestamp
    type: str               # 'high' | 'low'
    timeframe: str          # e.g. '5min', '15min', '1H'
    broken: bool = False    # True once price has traded through this level

    def __repr__(self) -> str:
        status = "BROKEN" if self.broken else "active"
        return (
            f"SwingPoint({self.type} @ {self.price:.2f}, "
            f"tf={self.timeframe}, ts={self.timestamp}, {status})"
        )


class SwingPointDetector:
    """
    Detects and tracks ICT swing highs and swing lows.

    Usage
    -----
    detector = SwingPointDetector()
    swing_points = detector.detect(df_5min, '5min')
    detector.update_broken(current_price)
    active = detector.get_active()
    """

    def __init__(self, lookbacks: Optional[dict] = None):
        """
        Parameters
        ----------
        lookbacks : dict, optional
            Per-timeframe lookback bars on each side (e.g. {"5min": 5}).
            Defaults to config.SWING_LOOKBACK.
        """
        self.lookbacks: dict = lookbacks if lookbacks is not None else config.SWING_LOOKBACK
        self.swing_points: list[SwingPoint] = []

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def detect(self, candles: pd.DataFrame, timeframe: str) -> list[SwingPoint]:
        """
        Scan candles and return newly detected swing points.

        The full list is also appended to self.swing_points for state tracking.
        History is capped at config.SWING_MAX_HISTORY.

        Parameters
        ----------
        candles   : pd.DataFrame — OHLCV with DatetimeIndex (US/Central)
        timeframe : str — timeframe key matching config.SWING_LOOKBACK

        Returns
        -------
        list[SwingPoint] — newly detected swings from this scan
        """
        if candles.empty:
            return []

        lookback = self._get_lookback(timeframe)
        new_swings: list[SwingPoint] = []

        highs = candles["high"].values
        lows = candles["low"].values
        timestamps = candles.index

        n = len(candles)
        # Need at least 2*lookback+1 candles to detect any swing
        if n < 2 * lookback + 1:
            return []

        for i in range(lookback, n - lookback):
            # ── Swing High ───────────────────────────────────────────
            if self._is_swing_high(highs, i, lookback):
                sp = SwingPoint(
                    price=float(highs[i]),
                    timestamp=timestamps[i],
                    type="high",
                    timeframe=timeframe,
                )
                new_swings.append(sp)

            # ── Swing Low ────────────────────────────────────────────
            if self._is_swing_low(lows, i, lookback):
                sp = SwingPoint(
                    price=float(lows[i]),
                    timestamp=timestamps[i],
                    type="low",
                    timeframe=timeframe,
                )
                new_swings.append(sp)

        # Append and cap history
        self.swing_points.extend(new_swings)
        if len(self.swing_points) > config.SWING_MAX_HISTORY:
            self.swing_points = self.swing_points[-config.SWING_MAX_HISTORY:]

        logger.debug(
            "detect(%s): found %d new swings (%d total)",
            timeframe, len(new_swings), len(self.swing_points),
        )
        return new_swings

    def update_broken(self, current_price: float) -> list[SwingPoint]:
        """
        Mark active swing points as broken when price trades through them.

        Swing High broken: current_price > swing_high.price
        Swing Low broken:  current_price < swing_low.price

        Parameters
        ----------
        current_price : float — last traded price (close or current bid/ask)

        Returns
        -------
        list[SwingPoint] — swing points newly marked broken in this call
        """
        newly_broken: list[SwingPoint] = []
        for sp in self.swing_points:
            if sp.broken:
                continue
            if sp.type == "high" and current_price > sp.price:
                sp.broken = True
                newly_broken.append(sp)
                logger.debug("Swing High %.2f broken at %.2f", sp.price, current_price)
            elif sp.type == "low" and current_price < sp.price:
                sp.broken = True
                newly_broken.append(sp)
                logger.debug("Swing Low %.2f broken at %.2f", sp.price, current_price)
        return newly_broken

    def get_active(self, type_filter: Optional[str] = None) -> list[SwingPoint]:
        """
        Return swing points that have NOT been broken yet.

        Parameters
        ----------
        type_filter : str, optional — 'high' | 'low' | None (both)

        Returns
        -------
        list[SwingPoint] sorted by timestamp ascending
        """
        active = [sp for sp in self.swing_points if not sp.broken]
        if type_filter is not None:
            active = [sp for sp in active if sp.type == type_filter]
        return sorted(active, key=lambda sp: sp.timestamp)

    def get_latest_swing_high(self) -> Optional[SwingPoint]:
        """Return the most recent unbroken swing high, or None."""
        highs = self.get_active("high")
        return highs[-1] if highs else None

    def get_latest_swing_low(self) -> Optional[SwingPoint]:
        """Return the most recent unbroken swing low, or None."""
        lows = self.get_active("low")
        return lows[-1] if lows else None

    def clear(self) -> None:
        """Reset internal state (call when starting a new session)."""
        self.swing_points.clear()

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_lookback(self, timeframe: str) -> int:
        """Return lookback for timeframe; fall back to default 5 if unknown."""
        return self.lookbacks.get(timeframe, 5)

    @staticmethod
    def _is_swing_high(highs, i: int, lookback: int) -> bool:
        """
        True if highs[i] is strictly greater than every other high
        in [i-lookback .. i-1] and [i+1 .. i+lookback].
        """
        pivot = highs[i]
        left = highs[i - lookback: i]
        right = highs[i + 1: i + lookback + 1]
        return all(pivot > h for h in left) and all(pivot > h for h in right)

    @staticmethod
    def _is_swing_low(lows, i: int, lookback: int) -> bool:
        """
        True if lows[i] is strictly less than every other low
        in [i-lookback .. i-1] and [i+1 .. i+lookback].
        """
        pivot = lows[i]
        left = lows[i - lookback: i]
        right = lows[i + 1: i + lookback + 1]
        return all(pivot < l for l in left) and all(pivot < l for l in right)
