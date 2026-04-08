"""
tests/test_regime_detector.py
==============================
Tests for gamma/regime_detector.py
"""

import numpy as np
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gamma.regime_detector import (
    RegimeDetector,
    RegimeResult,
    classify_regime,
    is_positive_regime,
    is_negative_regime,
    is_near_flip,
    DEFAULT_NEAR_FLIP_POINTS,
)
from gamma.gex_calculator import GEXCalculator
from gamma.options_data import generate_synthetic_chain


# ---------------------------------------------------------------------------
# detect_from_values — raw input path
# ---------------------------------------------------------------------------

class TestDetectFromValues:
    def test_positive_regime_when_spot_above_flip(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=17050.0, gamma_flip=17000.0, total_gex=1000.0)
        assert r.regime == "positive"

    def test_negative_regime_when_spot_below_flip(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=16950.0, gamma_flip=17000.0)
        assert r.regime == "negative"

    def test_neutral_regime_when_spot_equals_flip(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=17000.0, gamma_flip=17000.0)
        assert r.regime == "neutral"

    def test_distance_always_positive(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=16900.0, gamma_flip=17000.0)
        assert r.distance_to_flip == 100.0

    def test_distance_computed(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=17050.0, gamma_flip=17000.0)
        assert r.distance_to_flip == 50.0


# ---------------------------------------------------------------------------
# Near-flip classification
# ---------------------------------------------------------------------------

class TestNearFlip:
    def test_within_threshold_is_near_flip(self):
        d = RegimeDetector(near_flip_points=15.0)
        r = d.detect_from_values(spot=17010.0, gamma_flip=17000.0)
        assert r.near_flip is True

    def test_exactly_at_threshold_is_near_flip(self):
        d = RegimeDetector(near_flip_points=15.0)
        r = d.detect_from_values(spot=17015.0, gamma_flip=17000.0)
        assert r.near_flip is True

    def test_outside_threshold_not_near_flip(self):
        d = RegimeDetector(near_flip_points=15.0)
        r = d.detect_from_values(spot=17050.0, gamma_flip=17000.0)
        assert r.near_flip is False

    def test_near_flip_recommends_reduce_size(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=17005.0, gamma_flip=17000.0)
        assert r.recommended_strategy == "reduce_size"

    def test_custom_threshold(self):
        d = RegimeDetector(near_flip_points=5.0)
        r1 = d.detect_from_values(spot=17010.0, gamma_flip=17000.0)
        r2 = d.detect_from_values(spot=17004.0, gamma_flip=17000.0)
        assert r1.near_flip is False  # 10 > 5
        assert r2.near_flip is True   # 4 <= 5


# ---------------------------------------------------------------------------
# Strategy recommendation
# ---------------------------------------------------------------------------

class TestStrategyRecommendation:
    def test_positive_recommends_silver_bullet(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=17100.0, gamma_flip=17000.0)  # 100 pts above
        assert r.recommended_strategy == "silver_bullet"

    def test_negative_recommends_ny_am(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=16900.0, gamma_flip=17000.0)
        assert r.recommended_strategy == "ny_am_reversal"

    def test_near_flip_overrides_regime(self):
        """Near flip should recommend reduce_size regardless of spot direction."""
        d = RegimeDetector(near_flip_points=20.0)
        r_pos = d.detect_from_values(spot=17010.0, gamma_flip=17000.0)
        r_neg = d.detect_from_values(spot=16990.0, gamma_flip=17000.0)
        assert r_pos.recommended_strategy == "reduce_size"
        assert r_neg.recommended_strategy == "reduce_size"

    def test_neutral_recommends_both(self):
        # Use negative threshold to effectively disable near-flip classification,
        # so we can test the underlying neutral -> "both" branch.
        d = RegimeDetector(near_flip_points=-1.0)
        r = d.detect_from_values(spot=17000.0, gamma_flip=17000.0)
        assert r.regime == "neutral"
        assert r.recommended_strategy == "both"


# ---------------------------------------------------------------------------
# Description text
# ---------------------------------------------------------------------------

class TestDescription:
    def test_positive_description_mentions_mean_reversion(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=17100.0, gamma_flip=17000.0)
        assert "mean reversion" in r.description.lower() or "range" in r.description.lower()

    def test_negative_description_mentions_momentum(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=16900.0, gamma_flip=17000.0)
        assert "momentum" in r.description.lower() or "wider" in r.description.lower()

    def test_near_flip_description_mentions_reduce(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=17005.0, gamma_flip=17000.0)
        assert "reduce" in r.description.lower() or "transition" in r.description.lower()


# ---------------------------------------------------------------------------
# Full pipeline (options chain -> GEX -> regime)
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_detect_from_gamma_regime(self):
        chain = generate_synthetic_chain(spot=17000.0)
        gex = GEXCalculator().calculate_gex(chain)
        result = RegimeDetector().detect(gex)
        assert isinstance(result, RegimeResult)

    def test_preserves_spot(self):
        chain = generate_synthetic_chain(spot=17500.0)
        gex = GEXCalculator().calculate_gex(chain)
        result = RegimeDetector().detect(gex)
        assert result.spot == 17500.0

    def test_preserves_gamma_flip(self):
        chain = generate_synthetic_chain(spot=17000.0)
        gex = GEXCalculator().calculate_gex(chain)
        result = RegimeDetector().detect(gex)
        assert result.gamma_flip == gex.gamma_flip

    def test_preserves_strength(self):
        chain = generate_synthetic_chain(spot=17000.0)
        gex = GEXCalculator().calculate_gex(chain)
        result = RegimeDetector().detect(gex)
        assert result.strength == gex.strength

    def test_high_spot_positive_regime(self):
        # Compute GEX for a normal chain, then re-evaluate regime with a
        # spot well above the detected flip level.
        chain = generate_synthetic_chain(spot=17000.0)
        gex = GEXCalculator().calculate_gex(chain)
        # Manually detect using a spot 500 points above the flip
        result = RegimeDetector().detect_from_values(
            spot=gex.gamma_flip + 500.0,
            gamma_flip=gex.gamma_flip,
            total_gex=gex.total_gex,
            strength=gex.strength,
        )
        assert result.regime == "positive"

    def test_low_spot_negative_regime(self):
        chain = generate_synthetic_chain(spot=17000.0)
        gex = GEXCalculator().calculate_gex(chain)
        result = RegimeDetector().detect_from_values(
            spot=gex.gamma_flip - 500.0,
            gamma_flip=gex.gamma_flip,
            total_gex=gex.total_gex,
            strength=gex.strength,
        )
        assert result.regime == "negative"


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def test_is_positive_regime(self):
        assert is_positive_regime(17100, 17000) is True
        assert is_positive_regime(16900, 17000) is False

    def test_is_negative_regime(self):
        assert is_negative_regime(16900, 17000) is True
        assert is_negative_regime(17100, 17000) is False

    def test_is_near_flip(self):
        assert is_near_flip(17010, 17000, threshold=15.0) is True
        assert is_near_flip(17100, 17000, threshold=15.0) is False

    def test_is_near_flip_default_threshold(self):
        assert is_near_flip(17014, 17000) is True   # 14 <= 15
        assert is_near_flip(17016, 17000) is False  # 16 > 15

    def test_classify_regime_shortcut(self):
        chain = generate_synthetic_chain(spot=17100.0)
        gex = GEXCalculator().calculate_gex(chain)
        result = classify_regime(gex)
        assert isinstance(result, RegimeResult)


# ---------------------------------------------------------------------------
# Repr / string representation
# ---------------------------------------------------------------------------

class TestRepresentation:
    def test_repr_includes_regime(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=17100.0, gamma_flip=17000.0)
        assert "positive" in repr(r)

    def test_repr_includes_spot_and_flip(self):
        d = RegimeDetector()
        r = d.detect_from_values(spot=17100.0, gamma_flip=17000.0)
        assert "17100" in repr(r)
        assert "17000" in repr(r)

    def test_near_flip_indicator_in_repr(self):
        d = RegimeDetector(near_flip_points=20.0)
        r = d.detect_from_values(spot=17010.0, gamma_flip=17000.0)
        assert "NEAR FLIP" in repr(r)
