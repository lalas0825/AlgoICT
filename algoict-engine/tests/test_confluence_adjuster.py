"""
tests/test_confluence_adjuster.py
===================================
Tests for sentiment/confluence_adjuster.py
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentiment.confluence_adjuster import (
    get_adjustments,
    get_adjustments_obj,
    describe_risk,
    is_trading_restricted,
    Adjustments,
    RISK_LEVELS,
)


# ---------------------------------------------------------------------------
# get_adjustments → dict values
# ---------------------------------------------------------------------------

class TestGetAdjustments:
    def test_extreme_min_confluence(self):
        adj = get_adjustments("extreme")
        assert adj["min_confluence"] == 10

    def test_extreme_position_multiplier(self):
        adj = get_adjustments("extreme")
        assert adj["position_multiplier"] == 0.5

    def test_high_min_confluence(self):
        adj = get_adjustments("high")
        assert adj["min_confluence"] == 9

    def test_high_position_multiplier(self):
        adj = get_adjustments("high")
        assert adj["position_multiplier"] == 0.75

    def test_medium_min_confluence(self):
        adj = get_adjustments("medium")
        assert adj["min_confluence"] == 8

    def test_medium_position_multiplier(self):
        adj = get_adjustments("medium")
        assert adj["position_multiplier"] == 0.90

    def test_low_min_confluence(self):
        adj = get_adjustments("low")
        assert adj["min_confluence"] == 7

    def test_low_position_multiplier(self):
        adj = get_adjustments("low")
        assert adj["position_multiplier"] == 1.0

    def test_none_min_confluence(self):
        adj = get_adjustments("none")
        assert adj["min_confluence"] == 7

    def test_none_position_multiplier(self):
        adj = get_adjustments("none")
        assert adj["position_multiplier"] == 1.0

    def test_returns_dict(self):
        adj = get_adjustments("high")
        assert isinstance(adj, dict)

    def test_dict_has_required_keys(self):
        adj = get_adjustments("high")
        assert "min_confluence" in adj
        assert "position_multiplier" in adj
        assert "risk_level" in adj

    def test_risk_level_key_matches(self):
        for level in RISK_LEVELS:
            adj = get_adjustments(level)
            assert adj["risk_level"] == level


# ---------------------------------------------------------------------------
# Risk ordering: extreme > high > medium > low/none
# ---------------------------------------------------------------------------

class TestRiskOrdering:
    def test_extreme_has_highest_confluence(self):
        assert get_adjustments("extreme")["min_confluence"] > get_adjustments("high")["min_confluence"]

    def test_high_above_medium_confluence(self):
        assert get_adjustments("high")["min_confluence"] > get_adjustments("medium")["min_confluence"]

    def test_medium_above_low_confluence(self):
        assert get_adjustments("medium")["min_confluence"] > get_adjustments("low")["min_confluence"]

    def test_low_equals_none_confluence(self):
        assert get_adjustments("low")["min_confluence"] == get_adjustments("none")["min_confluence"]

    def test_extreme_has_lowest_position_mult(self):
        assert get_adjustments("extreme")["position_multiplier"] < get_adjustments("high")["position_multiplier"]

    def test_high_below_medium_position_mult(self):
        assert get_adjustments("high")["position_multiplier"] < get_adjustments("medium")["position_multiplier"]

    def test_medium_below_none_position_mult(self):
        assert get_adjustments("medium")["position_multiplier"] < get_adjustments("none")["position_multiplier"]

    def test_none_full_position(self):
        assert get_adjustments("none")["position_multiplier"] == 1.0

    def test_extreme_position_is_half(self):
        assert get_adjustments("extreme")["position_multiplier"] == 0.5


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------

class TestInvalidInput:
    def test_invalid_risk_raises(self):
        with pytest.raises(ValueError):
            get_adjustments("unknown")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            get_adjustments("")

    def test_number_raises(self):
        with pytest.raises(ValueError):
            get_adjustments("5")

    def test_uppercase_handled(self):
        # Should be case-insensitive
        adj = get_adjustments("HIGH")
        assert adj["min_confluence"] == 9

    def test_mixed_case_handled(self):
        adj = get_adjustments("Extreme")
        assert adj["min_confluence"] == 10

    def test_whitespace_stripped(self):
        adj = get_adjustments("  high  ")
        assert adj["min_confluence"] == 9


# ---------------------------------------------------------------------------
# get_adjustments_obj → Adjustments dataclass
# ---------------------------------------------------------------------------

class TestGetAdjustmentsObj:
    def test_returns_adjustments_type(self):
        adj = get_adjustments_obj("high")
        assert isinstance(adj, Adjustments)

    def test_frozen_immutable(self):
        adj = get_adjustments_obj("high")
        with pytest.raises((AttributeError, TypeError)):
            adj.min_confluence = 99  # type: ignore

    def test_as_dict_matches_get_adjustments(self):
        obj = get_adjustments_obj("medium")
        d = get_adjustments("medium")
        assert obj.min_confluence == d["min_confluence"]
        assert obj.position_multiplier == d["position_multiplier"]

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            get_adjustments_obj("invalid")


# ---------------------------------------------------------------------------
# describe_risk
# ---------------------------------------------------------------------------

class TestDescribeRisk:
    def test_extreme_mentions_fomc(self):
        desc = describe_risk("extreme")
        assert "FOMC" in desc or "half" in desc.lower() or "size" in desc.lower()

    def test_high_mentions_cpi_or_nfp(self):
        desc = describe_risk("high")
        assert "CPI" in desc or "NFP" in desc or "reduc" in desc.lower()

    def test_none_mentions_standard(self):
        desc = describe_risk("none")
        assert "standard" in desc.lower() or "ICT" in desc

    def test_all_levels_return_non_empty(self):
        for level in RISK_LEVELS:
            assert len(describe_risk(level)) > 0


# ---------------------------------------------------------------------------
# is_trading_restricted
# ---------------------------------------------------------------------------

class TestIsTradingRestricted:
    def test_extreme_restricted(self):
        assert is_trading_restricted("extreme") is True

    def test_high_restricted(self):
        assert is_trading_restricted("high") is True

    def test_medium_restricted(self):
        assert is_trading_restricted("medium") is True

    def test_low_not_restricted(self):
        assert is_trading_restricted("low") is False

    def test_none_not_restricted(self):
        assert is_trading_restricted("none") is False


# ---------------------------------------------------------------------------
# Integration: calendar -> adjuster
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_fomc_day_gets_extreme_adjustment(self):
        import datetime
        from sentiment.economic_calendar import get_event_risk
        # FOMC 2024-01-31
        risk = get_event_risk(datetime.date(2024, 1, 31))
        adj = get_adjustments(risk)
        assert adj["min_confluence"] == 10
        assert adj["position_multiplier"] == 0.5

    def test_cpi_day_gets_high_adjustment(self):
        import datetime
        from sentiment.economic_calendar import get_event_risk
        # CPI 2024-01-11
        risk = get_event_risk(datetime.date(2024, 1, 11))
        adj = get_adjustments(risk)
        assert adj["min_confluence"] == 9
        assert adj["position_multiplier"] == 0.75

    def test_quiet_day_gets_standard_adjustment(self):
        import datetime
        from sentiment.economic_calendar import get_event_risk
        risk = get_event_risk(datetime.date(2024, 1, 3))
        adj = get_adjustments(risk)
        assert adj["min_confluence"] == 7
        assert adj["position_multiplier"] == 1.0

    def test_nfp_day_gets_high_adjustment(self):
        import datetime
        from sentiment.economic_calendar import get_event_risk
        # NFP 2024-01-05
        risk = get_event_risk(datetime.date(2024, 1, 5))
        adj = get_adjustments(risk)
        assert adj["min_confluence"] == 9
