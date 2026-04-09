"""
tests/test_vpin_calculator.py
==============================
Tests for toxicity/vpin_calculator.py
"""

import pytest
import pandas as pd
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from toxicity.volume_buckets import VolumeBucket, VolumeBucketizer
from toxicity.bulk_classifier import BVCClassifier, ClassifiedBucket
from toxicity.vpin_calculator import (
    VPINCalculator,
    VPINReading,
    classify_toxicity,
    is_extreme,
    is_high_or_worse,
    tag_trades_with_vpin,
    analyze_vpin_impact,
    CALM_MAX,
    NORMAL_MAX,
    ELEVATED_MAX,
    HIGH_MAX,
)


def _ts(i):
    return pd.Timestamp("2024-01-02 08:30", tz="America/Chicago") + pd.Timedelta(minutes=i)


def _classified(dp: float, volume: float = 10000, t_idx: int = 0) -> ClassifiedBucket:
    bucket = VolumeBucket(
        volume=volume,
        start_price=17000.0,
        end_price=17000.0 + dp,
        start_time=_ts(t_idx),
        end_time=_ts(t_idx),
        n_bars=1,
    )
    classifier = BVCClassifier()
    # Warm up sigma so dp maps to a meaningful z
    for _ in range(100):
        classifier.classify(VolumeBucket(
            volume=volume, start_price=17000, end_price=17000 + 1.0,
            start_time=_ts(0), end_time=_ts(0), n_bars=1,
        ))
    return classifier.classify(bucket)


# ---------------------------------------------------------------------------
# Toxicity classification
# ---------------------------------------------------------------------------

class TestClassifyToxicity:
    def test_calm(self):
        assert classify_toxicity(0.20) == "calm"
        assert classify_toxicity(0.34) == "calm"
        assert classify_toxicity(0.35) == "calm"  # boundary: <= 0.35

    def test_normal(self):
        assert classify_toxicity(0.40) == "normal"
        assert classify_toxicity(0.45) == "normal"

    def test_elevated(self):
        assert classify_toxicity(0.50) == "elevated"
        assert classify_toxicity(0.55) == "elevated"

    def test_high(self):
        assert classify_toxicity(0.60) == "high"
        assert classify_toxicity(0.70) == "high"

    def test_extreme(self):
        assert classify_toxicity(0.71) == "extreme"
        assert classify_toxicity(0.90) == "extreme"

    def test_boundaries_match_skill(self):
        assert CALM_MAX == 0.35
        assert NORMAL_MAX == 0.45
        assert ELEVATED_MAX == 0.55
        assert HIGH_MAX == 0.70

    def test_is_extreme(self):
        assert is_extreme(0.75) is True
        assert is_extreme(0.70) is False

    def test_is_high_or_worse(self):
        assert is_high_or_worse(0.60) is True
        assert is_high_or_worse(0.80) is True
        assert is_high_or_worse(0.45) is False


# ---------------------------------------------------------------------------
# Calculator mechanics
# ---------------------------------------------------------------------------

class TestCalculatorMechanics:
    def test_not_ready_initially(self):
        calc = VPINCalculator(num_buckets=5)
        assert calc.ready is False

    def test_ready_after_num_buckets(self):
        calc = VPINCalculator(num_buckets=5)
        for i in range(5):
            calc.add(_classified(dp=1.0, t_idx=i))
        assert calc.ready is True

    def test_first_readings_return_none(self):
        calc = VPINCalculator(num_buckets=5)
        for i in range(4):
            assert calc.add(_classified(dp=1.0, t_idx=i)) is None

    def test_fifth_reading_returns_value(self):
        calc = VPINCalculator(num_buckets=5)
        result = None
        for i in range(5):
            result = calc.add(_classified(dp=1.0, t_idx=i))
        assert result is not None
        assert isinstance(result, VPINReading)

    def test_vpin_in_valid_range(self):
        calc = VPINCalculator(num_buckets=10)
        for i in range(10):
            calc.add(_classified(dp=2.0, t_idx=i))
        reading = calc.latest
        assert 0.0 <= reading.vpin <= 1.0

    def test_balanced_market_low_vpin(self):
        """
        Alternating +/- price changes of the same magnitude should
        produce LOW VPIN (balanced buy/sell per bucket).
        """
        calc = VPINCalculator(num_buckets=10)
        for i in range(10):
            # Alternate: near-zero dp -> balanced bucket -> imbalance near 0
            calc.add(_classified(dp=0.0, t_idx=i))
        # All balanced -> VPIN should be very low
        assert calc.latest.vpin < 0.1

    def test_one_sided_market_high_vpin(self):
        """Strong one-directional moves produce HIGH VPIN."""
        calc = VPINCalculator(num_buckets=10)
        # Build each classified bucket with a large positive z
        classifier = BVCClassifier()
        for i in range(50):
            classifier.classify(VolumeBucket(
                volume=10000, start_price=17000, end_price=17000 + 0.1,
                start_time=_ts(0), end_time=_ts(0), n_bars=1,
            ))
        # Now feed 10 huge-positive buckets (z >> 0 -> almost all buy)
        for i in range(10):
            b = VolumeBucket(
                volume=10000,
                start_price=17000,
                end_price=17000 + 20.0,   # huge positive move
                start_time=_ts(i),
                end_time=_ts(i),
                n_bars=1,
            )
            calc.add(classifier.classify(b))
        assert calc.latest.vpin > 0.5

    def test_reset_clears_state(self):
        calc = VPINCalculator(num_buckets=5)
        for i in range(5):
            calc.add(_classified(dp=1.0, t_idx=i))
        calc.reset()
        assert calc.ready is False
        assert calc.latest is None


# ---------------------------------------------------------------------------
# VPIN formula correctness
# ---------------------------------------------------------------------------

class TestVPINFormula:
    def test_perfectly_balanced_zero_vpin(self):
        """
        If every bucket has exactly 50/50 buy/sell, imbalance=0 -> VPIN=0.
        """
        calc = VPINCalculator(num_buckets=5)
        # Manually construct buckets with exactly balanced splits
        for i in range(5):
            bucket = VolumeBucket(
                volume=10000, start_price=17000, end_price=17000,
                start_time=_ts(i), end_time=_ts(i), n_bars=1,
            )
            cb = ClassifiedBucket(
                bucket=bucket,
                buy_volume=5000, sell_volume=5000, imbalance=0,
                sigma_used=1.0, z=0.0,
            )
            calc.add(cb)
        assert calc.latest.vpin == pytest.approx(0.0)

    def test_perfectly_one_sided_max_vpin(self):
        """
        If every bucket is 100% buy (imbalance == volume), VPIN = 1.0.
        """
        calc = VPINCalculator(num_buckets=5)
        for i in range(5):
            bucket = VolumeBucket(
                volume=10000, start_price=17000, end_price=17100,
                start_time=_ts(i), end_time=_ts(i), n_bars=1,
            )
            cb = ClassifiedBucket(
                bucket=bucket,
                buy_volume=10000, sell_volume=0, imbalance=10000,
                sigma_used=1.0, z=5.0,
            )
            calc.add(cb)
        assert calc.latest.vpin == pytest.approx(1.0)

    def test_half_one_sided_half_balanced(self):
        """
        5 perfectly one-sided + 5 balanced -> VPIN = 0.5
        (imbalance sums to 50000, divided by 10*10000 = 100000 -> 0.5)
        """
        calc = VPINCalculator(num_buckets=10)
        bucket = VolumeBucket(
            volume=10000, start_price=17000, end_price=17000,
            start_time=_ts(0), end_time=_ts(0), n_bars=1,
        )
        for i in range(5):
            calc.add(ClassifiedBucket(
                bucket=bucket, buy_volume=10000, sell_volume=0,
                imbalance=10000, sigma_used=1.0, z=5.0,
            ))
        for i in range(5):
            calc.add(ClassifiedBucket(
                bucket=bucket, buy_volume=5000, sell_volume=5000,
                imbalance=0, sigma_used=1.0, z=0.0,
            ))
        assert calc.latest.vpin == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# History dataframe
# ---------------------------------------------------------------------------

class TestHistoryDF:
    def test_empty_history(self):
        calc = VPINCalculator()
        df = calc.history_df()
        assert df.empty

    def test_history_after_readings(self):
        calc = VPINCalculator(num_buckets=3)
        for i in range(5):
            calc.add(_classified(dp=1.0, t_idx=i))
        df = calc.history_df()
        # After 5 adds with window=3, we get 3 readings
        assert len(df) == 3
        assert "vpin" in df.columns
        assert "toxicity" in df.columns


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------

class TestProcessSeries:
    def test_process_synthetic_series(self):
        # Build 1000 bars of 500 volume each = 500,000 total.
        # With daily_volume=500,000 and num_buckets=50, bucket_size=10,000.
        # So 50 buckets total. Window=20 -> 31 readings.
        rows = []
        np.random.seed(42)
        for i in range(1000):
            rows.append({
                "open": 17000 + np.random.normal(0, 0.1),
                "high": 17001,
                "low": 16999,
                "close": 17000 + np.random.normal(0, 0.1),
                "volume": 500,
            })
        df = pd.DataFrame(rows, index=[_ts(i) for i in range(1000)])

        calc = VPINCalculator(num_buckets=20)
        result_df = calc.process_series(df, daily_volume=500_000)
        # 50 buckets, window=20 -> 31 readings
        assert len(result_df) >= 20

    def test_empty_series(self):
        calc = VPINCalculator()
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = calc.process_series(df, daily_volume=500_000)
        assert result.empty


# ---------------------------------------------------------------------------
# Trade tagging + impact analysis
# ---------------------------------------------------------------------------

class MockTrade:
    def __init__(self, entry_time, pnl, confluence_score=9):
        self.entry_time = entry_time
        self.pnl = pnl
        self.confluence_score = confluence_score


class TestTradeTagging:
    def test_tag_with_vpin(self):
        vpin_df = pd.DataFrame({
            "vpin": [0.20, 0.45, 0.75],
            "toxicity": ["calm", "normal", "extreme"],
            "bucket_count": [50, 50, 50],
        }, index=[_ts(0), _ts(10), _ts(20)])

        trades = [
            MockTrade(_ts(5), pnl=100),    # between idx 0 and 10 -> vpin=0.20
            MockTrade(_ts(15), pnl=-50),   # between 10 and 20 -> vpin=0.45
            MockTrade(_ts(25), pnl=-200),  # after 20 -> vpin=0.75
        ]
        tagged = tag_trades_with_vpin(trades, vpin_df)
        assert tagged[0]["vpin"] == 0.20
        assert tagged[1]["vpin"] == 0.45
        assert tagged[2]["vpin"] == 0.75
        assert tagged[0]["toxicity"] == "calm"
        assert tagged[2]["toxicity"] == "extreme"

    def test_tag_trade_before_vpin_history(self):
        vpin_df = pd.DataFrame({
            "vpin": [0.45],
            "toxicity": ["normal"],
            "bucket_count": [50],
        }, index=[_ts(10)])

        trades = [MockTrade(_ts(5), pnl=100)]   # before any reading
        tagged = tag_trades_with_vpin(trades, vpin_df)
        assert tagged[0]["vpin"] is None

    def test_empty_vpin_series(self):
        trades = [MockTrade(_ts(5), pnl=100)]
        tagged = tag_trades_with_vpin(trades, pd.DataFrame())
        assert tagged[0]["vpin"] is None


class TestImpactAnalysis:
    def test_report_structure(self):
        tagged = [
            {"entry_time": _ts(0), "pnl": 500, "confluence_score": 9,
             "vpin": 0.20, "toxicity": "calm"},
            {"entry_time": _ts(1), "pnl": -200, "confluence_score": 9,
             "vpin": 0.75, "toxicity": "extreme"},
            {"entry_time": _ts(2), "pnl": 300, "confluence_score": 9,
             "vpin": 0.40, "toxicity": "normal"},
        ]
        report = analyze_vpin_impact(tagged)
        assert report.total_trades == 3
        assert report.trades_with_vpin == 3
        assert "extreme" in report.by_toxicity

    def test_high_vpin_loses_money(self):
        """
        Trades in high VPIN (>0.55) should be counted correctly.
        """
        tagged = [
            {"entry_time": _ts(0), "pnl": -500, "confluence_score": 9,
             "vpin": 0.80, "toxicity": "extreme"},
            {"entry_time": _ts(1), "pnl": -300, "confluence_score": 9,
             "vpin": 0.60, "toxicity": "high"},
            {"entry_time": _ts(2), "pnl": 200, "confluence_score": 9,
             "vpin": 0.30, "toxicity": "calm"},
        ]
        report = analyze_vpin_impact(tagged)
        assert report.high_vpin_trades == 2
        assert report.high_vpin_pnl == -800
        assert report.extreme_vpin_trades == 1
        assert report.extreme_vpin_pnl == -500

    def test_low_vpin_wins(self):
        tagged = [
            {"entry_time": _ts(0), "pnl": 500, "confluence_score": 9,
             "vpin": 0.25, "toxicity": "calm"},
            {"entry_time": _ts(1), "pnl": 300, "confluence_score": 9,
             "vpin": 0.40, "toxicity": "normal"},
        ]
        report = analyze_vpin_impact(tagged)
        assert report.low_vpin_trades == 2
        assert report.low_vpin_pnl == 800
        assert report.low_vpin_win_rate == 1.0

    def test_ignores_none_vpin(self):
        tagged = [
            {"entry_time": _ts(0), "pnl": 100, "confluence_score": 9,
             "vpin": None, "toxicity": None},
        ]
        report = analyze_vpin_impact(tagged)
        assert report.total_trades == 1
        assert report.trades_with_vpin == 0
