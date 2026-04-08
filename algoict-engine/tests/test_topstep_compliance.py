"""
tests/test_topstep_compliance.py
==================================
Unit tests for risk/topstep_compliance.py

Run: cd algoict-engine && python -m pytest tests/test_topstep_compliance.py -v
"""

import pytest
from datetime import datetime, time
import pytz

from risk.topstep_compliance import (
    check_compliance,
    ComplianceResult,
    is_within_profit_target,
)


CT = pytz.timezone("US/Central")

# Baseline safe values
SAFE_BALANCE = 50_000.0
SAFE_HIGH    = 50_000.0
SAFE_PNL     = 0.0
SAFE_CONTR   = 0
SAFE_TIME    = CT.localize(datetime(2025, 3, 3, 10, 0))   # 10:00 AM CT


def _dt(hour: int, minute: int = 0) -> datetime:
    return CT.localize(datetime(2025, 3, 3, hour, minute))


class TestCompliantBaseline:

    def test_baseline_is_compliant(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, SAFE_CONTR, SAFE_TIME
        )
        assert result.is_compliant is True
        assert result.violations == []


class TestMLLViolation:

    def test_balance_below_mll_floor_is_violation(self):
        """balance < balance_high - $2,000 → MLL violation."""
        result = check_compliance(
            balance=47_999.0,      # 50k - 2001 = below floor
            balance_high=50_000.0,
            daily_pnl=0.0,
            num_contracts=0,
            current_time_ct=SAFE_TIME,
        )
        assert result.is_compliant is False
        assert "MLL" in result.violations

    def test_balance_exactly_at_mll_floor_is_compliant(self):
        """balance == balance_high - $2,000 → still compliant (strict <)."""
        result = check_compliance(
            balance=48_000.0,
            balance_high=50_000.0,
            daily_pnl=0.0,
            num_contracts=0,
            current_time_ct=SAFE_TIME,
        )
        assert result.is_compliant is True

    def test_mll_warning_within_200_of_floor(self):
        """$100 above MLL floor → warning but no violation."""
        result = check_compliance(
            balance=48_100.0,
            balance_high=50_000.0,
            daily_pnl=0.0,
            num_contracts=0,
            current_time_ct=SAFE_TIME,
        )
        assert result.is_compliant is True
        assert any("MLL WARNING" in w for w in result.warnings)

    def test_mll_uses_balance_high_as_reference(self):
        """MLL floor = balance_high - $2,000, NOT initial balance."""
        result = check_compliance(
            balance=51_500.0,
            balance_high=53_000.0,  # high is 53k, floor is 51k
            daily_pnl=0.0,
            num_contracts=0,
            current_time_ct=SAFE_TIME,
        )
        assert result.is_compliant is True

    def test_mll_violation_after_balance_high_grows(self):
        result = check_compliance(
            balance=50_900.0,
            balance_high=53_000.0,  # floor = 51k → 50.9k < 51k
            daily_pnl=0.0,
            num_contracts=0,
            current_time_ct=SAFE_TIME,
        )
        assert "MLL" in result.violations


class TestDLLViolation:

    def test_daily_pnl_below_1000_is_violation(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, -1001.0, SAFE_CONTR, SAFE_TIME
        )
        assert result.is_compliant is False
        assert "DLL" in result.violations

    def test_daily_pnl_exactly_minus_1000_is_compliant(self):
        """daily_pnl == -$1,000 → still compliant (strict <)."""
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, -1000.0, SAFE_CONTR, SAFE_TIME
        )
        assert result.is_compliant is True

    def test_dll_warning_within_100_of_limit(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, -920.0, SAFE_CONTR, SAFE_TIME
        )
        assert result.is_compliant is True
        assert any("DLL WARNING" in w for w in result.warnings)

    def test_positive_pnl_no_dll(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, 500.0, SAFE_CONTR, SAFE_TIME
        )
        assert "DLL" not in result.violations


class TestMaxContractsViolation:

    def test_51_contracts_is_violation(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, 51, SAFE_TIME
        )
        assert result.is_compliant is False
        assert "MAX_CONTRACTS" in result.violations

    def test_50_contracts_is_compliant(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, 50, SAFE_TIME
        )
        assert "MAX_CONTRACTS" not in result.violations

    def test_zero_contracts_is_compliant(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, 0, SAFE_TIME
        )
        assert "MAX_CONTRACTS" not in result.violations


class TestTimeViolation:

    def test_past_1510_with_open_positions_is_violation(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, 5, _dt(15, 11)
        )
        assert result.is_compliant is False
        assert "TIME" in result.violations

    def test_past_1510_with_no_positions_is_compliant(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, 0, _dt(15, 11)
        )
        assert "TIME" not in result.violations

    def test_exactly_1510_with_positions_is_violation(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, 1, _dt(15, 10)
        )
        assert "TIME" in result.violations

    def test_before_1510_with_positions_is_compliant(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, 10, _dt(15, 9)
        )
        assert "TIME" not in result.violations

    def test_hard_close_warning_after_1500_before_1510(self):
        """Past engine hard close (15:00) but before Topstep deadline (15:10)."""
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, 3, _dt(15, 5)
        )
        assert "TIME" not in result.violations  # not a violation yet
        assert any("TIME WARNING" in w for w in result.warnings)


class TestMultipleViolations:

    def test_mll_and_dll_together(self):
        result = check_compliance(
            balance=47_000.0,
            balance_high=50_000.0,
            daily_pnl=-1_200.0,
            num_contracts=0,
            current_time_ct=SAFE_TIME,
        )
        assert "MLL" in result.violations
        assert "DLL" in result.violations
        assert result.is_compliant is False

    def test_all_four_violations(self):
        result = check_compliance(
            balance=47_000.0,
            balance_high=50_000.0,
            daily_pnl=-1_500.0,
            num_contracts=55,
            current_time_ct=_dt(15, 15),
        )
        assert len(result.violations) == 4
        assert result.is_compliant is False

    def test_result_is_compliance_result_type(self):
        result = check_compliance(
            SAFE_BALANCE, SAFE_HIGH, SAFE_PNL, SAFE_CONTR, SAFE_TIME
        )
        assert isinstance(result, ComplianceResult)


class TestProfitTarget:

    def test_at_profit_target(self):
        """$50,000 + $3,000 profit = $53,000 balance → target reached."""
        assert is_within_profit_target(53_000.0) is True

    def test_above_profit_target(self):
        assert is_within_profit_target(55_000.0) is True

    def test_below_profit_target(self):
        assert is_within_profit_target(52_999.0) is False

    def test_starting_balance_not_at_target(self):
        assert is_within_profit_target(50_000.0) is False
