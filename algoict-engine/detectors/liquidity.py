"""
detectors/liquidity.py
=======================
ICT Liquidity level detection — BSL, SSL, PDH, PDL, PWH, PWL, equal levels.

Definitions
-----------
BSL  (Buy Side Liquidity)  : swing highs / equal highs — pool of resting
                             buy-stop orders above price. A sweep takes price
                             above the level and closes back below it.

SSL  (Sell Side Liquidity) : swing lows / equal lows — pool of resting
                             sell-stop orders below price. A sweep takes price
                             below the level and closes back above it.

PDH / PDL : Previous Day High / Low — most recent completed daily bar.
PWH / PWL : Previous Week High / Low — most recent completed weekly bar.

Equal Highs / Equal Lows : 2+ swing highs (or lows) whose prices are within
                           threshold_pct of each other. These cluster at the
                           same psychological price and represent dense BSL/SSL.

Sweep : the current candle's wick pierces the level but the candle CLOSES
        on the original side — indicating the liquidity was taken without
        commitment to the new side.

All DataFrames must have US/Central DatetimeIndex and OHLCV columns.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from detectors.swing_points import SwingPoint, SwingPointDetector

logger = logging.getLogger(__name__)


@dataclass
class LiquidityLevel:
    """Represents a liquidity pool / key price level."""

    price: float
    type: str           # 'BSL'|'SSL'|'PDH'|'PDL'|'PWH'|'PWL'|'equal_highs'|'equal_lows'
    swept: bool = False
    timestamp: Optional[pd.Timestamp] = None

    def __repr__(self) -> str:
        status = "SWEPT" if self.swept else "active"
        ts = f", ts={self.timestamp}" if self.timestamp else ""
        return f"LiquidityLevel({self.type} @ {self.price:.4f}{ts}, {status})"


class LiquidityDetector:
    """
    Detects and tracks ICT liquidity levels.

    Usage
    -----
    det = LiquidityDetector()
    levels = det.detect_equal_levels(swing_detector, "5min")
    pdh, pdl = det.get_pdh_pdl(df_daily)
    swept = det.check_sweep(current_candle_row, levels)
    """

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def detect_equal_levels(
        self,
        swing_points: SwingPointDetector,
        timeframe: str,
        threshold_pct: float = 0.001,
        min_count: int = 2,
    ) -> list[LiquidityLevel]:
        """
        Find clusters of swing highs / lows within threshold_pct of each other.

        Equal highs cluster → BSL / 'equal_highs' level (avg price of group)
        Equal lows  cluster → SSL / 'equal_lows'  level (avg price of group)

        Parameters
        ----------
        swing_points  : SwingPointDetector — populated with swing history
        timeframe     : str — filter swings by this timeframe
        threshold_pct : float — max relative price difference for same cluster
                        (default 0.001 = 0.1%)
        min_count     : int — minimum swings in a cluster (default 2)

        Returns
        -------
        list[LiquidityLevel]
        """
        highs = [
            sp for sp in swing_points.swing_points
            if sp.type == "high" and sp.timeframe == timeframe and not sp.broken
        ]
        lows = [
            sp for sp in swing_points.swing_points
            if sp.type == "low" and sp.timeframe == timeframe and not sp.broken
        ]

        levels: list[LiquidityLevel] = []
        levels.extend(self._cluster_swings(highs, "equal_highs", threshold_pct, min_count))
        levels.extend(self._cluster_swings(lows, "equal_lows", threshold_pct, min_count))
        return levels

    def get_pdh_pdl(self, df_daily: pd.DataFrame) -> tuple[float, float]:
        """
        Return the Previous Day High and Low.

        Expects df_daily to contain at least one completed daily bar.
        The LAST row is treated as the most recent completed day.

        Returns
        -------
        (PDH, PDL) — or (nan, nan) if data unavailable
        """
        if df_daily.empty:
            import math
            return math.nan, math.nan
        row = df_daily.iloc[-1]
        return float(row["high"]), float(row["low"])

    def get_pwh_pwl(self, df_weekly: pd.DataFrame) -> tuple[float, float]:
        """
        Return the Previous Week High and Low.

        The LAST row of df_weekly is treated as the most recent completed week.

        Returns
        -------
        (PWH, PWL) — or (nan, nan) if data unavailable
        """
        if df_weekly.empty:
            import math
            return math.nan, math.nan
        row = df_weekly.iloc[-1]
        return float(row["high"]), float(row["low"])

    def build_key_levels(
        self,
        df_daily: Optional[pd.DataFrame] = None,
        df_weekly: Optional[pd.DataFrame] = None,
    ) -> list[LiquidityLevel]:
        """
        Convenience method: build PDH/PDL and PWH/PWL LiquidityLevel objects.

        Parameters
        ----------
        df_daily  : pd.DataFrame, optional
        df_weekly : pd.DataFrame, optional

        Returns
        -------
        list[LiquidityLevel]
        """
        levels: list[LiquidityLevel] = []

        if df_daily is not None and not df_daily.empty:
            pdh, pdl = self.get_pdh_pdl(df_daily)
            import math
            if not math.isnan(pdh):
                ts = df_daily.index[-1]
                levels.append(LiquidityLevel(price=pdh, type="PDH", timestamp=ts))
                levels.append(LiquidityLevel(price=pdl, type="PDL", timestamp=ts))

        if df_weekly is not None and not df_weekly.empty:
            pwh, pwl = self.get_pwh_pwl(df_weekly)
            import math
            if not math.isnan(pwh):
                ts = df_weekly.index[-1]
                levels.append(LiquidityLevel(price=pwh, type="PWH", timestamp=ts))
                levels.append(LiquidityLevel(price=pwl, type="PWL", timestamp=ts))

        return levels

    def check_sweep(
        self,
        candle: pd.Series,
        levels: list[LiquidityLevel],
    ) -> list[LiquidityLevel]:
        """
        Detect which levels were swept by the given candle.

        Sweep logic (wick through, close back):
          BSL / PDH / PWH / equal_highs :
            candle.high > level.price AND candle.close < level.price
          SSL / PDL / PWL / equal_lows  :
            candle.low  < level.price AND candle.close > level.price

        Parameters
        ----------
        candle : pd.Series with 'high', 'low', 'close' keys
        levels : list[LiquidityLevel] — levels to check against

        Returns
        -------
        list[LiquidityLevel] — levels newly swept by this candle
        """
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        _bsl_types = {"BSL", "PDH", "PWH", "equal_highs"}
        _ssl_types = {"SSL", "PDL", "PWL", "equal_lows"}

        swept: list[LiquidityLevel] = []
        for level in levels:
            if level.swept:
                continue
            if level.type in _bsl_types:
                if high > level.price and close < level.price:
                    level.swept = True
                    swept.append(level)
                    logger.debug("BSL sweep: %s at high=%.4f, close=%.4f", level, high, close)
            elif level.type in _ssl_types:
                if low < level.price and close > level.price:
                    level.swept = True
                    swept.append(level)
                    logger.debug("SSL sweep: %s at low=%.4f, close=%.4f", level, low, close)
        return swept

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _cluster_swings(
        swings: list[SwingPoint],
        level_type: str,
        threshold_pct: float,
        min_count: int,
    ) -> list[LiquidityLevel]:
        """
        Group swings by price proximity and return one LiquidityLevel per
        cluster that meets min_count.

        Uses a greedy single-pass clustering: sort by price, then merge
        consecutive swings within threshold_pct of the cluster centre.
        """
        if not swings:
            return []

        sorted_swings = sorted(swings, key=lambda sp: sp.price)
        levels: list[LiquidityLevel] = []

        cluster: list[SwingPoint] = [sorted_swings[0]]

        def _flush(cluster: list[SwingPoint]) -> None:
            if len(cluster) >= min_count:
                avg_price = sum(sp.price for sp in cluster) / len(cluster)
                latest_ts = max(sp.timestamp for sp in cluster)
                levels.append(LiquidityLevel(
                    price=avg_price,
                    type=level_type,
                    timestamp=latest_ts,
                ))

        for sp in sorted_swings[1:]:
            centre = sum(s.price for s in cluster) / len(cluster)
            if centre > 0 and abs(sp.price - centre) / centre <= threshold_pct:
                cluster.append(sp)
            else:
                _flush(cluster)
                cluster = [sp]

        _flush(cluster)
        return levels
