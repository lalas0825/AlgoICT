"""
tests/test_report.py
=====================
Tests for backtest/report.py  (generate_report).
"""

import os
import math
import datetime
import pytest
import pandas as pd
import tempfile

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.backtester import Trade
from backtest.report import generate_report, _build_equity_curve, _max_drawdown, _sharpe
from backtest.combine_simulator import simulate_combine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(day, hour=9, minute=0):
    return pd.Timestamp(
        f"2024-01-{day:02d} {hour:02d}:{minute:02d}:00",
        tz="America/Chicago",
    )


def _trade(day, pnl, confluence_score=9, reason=None, entry_hour=9):
    if reason is None:
        reason = "target" if pnl > 0 else "stop"
    entry = _ts(day, entry_hour)
    exit_ = _ts(day, entry_hour + 1)
    return Trade(
        strategy="ny_am_reversal",
        symbol="MNQ",
        direction="long",
        entry_time=entry,
        exit_time=exit_,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        exit_price=102.0 if pnl > 0 else 99.0,
        contracts=125,
        pnl=float(pnl),
        reason=reason,
        confluence_score=confluence_score,
        duration_bars=60,
    )


def _standard_trades():
    """5 wins, 3 losses across 8 days."""
    return [
        _trade(1, 500), _trade(2, -250), _trade(3, 500),
        _trade(4, -250), _trade(5, 500), _trade(6, -250),
        _trade(7, 500), _trade(8, 500),
    ]


# ---------------------------------------------------------------------------
# Basic output
# ---------------------------------------------------------------------------

class TestReportOutput:
    def test_empty_returns_string(self):
        result = generate_report([])
        assert isinstance(result, str)
        assert "no trades" in result

    def test_returns_string(self):
        result = generate_report(_standard_trades())
        assert isinstance(result, str)

    def test_contains_key_sections(self):
        report = generate_report(_standard_trades())
        assert "Win Rate" in report
        assert "Profit Factor" in report
        assert "Sharpe" in report
        assert "Max Drawdown" in report

    def test_contains_confluence_bands(self):
        report = generate_report(_standard_trades())
        assert "7-8" in report
        assert "9-11" in report
        assert "12+" in report

    def test_contains_weekday_section(self):
        report = generate_report(_standard_trades())
        assert "Mon" in report or "Tue" in report or "Wed" in report

    def test_single_trade(self):
        report = generate_report([_trade(1, 250)])
        assert "1" in report   # at least 1 trade shown


# ---------------------------------------------------------------------------
# Metric correctness
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_win_rate_in_report(self):
        trades = [_trade(1, 500), _trade(2, -250)]
        report = generate_report(trades)
        # 1 win / 2 trades = 50%
        assert "50%" in report

    def test_total_pnl_in_report(self):
        trades = [_trade(1, 300), _trade(2, -100)]
        report = generate_report(trades)
        assert "200" in report   # $200 total

    def test_profit_factor_inf_no_losses(self):
        trades = [_trade(1, 500), _trade(2, 300)]
        report = generate_report(trades)
        assert "inf" in report.lower() or "Inf" in report

    def test_max_drawdown_zero_all_wins(self):
        trades = [_trade(d, 300) for d in range(1, 4)]
        report = generate_report(trades)
        # Running peak never drops, so max_dd = 0
        assert "$0.00" in report


# ---------------------------------------------------------------------------
# Combine section
# ---------------------------------------------------------------------------

class TestCombineSection:
    def test_combine_section_included_when_passed(self):
        trades = [_trade(d, 600) for d in range(1, 7)]
        combine = simulate_combine(trades)
        report = generate_report(trades, combine_result=combine)
        assert "Combine" in report
        assert "PASSED" in report

    def test_combine_section_shows_failure(self):
        trades = [_trade(d, 200) for d in range(1, 4)]
        combine = simulate_combine(trades)
        report = generate_report(trades, combine_result=combine)
        assert "FAILED" in report

    def test_no_combine_section_by_default(self):
        report = generate_report(_standard_trades())
        assert "Combine" not in report


# ---------------------------------------------------------------------------
# Equity CSV
# ---------------------------------------------------------------------------

class TestEquityCSV:
    def test_csv_written(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            generate_report(_standard_trades(), equity_csv=path)
            assert os.path.exists(path)
            with open(path) as f:
                lines = f.readlines()
            assert lines[0].strip() == "timestamp,cumulative_pnl"
            assert len(lines) == len(_standard_trades()) + 1   # header + rows
        finally:
            os.unlink(path)

    def test_csv_values_cumulative(self):
        trades = [_trade(1, 200), _trade(2, 100), _trade(3, -50)]
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            path = f.name
        try:
            generate_report(trades, equity_csv=path)
            with open(path) as f:
                lines = f.readlines()
            # rows: 200, 300, 250
            values = [float(l.split(",")[1].strip()) for l in lines[1:]]
            assert abs(values[0] - 200.0) < 0.01
            assert abs(values[1] - 300.0) < 0.01
            assert abs(values[2] - 250.0) < 0.01
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_build_equity_curve_ordered(self):
        t1 = _trade(3, 100)
        t2 = _trade(1, 200)   # earlier
        curve = _build_equity_curve([t1, t2])
        # Should be sorted: t2 first (day 1), t1 second (day 3)
        assert curve[0][1] == 200.0
        assert curve[1][1] == 300.0

    def test_max_drawdown_empty(self):
        assert _max_drawdown([]) == 0.0

    def test_max_drawdown_no_drawdown(self):
        curve = [(_ts(i), float(i * 100)) for i in range(1, 6)]
        assert _max_drawdown(curve) == 0.0

    def test_max_drawdown_correct(self):
        # peak=500, trough=200 → dd=300
        curve = [
            (_ts(1), 100.0),
            (_ts(2), 500.0),
            (_ts(3), 200.0),
            (_ts(4), 400.0),
        ]
        assert abs(_max_drawdown(curve) - 300.0) < 0.01

    def test_sharpe_insufficient_data(self):
        assert _sharpe([]) == 0.0
        assert _sharpe([100.0]) == 0.0

    def test_sharpe_zero_variance(self):
        assert _sharpe([100.0, 100.0, 100.0]) == 0.0

    def test_sharpe_positive_returns(self):
        # All positive daily returns → positive Sharpe
        s = _sharpe([100.0, 200.0, 150.0, 120.0, 180.0])
        assert s > 0

    def test_sharpe_negative_returns(self):
        s = _sharpe([-100.0, -200.0, -150.0])
        assert s < 0
