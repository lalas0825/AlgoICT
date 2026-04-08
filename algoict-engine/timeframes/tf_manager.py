"""
timeframes/tf_manager.py
========================
Aggregates 1-min OHLCV bars into higher timeframes.

All timestamps must be in US/Central (as produced by data_loader).
OHLCV aggregation rule: first(O), max(H), min(L), last(C), sum(V).

Supported timeframes: '5min', '15min', '1H', '4H', 'D', 'W'

NOTE on Daily bars:
    Futures trade nearly 24/5. We anchor daily bars at 18:00 CT (6 PM),
    which is when the CME Globex session opens. This means each "day" bar
    represents 23 hours of trading (18:00 CT to 17:00 CT next day, with a
    1-hour break). For backtesting ICT strategies this is correct — the
    "daily candle" you see on a chart is anchored at 6 PM CT open.
"""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Map our TF labels → pandas resample offsets
# pandas 2.x uses 'min' instead of deprecated 'T', 'h' instead of 'H'
_RESAMPLE_MAP = {
    "5min":  "5min",
    "15min": "15min",
    "1H":    "1h",
    "4H":    "4h",
    "D":     "23h",   # anchored at 18:00 CT — see class method below
    "W":     "5D",    # Mon-Fri week — anchored at Monday 18:00 CT
}

_OHLCV_AGG = {
    "open":   "first",
    "high":   "max",
    "low":    "min",
    "close":  "last",
    "volume": "sum",
}


class TimeframeManager:
    """
    Aggregates 1-min futures bars into higher timeframes using pandas resample.

    Usage:
        tf = TimeframeManager()
        df_5min  = tf.aggregate(df_1min, '5min')
        df_daily = tf.aggregate(df_1min, 'D')
        tf.clear_cache()
    """

    SUPPORTED = {"5min", "15min", "1H", "4H", "D", "W"}

    def __init__(self):
        self._cache: dict[str, pd.DataFrame] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def aggregate(self, df_1min: pd.DataFrame, target_tf: str) -> pd.DataFrame:
        """
        Aggregate a 1-min DataFrame into the target timeframe.

        Parameters
        ----------
        df_1min   : pd.DataFrame with DatetimeIndex (US/Central), columns OHLCV
        target_tf : str — one of '5min', '15min', '1H', '4H', 'D', 'W'

        Returns
        -------
        pd.DataFrame — same timezone, same column order, no NaN rows
        """
        if target_tf not in self.SUPPORTED:
            raise ValueError(
                f"Unsupported timeframe '{target_tf}'. "
                f"Choose from: {sorted(self.SUPPORTED)}"
            )

        if target_tf in self._cache:
            return self._cache[target_tf]

        self._validate_input(df_1min)

        if target_tf in ("D", "W"):
            result = self._aggregate_session(df_1min, target_tf)
        else:
            result = self._aggregate_intraday(df_1min, target_tf)

        # Drop bars where we have no data (gaps produce NaN open/close)
        result = result.dropna(subset=["open", "close"])
        result["volume"] = result["volume"].fillna(0).astype(int)

        self._cache[target_tf] = result
        logger.debug("Aggregated %d 1min bars → %d %s bars", len(df_1min), len(result), target_tf)
        return result

    def clear_cache(self) -> None:
        """Invalidate cached frames (call when new 1min bars arrive)."""
        self._cache.clear()

    def get_latest(self, target_tf: str) -> Optional[pd.Series]:
        """Return the most-recent completed bar for the given timeframe."""
        df = self._cache.get(target_tf)
        if df is None or df.empty:
            return None
        return df.iloc[-1]

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_input(df: pd.DataFrame) -> None:
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing columns: {missing}")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError("DataFrame index must be a DatetimeIndex")
        if df.index.tz is None:
            raise ValueError("DatetimeIndex must be timezone-aware (US/Central expected)")

    def _aggregate_intraday(self, df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
        """
        Standard resample for sub-daily timeframes (5min, 15min, 1H, 4H).
        Label and closed are both 'left': each bar is labelled by its open time.
        """
        freq = _RESAMPLE_MAP[target_tf]
        result = (
            df.resample(freq, label="left", closed="left")
            .agg(_OHLCV_AGG)
        )
        return result

    def _aggregate_session(self, df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
        """
        Daily / Weekly aggregation anchored at 18:00 CT (CME Globex open).

        For daily bars: each bar spans exactly one trading session
            from 18:00 CT (prev calendar day) to 17:00 CT.
        For weekly bars: each bar spans Monday 18:00 CT to Friday 17:00 CT.
        """
        if target_tf == "D":
            # Group by "trading date" = calendar date of the CLOSE (17:00 CT side)
            # A bar from 2025-03-03 18:00 CT to 2025-03-04 16:59 CT belongs to "2025-03-04"
            # We assign session day = actual date if time >= 18:00, else actual date
            #   Bars 18:00-23:59 belong to NEXT calendar day's session
            #   Bars 00:00-17:59 belong to SAME calendar day's session
            session_day = df.index.map(
                lambda ts: (ts + pd.Timedelta(hours=6)).date()
            )
            result = df.groupby(session_day).agg(_OHLCV_AGG)
            result.index = pd.to_datetime(result.index).tz_localize(df.index.tz)
            result.index.name = df.index.name

        else:  # "W"
            # Weekly bars: group by ISO week, anchor to Monday
            # Same session-shift: bars from Sunday 18:00 CT count toward Monday's week
            session_day = df.index.map(
                lambda ts: (ts + pd.Timedelta(hours=6)).date()
            )
            week_key = pd.to_datetime(session_day).to_series().apply(
                lambda d: d - pd.Timedelta(days=d.weekday())  # Monday of that week
            ).values
            result = df.groupby(week_key).agg(_OHLCV_AGG)
            result.index = pd.to_datetime(result.index).tz_localize(df.index.tz)
            result.index.name = df.index.name

        return result
