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

    @staticmethod
    def refresh_equal_levels_into(
        tracked: list,
        swing_points,
        timeframe: str,
        threshold_pct: float = 0.001,
        min_count: int = 2,
        merge_tolerance_pct: float = 0.0005,
    ) -> int:
        """Compute equal_highs / equal_lows from current swings and merge them
        into `tracked` (the engine's live tracked_levels list) without
        creating duplicates.

        Dedup rule: a newly-detected equal level is considered "the same" as
        an existing one when both are the same type AND within
        merge_tolerance_pct of each other. In that case we skip (keep the
        existing level's swept flag and timestamp intact — we do NOT want
        to reset a swept flag just because the cluster recomputed).

        Stale "equal_*" levels whose cluster no longer holds are NOT pruned
        here — the strategy already filters on `swept==True`, so once a
        level is swept it stops mattering. Keeping the merged list small
        (O(tens)) makes pruning unnecessary.

        Returns
        -------
        int — number of NEW levels appended to `tracked`.
        """
        # Build a LiquidityDetector view of the swing input.
        det = LiquidityDetector()
        new_levels = det.detect_equal_levels(
            swing_points, timeframe, threshold_pct, min_count,
        )
        if not new_levels:
            return 0

        _LVL_TYPES = ("equal_highs", "equal_lows")
        existing = [
            lvl for lvl in tracked
            if getattr(lvl, "type", "") in _LVL_TYPES
        ]

        added = 0
        for new in new_levels:
            is_dup = False
            for old in existing:
                if old.type != new.type:
                    continue
                centre = old.price
                if centre <= 0:
                    continue
                if abs(new.price - centre) / centre <= merge_tolerance_pct:
                    is_dup = True
                    break
            if not is_dup:
                tracked.append(new)
                added += 1
        return added

    def get_pdh_pdl(
        self,
        df_daily: pd.DataFrame,
        as_of_ts: Optional[pd.Timestamp] = None,
    ) -> tuple[float, float]:
        """
        Return the Previous Day High and Low — i.e., the most recent
        COMPLETED daily session's high/low.

        CRITICAL (2026-04-23 fix): The last row of ``df_daily`` may be the
        CURRENT forming session (tf_manager anchors daily sessions at
        18:00 CT = CME Globex open; a bar labelled for "today's session"
        starts at yesterday 18:00 CT and runs until today 17:00 CT — it
        is FORMING all day). Using ``.iloc[-1]`` without a completion
        check returns the forming bar, which means "PDH" is actually the
        running high of the current session, not the previous one.

        When ``as_of_ts`` is provided we drop the forming bar by keeping
        only rows whose session-label date is strictly before the current
        session's date. Falls back to ``iloc[-1]`` (legacy behavior) if
        ``as_of_ts`` is None — callers that have a clock (main.py seed,
        backtest per-bar loop) should always pass it.

        Parameters
        ----------
        df_daily : pd.DataFrame — output of TimeframeManager.aggregate(_, "D")
        as_of_ts : pd.Timestamp, optional — US/Central clock for forming-bar
            exclusion. When provided, its date (+6h CME shift) becomes the
            "today" that is excluded from PDH computation.

        Returns
        -------
        (PDH, PDL) — or (nan, nan) if no completed session available
        """
        import math
        if df_daily.empty:
            return math.nan, math.nan
        completed = df_daily
        if as_of_ts is not None:
            # Compute today's session-label the same way tf_manager does
            today_label = (as_of_ts + pd.Timedelta(hours=6)).date()
            # Keep only bars whose label is strictly before today's session
            completed = df_daily[df_daily.index.map(lambda ts: ts.date()) < today_label]
            if completed.empty:
                return math.nan, math.nan
        row = completed.iloc[-1]
        return float(row["high"]), float(row["low"])

    def get_pwh_pwl(
        self,
        df_weekly: pd.DataFrame,
        as_of_ts: Optional[pd.Timestamp] = None,
    ) -> tuple[float, float]:
        """
        Return the Previous Week High and Low — i.e., the most recent
        COMPLETED weekly bar (Mon-Fri completed session).

        CRITICAL (2026-04-23 fix): Same root cause as ``get_pdh_pdl``. The
        last row of ``df_weekly`` is the CURRENT forming week whenever we
        are inside that Mon-Fri window. tf_manager labels each weekly bar
        by the Monday of the ISO week; the current forming bar stays under
        that Monday label until Friday 17:00 CT. Taking ``.iloc[-1]`` then
        returns this forming bar — "PWH" ends up being the running high
        of the current week.

        Fix: when ``as_of_ts`` is provided, exclude any weekly bar whose
        Monday label matches the current week's Monday.

        Parameters
        ----------
        df_weekly : pd.DataFrame — output of TimeframeManager.aggregate(_, "W")
        as_of_ts : pd.Timestamp, optional

        Returns
        -------
        (PWH, PWL) — or (nan, nan)
        """
        import math
        if df_weekly.empty:
            return math.nan, math.nan
        completed = df_weekly
        if as_of_ts is not None:
            # Compute current week's Monday the same way tf_manager does
            session_date = (as_of_ts + pd.Timedelta(hours=6)).date()
            # Monday of the ISO week containing session_date
            current_monday = pd.Timestamp(session_date) - pd.Timedelta(
                days=pd.Timestamp(session_date).weekday()
            )
            current_monday = current_monday.date()
            # Keep only weekly bars strictly before the current week's Monday
            completed = df_weekly[df_weekly.index.map(lambda ts: ts.date()) < current_monday]
            if completed.empty:
                return math.nan, math.nan
        row = completed.iloc[-1]
        return float(row["high"]), float(row["low"])

    def build_key_levels(
        self,
        df_daily: Optional[pd.DataFrame] = None,
        df_weekly: Optional[pd.DataFrame] = None,
        as_of_ts: Optional[pd.Timestamp] = None,
    ) -> list[LiquidityLevel]:
        """
        Convenience method: build PDH/PDL and PWH/PWL LiquidityLevel objects.

        Parameters
        ----------
        df_daily  : pd.DataFrame, optional — daily bars (tf_manager "D")
        df_weekly : pd.DataFrame, optional — weekly bars (tf_manager "W")
        as_of_ts  : pd.Timestamp, optional — US/Central clock for
            forming-bar exclusion. When provided, PDH/PDL/PWH/PWL come
            from the most recent COMPLETED daily/weekly session.

            Callers should pass the latest 1-min bar's timestamp so the
            "today" and "current-week" forming bars get dropped. Omitting
            this reproduces legacy behavior (iloc[-1]) which reads from
            the forming bar — that bug at 2026-04-22 caused PWH to show
            27,138 instead of the real 26,883.

        Returns
        -------
        list[LiquidityLevel]
        """
        levels: list[LiquidityLevel] = []
        import math

        if df_daily is not None and not df_daily.empty:
            pdh, pdl = self.get_pdh_pdl(df_daily, as_of_ts=as_of_ts)
            if not math.isnan(pdh):
                # Use the level's own bar timestamp (exclude forming)
                if as_of_ts is not None:
                    today_label = (as_of_ts + pd.Timedelta(hours=6)).date()
                    completed = df_daily[df_daily.index.map(lambda t: t.date()) < today_label]
                    ts = completed.index[-1] if not completed.empty else df_daily.index[-1]
                else:
                    ts = df_daily.index[-1]
                levels.append(LiquidityLevel(price=pdh, type="PDH", timestamp=ts))
                levels.append(LiquidityLevel(price=pdl, type="PDL", timestamp=ts))

        if df_weekly is not None and not df_weekly.empty:
            pwh, pwl = self.get_pwh_pwl(df_weekly, as_of_ts=as_of_ts)
            if not math.isnan(pwh):
                if as_of_ts is not None:
                    session_date = (as_of_ts + pd.Timedelta(hours=6)).date()
                    current_monday = pd.Timestamp(session_date) - pd.Timedelta(
                        days=pd.Timestamp(session_date).weekday()
                    )
                    current_monday = current_monday.date()
                    completed = df_weekly[df_weekly.index.map(lambda t: t.date()) < current_monday]
                    ts = completed.index[-1] if not completed.empty else df_weekly.index[-1]
                else:
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
