"""
tests/test_risk_audit.py
========================
Tests for backtest/risk_audit.py  (audit_trades).
"""

import math
import datetime
import pytest
import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.backtester import Trade
from backtest.risk_audit import audit_trades
import config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MNQ_PV = 2.0

def _ts(hour, minute=0, day=1):
    return pd.Timestamp(f"2024-01-{day:02d} {hour:02d}:{minute:02d}:00", tz="America/Chicago")


def _good_trade(
    entry_price=100.0,
    stop_price=99.0,
    contracts=None,
    pnl=None,
    reason="target",
    confluence_score=9,
    direction="long",
    entry_time=None,
    exit_time=None,
    day=1,
):
    """Build a trade that passes all audit rules by default."""
    stop_dist = abs(entry_price - stop_price)
    if contracts is None:
        raw = config.RISK_PER_TRADE / (stop_dist * MNQ_PV)
        contracts = max(1, min(int(math.floor(raw)), config.MAX_CONTRACTS))
    if pnl is None:
        pnl = contracts * stop_dist * MNQ_PV * 2   # 1:2 RR win
    entry_time = entry_time or _ts(9, 30, day=day)
    if exit_time is None:
        exit_time = _ts(10, 0, day=day) if reason != "hard_close" else _ts(15, 1, day=day)
    return Trade(
        strategy="ny_am_reversal",
        symbol="MNQ",
        direction=direction,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=entry_price + 2 * stop_dist if direction == "long" else entry_price - 2 * stop_dist,
        exit_price=entry_price + 2 * stop_dist if pnl > 0 else stop_price,
        contracts=contracts,
        pnl=pnl,
        reason=reason,
        confluence_score=confluence_score,
        duration_bars=30,
    )


# ---------------------------------------------------------------------------
# Clean trades
# ---------------------------------------------------------------------------

class TestCleanTrades:
    def test_empty_list(self):
        result = audit_trades([])
        assert result.is_clean
        assert result.violation_count == 0

    def test_single_good_trade(self):
        t = _good_trade()
        result = audit_trades([t])
        assert result.is_clean
        assert result.violation_count == 0

    def test_multiple_good_trades_same_day(self):
        trades = [_good_trade(day=1), _good_trade(entry_price=200.0, stop_price=199.0, day=1)]
        result = audit_trades(trades)
        assert result.is_clean

    def test_good_trades_across_days(self):
        trades = [_good_trade(day=d) for d in range(1, 6)]
        result = audit_trades(trades)
        assert result.is_clean

    def test_hard_close_trade_allowed_after_1500(self):
        t = _good_trade(
            reason="hard_close",
            exit_time=_ts(15, 1),
            pnl=-200,
        )
        result = audit_trades([t])
        assert result.is_clean


# ---------------------------------------------------------------------------
# Rule 1: Max risk
# ---------------------------------------------------------------------------

class TestMaxRisk:
    def test_exactly_250_ok(self):
        # stop_dist=5.0, floor(250/(5*2))=25 contracts → risk = 5.0 * 25 * 2 = $250
        t = _good_trade(entry_price=100.0, stop_price=95.0, contracts=25)
        result = audit_trades([t])
        assert result.is_clean

    def test_risk_over_250_flagged(self):
        # stop_dist=1.0, contracts=200 → risk = $400
        t = _good_trade(entry_price=100.0, stop_price=99.0, contracts=200)
        result = audit_trades([t])
        assert not result.is_clean
        assert any("max_risk_exceeded" in v for v in result.violations)

    def test_risk_just_above_250_flagged(self):
        # risk = $250.02
        t = _good_trade(entry_price=100.0, stop_price=99.0, contracts=125)
        # inflate contracts by 1 while keeping stop_dist=1.0 → risk=$252
        t.contracts = 126
        result = audit_trades([t])
        assert not result.is_clean

    def test_small_stop_large_contracts_ok_if_floor(self):
        # stop_dist=0.5, raw=250, floor=250 (or MAX_CONTRACTS=50 cap)
        t = _good_trade(entry_price=100.0, stop_price=99.5)
        result = audit_trades([t])
        assert result.is_clean


# ---------------------------------------------------------------------------
# Rule 2: Floor sizing
# ---------------------------------------------------------------------------

class TestFloorSizing:
    def test_oversized_flagged(self):
        # stop_dist=1.0, correct=125, we put 126
        t = _good_trade(entry_price=100.0, stop_price=99.0)
        t.contracts = t.contracts + 1
        result = audit_trades([t])
        assert not result.is_clean
        assert any("oversized" in v for v in result.violations)

    def test_undersized_ok(self):
        # Soft override may reduce contracts (VPIN/SWC)
        t = _good_trade(entry_price=100.0, stop_price=99.0)
        t.contracts = max(1, t.contracts - 1)
        result = audit_trades([t])
        assert result.is_clean

    def test_minimum_1_contract(self):
        # Very wide stop: raw < 1 → floor to 1
        t = _good_trade(entry_price=100.0, stop_price=50.0, contracts=1)
        result = audit_trades([t])
        assert result.is_clean


# ---------------------------------------------------------------------------
# Rule 3: Hard close
# ---------------------------------------------------------------------------

class TestHardClose:
    def test_exit_before_1500_ok(self):
        t = _good_trade(exit_time=_ts(14, 59), reason="target")
        result = audit_trades([t])
        assert result.is_clean

    def test_exit_at_1500_non_hard_close_flagged(self):
        t = _good_trade(exit_time=_ts(15, 0), reason="target")
        result = audit_trades([t])
        assert not result.is_clean
        assert any("hard_close_violation" in v for v in result.violations)

    def test_exit_after_1500_hard_close_ok(self):
        t = _good_trade(exit_time=_ts(15, 5), reason="hard_close", pnl=-50)
        result = audit_trades([t])
        assert result.is_clean


# ---------------------------------------------------------------------------
# Rule 4: Min confluence
# ---------------------------------------------------------------------------

class TestMinConfluence:
    def test_score_7_ok(self):
        t = _good_trade(confluence_score=7)
        result = audit_trades([t])
        assert result.is_clean

    def test_score_6_flagged(self):
        t = _good_trade(confluence_score=6)
        result = audit_trades([t])
        assert not result.is_clean
        assert any("low_confluence" in v for v in result.violations)

    def test_score_0_flagged(self):
        t = _good_trade(confluence_score=0)
        result = audit_trades([t])
        assert not result.is_clean


# ---------------------------------------------------------------------------
# Rule 5: Kill switch
# ---------------------------------------------------------------------------

class TestKillSwitch:
    def test_3_losses_stop_4th(self):
        """4th trade on same day after 3 consecutive losses = violation."""
        base_time = _ts(9, 0, day=1)
        def loss_trade(offset_min):
            t = _good_trade(
                pnl=-250.0,
                entry_time=base_time + pd.Timedelta(minutes=offset_min),
                exit_time=base_time + pd.Timedelta(minutes=offset_min + 5),
                reason="stop",
            )
            return t

        trades = [loss_trade(i * 10) for i in range(4)]  # 4 losses
        result = audit_trades(trades)
        assert not result.is_clean
        assert any("kill_switch" in v for v in result.violations)

    def test_2_losses_then_win_resets(self):
        """After win, consecutive losses reset — next loss is NOT a kill switch violation."""
        def make(offset, pnl):
            return _good_trade(
                pnl=pnl,
                entry_time=_ts(9, 0) + pd.Timedelta(minutes=offset),
                exit_time=_ts(9, 0) + pd.Timedelta(minutes=offset + 5),
                reason="stop" if pnl < 0 else "target",
            )
        trades = [make(0, -250), make(10, -250), make(20, 500), make(30, -250), make(40, -250)]
        result = audit_trades(trades)
        assert result.is_clean

    def test_3_losses_next_day_ok(self):
        """Kill switch resets daily — next day's first trade is fine."""
        losses_day1 = [_good_trade(pnl=-250, reason="stop", day=1) for _ in range(3)]
        win_day2 = _good_trade(day=2)
        result = audit_trades(losses_day1 + [win_day2])
        # Only violation would be if a 4th trade on day1 existed — here it doesn't
        assert result.is_clean


# ---------------------------------------------------------------------------
# Rule 6: Profit cap
# ---------------------------------------------------------------------------

class TestProfitCap:
    def test_trade_after_1500_pnl_flagged(self):
        """Daily P&L already at $1500 — next trade on same day = violation."""
        big_win = _good_trade(pnl=1500.0, entry_time=_ts(9, 0), exit_time=_ts(9, 5))
        extra = _good_trade(pnl=250.0, entry_time=_ts(9, 30), exit_time=_ts(9, 35))
        result = audit_trades([big_win, extra])
        assert not result.is_clean
        assert any("profit_cap" in v for v in result.violations)

    def test_pnl_exactly_1499_ok(self):
        """$1,499 cumulative — still allowed to trade."""
        trade1 = _good_trade(pnl=1499.0, entry_time=_ts(9, 0), exit_time=_ts(9, 5))
        trade2 = _good_trade(pnl=100.0, entry_time=_ts(9, 30), exit_time=_ts(9, 35))
        result = audit_trades([trade1, trade2])
        assert result.is_clean

    def test_profit_cap_resets_next_day(self):
        """Profit cap is per-day — next day starts fresh."""
        day1 = _good_trade(pnl=2000.0, day=1)
        day2 = _good_trade(pnl=250.0, day=2)
        result = audit_trades([day1, day2])
        assert result.is_clean

    def test_multiple_violations_counted(self):
        """Two trades after cap = 2 violations."""
        big_win = _good_trade(pnl=1500.0, entry_time=_ts(9, 0), exit_time=_ts(9, 5))
        extra1 = _good_trade(pnl=100.0, entry_time=_ts(9, 30), exit_time=_ts(9, 35))
        extra2 = _good_trade(pnl=100.0, entry_time=_ts(10, 0), exit_time=_ts(10, 5))
        result = audit_trades([big_win, extra1, extra2])
        assert result.violation_count >= 2
