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
    is_ifvg: bool = False  # True when this is an Inversed FVG

    @property
    def midpoint(self) -> float:
        return self.bottom + 0.5 * (self.top - self.bottom)

    def __repr__(self) -> str:
        kind = "IFVG" if self.is_ifvg else "FVG"
        status = "MITIGATED" if self.mitigated else "active"
        return (
            f"{kind}({self.direction} [{self.bottom:.2f}-{self.top:.2f}], "
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

    # IFVG conversion threshold: crossing candle body must be >= this × ATR
    IFVG_ATR_MULTIPLIER = 1.5

    def update_mitigation(
        self,
        current_price: float,
        candle_body: Optional[float] = None,
        atr_14: Optional[float] = None,
    ) -> list[FVG]:
        """
        Mark active FVGs as mitigated when price fills FVG_MITIGATION_RATIO
        of the gap from the entry side (M17a, configurable; 0.75 default vs
        ICT standard 0.50 — FVGs survive longer so post-sweep returns still
        qualify). Also invalidate active IFVGs whose opposite extreme is
        breached.

        Bullish FVG: mitigated when price <= top   - ratio * (top - bottom)
        Bearish FVG: mitigated when price >= bottom + ratio * (top - bottom)

        IFVG conversion: a mitigated FVG is promoted to IFVG (inverted
        direction) ONLY when the crossing candle shows displacement — i.e.
        candle_body > 1.5 × ATR(14). Weak crosses just kill the FVG.

        Parameters
        ----------
        current_price : float — last traded price (close or bid/ask)
        candle_body   : float, optional — abs(open - close) of the latest
                        candle. Required for IFVG conversion.
        atr_14        : float, optional — 14-period ATR at the latest candle.
                        Required for IFVG conversion.

        Returns
        -------
        list[FVG] — FVGs newly mitigated in this call
        """
        newly_mitigated: list[FVG] = []
        new_ifvgs: list[FVG] = []

        # Can we evaluate displacement for IFVG conversion?
        has_displacement_data = (
            candle_body is not None
            and atr_14 is not None
            and atr_14 > 0
        )
        is_displacement = (
            has_displacement_data
            and candle_body > self.IFVG_ATR_MULTIPLIER * atr_14
        )

        for fvg in self.fvgs:
            if fvg.mitigated:
                continue

            # ── Regular FVG mitigation (uses configurable ratio) ───────
            if not fvg.is_ifvg:
                gap = fvg.top - fvg.bottom
                mitigated_now = False
                if fvg.direction == "bullish":
                    mitigation_level = fvg.top - FVG_MITIGATION_RATIO * gap
                    if current_price <= mitigation_level:
                        mitigated_now = True
                elif fvg.direction == "bearish":
                    mitigation_level = fvg.bottom + FVG_MITIGATION_RATIO * gap
                    if current_price >= mitigation_level:
                        mitigated_now = True

                if mitigated_now:
                    fvg.mitigated = True
                    newly_mitigated.append(fvg)

                    if is_displacement:
                        inv_dir = "bearish" if fvg.direction == "bullish" else "bullish"
                        new_ifvgs.append(FVG(
                            top=fvg.top, bottom=fvg.bottom,
                            direction=inv_dir, timeframe=fvg.timeframe,
                            candle_index=fvg.candle_index, timestamp=fvg.timestamp,
                            is_ifvg=True,
                        ))
                        logger.debug(
                            "%s FVG mitigated (ratio=%.2f) with displacement "
                            "(body=%.2f > %.1fx ATR=%.2f) -> %s IFVG [%.2f-%.2f]",
                            fvg.direction.title(), FVG_MITIGATION_RATIO,
                            candle_body, self.IFVG_ATR_MULTIPLIER, atr_14,
                            inv_dir.title(), fvg.bottom, fvg.top,
                        )
                    else:
                        logger.debug(
                            "%s FVG mitigated (ratio=%.2f, weak cross, no IFVG) [%.2f-%.2f]",
                            fvg.direction.title(), FVG_MITIGATION_RATIO,
                            fvg.bottom, fvg.top,
                        )

            # ── IFVG invalidation: price breaches opposite extreme ─────
            else:
                if fvg.direction == "bullish" and current_price < fvg.bottom:
                    fvg.mitigated = True
                    logger.debug("Bullish IFVG [%.2f-%.2f] invalidated at %.2f", fvg.bottom, fvg.top, current_price)
                elif fvg.direction == "bearish" and current_price > fvg.top:
                    fvg.mitigated = True
                    logger.debug("Bearish IFVG [%.2f-%.2f] invalidated at %.2f", fvg.bottom, fvg.top, current_price)

        self.fvgs.extend(new_ifvgs)
        if len(self.fvgs) > FVG_MAX_HISTORY:
            self.fvgs = self.fvgs[-FVG_MAX_HISTORY:]
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

    def get_active_ifvgs(
        self,
        timeframe: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> list[FVG]:
        """Return active IFVGs (inversed FVGs), optionally filtered."""
        active = [f for f in self.fvgs if not f.mitigated and f.is_ifvg]
        if timeframe is not None:
            active = [f for f in active if f.timeframe == timeframe]
        if direction is not None:
            active = [f for f in active if f.direction == direction]
        return sorted(active, key=lambda f: f.timestamp)

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
