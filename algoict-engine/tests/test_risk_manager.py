"""
tests/test_risk_manager.py
===========================
Unit tests for risk/risk_manager.py

Run: cd algoict-engine && python -m pytest tests/test_risk_manager.py -v
"""

import pytest
from datetime import datetime, time
import pytz

from risk.risk_manager import RiskManager


CT = pytz.timezone("US/Central")


def _dt(hour: int, minute: int = 0) -> datetime:
    """Helper: tz-aware CT datetime."""
    return CT.localize(datetime(2025, 3, 3, hour, minute))


class TestRecordTrade:

    def test_single_loss_increments_consecutive_losses(self):
        rm = RiskManager()
        rm.record_trade(-250)
        assert rm.consecutive_losses == 1
        assert rm.daily_pnl == pytest.approx(-250)

    def test_win_resets_consecutive_losses(self):
        rm = RiskManager()
        rm.record_trade(-250)
        rm.record_trade(-250)
        rm.record_trade(300)   # win — reset
        assert rm.consecutive_losses == 0

    def test_trades_today_increments_each_call(self):
        rm = RiskManager()
        rm.record_trade(100)
        rm.record_trade(-100)
        assert rm.trades_today == 2

    def test_daily_pnl_accumulates(self):
        rm = RiskManager()
        rm.record_trade(300)
        rm.record_trade(-100)
        rm.record_trade(200)
        assert rm.daily_pnl == pytest.approx(400)

    def test_three_losses_activate_kill_switch(self):
        rm = RiskManager()
        rm.record_trade(-250)
        rm.record_trade(-250)
        assert not rm.kill_switch_active
        rm.record_trade(-250)
        assert rm.kill_switch_active

    def test_loss_exceeds_750_activates_kill_switch(self):
        """Single large loss exceeds KILL_SWITCH_AMOUNT."""
        rm = RiskManager()
        rm.record_trade(-800)
        assert rm.kill_switch_active

    def test_two_losses_plus_partial_no_kill_switch(self):
        rm = RiskManager()
        rm.record_trade(-250)
        rm.record_trade(-250)
        assert not rm.kill_switch_active

    def test_daily_pnl_1500_activates_profit_cap(self):
        rm = RiskManager()
        rm.record_trade(1500)
        assert rm.profit_cap_active

    def test_daily_pnl_below_1500_no_cap(self):
        rm = RiskManager()
        rm.record_trade(1499)
        assert not rm.profit_cap_active

    def test_accumulated_wins_trigger_profit_cap(self):
        rm = RiskManager()
        rm.record_trade(800)
        rm.record_trade(700)   # 1500 total
        assert rm.profit_cap_active


class TestCanTrade:

    def test_fresh_manager_allows_trade(self):
        rm = RiskManager()
        allowed, reason = rm.can_trade()
        assert allowed is True
        assert reason == "ok"

    def test_kill_switch_blocks_trade(self):
        rm = RiskManager()
        rm.kill_switch_active = True
        allowed, reason = rm.can_trade()
        assert allowed is False
        assert reason == "kill_switch"

    def test_profit_cap_blocks_trade(self):
        rm = RiskManager()
        rm.profit_cap_active = True
        allowed, reason = rm.can_trade()
        assert allowed is False
        assert reason == "profit_cap"

    def test_vpin_halt_blocks_trade(self):
        rm = RiskManager()
        rm._vpin_halt_active = True
        allowed, reason = rm.can_trade()
        assert allowed is False
        assert reason == "vpin_halted"

    def test_max_trades_blocks_trade(self):
        rm = RiskManager()
        rm.trades_today = 3   # MAX_MNQ_TRADES_PER_DAY = 3
        allowed, reason = rm.can_trade()
        assert allowed is False
        assert reason == "max_trades"

    def test_vpin_halt_takes_priority_over_kill_switch(self):
        rm = RiskManager()
        rm._vpin_halt_active = True
        rm.kill_switch_active = True
        _, reason = rm.can_trade()
        assert reason == "vpin_halted"

    def test_kill_switch_takes_priority_over_profit_cap(self):
        rm = RiskManager()
        rm.kill_switch_active = True
        rm.profit_cap_active = True
        _, reason = rm.can_trade()
        assert reason == "kill_switch"

    def test_two_trades_still_allowed(self):
        rm = RiskManager()
        rm.trades_today = 2
        allowed, _ = rm.can_trade()
        assert allowed is True


class TestHardClose:

    def test_before_hard_close_is_false(self):
        rm = RiskManager()
        assert rm.check_hard_close(_dt(14, 59)) is False

    def test_at_hard_close_is_true(self):
        rm = RiskManager()
        assert rm.check_hard_close(_dt(15, 0)) is True

    def test_after_hard_close_is_true(self):
        rm = RiskManager()
        assert rm.check_hard_close(_dt(15, 30)) is True

    def test_early_morning_is_false(self):
        rm = RiskManager()
        assert rm.check_hard_close(_dt(9, 0)) is False


class TestOverrides:

    def test_swc_sets_confluence_adjustment(self):
        rm = RiskManager()
        rm.set_swc_overrides(min_conf_adj=1, pos_mult=0.8)
        assert rm.effective_min_confluence == 8   # 7 + 1
        assert rm.position_multiplier == pytest.approx(0.8)

    def test_vpin_halt_sets_flag(self):
        rm = RiskManager()
        rm.set_vpin_overrides(halted=True, tighten_pct=0.25, pos_mult=0.75)
        allowed, reason = rm.can_trade()
        assert allowed is False
        assert reason == "vpin_halted"

    def test_vpin_reduces_position_multiplier(self):
        rm = RiskManager()
        rm.set_vpin_overrides(halted=False, tighten_pct=0.0, pos_mult=0.75)
        assert rm.position_multiplier == pytest.approx(0.75)

    def test_position_multiplier_takes_min(self):
        """SWC sets 0.8, then VPIN sets 0.75 → result is 0.75 (the min)."""
        rm = RiskManager()
        rm.set_swc_overrides(min_conf_adj=0, pos_mult=0.8)
        rm.set_vpin_overrides(halted=False, tighten_pct=0.0, pos_mult=0.75)
        assert rm.position_multiplier == pytest.approx(0.75)

    def test_emergency_flatten_activates_kill_switch(self):
        rm = RiskManager()
        rm.emergency_flatten()
        assert rm.kill_switch_active is True


class TestResetDaily:

    def test_reset_clears_all_state(self):
        rm = RiskManager()
        rm.record_trade(-300)
        rm.record_trade(-300)
        rm.record_trade(-300)  # activates kill switch
        rm.profit_cap_active = True
        rm._vpin_halted = True
        rm._min_confluence_adj = 2
        rm._position_multiplier = 0.5

        rm.reset_daily()

        assert rm.daily_pnl == 0.0
        assert rm.consecutive_losses == 0
        assert rm.trades_today == 0
        assert rm.kill_switch_active is False
        assert rm.profit_cap_active is False
        assert rm._vpin_halted is False
        assert rm._min_confluence_adj == 0
        assert rm.position_multiplier == pytest.approx(1.0)

    def test_can_trade_after_reset(self):
        rm = RiskManager()
        rm.record_trade(-250)
        rm.record_trade(-250)
        rm.record_trade(-250)
        assert rm.can_trade()[0] is False
        rm.reset_daily()
        assert rm.can_trade()[0] is True
