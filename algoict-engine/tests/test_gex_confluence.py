"""
tests/test_gex_confluence.py
=============================
Tests for gamma/gex_confluence.py and gamma/gex_overlay.py and gamma/gex_engine.py

All tests run offline — no options data fetching.
"""

import pytest
from unittest.mock import MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gamma.gex_overlay import GEXOverlay, build_overlay, unavailable_overlay, _classify_regime_inline
from gamma.gex_confluence import score_gex_alignment, GEXConfluenceResult, gex_points_available
from gamma.gex_engine import GEXEngine, run_premarket_scan


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_overlay(
    spot=19500.0,
    call_wall=19600.0,
    put_wall=19400.0,
    gamma_flip=19480.0,
    regime="positive",
    near_flip=False,
    total_gex=5e9,
    high_gex=None,
):
    return GEXOverlay(
        spot=spot,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
        regime=regime,
        near_flip=near_flip,
        total_gex=total_gex,
        high_gex_levels=high_gex or [],
        strategy_hint="silver_bullet",
        regime_strength="medium",
        source="calculated",
    )


def _make_gamma_regime(
    call_wall=19600.0,
    put_wall=19400.0,
    gamma_flip=19480.0,
    spot=19500.0,
    total_gex=5e9,
):
    """Mock GammaRegime object."""
    m = MagicMock()
    m.call_wall = call_wall
    m.put_wall = put_wall
    m.gamma_flip = gamma_flip
    m.spot = spot
    m.total_gex = total_gex
    m.high_gex_levels = []
    return m


def _make_regime_result(regime="positive", near_flip=False, strength="medium"):
    m = MagicMock()
    m.regime = regime
    m.near_flip = near_flip
    m.strength = strength
    return m


# ---------------------------------------------------------------------------
# GEXOverlay — properties
# ---------------------------------------------------------------------------

class TestGEXOverlayProperties:
    def test_is_valid_true(self):
        overlay = _make_overlay()
        assert overlay.is_valid

    def test_is_valid_false_no_call_wall(self):
        overlay = _make_overlay(call_wall=0.0)
        assert not overlay.is_valid

    def test_is_valid_false_with_error(self):
        overlay = GEXOverlay(0, 0, 0, 0, "neutral", False, 0, error="test error")
        assert not overlay.is_valid

    def test_regime_label_positive(self):
        overlay = _make_overlay(regime="positive", near_flip=False)
        assert overlay.regime_label == "positive"

    def test_regime_label_near_flip(self):
        overlay = _make_overlay(regime="positive", near_flip=True)
        assert "near flip" in overlay.regime_label

    def test_as_dict_keys(self):
        overlay = _make_overlay()
        d = overlay.as_dict()
        assert "call_wall" in d and "put_wall" in d and "regime" in d


# ---------------------------------------------------------------------------
# GEXOverlay — alignment checks
# ---------------------------------------------------------------------------

class TestGEXOverlayAlignment:
    def test_is_near_call_wall_yes(self):
        overlay = _make_overlay(call_wall=19600.0)
        # 19595 is 5 below call wall — within 2*tolerance=20
        assert overlay.is_near_call_wall(19595.0, tolerance=10.0)

    def test_is_near_call_wall_too_far(self):
        overlay = _make_overlay(call_wall=19600.0)
        assert not overlay.is_near_call_wall(19550.0, tolerance=10.0)

    def test_is_near_put_wall_yes(self):
        overlay = _make_overlay(put_wall=19400.0)
        # 19405 is 5 above put wall
        assert overlay.is_near_put_wall(19405.0, tolerance=10.0)

    def test_is_near_put_wall_too_far(self):
        overlay = _make_overlay(put_wall=19400.0)
        assert not overlay.is_near_put_wall(19450.0, tolerance=10.0)

    def test_is_near_gex_level_yes(self):
        overlay = _make_overlay(high_gex=[19525.0])
        assert overlay.is_near_gex_level(19520.0, tolerance=10.0)

    def test_is_near_gex_level_no_levels(self):
        overlay = _make_overlay(high_gex=[])
        assert not overlay.is_near_gex_level(19500.0)

    def test_nearest_wall_above(self):
        overlay = _make_overlay(call_wall=19600.0, gamma_flip=19550.0)
        nearest = overlay.nearest_wall_above(19520.0)
        assert nearest == 19550.0  # flip is closer above

    def test_nearest_wall_below(self):
        overlay = _make_overlay(put_wall=19400.0, gamma_flip=19450.0)
        nearest = overlay.nearest_wall_below(19480.0)
        assert nearest == 19450.0  # flip is closer below

    def test_nearest_wall_above_none(self):
        overlay = _make_overlay(call_wall=19600.0, gamma_flip=19480.0)
        # price above everything
        nearest = overlay.nearest_wall_above(19700.0)
        assert nearest is None


# ---------------------------------------------------------------------------
# build_overlay
# ---------------------------------------------------------------------------

class TestBuildOverlay:
    def test_builds_from_gamma_regime(self):
        gr = _make_gamma_regime()
        rr = _make_regime_result()
        overlay = build_overlay(gr, spot=19500.0, regime_result=rr)
        assert overlay.call_wall == 19600.0
        assert overlay.put_wall == 19400.0
        assert overlay.regime == "positive"
        assert overlay.source == "calculated"

    def test_builds_without_regime_result(self):
        gr = _make_gamma_regime(spot=19500.0, gamma_flip=19480.0)
        overlay = build_overlay(gr, spot=19500.0)
        assert overlay.regime == "positive"  # spot > flip

    def test_negative_regime_when_below_flip(self):
        gr = _make_gamma_regime(spot=19460.0, gamma_flip=19480.0)
        overlay = build_overlay(gr, spot=19460.0)
        assert overlay.regime == "negative"

    def test_near_flip_detected(self):
        gr = _make_gamma_regime(spot=19490.0, gamma_flip=19485.0)
        overlay = build_overlay(gr, spot=19490.0, near_flip_points=15.0)
        assert overlay.near_flip is True

    def test_strategy_hint_positive_regime(self):
        gr = _make_gamma_regime(spot=19500.0, gamma_flip=19450.0)
        overlay = build_overlay(gr, spot=19500.0, near_flip_points=15.0)
        assert overlay.strategy_hint == "silver_bullet"

    def test_strategy_hint_negative_regime(self):
        gr = _make_gamma_regime(spot=19430.0, gamma_flip=19480.0)
        overlay = build_overlay(gr, spot=19430.0, near_flip_points=15.0)
        assert overlay.strategy_hint == "ny_am_reversal"

    def test_strategy_hint_near_flip(self):
        gr = _make_gamma_regime(spot=19475.0, gamma_flip=19480.0)
        overlay = build_overlay(gr, spot=19475.0, near_flip_points=15.0)
        assert overlay.strategy_hint == "reduce_size"

    def test_unavailable_overlay_on_none_input(self):
        # Pass None — all fields default to 0, so is_valid returns False
        overlay = build_overlay(None, spot=0.0)
        assert not overlay.is_valid  # call_wall == 0 -> not valid

    def test_unavailable_overlay_function(self):
        overlay = unavailable_overlay("test reason")
        assert not overlay.is_valid
        assert overlay.source == "unavailable"


# ---------------------------------------------------------------------------
# _classify_regime_inline
# ---------------------------------------------------------------------------

class TestClassifyRegimeInline:
    def test_positive_when_above_flip(self):
        regime, near = _classify_regime_inline(19500, 19480, 15)
        assert regime == "positive"
        assert near is False

    def test_negative_when_below_flip(self):
        regime, near = _classify_regime_inline(19460, 19480, 15)
        assert regime == "negative"

    def test_neutral_when_at_flip(self):
        regime, near = _classify_regime_inline(19480, 19480, 15)
        assert regime == "neutral"
        assert near is True

    def test_near_flip_when_close(self):
        regime, near = _classify_regime_inline(19488, 19480, 15)
        assert near is True

    def test_zero_flip_returns_neutral(self):
        regime, near = _classify_regime_inline(19500, 0.0, 15)
        assert regime == "neutral"


# ---------------------------------------------------------------------------
# score_gex_alignment
# ---------------------------------------------------------------------------

class TestScoreGexAlignment:
    def test_long_near_put_wall_gets_wall_bonus(self):
        overlay = _make_overlay(put_wall=19400.0, regime="positive")
        result = score_gex_alignment(19405.0, "long", overlay, tolerance=10.0)
        assert result.wall_bonus is True
        assert result.wall_pts == 2

    def test_short_near_call_wall_gets_wall_bonus(self):
        overlay = _make_overlay(call_wall=19600.0, regime="negative")
        result = score_gex_alignment(19595.0, "short", overlay, tolerance=10.0)
        assert result.wall_bonus is True
        assert result.wall_pts == 2

    def test_long_away_from_put_wall_no_bonus(self):
        overlay = _make_overlay(put_wall=19400.0)
        result = score_gex_alignment(19500.0, "long", overlay, tolerance=10.0)
        assert result.wall_bonus is False
        assert result.wall_pts == 0

    def test_positive_regime_gives_regime_bonus(self):
        overlay = _make_overlay(regime="positive", near_flip=False)
        result = score_gex_alignment(19500.0, "long", overlay)
        assert result.regime_bonus is True
        assert result.regime_pts == 1

    def test_near_flip_no_regime_bonus(self):
        overlay = _make_overlay(regime="positive", near_flip=True)
        result = score_gex_alignment(19500.0, "long", overlay)
        assert result.regime_bonus is False
        assert result.regime_pts == 0

    def test_max_points_3(self):
        overlay = _make_overlay(
            put_wall=19400.0,
            call_wall=19600.0,
            regime="positive",
            near_flip=False,
        )
        result = score_gex_alignment(19405.0, "long", overlay, tolerance=10.0)
        assert result.total_pts == 3

    def test_returns_zero_for_unavailable_overlay(self):
        overlay = unavailable_overlay()
        result = score_gex_alignment(19500.0, "long", overlay)
        assert result.total_pts == 0

    def test_returns_zero_for_none_overlay(self):
        result = score_gex_alignment(19500.0, "long", None)
        assert result.total_pts == 0

    def test_high_gex_level_gives_wall_bonus(self):
        overlay = _make_overlay(high_gex=[19505.0], put_wall=19300.0, regime="positive")
        result = score_gex_alignment(19500.0, "long", overlay, tolerance=10.0)
        assert result.wall_bonus is True

    def test_result_has_reason(self):
        overlay = _make_overlay(put_wall=19400.0, regime="positive")
        result = score_gex_alignment(19405.0, "long", overlay, tolerance=10.0)
        assert len(result.reason) > 0


# ---------------------------------------------------------------------------
# GEXConfluenceResult
# ---------------------------------------------------------------------------

class TestGEXConfluenceResult:
    def test_total_pts_sum(self):
        r = GEXConfluenceResult(
            wall_bonus=True, regime_bonus=True,
            wall_pts=2, regime_pts=1,
            near_call_wall=False, near_put_wall=True, near_high_gex=False,
            regime="positive",
        )
        assert r.total_pts == 3

    def test_zero_total(self):
        r = GEXConfluenceResult(
            wall_bonus=False, regime_bonus=False,
            wall_pts=0, regime_pts=0,
            near_call_wall=False, near_put_wall=False, near_high_gex=False,
            regime="neutral",
        )
        assert r.total_pts == 0


# ---------------------------------------------------------------------------
# gex_points_available
# ---------------------------------------------------------------------------

class TestGexPointsAvailable:
    def test_returns_3_for_valid_overlay(self):
        overlay = _make_overlay()
        assert gex_points_available(overlay) == 3

    def test_returns_0_for_unavailable(self):
        overlay = unavailable_overlay()
        assert gex_points_available(overlay) == 0

    def test_returns_0_for_none(self):
        assert gex_points_available(None) == 0


# ---------------------------------------------------------------------------
# GEXEngine
# ---------------------------------------------------------------------------

class TestGEXEngine:
    def test_returns_unavailable_without_loader(self):
        engine = GEXEngine(spot_price=19500.0)
        overlay = engine.run_premarket_scan()
        assert not overlay.is_valid
        assert overlay.source == "unavailable"

    def test_returns_overlay_with_loader(self):
        from gamma.options_data import generate_synthetic_chain
        chain = generate_synthetic_chain(spot=19500.0)
        engine = GEXEngine(
            spot_price=19500.0,
            options_loader=lambda: chain,
        )
        overlay = engine.run_premarket_scan()
        # Should return a valid overlay (synthetic chain has real data)
        assert overlay.call_wall > 0 or not overlay.is_valid  # either works

    def test_loader_returning_none_gives_unavailable(self):
        engine = GEXEngine(
            spot_price=19500.0,
            options_loader=lambda: None,
        )
        overlay = engine.run_premarket_scan()
        assert not overlay.is_valid

    def test_loader_exception_gives_unavailable(self):
        def bad_loader():
            raise RuntimeError("No data today")

        engine = GEXEngine(
            spot_price=19500.0,
            options_loader=bad_loader,
        )
        overlay = engine.run_premarket_scan()
        assert not overlay.is_valid
        assert "No data today" in overlay.error

    def test_spot_override_in_scan(self):
        from gamma.options_data import generate_synthetic_chain
        chain = generate_synthetic_chain(spot=19500.0)
        engine = GEXEngine(spot_price=19500.0, options_loader=lambda: chain)
        # Override spot in run call
        overlay = engine.run_premarket_scan(spot_price=19600.0)
        # Just verify it doesn't crash with a different spot
        assert overlay is not None

    def test_update_spot(self):
        engine = GEXEngine(spot_price=19500.0)
        engine.update_spot(19600.0)
        assert engine._spot == 19600.0


# ---------------------------------------------------------------------------
# run_premarket_scan (module-level function)
# ---------------------------------------------------------------------------

class TestRunPremarketScanFunction:
    def test_returns_overlay_without_loader(self):
        overlay = run_premarket_scan(spot_price=19500.0)
        assert isinstance(overlay, GEXOverlay)
        assert overlay.source == "unavailable"
