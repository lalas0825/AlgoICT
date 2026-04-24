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
FVG_MITIGATION_MODE = getattr(config, "FVG_MITIGATION_MODE", "body_close")


@dataclass
class FVG:
    """Represents a detected ICT Fair Value Gap."""

    top: float          # upper boundary of the gap
    bottom: float       # lower boundary of the gap
    direction: str      # 'bullish' | 'bearish'
    timeframe: str
    candle_index: int   # index of the middle candle (i in the 3-candle pattern)
    timestamp: pd.Timestamp   # timestamp of the middle candle
    # stop_reference: "outer wick" of candle 1 (pre-gap candle):
    #   Bullish FVG: candle_1 low  (below FVG.bottom = candle_1 high)
    #   Bearish FVG: candle_1 high (above FVG.top    = candle_1 low)
    # ICT Silver Bullet places the stop 1 tick beyond this value
    # (section 5.1: "the number one candle is where your stop loss is").
    # NaN default preserves backward-compat for callers constructing FVGs
    # directly in tests without the candle-1 OHLC context.
    stop_reference: float = float("nan")
    mitigated: bool = False
    is_ifvg: bool = False  # True when this is an Inversed FVG

    @property
    def midpoint(self) -> float:
        return self.bottom + 0.5 * (self.top - self.bottom)

    @property
    def consequent_encroachment(self) -> float:
        """ICT Consequent Encroachment — 50% of the FVG gap. Distinct from
        the OB Mean Threshold (50% of OB body). Used as scale-in level per
        ICT section 2.3 ('if it touches the consequent encroachment I'll
        buy that too') and as invalidation threshold in some ICT-derivative
        methodologies (though ICT himself only invalidates on body close
        beyond the FVG distal)."""
        return self.midpoint

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
                    # Candle 1 (pre-gap) LOW is the stop reference — a tick
                    # below this is where ICT anchors the Silver Bullet stop.
                    stop_reference=float(lows[i - 1]),
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
                    # Candle 1 HIGH — one tick above = short stop per ICT.
                    stop_reference=float(highs[i - 1]),
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
        Update FVG mitigation state.

        Two modes, selected by config.FVG_MITIGATION_MODE:

        "body_close" (ICT canonical, default 2026-04-20)
            An FVG is only INVALIDATED when the candle BODY closes beyond
            the distal edge. Wicks through the gap do NOT count. 50-75%
            fill is a normal retrace / add-position zone, not invalidation.
            ICT quote: "we don't want to ever want to see the bodies close
            above it".
              Bullish FVG: mitigated when close < fvg.bottom (distal)
              Bearish FVG: mitigated when close > fvg.top    (distal)
            Every body-close invalidation produces an IFVG (polarity flip)
            — no ATR displacement filter needed; ICT treats any body close
            through the distal as the algorithmic trigger.

        "ratio" (legacy, pre-ICT-alignment)
            Mitigate at FVG_MITIGATION_RATIO fill of the gap. IFVG
            conversion gated on candle_body > IFVG_ATR_MULTIPLIER × ATR(14).
            Kept for A/B testing and backward compatibility only.

        IFVG invalidation (both modes): bullish IFVG killed when close <
        fvg.bottom, bearish IFVG killed when close > fvg.top.

        Parameters
        ----------
        current_price : float — CLOSE of the latest candle.
        candle_body   : float, optional — |close - open| of latest candle.
                        Only consulted in "ratio" mode.
        atr_14        : float, optional — 14-period ATR at the latest candle.
                        Only consulted in "ratio" mode.

        Returns
        -------
        list[FVG] — FVGs newly mitigated in this call
        """
        newly_mitigated: list[FVG] = []
        new_ifvgs: list[FVG] = []

        # Pre-compute displacement flag for legacy "ratio" mode only.
        is_displacement = False
        if FVG_MITIGATION_MODE == "ratio":
            has_disp_data = (
                candle_body is not None
                and atr_14 is not None
                and atr_14 > 0
            )
            is_displacement = (
                has_disp_data
                and candle_body > self.IFVG_ATR_MULTIPLIER * atr_14
            )

        for fvg in self.fvgs:
            if fvg.mitigated:
                continue

            # ── IFVG invalidation (common to both modes) ───────────────
            if fvg.is_ifvg:
                if fvg.direction == "bullish" and current_price < fvg.bottom:
                    fvg.mitigated = True
                    logger.debug(
                        "Bullish IFVG [%.2f-%.2f] invalidated at %.2f",
                        fvg.bottom, fvg.top, current_price,
                    )
                elif fvg.direction == "bearish" and current_price > fvg.top:
                    fvg.mitigated = True
                    logger.debug(
                        "Bearish IFVG [%.2f-%.2f] invalidated at %.2f",
                        fvg.bottom, fvg.top, current_price,
                    )
                continue

            # ── Regular FVG mitigation ─────────────────────────────────
            if FVG_MITIGATION_MODE == "body_close":
                # ICT canonical: only body close beyond distal invalidates.
                invalidate = False
                if fvg.direction == "bullish" and current_price < fvg.bottom:
                    invalidate = True
                elif fvg.direction == "bearish" and current_price > fvg.top:
                    invalidate = True

                if invalidate:
                    fvg.mitigated = True
                    newly_mitigated.append(fvg)
                    # Every body-close invalidation → IFVG (ICT polarity flip)
                    inv_dir = "bearish" if fvg.direction == "bullish" else "bullish"
                    new_ifvgs.append(FVG(
                        top=fvg.top, bottom=fvg.bottom,
                        direction=inv_dir, timeframe=fvg.timeframe,
                        candle_index=fvg.candle_index, timestamp=fvg.timestamp,
                        is_ifvg=True,
                    ))
                    logger.debug(
                        "%s FVG body-closed through distal -> %s IFVG [%.2f-%.2f]",
                        fvg.direction.title(), inv_dir.title(),
                        fvg.bottom, fvg.top,
                    )
                continue

            # ── Legacy "ratio" mode ────────────────────────────────────
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
        # Exclude IFVGs — this method returns REGULAR FVGs only. IFVGs are
        # inverted-direction products of a mitigated parent FVG; they live
        # in the same self.fvgs list but are semantically distinct and
        # callers fetch them via get_active_ifvgs(). Prior to 2026-04-17
        # the is_ifvg flag was NOT filtered here — a bullish IFVG would
        # leak into get_active(direction="bullish") and the strategy's
        # `used_ifvg` flag (which depends on the FVG fallback never
        # matching) stayed False, misreporting the setup in logs as a
        # regular FVG.
        active = [fvg for fvg in self.fvgs if not fvg.mitigated and not fvg.is_ifvg]
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
