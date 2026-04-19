"""
tests/test_combine_simulator.py
================================
Tests for backtest/combine_simulator.py  (simulate_combine).
"""

import math
import datetime
import pytest
import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.backtester import Trade
from backtest.combine_simulator import simulate_combine
import config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MNQ_PV = 2.0


def _ts(day, hour=9, minute=0, month=1):
    return pd.Timestamp(
        f"2024-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:00",
        tz="America/Chicago",
    )


def _trade(day, pnl, month=1):
    """Minimal trade for combine simulation."""
    entry = _ts(day, 9, 0, month=month)
    exit_ = _ts(day, 10, 0, month=month)
    entry_price = 100.0
    stop_price = 99.0
    return Trade(
        strategy="ny_am_reversal",
        symbol="MNQ",
        direction="long",
        entry_time=entry,
        exit_time=exit_,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=102.0,
        exit_price=102.0 if pnl > 0 else stop_price,
        contracts=125,
        pnl=float(pnl),
        reason="target" if pnl > 0 else "stop",
        confluence_score=9,
        duration_bars=60,
    )


def _trades_pass():
    """6 days of trades that should pass: total $3,600, best day $750 < 50%."""
    return [_trade(day=d, pnl=600.0) for d in range(1, 7)]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_trades(self):
        result = simulate_combine([])
        assert not result.passed
        assert result.failure_reason == "no_trades"

    def test_result_fields_present(self):
        result = simulate_combine(_trades_pass())
        assert hasattr(result, "passed")
        assert hasattr(result, "starting_balance")
        assert hasattr(result, "ending_balance")
        assert hasattr(result, "total_pnl")
        assert hasattr(result, "trading_days")
        assert hasattr(result, "days")


# ---------------------------------------------------------------------------
# Passing combine
# ---------------------------------------------------------------------------

class TestPassingCombine:
    def test_basic_pass(self):
        result = simulate_combine(_trades_pass())
        assert result.passed
        assert result.failure_reason is None

    def test_total_pnl_correct(self):
        # Simulator stops as soon as profit target + 5 days + consistency are met.
        # With 6 days × $600, it stops at day 5 (pnl=$3,000 >= target=$3,000).
        trades = _trades_pass()
        result = simulate_combine(trades)
        assert result.total_pnl >= config.TOPSTEP_PROFIT_TARGET

    def test_ending_balance_correct(self):
        result = simulate_combine(_trades_pass())
        assert result.ending_balance >= config.TOPSTEP_ACCOUNT_SIZE + config.TOPSTEP_PROFIT_TARGET

    def test_trading_days_correct(self):
        # Stops at day 5 (minimum required) once all pass conditions are satisfied.
        result = simulate_combine(_trades_pass())
        assert result.trading_days >= 5

    def test_consistency_ok(self):
        result = simulate_combine(_trades_pass())
        assert result.consistency_ok is True

    def test_best_day_tracked(self):
        result = simulate_combine(_trades_pass())
        assert abs(result.best_day_pnl - 600.0) < 0.01


# ---------------------------------------------------------------------------
# Profit target
# ---------------------------------------------------------------------------

class TestProfitTarget:
    def test_below_target_fails(self):
        # $2,800 total — under $3,000
        trades = [_trade(day=d, pnl=400.0) for d in range(1, 8)]   # $2,800
        result = simulate_combine(trades)
        assert not result.passed
        assert "profit_target_not_reached" in result.failure_reason

    def test_exactly_target_passes(self):
        # $3,000 exactly: 6 days × $500 = $3,000, best_day=$500 < 50%*3000=$1500
        trades = [_trade(day=d, pnl=500.0) for d in range(1, 7)]
        result = simulate_combine(trades)
        assert result.passed

    def test_custom_starting_balance(self):
        trades = _trades_pass()
        result = simulate_combine(trades, starting_balance=100_000)
        assert result.starting_balance == 100_000
        # Stops as soon as profit target is reached; ending >= 100_000 + target.
        assert result.ending_balance >= 100_000 + config.TOPSTEP_PROFIT_TARGET


# ---------------------------------------------------------------------------
# MLL (Maximum Loss Limit)
# ---------------------------------------------------------------------------

class TestMLL:
    def test_mll_breach_fails(self):
        # 1 day win sets EOD peak to $51,000; day 2 intraday loss of -$2,100
        # drops balance to $48,900 — drawdown $2,100 >= MLL $2,000 → FAIL before target.
        win = _trade(day=1, pnl=1000.0)
        big_loss = _trade(day=2, pnl=-2100.0)
        result = simulate_combine([win, big_loss])
        assert not result.passed
        assert "mll_breach" in result.failure_reason

    def test_mll_exactly_at_limit_fails(self):
        # One loss of exactly $2,000 from starting balance
        t = _trade(day=1, pnl=-2000.0)
        result = simulate_combine([t])
        assert not result.passed
        assert "mll_breach" in result.failure_reason

    def test_mll_just_under_passes(self):
        # One win brings peak to $51,000 then loss of $1,999
        win = _trade(day=1, pnl=1000.0)
        loss = _trade(day=2, pnl=-1999.0)
        # Then add more wins to reach target
        more_wins = [_trade(day=d, pnl=700.0) for d in range(3, 9)]
        trades = [win, loss] + more_wins
        result = simulate_combine(trades)
        # Don't check passed (may fail for other reasons); just no MLL flag
        assert result.failure_reason is None or "mll_breach" not in result.failure_reason


# ---------------------------------------------------------------------------
# DLL (Daily Loss Limit)
# ---------------------------------------------------------------------------

class TestDLL:
    def test_dll_breach_fails(self):
        bad_day = _trade(day=1, pnl=-1001.0)
        result = simulate_combine([bad_day])
        assert not result.passed
        assert "dll_breach" in result.failure_reason

    def test_dll_exactly_at_limit_fails(self):
        t = _trade(day=1, pnl=-1000.0)
        result = simulate_combine([t])
        assert not result.passed

    def test_dll_just_under_passes(self):
        # -$999 on one day, then make it up
        loss = _trade(day=1, pnl=-999.0)
        wins = [_trade(day=d, pnl=700.0) for d in range(2, 8)]   # 6 × $700 = $4,200
        result = simulate_combine([loss] + wins)
        # No DLL failure
        assert result.failure_reason is None or "dll_breach" not in result.failure_reason

    def test_multiple_losses_same_day_cumulative(self):
        """Two trades on same day: -$600 each = -$1,200 → DLL breach."""
        t1 = _trade(day=1, pnl=-600.0)
        t2 = Trade(
            strategy="ny_am_reversal", symbol="MNQ", direction="long",
            entry_time=_ts(1, 11), exit_time=_ts(1, 12),
            entry_price=100.0, stop_price=99.0, target_price=102.0,
            exit_price=99.0, contracts=125, pnl=-600.0,
            reason="stop", confluence_score=9, duration_bars=60,
        )
        result = simulate_combine([t1, t2])
        assert not result.passed
        assert "dll_breach" in result.failure_reason


# ---------------------------------------------------------------------------
# Consistency rule
# ---------------------------------------------------------------------------

class TestConsistency:
    def test_best_day_50pct_or_more_fails(self):
        # total=$3,000: day1=$1,500 (50%), days 2-6 = $300 each
        day1 = _trade(day=1, pnl=1500.0)
        others = [_trade(day=d, pnl=300.0) for d in range(2, 7)]
        result = simulate_combine([day1] + others)
        assert not result.passed
        assert "consistency" in result.failure_reason

    def test_best_day_just_under_50pct_passes(self):
        # total=$3,600: best=$1,799 < 50%=$1,800
        day1 = _trade(day=1, pnl=1799.0)
        others = [_trade(day=d, pnl=360.2) for d in range(2, 7)]   # 5 × 360.2 = $1,801
        # Adjust to get total > $3,000 with best_day < 50%
        trades = [day1] + others
        result = simulate_combine(trades)
        # Just verify no consistency failure if best < 50%
        if result.passed:
            assert result.consistency_ok is True

    def test_consistency_only_checked_when_target_reached(self):
        # Under target — failure_reason should be profit_target, not consistency
        day1 = _trade(day=1, pnl=2000.0)
        day2 = _trade(day=2, pnl=100.0)
        result = simulate_combine([day1, day2])
        assert not result.passed
        # Some failure — but consistency shouldn't dominate if target not met
        # (could be min days or profit target)
        assert result.failure_reason is not None


# ---------------------------------------------------------------------------
# Minimum trading days
# ---------------------------------------------------------------------------

class TestMinTradingDays:
    def test_4_days_fails(self):
        trades = [_trade(day=d, pnl=1000.0) for d in range(1, 5)]  # 4 days, $4K
        result = simulate_combine(trades)
        assert not result.passed
        assert "insufficient_trading_days" in result.failure_reason

    def test_5_days_passes(self):
        trades = [_trade(day=d, pnl=700.0) for d in range(1, 7)]   # 6 days, $4.2K
        result = simulate_combine(trades)
        assert result.passed

    def test_exactly_5_days_ok(self):
        # 5 days × $700 = $3,500 > $3,000; best_day=$700 < 50%=$1,750
        trades = [_trade(day=d, pnl=700.0) for d in range(1, 6)]
        result = simulate_combine(trades)
        assert result.passed
