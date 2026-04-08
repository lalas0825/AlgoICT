"""
tests/test_gex_calculator.py
=============================
Tests for gamma/gex_calculator.py

Includes "known-answer" tests with hand-computed Black-Scholes gamma
values for validation.
"""

import math
import numpy as np
import pytest
from scipy.stats import norm

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gamma.gex_calculator import (
    GEXCalculator,
    GammaRegime,
    GEXLevel,
    black_scholes_gamma,
    calculate_gex_from_chain,
    find_call_wall,
    find_put_wall,
)
from gamma.options_data import generate_synthetic_chain


# ---------------------------------------------------------------------------
# Black-Scholes gamma — known-answer tests
# ---------------------------------------------------------------------------

class TestBlackScholesGamma:
    def test_atm_gamma_positive(self):
        # At-the-money: spot == strike
        g = black_scholes_gamma(
            spot=17000, strike=17000,
            days_to_expiry=30, implied_vol=0.20, risk_free_rate=0.05,
        )
        assert g > 0

    def test_deep_itm_call_low_gamma(self):
        # Deep ITM -> gamma approaches 0
        g_itm = black_scholes_gamma(
            spot=17000, strike=15000,
            days_to_expiry=30, implied_vol=0.20,
        )
        g_atm = black_scholes_gamma(
            spot=17000, strike=17000,
            days_to_expiry=30, implied_vol=0.20,
        )
        assert g_itm < g_atm

    def test_deep_otm_call_low_gamma(self):
        g_otm = black_scholes_gamma(
            spot=17000, strike=19000,
            days_to_expiry=30, implied_vol=0.20,
        )
        g_atm = black_scholes_gamma(
            spot=17000, strike=17000,
            days_to_expiry=30, implied_vol=0.20,
        )
        assert g_otm < g_atm

    def test_gamma_peaks_at_atm(self):
        # Sweep strikes around spot and confirm max gamma is near ATM
        strikes = np.linspace(15000, 19000, 81)
        gammas = np.array([
            black_scholes_gamma(spot=17000, strike=k,
                                days_to_expiry=30, implied_vol=0.20)
            for k in strikes
        ])
        peak_idx = int(np.argmax(gammas))
        # Peak within 200 points of ATM (close enough given 50pt grid)
        assert abs(strikes[peak_idx] - 17000) <= 200

    def test_manual_calculation_atm(self):
        """
        Hand-compute gamma for spot=100, strike=100, T=1/12, iv=0.2, r=0.05.
        d1 = (ln(1) + (0.05 + 0.5*0.04)*(1/12)) / (0.2*sqrt(1/12))
           = (0 + 0.07 * 0.0833) / (0.2 * 0.2887)
           = 0.005833 / 0.05774
           = 0.10104
        gamma = phi(d1) / (S * sigma * sqrt(T))
              = phi(0.10104) / (100 * 0.2 * 0.2887)
              = 0.3968 / 5.7735
              = 0.0687
        """
        g = black_scholes_gamma(
            spot=100, strike=100, days_to_expiry=30.4, implied_vol=0.20, risk_free_rate=0.05,
        )
        # Recompute directly for exact comparison
        T = 30.4 / 365
        d1 = (math.log(100 / 100) + (0.05 + 0.5 * 0.20 ** 2) * T) / (0.20 * math.sqrt(T))
        expected = norm.pdf(d1) / (100 * 0.20 * math.sqrt(T))
        assert abs(g - expected) < 1e-10

    def test_higher_iv_lower_gamma(self):
        """Higher implied vol flattens the distribution -> lower peak gamma at ATM."""
        g_low = black_scholes_gamma(spot=17000, strike=17000, days_to_expiry=30, implied_vol=0.10)
        g_high = black_scholes_gamma(spot=17000, strike=17000, days_to_expiry=30, implied_vol=0.40)
        assert g_low > g_high

    def test_negative_spot_raises(self):
        with pytest.raises(ValueError):
            black_scholes_gamma(spot=-100, strike=100, days_to_expiry=30, implied_vol=0.20)

    def test_negative_strike_raises(self):
        with pytest.raises(ValueError):
            black_scholes_gamma(spot=100, strike=-100, days_to_expiry=30, implied_vol=0.20)

    def test_negative_iv_raises(self):
        with pytest.raises(ValueError):
            black_scholes_gamma(spot=100, strike=100, days_to_expiry=30, implied_vol=-0.20)

    def test_zero_dte_handled(self):
        # days_to_expiry=0 should not crash (floored to 1 day internally)
        g = black_scholes_gamma(spot=17000, strike=17000, days_to_expiry=0, implied_vol=0.20)
        assert g > 0


# ---------------------------------------------------------------------------
# GEX calculator — synthetic chain
# ---------------------------------------------------------------------------

class TestGEXCalculator:
    def test_returns_gamma_regime(self):
        chain = generate_synthetic_chain(spot=17000.0)
        calc = GEXCalculator()
        result = calc.calculate_gex(chain)
        assert isinstance(result, GammaRegime)

    def test_spot_preserved(self):
        chain = generate_synthetic_chain(spot=17500.0)
        calc = GEXCalculator()
        result = calc.calculate_gex(chain)
        assert result.spot == 17500.0

    def test_levels_populated(self):
        chain = generate_synthetic_chain(spot=17000.0, strikes_per_side=10)
        result = GEXCalculator().calculate_gex(chain)
        assert len(result.levels) == len(chain.strikes)

    def test_gex_level_structure(self):
        chain = generate_synthetic_chain(spot=17000.0)
        result = GEXCalculator().calculate_gex(chain)
        lvl = result.levels[0]
        assert isinstance(lvl, GEXLevel)
        assert hasattr(lvl, "call_gex")
        assert hasattr(lvl, "put_gex")
        assert hasattr(lvl, "net_gex")

    def test_call_gex_positive(self):
        """Call GEX should always be positive (dealers long calls)."""
        chain = generate_synthetic_chain(spot=17000.0)
        result = GEXCalculator().calculate_gex(chain)
        for lvl in result.levels:
            assert lvl.call_gex >= 0

    def test_put_gex_negative(self):
        """Put GEX should always be negative (dealers short puts)."""
        chain = generate_synthetic_chain(spot=17000.0)
        result = GEXCalculator().calculate_gex(chain)
        for lvl in result.levels:
            assert lvl.put_gex <= 0

    def test_net_gex_is_sum(self):
        chain = generate_synthetic_chain(spot=17000.0)
        result = GEXCalculator().calculate_gex(chain)
        for lvl in result.levels:
            assert abs(lvl.net_gex - (lvl.call_gex + lvl.put_gex)) < 1e-6


# ---------------------------------------------------------------------------
# Call Wall / Put Wall detection
# ---------------------------------------------------------------------------

class TestCallPutWalls:
    def test_call_wall_matches_specified(self):
        """Synthetic chain with call wall at 17050 should return 17050."""
        chain = generate_synthetic_chain(
            spot=17000.0,
            call_wall_strike=17050.0,
            put_wall_strike=16950.0,
            strike_spacing=25.0,
            strikes_per_side=20,
        )
        result = GEXCalculator().calculate_gex(chain)
        # Peak should be near 17050 (within 25 points due to grid)
        assert abs(result.call_wall - 17050.0) <= 25.0

    def test_put_wall_matches_specified(self):
        chain = generate_synthetic_chain(
            spot=17000.0,
            call_wall_strike=17050.0,
            put_wall_strike=16950.0,
            strike_spacing=25.0,
            strikes_per_side=20,
        )
        result = GEXCalculator().calculate_gex(chain)
        assert abs(result.put_wall - 16950.0) <= 25.0

    def test_call_wall_above_put_wall_when_symmetric(self):
        chain = generate_synthetic_chain(
            spot=17000.0,
            call_wall_strike=17200.0,
            put_wall_strike=16800.0,
        )
        result = GEXCalculator().calculate_gex(chain)
        assert result.call_wall > result.put_wall

    def test_find_call_wall_helper(self):
        strikes = np.array([100, 110, 120, 130])
        call_gex = np.array([1.0, 5.0, 3.0, 2.0])
        assert find_call_wall(strikes, call_gex) == 110.0

    def test_find_put_wall_helper(self):
        strikes = np.array([100, 110, 120, 130])
        put_gex = np.array([-1.0, -5.0, -10.0, -2.0])
        # Most negative = strongest put wall
        assert find_put_wall(strikes, put_gex) == 120.0

    def test_walls_are_different_strikes(self):
        chain = generate_synthetic_chain(
            spot=17000.0,
            call_wall_strike=17200.0,
            put_wall_strike=16800.0,
        )
        result = GEXCalculator().calculate_gex(chain)
        assert result.call_wall != result.put_wall


# ---------------------------------------------------------------------------
# Gamma Flip detection
# ---------------------------------------------------------------------------

class TestGammaFlip:
    def test_flip_between_walls(self):
        """With call wall above spot and put wall below, flip should be between them."""
        chain = generate_synthetic_chain(
            spot=17000.0,
            call_wall_strike=17200.0,
            put_wall_strike=16800.0,
        )
        result = GEXCalculator().calculate_gex(chain)
        assert result.put_wall < result.gamma_flip < result.call_wall + 50

    def test_no_crossing_all_positive(self):
        """If all net_gex is positive, flip falls back to lowest strike."""
        calc = GEXCalculator()
        strikes = np.array([16900.0, 17000.0, 17100.0])
        call_oi = np.array([5000.0, 5000.0, 5000.0])
        put_oi = np.array([10.0, 10.0, 10.0])  # tiny puts
        iv = np.array([0.20, 0.20, 0.20])
        result = calc.calculate_gex_arrays(
            spot=17000.0, strikes=strikes,
            call_oi=call_oi, put_oi=put_oi,
            implied_vol=iv, days_to_expiry=30,
        )
        # net_gex mostly positive -> flip at lowest strike
        assert result.gamma_flip == 16900.0

    def test_no_crossing_all_negative(self):
        calc = GEXCalculator()
        strikes = np.array([16900.0, 17000.0, 17100.0])
        call_oi = np.array([10.0, 10.0, 10.0])
        put_oi = np.array([5000.0, 5000.0, 5000.0])
        iv = np.array([0.20, 0.20, 0.20])
        result = calc.calculate_gex_arrays(
            spot=17000.0, strikes=strikes,
            call_oi=call_oi, put_oi=put_oi,
            implied_vol=iv, days_to_expiry=30,
        )
        assert result.gamma_flip == 17100.0

    def test_flip_linear_interpolation(self):
        """
        Two strikes with net_gex [+10, -10] -> flip at midpoint.
        """
        calc = GEXCalculator()
        # Build arrays such that net_gex at strike 17000 > 0 and at 17100 < 0
        # by using puts that dominate the upper strike.
        strikes = np.array([17000.0, 17100.0])
        call_oi = np.array([5000.0, 100.0])
        put_oi = np.array([100.0, 5000.0])
        iv = np.array([0.20, 0.20])
        result = calc.calculate_gex_arrays(
            spot=17050.0, strikes=strikes,
            call_oi=call_oi, put_oi=put_oi,
            implied_vol=iv, days_to_expiry=30,
        )
        # Flip should be somewhere between 17000 and 17100
        assert 17000 < result.gamma_flip < 17100


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

class TestRegime:
    def test_positive_regime_spot_above_flip(self):
        calc = GEXCalculator()
        strikes = np.array([16900.0, 17000.0, 17100.0])
        call_oi = np.array([5000.0, 5000.0, 100.0])
        put_oi = np.array([100.0, 5000.0, 5000.0])
        iv = np.array([0.20, 0.20, 0.20])
        # Spot well above the flip (which will be somewhere in the middle)
        result = calc.calculate_gex_arrays(
            spot=17200.0, strikes=strikes,
            call_oi=call_oi, put_oi=put_oi,
            implied_vol=iv, days_to_expiry=30,
        )
        assert result.regime in ("positive", "neutral")

    def test_negative_regime_spot_below_flip(self):
        calc = GEXCalculator()
        strikes = np.array([16900.0, 17000.0, 17100.0])
        call_oi = np.array([5000.0, 5000.0, 100.0])
        put_oi = np.array([100.0, 5000.0, 5000.0])
        iv = np.array([0.20, 0.20, 0.20])
        result = calc.calculate_gex_arrays(
            spot=16800.0, strikes=strikes,
            call_oi=call_oi, put_oi=put_oi,
            implied_vol=iv, days_to_expiry=30,
        )
        assert result.regime in ("negative", "neutral")

    def test_strength_categories(self):
        chain = generate_synthetic_chain(spot=17000.0)
        result = GEXCalculator().calculate_gex(chain)
        assert result.strength in ("weak", "moderate", "strong")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_empty_strikes_raises(self):
        calc = GEXCalculator()
        with pytest.raises(ValueError):
            calc.calculate_gex_arrays(
                spot=17000, strikes=np.array([]),
                call_oi=np.array([]), put_oi=np.array([]),
                implied_vol=np.array([]), days_to_expiry=30,
            )

    def test_mismatched_array_lengths_raises(self):
        calc = GEXCalculator()
        with pytest.raises(ValueError):
            calc.calculate_gex_arrays(
                spot=17000,
                strikes=np.array([17000, 17100]),
                call_oi=np.array([100]),  # wrong length
                put_oi=np.array([100, 100]),
                implied_vol=np.array([0.20, 0.20]),
                days_to_expiry=30,
            )


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

class TestConvenience:
    def test_calculate_gex_from_chain(self):
        chain = generate_synthetic_chain(spot=17000.0)
        result = calculate_gex_from_chain(chain)
        assert isinstance(result, GammaRegime)
        assert result.spot == 17000.0
