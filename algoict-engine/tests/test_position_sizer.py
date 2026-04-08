"""
tests/test_position_sizer.py
=============================
Unit tests for risk/position_sizer.py

Run: cd algoict-engine && python -m pytest tests/test_position_sizer.py -v
"""

import pytest
from risk.position_sizer import calculate_position, PositionResult


class TestCoreCalculation:

    def test_stop_15pts_gives_8_contracts(self):
        """
        stop=15, risk=250, point_value=2.0
        raw = 250 / (15 × 2) = 8.33 → floor = 8
        actual_stop = 250 / (8 × 2) = 15.625
        """
        result = calculate_position(stop_points=15.0)
        assert result.contracts == 8
        assert result.actual_stop_points == pytest.approx(15.625)
        assert result.breathing_room == pytest.approx(0.625)
        assert result.risk_dollars == 250.0

    def test_stop_10pts_gives_12_contracts(self):
        """
        raw = 250 / (10 × 2) = 12.5 → floor = 12
        actual_stop = 250 / (12 × 2) = 10.4167
        """
        result = calculate_position(stop_points=10.0)
        assert result.contracts == 12
        assert result.actual_stop_points == pytest.approx(250 / 24)
        assert result.breathing_room == pytest.approx(250 / 24 - 10)

    def test_stop_25pts_gives_5_contracts(self):
        """raw = 250 / (25 × 2) = 5.0 → floor = 5 (exact)"""
        result = calculate_position(stop_points=25.0)
        assert result.contracts == 5
        assert result.actual_stop_points == pytest.approx(25.0)
        assert result.breathing_room == pytest.approx(0.0)

    def test_stop_very_large_floors_to_1_contract(self):
        """raw = 250 / (200 × 2) = 0.625 → floor = 0 → clamped to 1"""
        result = calculate_position(stop_points=200.0)
        assert result.contracts == 1

    def test_stop_very_small_capped_at_max_contracts(self):
        """raw = 250 / (0.5 × 2) = 250 → clamped to 50"""
        result = calculate_position(stop_points=0.5)
        assert result.contracts == 50

    def test_custom_max_contracts(self):
        """Custom ceiling of 5 contracts."""
        result = calculate_position(stop_points=0.5, max_contracts=5)
        assert result.contracts == 5

    def test_custom_risk_amount(self):
        """risk=500 doubles the contracts vs risk=250."""
        r250 = calculate_position(stop_points=15.0, risk=250)
        r500 = calculate_position(stop_points=15.0, risk=500)
        assert r500.contracts == r250.contracts * 2

    def test_nq_point_value_20(self):
        """NQ is $20/point. stop=2.5pts, risk=250 → raw=5 → 5 contracts."""
        result = calculate_position(stop_points=2.5, point_value=20.0)
        assert result.contracts == 5

    def test_risk_dollars_always_matches_input(self):
        result = calculate_position(stop_points=15.0, risk=300)
        assert result.risk_dollars == 300.0

    def test_breathing_room_always_non_negative(self):
        """breathing_room must be >= 0 (actual_stop >= requested_stop)."""
        for stop in [5, 10, 15, 20, 25, 50, 100]:
            result = calculate_position(stop_points=float(stop))
            assert result.breathing_room >= 0.0

    def test_actual_stop_preserves_dollar_risk(self):
        """contracts × actual_stop × point_value == risk_dollars."""
        result = calculate_position(stop_points=15.0)
        assert (
            result.contracts * result.actual_stop_points * 2.0
            == pytest.approx(result.risk_dollars)
        )

    def test_result_is_position_result_dataclass(self):
        result = calculate_position(stop_points=15.0)
        assert isinstance(result, PositionResult)


class TestValidation:

    def test_zero_stop_raises(self):
        with pytest.raises(ValueError):
            calculate_position(stop_points=0.0)

    def test_negative_stop_raises(self):
        with pytest.raises(ValueError):
            calculate_position(stop_points=-5.0)

    def test_zero_point_value_raises(self):
        with pytest.raises(ValueError):
            calculate_position(stop_points=15.0, point_value=0.0)

    def test_negative_risk_raises(self):
        with pytest.raises(ValueError):
            calculate_position(stop_points=15.0, risk=-100.0)
