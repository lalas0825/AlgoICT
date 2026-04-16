"""
detectors/fair_value_gap.py
============================
ICT Fair Value Gap (FVG) detection and mitigation tracking.

Definitions
-----------
Bullish FVG : candle[i-2].high < candle[i].low
              top    = candle[i].low
              bottom = candle[i-2].high
              (price gapped UP — bullish imbalance)

Bearish FVG : candle[i-2].low > candle[i].high
              top    = candle[i-2].low
              bottom = candle[i].high
              (price gapped DOWN — bearish imbalance)

Mitigation : price touches the 50% level of the gap
             (bottom + 0.5 * (top - bottom)).
             Once mitigated, the FVG is removed from the active list.

All DataFrames must have US/Central DatetimeIndex and OHLCV columns.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

logger = logging.getLogger(__name__)

FVG_MAX_HISTORY = getattr(config, "FVG_MAX_HISTORY", 100)
FVG_MITIGATION_RATIO = getattr(config, "FVG_MITIGATION_RATIO", 0.75)


@dataclass
class FVG:
    """Represents a detected ICT Fair Value Gap."""

    top: float          # upper boundary of the gap
    bottom: float       # lower boundary of the gap
    direction: str      # 'bullish' | 'bearish'
    timeframe: str
    candle_index: int   # index of the middle candle (i in the 3-candle pattern)
    timestamp: pd.Timestamp   # timestamp of the middle candle
    mitigated: bool = False

    @property
    def midpoint(self) -> float:
        return self.bottom + 0.5 * (self.top - self.bottom)

    def __repr__(self) -> str:
        status = "MITIGATED" if self.mitigated else "active"
        return (
            f"FVG({self.direction} [{self.bottom:.2f}–{self.top:.2f}], "
            f"tf={self.timeframe}, ts={self.timestamp}, {status})"
        )


class FairValueGapDetector:
    """
    Detects and tracks ICT Fair Value Gaps.

    Usage
    -----
    detector = FairValueGapDetector()
    fvgs = detector.detect(df_5min, '5min')
    detector.update_mitigation(current_price)
    active = detector.get_active()
    """

    def __init__(self):
        self.fvgs: list[FVG] = []

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def detect(self, candles: pd.DataFrame, timeframe: str) -> list[FVG]:
        """
        Scan candles for new FVGs and return newly detected ones.

        Skips candles whose timestamps are already in self.fvgs to avoid
        re-detecting on repeated calls with growing slices.

        Parameters
        ----------
        candles   : pd.DataFrame — OHLCV with DatetimeIndex
        timeframe : str

        Returns
        -------
        list[FVG] — newly detected FVGs from this scan
        """
        if len(candles) < 3:
            return []

        existing_keys = {(fvg.timestamp, fvg.timeframe) for fvg in self.fvgs}
        new_fvgs: list[FVG] = []

        highs = candles["high"].values
        lows = candles["low"].values
        timestamps = candles.index

        for i in range(1, len(candles) - 1):
            ts = timestamps[i]
            if (ts, timeframe) in existing_keys:
                continue

            # ── Bullish FVG ──────────────────────────────────────────
            if highs[i - 1] < lows[i + 1]:
                fvg = FVG(
                    top=float(lows[i + 1]),
                    bottom=float(highs[i - 1]),
                    direction="bullish",
                    timeframe=timeframe,
                    candle_index=i,
                    timestamp=ts,
                )
                new_fvgs.append(fvg)
                existing_keys.add((ts, timeframe))

            # ── Bearish FVG ──────────────────────────────────────────
            elif lows[i - 1] > highs[i + 1]:
                fvg = FVG(
                    top=float(lows[i - 1]),
                    bottom=float(highs[i + 1]),
                    direction="bearish",
                    timeframe=timeframe,
                    candle_index=i,
                    timestamp=ts,
                )
                new_fvgs.append(fvg)
                existing_keys.add((ts, timeframe))

        self.fvgs.extend(new_fvgs)
        if len(self.fvgs) > FVG_MAX_HISTORY:
            self.fvgs = self.fvgs[-FVG_MAX_HISTORY:]

        logger.debug(
            "detect(%s): found %d new FVGs (%d total)",
            timeframe, len(new_fvgs), len(self.fvgs),
        )
        return new_fvgs

    def update_mitigation(self, current_price: float) -> list[FVG]:
        """
        Mark active FVGs as mitigated when price fills FVG_MITIGATION_RATIO of the gap.

        Bullish FVG: mitigated when price <= top   - ratio * (top - bottom)
                     i.e. price fills ratio from the top downward
        Bearish FVG: mitigated when price >= bottom + ratio * (top - bottom)
                     i.e. price fills ratio from the bottom upward

        With FVG_MITIGATION_RATIO=0.75 (vs ICT standard 0.50), FVGs survive longer,
        giving more time for price to return after a sweep.

        Parameters
        ----------
        current_price : float — last traded price (close or bid/ask)

        Returns
        -------
        list[FVG] — FVGs newly mitigated in this call
        """
        newly_mitigated: list[FVG] = []
        for fvg in self.fvgs:
            if fvg.mitigated:
                continue
            gap = fvg.top - fvg.bottom
            if fvg.direction == "bullish":
                mitigation_level = fvg.top - FVG_MITIGATION_RATIO * gap
                if current_price <= mitigation_level:
                    fvg.mitigated = True
                    newly_mitigated.append(fvg)
                    logger.debug(
                        "Bullish FVG [%.2f–%.2f] mitigated at %.2f (level=%.2f, ratio=%.2f)",
                        fvg.bottom, fvg.top, current_price, mitigation_level, FVG_MITIGATION_RATIO,
                    )
            elif fvg.direction == "bearish":
                mitigation_level = fvg.bottom + FVG_MITIGATION_RATIO * gap
                if current_price >= mitigation_level:
                    fvg.mitigated = True
                    newly_mitigated.append(fvg)
                    logger.debug(
                        "Bearish FVG [%.2f–%.2f] mitigated at %.2f (level=%.2f, ratio=%.2f)",
                        fvg.bottom, fvg.top, current_price, mitigation_level, FVG_MITIGATION_RATIO,
                    )
        return newly_mitigated

    def get_active(
        self,
        timeframe: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> list[FVG]:
        """
        Return FVGs that have NOT been mitigated yet.

        Parameters
        ----------
        timeframe : str, optional — filter by timeframe
        direction : str, optional — 'bullish' | 'bearish' | None (both)

        Returns
        -------
        list[FVG] sorted by timestamp ascending
        """
        active = [fvg for fvg in self.fvgs if not fvg.mitigated]
        if timeframe is not None:
            active = [fvg for fvg in active if fvg.timeframe == timeframe]
        if direction is not None:
            active = [fvg for fvg in active if fvg.direction == direction]
        return sorted(active, key=lambda fvg: fvg.timestamp)

    def get_nearest(
        self,
        current_price: float,
        direction: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Optional["FVG"]:
        """
        Return the nearest active FVG to current_price.

        Parameters
        ----------
        current_price : float
        direction     : str, optional — filter by direction
        timeframe     : str, optional — filter by timeframe

        Returns
        -------
        FVG | None
        """
        candidates = self.get_active(timeframe=timeframe, direction=direction)
        if not candidates:
            return None
        return min(candidates, key=lambda fvg: abs(fvg.midpoint - current_price))

    def clear(self) -> None:
        """Reset all detected FVGs."""
        self.fvgs.clear()
