"""
tests/test_bulk_classifier.py
==============================
Tests for toxicity/bulk_classifier.py
"""

import math
import pytest
import pandas as pd
from scipy.stats import norm

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from toxicity.volume_buckets import VolumeBucket
from toxicity.bulk_classifier import (
    BVCClassifier,
    ClassifiedBucket,
    buy_fraction_from_z,
    classify_buckets,
    DEFAULT_SIGMA_ALPHA,
    SIGMA_SEED_FLOOR,
)


def _ts(i):
    return pd.Timestamp("2024-01-02 08:30", tz="America/Chicago") + pd.Timedelta(minutes=i)


def _bucket(price_change: float, volume: float = 10000) -> VolumeBucket:
    return VolumeBucket(
        volume=volume,
        start_price=17000.0,
        end_price=17000.0 + price_change,
        start_time=_ts(0),
        end_time=_ts(1),
        n_bars=1,
    )


# ---------------------------------------------------------------------------
# buy_fraction_from_z
# ---------------------------------------------------------------------------

class TestBuyFractionFromZ:
    def test_zero_z_half(self):
        assert buy_fraction_from_z(0.0) == pytest.approx(0.5)

    def test_positive_z_over_half(self):
        assert buy_fraction_from_z(1.0) > 0.5

    def test_negative_z_under_half(self):
        assert buy_fraction_from_z(-1.0) < 0.5

    def test_extreme_positive_z(self):
        # z=5 -> buy fraction ~1.0
        assert buy_fraction_from_z(5.0) == pytest.approx(1.0, abs=1e-4)

    def test_extreme_negative_z(self):
        # z=-5 -> buy fraction ~0.0
        assert buy_fraction_from_z(-5.0) == pytest.approx(0.0, abs=1e-4)

    def test_matches_norm_cdf(self):
        for z in [-2.0, -0.5, 0.3, 1.5, 2.2]:
            assert buy_fraction_from_z(z) == pytest.approx(float(norm.cdf(z)))


# ---------------------------------------------------------------------------
# BVCClassifier — single bucket
# ---------------------------------------------------------------------------

class TestSingleBucket:
    def test_flat_price_balanced(self):
        """Zero price change -> buy ~= sell -> imbalance = 0."""
        c = BVCClassifier()
        bucket = _bucket(price_change=0.0)
        result = c.classify(bucket)
        assert result.buy_volume == pytest.approx(result.sell_volume)
        assert result.imbalance == pytest.approx(0.0)

    def test_strong_up_more_buys(self):
        c = BVCClassifier()
        # Seed sigma at 1.0 first
        c.classify(_bucket(1.0))
        result = c.classify(_bucket(3.0))
        assert result.buy_volume > result.sell_volume

    def test_strong_down_more_sells(self):
        c = BVCClassifier()
        c.classify(_bucket(1.0))
        result = c.classify(_bucket(-3.0))
        assert result.sell_volume > result.buy_volume

    def test_fractions_sum_to_one(self):
        c = BVCClassifier()
        result = c.classify(_bucket(price_change=2.0))
        total = result.buy_volume + result.sell_volume
        assert total == pytest.approx(10000)

    def test_first_bucket_seeds_sigma(self):
        c = BVCClassifier()
        assert c.sigma is None
        c.classify(_bucket(price_change=5.0))
        assert c.sigma is not None
        assert c.sigma >= SIGMA_SEED_FLOOR

    def test_zero_first_bucket_uses_seed_floor(self):
        c = BVCClassifier()
        c.classify(_bucket(price_change=0.0))
        assert c.sigma == SIGMA_SEED_FLOOR


# ---------------------------------------------------------------------------
# Sigma EMA update
# ---------------------------------------------------------------------------

class TestSigmaEMA:
    def test_sigma_converges_to_constant_input(self):
        c = BVCClassifier()
        for _ in range(200):
            c.classify(_bucket(price_change=2.0))
        # Sigma should converge to ~2.0
        assert c.sigma == pytest.approx(2.0, abs=0.1)

    def test_sigma_responds_to_regime_change(self):
        c = BVCClassifier(sigma_alpha=0.1)
        # Calm period
        for _ in range(100):
            c.classify(_bucket(price_change=0.5))
        sigma_calm = c.sigma

        # Storm period
        for _ in range(100):
            c.classify(_bucket(price_change=5.0))
        sigma_storm = c.sigma

        assert sigma_storm > sigma_calm * 3

    def test_custom_alpha(self):
        c = BVCClassifier(sigma_alpha=0.5)
        assert c.sigma_alpha == 0.5

    def test_invalid_alpha(self):
        with pytest.raises(ValueError):
            BVCClassifier(sigma_alpha=0.0)
        with pytest.raises(ValueError):
            BVCClassifier(sigma_alpha=1.5)

    def test_sigma_never_zero(self):
        """Even with all-zero price changes, sigma stays >= SIGMA_SEED_FLOOR."""
        c = BVCClassifier()
        for _ in range(50):
            c.classify(_bucket(price_change=0.0))
        assert c.sigma >= SIGMA_SEED_FLOOR


# ---------------------------------------------------------------------------
# BVC formula correctness
# ---------------------------------------------------------------------------

class TestBVCFormula:
    def test_known_answer_z_equals_one(self):
        """
        Seed sigma to exactly 1.0, then classify a bucket with dp=1.0.
        buy_fraction should equal norm.cdf(1.0) ≈ 0.8413.
        """
        c = BVCClassifier(sigma_alpha=1.0)   # alpha=1 -> sigma = |dp|
        c.classify(_bucket(price_change=1.0))   # sigma now = 1.0
        # Next bucket with dp=1.0 -> sigma updates but still close to 1.0
        # Use a different approach: manual sigma injection via repeat
        c2 = BVCClassifier()
        for _ in range(500):
            c2.classify(_bucket(price_change=1.0))
        # Sigma should be ~1.0
        result = c2.classify(_bucket(price_change=1.0))
        expected_buy_fraction = float(norm.cdf(1.0))
        assert result.buy_fraction == pytest.approx(expected_buy_fraction, abs=0.01)

    def test_imbalance_is_abs_difference(self):
        c = BVCClassifier()
        result = c.classify(_bucket(price_change=3.0))
        assert result.imbalance == pytest.approx(
            abs(result.buy_volume - result.sell_volume)
        )

    def test_buy_fraction_property(self):
        c = BVCClassifier()
        result = c.classify(_bucket(price_change=0.0, volume=5000))
        assert result.buy_fraction == pytest.approx(0.5, abs=0.01)

    def test_classify_all(self):
        c = BVCClassifier()
        buckets = [_bucket(price_change=float(i)) for i in range(-5, 6)]
        results = c.classify_all(buckets)
        assert len(results) == len(buckets)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_sigma(self):
        c = BVCClassifier()
        c.classify(_bucket(price_change=5.0))
        assert c.sigma is not None
        c.reset()
        assert c.sigma is None

    def test_convenience_function(self):
        buckets = [_bucket(1.0), _bucket(-1.0), _bucket(2.0)]
        results = classify_buckets(buckets)
        assert len(results) == 3
