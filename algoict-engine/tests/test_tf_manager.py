"""
tests/test_tf_manager.py
========================
Unit tests for timeframes/tf_manager.py

Run: cd algoict-engine && python -m pytest tests/test_tf_manager.py -v
"""

import datetime
import pandas as pd
import pytest

from timeframes.tf_manager import TimeframeManager


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_1min_df(
    start: str,
    periods: int,
    open_: float = 100.0,
    tz: str = "US/Central",
) -> pd.DataFrame:
    """Build a minimal 1-min OHLCV DataFrame."""
    idx = pd.date_range(start, periods=periods, freq="1min", tz=tz)
    return pd.DataFrame({
        "open":   [open_ + i for i in range(periods)],
        "high":   [open_ + i + 2 for i in range(periods)],
        "low":    [open_ + i - 1 for i in range(periods)],
        "close":  [open_ + i + 1 for i in range(periods)],
        "volume": [100] * periods,
    }, index=idx)


def _known_5bar() -> pd.DataFrame:
    """
    5 consecutive 1-min bars starting at 09:00 CT on a weekday.
    Used to verify OHLCV aggregation math precisely.

    Bar  open  high  low   close  vol
    0    10    15    8     12     100
    1    12    18    11    15     200
    2    15    20    13    17     150
    3    17    22    14    19     300
    4    19    25    16    21     250
    """
    idx = pd.date_range("2025-03-03 09:00", periods=5, freq="1min", tz="US/Central")
    return pd.DataFrame({
        "open":   [10, 12, 15, 17, 19],
        "high":   [15, 18, 20, 22, 25],
        "low":    [ 8, 11, 13, 14, 16],
        "close":  [12, 15, 17, 19, 21],
        "volume": [100, 200, 150, 300, 250],
    }, index=idx)


# ─── Tests: OHLCV Aggregation ────────────────────────────────────────────────

class TestOhlcvAggregation:

    def test_5min_open_is_first(self):
        """open of 5min bar = open of first 1min bar."""
        tf = TimeframeManager()
        df = _known_5bar()
        agg = tf.aggregate(df, "5min")
        assert len(agg) == 1
        assert agg.iloc[0]["open"] == 10

    def test_5min_high_is_max(self):
        """high of 5min bar = max of all 1min highs."""
        tf = TimeframeManager()
        agg = tf.aggregate(_known_5bar(), "5min")
        assert agg.iloc[0]["high"] == 25

    def test_5min_low_is_min(self):
        """low of 5min bar = min of all 1min lows."""
        tf = TimeframeManager()
        agg = tf.aggregate(_known_5bar(), "5min")
        assert agg.iloc[0]["low"] == 8

    def test_5min_close_is_last(self):
        """close of 5min bar = close of last 1min bar."""
        tf = TimeframeManager()
        agg = tf.aggregate(_known_5bar(), "5min")
        assert agg.iloc[0]["close"] == 21

    def test_5min_volume_is_sum(self):
        """volume of 5min bar = sum of all 1min volumes."""
        tf = TimeframeManager()
        agg = tf.aggregate(_known_5bar(), "5min")
        assert agg.iloc[0]["volume"] == 1000  # 100+200+150+300+250

    def test_5min_bar_count(self):
        """10 × 1min bars → 2 × 5min bars."""
        tf = TimeframeManager()
        df = _make_1min_df("2025-03-03 09:00", 10)
        agg = tf.aggregate(df, "5min")
        assert len(agg) == 2

    def test_15min_bar_count(self):
        """60 × 1min bars → 4 × 15min bars."""
        tf = TimeframeManager()
        df = _make_1min_df("2025-03-03 09:00", 60)
        agg = tf.aggregate(df, "15min")
        assert len(agg) == 4

    def test_1h_bar_count(self):
        """120 × 1min bars → 2 × 1H bars."""
        tf = TimeframeManager()
        df = _make_1min_df("2025-03-03 09:00", 120)
        agg = tf.aggregate(df, "1H")
        assert len(agg) == 2

    def test_4h_bar_count(self):
        """480 × 1min bars → 2 × 4H bars."""
        tf = TimeframeManager()
        df = _make_1min_df("2025-03-03 08:00", 480)
        agg = tf.aggregate(df, "4H")
        assert len(agg) == 2

    def test_columns_preserved(self):
        """Output columns are always [open, high, low, close, volume]."""
        tf = TimeframeManager()
        df = _known_5bar()
        for timeframe in ["5min", "15min", "1H"]:
            agg = tf.aggregate(df, timeframe)
            assert list(agg.columns) == ["open", "high", "low", "close", "volume"], \
                f"Bad columns for {timeframe}"

    def test_index_is_datetime_with_tz(self):
        """Aggregated index is tz-aware DatetimeIndex."""
        tf = TimeframeManager()
        agg = tf.aggregate(_known_5bar(), "5min")
        assert isinstance(agg.index, pd.DatetimeIndex)
        assert agg.index.tz is not None

    def test_volume_dtype_is_int(self):
        """Volume column dtype is integer after aggregation."""
        tf = TimeframeManager()
        agg = tf.aggregate(_known_5bar(), "5min")
        assert pd.api.types.is_integer_dtype(agg["volume"])


# ─── Tests: Daily / Weekly ────────────────────────────────────────────────────

class TestDailyWeekly:

    def test_daily_bar_count_two_days(self):
        """2 trading days of 1-min data → 2 daily bars."""
        tf = TimeframeManager()
        # Day 1: 09:00-16:00 CT on 2025-03-03 (Mon)
        # Day 2: 09:00-16:00 CT on 2025-03-04 (Tue)
        day1 = _make_1min_df("2025-03-03 09:00", 420)  # 7h
        day2 = _make_1min_df("2025-03-04 09:00", 420)
        df = pd.concat([day1, day2])
        agg = tf.aggregate(df, "D")
        assert len(agg) == 2

    def test_weekly_bar_one_week(self):
        """5 trading days of 1-min data → 1 weekly bar."""
        tf = TimeframeManager()
        dfs = []
        for d in range(5):  # Mon-Fri
            date = pd.Timestamp("2025-03-03") + pd.Timedelta(days=d)
            dfs.append(_make_1min_df(f"{date.date()} 09:00", 60))
        df = pd.concat(dfs)
        agg = tf.aggregate(df, "W")
        assert len(agg) == 1


# ─── Tests: Cache ────────────────────────────────────────────────────────────

class TestCache:

    def test_cache_returns_same_object(self):
        """Second call with same TF returns cached result (same id)."""
        tf = TimeframeManager()
        df = _make_1min_df("2025-03-03 09:00", 10)
        first = tf.aggregate(df, "5min")
        second = tf.aggregate(df, "5min")
        assert first is second

    def test_clear_cache_invalidates(self):
        """After clear_cache, next call recomputes."""
        tf = TimeframeManager()
        df = _make_1min_df("2025-03-03 09:00", 10)
        first = tf.aggregate(df, "5min")
        tf.clear_cache()
        second = tf.aggregate(df, "5min")
        # Should be equal in value but different objects
        assert first is not second
        pd.testing.assert_frame_equal(first, second)


# ─── Tests: Validation ───────────────────────────────────────────────────────

class TestValidation:

    def test_invalid_timeframe_raises(self):
        """Unknown timeframe raises ValueError."""
        tf = TimeframeManager()
        df = _make_1min_df("2025-03-03 09:00", 5)
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            tf.aggregate(df, "3min")

    def test_missing_column_raises(self):
        """DataFrame without required columns raises ValueError."""
        tf = TimeframeManager()
        df = pd.DataFrame(
            {"open": [1, 2], "high": [3, 4]},
            index=pd.date_range("2025-03-03 09:00", periods=2, freq="1min", tz="US/Central"),
        )
        with pytest.raises(ValueError, match="missing columns"):
            tf.aggregate(df, "5min")

    def test_naive_timezone_raises(self):
        """DataFrame with naive DatetimeIndex raises ValueError."""
        tf = TimeframeManager()
        df = pd.DataFrame(
            {"open": [1], "high": [2], "low": [0], "close": [1], "volume": [10]},
            index=pd.date_range("2025-03-03 09:00", periods=1, freq="1min"),  # no tz
        )
        with pytest.raises(ValueError, match="timezone-aware"):
            tf.aggregate(df, "5min")
