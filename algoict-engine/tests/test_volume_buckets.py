"""
tests/test_volume_buckets.py
=============================
Tests for toxicity/volume_buckets.py
"""

import pytest
import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from toxicity.volume_buckets import (
    VolumeBucket,
    VolumeBucketizer,
    DEFAULT_NUM_BUCKETS,
)


def _ts(i):
    return pd.Timestamp("2024-01-02 08:30", tz="America/Chicago") + pd.Timedelta(minutes=i)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInit:
    def test_bucket_size_computed(self):
        b = VolumeBucketizer(daily_volume=500_000, num_buckets=50)
        assert b.bucket_size == 10_000

    def test_default_num_buckets(self):
        b = VolumeBucketizer(daily_volume=500_000)
        assert b.num_buckets == 50

    def test_invalid_daily_volume(self):
        with pytest.raises(ValueError):
            VolumeBucketizer(daily_volume=0)

    def test_invalid_num_buckets(self):
        with pytest.raises(ValueError):
            VolumeBucketizer(daily_volume=500_000, num_buckets=0)


# ---------------------------------------------------------------------------
# Single bar scenarios
# ---------------------------------------------------------------------------

class TestSingleBar:
    def test_bar_below_bucket_size_no_emit(self):
        b = VolumeBucketizer(daily_volume=500_000, num_buckets=50)   # bucket_size=10k
        out = b.add_bar(_ts(0), open_price=17000, close_price=17001, volume=5000)
        assert out == []

    def test_bar_exactly_bucket_size_emits_one(self):
        b = VolumeBucketizer(daily_volume=500_000, num_buckets=50)
        out = b.add_bar(_ts(0), open_price=17000, close_price=17001, volume=10000)
        assert len(out) == 1
        assert out[0].volume == 10000

    def test_bar_double_bucket_emits_two(self):
        b = VolumeBucketizer(daily_volume=500_000, num_buckets=50)
        out = b.add_bar(_ts(0), open_price=17000, close_price=17002, volume=20000)
        assert len(out) == 2

    def test_bar_triple_bucket_emits_three(self):
        b = VolumeBucketizer(daily_volume=500_000, num_buckets=50)
        out = b.add_bar(_ts(0), open_price=17000, close_price=17003, volume=30000)
        assert len(out) == 3

    def test_zero_volume_no_emit(self):
        b = VolumeBucketizer(daily_volume=500_000)
        out = b.add_bar(_ts(0), open_price=17000, close_price=17001, volume=0)
        assert out == []


# ---------------------------------------------------------------------------
# Multi-bar accumulation
# ---------------------------------------------------------------------------

class TestAccumulation:
    def test_accumulate_across_bars(self):
        b = VolumeBucketizer(daily_volume=500_000, num_buckets=50)   # 10k per bucket
        b.add_bar(_ts(0), 17000, 17000, 3000)
        b.add_bar(_ts(1), 17000, 17000, 3000)
        out = b.add_bar(_ts(2), 17000, 17000, 4000)   # total = 10k
        assert len(out) == 1
        assert out[0].volume == 10000

    def test_bucket_spans_multiple_bars_n_bars(self):
        b = VolumeBucketizer(daily_volume=500_000, num_buckets=50)
        b.add_bar(_ts(0), 17000, 17001, 3000)
        b.add_bar(_ts(1), 17001, 17002, 3000)
        out = b.add_bar(_ts(2), 17002, 17003, 4000)
        assert out[0].n_bars == 3

    def test_price_change_computed_correctly(self):
        b = VolumeBucketizer(daily_volume=500_000)
        b.add_bar(_ts(0), 17000, 17000, 5000)
        out = b.add_bar(_ts(1), 17000, 17002, 5000)
        assert len(out) == 1
        # Start price near 17000, end price at 17002
        assert out[0].start_price == pytest.approx(17000, abs=0.1)
        assert out[0].end_price == pytest.approx(17002, abs=0.1)
        assert out[0].price_change == pytest.approx(2.0, abs=0.1)


# ---------------------------------------------------------------------------
# DataFrame processing
# ---------------------------------------------------------------------------

class TestProcessDataFrame:
    def test_empty_df(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        b = VolumeBucketizer(daily_volume=500_000)
        result = b.process_dataframe(df)
        assert result == []

    def test_all_bars_sum_to_full_day(self):
        """1000 bars of 500 volume each = 500,000 total -> 50 buckets."""
        rows = []
        for i in range(1000):
            rows.append({
                "open": 17000 + i * 0.01,
                "high": 17000 + i * 0.01 + 0.5,
                "low": 17000 + i * 0.01 - 0.5,
                "close": 17000 + (i + 1) * 0.01,
                "volume": 500,
            })
        df = pd.DataFrame(rows, index=[_ts(i) for i in range(1000)])

        b = VolumeBucketizer(daily_volume=500_000, num_buckets=50)
        buckets = b.process_dataframe(df)
        assert len(buckets) == 50

    def test_bucket_volumes_all_equal(self):
        rows = []
        for i in range(1000):
            rows.append({"open": 17000, "high": 17001, "low": 16999,
                         "close": 17000, "volume": 500})
        df = pd.DataFrame(rows, index=[_ts(i) for i in range(1000)])

        buckets = VolumeBucketizer(daily_volume=500_000).process_dataframe(df)
        for b in buckets:
            assert b.volume == pytest.approx(10000, abs=0.01)

    def test_preserves_timestamps(self):
        rows = [{"open": 17000, "high": 17001, "low": 16999,
                 "close": 17000, "volume": 5000} for _ in range(4)]
        df = pd.DataFrame(rows, index=[_ts(i) for i in range(4)])
        buckets = VolumeBucketizer(daily_volume=500_000).process_dataframe(df)
        assert len(buckets) == 2
        assert buckets[0].start_time == _ts(0)
        assert buckets[1].end_time == _ts(3)


# ---------------------------------------------------------------------------
# Flush / reset
# ---------------------------------------------------------------------------

class TestFlushReset:
    def test_flush_partial(self):
        b = VolumeBucketizer(daily_volume=500_000)
        b.add_bar(_ts(0), 17000, 17001, 3000)
        partial = b.flush()
        assert partial is not None
        assert partial.volume == 3000

    def test_flush_empty_returns_none(self):
        b = VolumeBucketizer(daily_volume=500_000)
        assert b.flush() is None

    def test_flush_clears_state(self):
        b = VolumeBucketizer(daily_volume=500_000)
        b.add_bar(_ts(0), 17000, 17001, 3000)
        b.flush()
        # Next bar should start fresh
        out = b.add_bar(_ts(1), 17000, 17001, 10000)
        assert len(out) == 1
        assert out[0].volume == 10000

    def test_reset_clears_state(self):
        b = VolumeBucketizer(daily_volume=500_000)
        b.add_bar(_ts(0), 17000, 17001, 3000)
        b.reset()
        assert b._cur_volume == 0

    def test_price_change_property(self):
        bucket = VolumeBucket(
            volume=10000, start_price=17000, end_price=17003,
            start_time=_ts(0), end_time=_ts(2), n_bars=3,
        )
        assert bucket.price_change == 3.0
