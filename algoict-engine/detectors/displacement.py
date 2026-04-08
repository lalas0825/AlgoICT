"""
detectors/displacement.py
==========================
ICT Displacement detection.

Definition
----------
A Displacement is a strong, impulsive candle whose BODY is larger than
2 × ATR (Average True Range) of the recent lookback.  It represents
institutional order flow entering the market with urgency — creating
imbalance and often leaving Fair Value Gaps.

Body = |close - open|  (excludes wicks)
ATR  = rolling mean of True Range over atr_period bars

Direction:
  bullish  — close > open (strong up move)
  bearish  — close < open (strong down move)

Magnitude = body size (in price units)

All DataFrames must have US/Central DatetimeIndex and OHLCV columns.
"""

import logging
from dataclasses import dataclass

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Default multiplier: body > multiplier × ATR
DISPLACEMENT_ATR_MULTIPLIER = 2.0


@dataclass
class Displacement:
    """Represents a single displacement candle."""

    direction: str      # 'bullish' | 'bearish'
    magnitude: float    # body size in price units
    atr: float          # ATR at the time of the candle
    timestamp: pd.Timestamp
    timeframe: str
    candle_index: int   # position in the DataFrame

    def __repr__(self) -> str:
        return (
            f"Displacement({self.direction}, mag={self.magnitude:.2f}, "
            f"atr={self.atr:.2f}, tf={self.timeframe}, ts={self.timestamp})"
        )


class DisplacementDetector:
    """
    Detects ICT displacement candles per timeframe.

    Usage
    -----
    det = DisplacementDetector()
    displacements = det.detect(df_5min, '5min')
    recent = det.get_recent(n=3)
    """

    def __init__(self, multiplier: float = DISPLACEMENT_ATR_MULTIPLIER):
        """
        Parameters
        ----------
        multiplier : float — body must exceed this × ATR to qualify
                    (default 2.0)
        """
        self.multiplier = multiplier
        self.displacements: list[Displacement] = []

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def detect(
        self,
        candles: pd.DataFrame,
        timeframe: str,
        atr_period: int = 14,
    ) -> list[Displacement]:
        """
        Scan candles for displacement moves and return newly detected ones.

        Skips candles whose timestamps are already tracked to avoid
        re-detecting on repeated calls with growing slices.

        Parameters
        ----------
        candles    : pd.DataFrame — OHLCV with DatetimeIndex
        timeframe  : str
        atr_period : int — lookback period for ATR (default 14)

        Returns
        -------
        list[Displacement] — newly detected displacements
        """
        if len(candles) < atr_period + 1:
            return []

        existing_keys = {(d.timestamp, d.timeframe) for d in self.displacements}
        new_disps: list[Displacement] = []

        opens = candles["open"].values
        highs = candles["high"].values
        lows = candles["low"].values
        closes = candles["close"].values
        timestamps = candles.index

        atr_arr = self._compute_atr(highs, lows, closes, atr_period)

        for i in range(atr_period, len(candles)):
            ts = timestamps[i]
            if (ts, timeframe) in existing_keys:
                continue

            body = abs(closes[i] - opens[i])
            threshold = self.multiplier * atr_arr[i]

            if body > threshold:
                direction = "bullish" if closes[i] > opens[i] else "bearish"
                disp = Displacement(
                    direction=direction,
                    magnitude=float(body),
                    atr=float(atr_arr[i]),
                    timestamp=ts,
                    timeframe=timeframe,
                    candle_index=i,
                )
                new_disps.append(disp)
                existing_keys.add((ts, timeframe))
                logger.debug("Displacement: %s", disp)

        self.displacements.extend(new_disps)
        logger.debug(
            "detect(%s): found %d new displacements (%d total)",
            timeframe, len(new_disps), len(self.displacements),
        )
        return new_disps

    def get_recent(
        self,
        n: int = 1,
        timeframe: str | None = None,
        direction: str | None = None,
    ) -> list[Displacement]:
        """
        Return the most recent N displacements, newest first.

        Parameters
        ----------
        n         : int — max number to return
        timeframe : str, optional — filter by timeframe
        direction : str, optional — 'bullish' | 'bearish'

        Returns
        -------
        list[Displacement]
        """
        result = list(self.displacements)
        if timeframe is not None:
            result = [d for d in result if d.timeframe == timeframe]
        if direction is not None:
            result = [d for d in result if d.direction == direction]
        # Sort descending by timestamp
        result.sort(key=lambda d: d.timestamp, reverse=True)
        return result[:n]

    def clear(self) -> None:
        """Reset all detected displacements."""
        self.displacements.clear()

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_atr(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int,
    ) -> np.ndarray:
        """
        Compute per-bar ATR using a simple rolling mean of True Range.

        TR[i] = max(H[i]-L[i], |H[i]-C[i-1]|, |L[i]-C[i-1]|)
        ATR[i] = mean(TR[i-period+1 .. i])
        """
        n = len(highs)
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )

        atr = np.zeros(n)
        for i in range(n):
            start = max(0, i - period + 1)
            atr[i] = tr[start: i + 1].mean()
        return atr
