"""Tests for db.adapters — pure conversion functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from db.adapters import (
    trade_to_row,
    signal_to_row,
    backtest_result_to_row,
    candidate_record_to_row,
    post_mortem_to_row,
    normalize_bot_state,
    _compute_max_drawdown,
    _compute_sharpe,
)


# ─── Fixtures ───────────────────────────────────────────────────────────

@dataclass
class FakeTrade:
    """Mirrors backtest.backtester.Trade fields."""
    strategy: str = "ny_am_reversal"
    symbol: str = "MNQ"
    direction: str = "long"
    entry_time: datetime = field(default_factory=lambda: datetime(2025, 3, 10, 14, 30, tzinfo=timezone.utc))
    exit_time: datetime = field(default_factory=lambda: datetime(2025, 3, 10, 14, 45, tzinfo=timezone.utc))
    entry_price: float = 18000.0
    stop_price: float = 17980.0
    target_price: float = 18060.0
    exit_price: float = 18060.0
    contracts: int = 1
    pnl: float = 120.0
    reason: str = "target"
    confluence_score: int = 12
    duration_bars: int = 15


@dataclass
class FakeBacktestResult:
    strategy: str = "ny_am_reversal"
    trades: list = field(default_factory=list)
    daily_pnl: dict = field(default_factory=dict)
    total_pnl: float = 500.0
    total_trades: int = 5
    wins: int = 3
    losses: int = 2
    win_rate: float = 0.6
    total_signals: int = 7
    start_date: datetime = field(default_factory=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc))
    end_date: datetime = field(default_factory=lambda: datetime(2025, 3, 31, tzinfo=timezone.utc))


# ─── trade_to_row ────────────────────────────────────────────────────────

class TestTradeToRow:
    def test_accepts_dataclass(self):
        row = trade_to_row(FakeTrade())
        assert row["direction"] == "long"
        assert row["strategy"] == "ny_am_reversal"
        assert row["entry_price"] == 18000.0
        assert row["pnl"] == 120.0
        assert row["confluence_score"] == 12
        assert "side" not in row  # Schema uses direction, not side

    def test_accepts_dict(self):
        row = trade_to_row({
            "direction": "short",
            "entry_price": 18500.0,
            "stop_price": 18520.0,
            "target_price": 18460.0,
            "exit_price": 18460.0,
            "entry_time": "2025-03-10T14:30:00+00:00",
            "pnl": 80.0,
            "contracts": 2,
            "confluence_score": 9,
            "strategy": "silver_bullet",
            "symbol": "MNQ",
        })
        assert row["direction"] == "short"
        assert row["contracts"] == 2
        assert row["strategy"] == "silver_bullet"

    def test_maps_stop_and_target_fields(self):
        """backtester.Trade uses stop_price/target_price; schema uses stop_loss/take_profit."""
        trade = FakeTrade(stop_price=17990, target_price=18030)
        row = trade_to_row(trade)
        assert row["stop_loss"] == 17990
        assert row["take_profit"] == 18030

    def test_generates_id_from_symbol_and_entry_time(self):
        row = trade_to_row(FakeTrade(), symbol="MNQ")
        assert row["id"].startswith("MNQ_")

    def test_uses_explicit_id_when_provided(self):
        row = trade_to_row({
            "id": "custom_trade_001",
            "direction": "long",
            "entry_price": 100,
            "stop_price": 99,
            "target_price": 102,
            "contracts": 1,
            "confluence_score": 10,
            "entry_time": "2025-03-10T14:30:00+00:00",
        })
        assert row["id"] == "custom_trade_001"

    def test_status_defaults_from_exit_time(self):
        closed = trade_to_row(FakeTrade())
        assert closed["status"] == "closed"

        open_trade = FakeTrade(exit_time=None, pnl=None, exit_price=None)
        open_row = trade_to_row(open_trade)
        assert open_row["status"] == "open"

    def test_entry_time_is_iso_string(self):
        row = trade_to_row(FakeTrade())
        assert isinstance(row["entry_time"], str)
        assert "T" in row["entry_time"]  # ISO format


# ─── signal_to_row ───────────────────────────────────────────────────────

class TestSignalToRow:
    def test_derives_ict_concepts_from_flags(self):
        row = signal_to_row({
            "timestamp": "2025-03-10T14:30:00+00:00",
            "direction": "long",
            "price": 18000,
            "confluence_score": 12,
            "liquidity_grab": True,
            "fair_value_gap": True,
            "order_block": False,
            "market_structure": True,
        })
        assert set(row["ict_concepts"]) == {"liquidity_grab", "fair_value_gap", "market_structure"}

    def test_prefers_explicit_concepts_list(self):
        row = signal_to_row({
            "timestamp": "2025-03-10T14:30:00+00:00",
            "direction": "long",
            "price": 18000,
            "confluence_score": 12,
            "ict_concepts": ["FVG", "OB"],
            "liquidity_grab": False,  # Should be overridden by explicit list
        })
        assert row["ict_concepts"] == ["FVG", "OB"]

    def test_active_defaults_to_true(self):
        row = signal_to_row({
            "timestamp": "2025-03-10T14:30:00+00:00",
            "direction": "long",
            "price": 18000,
            "confluence_score": 12,
        })
        assert row["active"] is True


# ─── backtest_result_to_row ─────────────────────────────────────────────

class TestBacktestResultToRow:
    def test_basic_conversion(self):
        result = FakeBacktestResult(
            trades=[FakeTrade(pnl=100), FakeTrade(pnl=-50), FakeTrade(pnl=200)],
            daily_pnl={datetime(2025, 1, 1).date(): 100, datetime(2025, 1, 2).date(): -50, datetime(2025, 1, 3).date(): 200},
        )
        row = backtest_result_to_row(result, run_id="test_run_001")
        assert row["id"] == "test_run_001"
        assert row["strategy"] == "ny_am_reversal"
        assert row["total_trades"] == 5
        assert row["winning_trades"] == 3
        assert row["losing_trades"] == 2
        assert row["win_rate"] == 0.6

    def test_profit_factor_calculation(self):
        result = FakeBacktestResult(
            trades=[FakeTrade(pnl=200), FakeTrade(pnl=-50), FakeTrade(pnl=100)],
        )
        row = backtest_result_to_row(result, run_id="pf_test")
        # Gross wins: 300, gross loss: 50 → PF = 6.0
        assert row["profit_factor"] == 6.0

    def test_profit_factor_zero_when_no_losses(self):
        result = FakeBacktestResult(
            trades=[FakeTrade(pnl=100), FakeTrade(pnl=200)],
        )
        row = backtest_result_to_row(result, run_id="pf_zero_loss")
        # No gross loss → safe guard returns 0.0
        assert row["profit_factor"] == 0.0

    def test_auto_generates_id_when_missing(self):
        row = backtest_result_to_row(FakeBacktestResult())
        assert row["id"].startswith("ny_am_reversal_")

    def test_config_passthrough(self):
        row = backtest_result_to_row(
            FakeBacktestResult(),
            run_id="x",
            config={"min_confluence": 7, "risk": 250},
        )
        assert row["config"]["min_confluence"] == 7

    def test_dates_converted_to_yyyy_mm_dd(self):
        row = backtest_result_to_row(FakeBacktestResult(), run_id="x")
        assert row["start_date"] == "2025-01-01"
        assert row["end_date"] == "2025-03-31"


class TestDrawdownAndSharpe:
    def test_drawdown_empty(self):
        assert _compute_max_drawdown({}) == 0.0

    def test_drawdown_monotonic_up(self):
        # Pure up curve → no drawdown
        dd = _compute_max_drawdown({f"2025-01-{i:02d}": 100 for i in range(1, 6)})
        assert dd == 0.0

    def test_drawdown_peak_then_dip(self):
        dd = _compute_max_drawdown({
            "2025-01-01": 100,
            "2025-01-02": 100,  # Peak at 200
            "2025-01-03": -50,  # Down to 150 → 25% dd
        })
        assert dd == pytest.approx(0.25)

    def test_sharpe_zero_variance_returns_zero(self):
        # All equal daily returns → zero variance → safe zero
        result = _compute_sharpe({f"2025-01-{i:02d}": 50 for i in range(1, 6)})
        assert result == 0.0

    def test_sharpe_positive_for_good_strategy(self):
        # Upward drift with moderate variance
        result = _compute_sharpe({
            "2025-01-01": 100,
            "2025-01-02": 120,
            "2025-01-03": 80,
            "2025-01-04": 150,
            "2025-01-05": 110,
        })
        assert result > 0


# ─── candidate_record_to_row ────────────────────────────────────────────

@dataclass
class FakeCandidateRecord:
    id: str = "H-001"
    hypothesis: dict = field(default_factory=lambda: {
        "name": "FVG-inside-OB",
        "ict_reasoning": "OB + FVG confluence means double institutional backing.",
        "condition": "fvg.inside(ob)",
    })
    strategy_name: str = "ny_am_reversal"
    status: str = "passed"
    gates_passed: int = 9
    gates_total: int = 9
    score: int = 85
    gate_results: dict = field(default_factory=dict)
    session_id: str = "LAB-20250310"
    mode: str = "generate"
    created_at: str = "2025-03-10T14:30:00+00:00"
    approved_at: str = None
    approved_by: str = None
    sharpe_improvement: float = 0.15
    net_profit_delta: float = 500.0
    notes: str = None


class TestCandidateRecordToRow:
    def test_basic_conversion(self):
        row = candidate_record_to_row(FakeCandidateRecord())
        assert row["id"] == "H-001"
        assert row["strategy_name"] == "ny_am_reversal"
        assert row["status"] == "passed"
        assert row["gates_passed"] == 9
        assert row["score"] == 85

    def test_hypothesis_extracts_ict_reasoning(self):
        row = candidate_record_to_row(FakeCandidateRecord())
        assert "institutional" in row["hypothesis"]  # from ict_reasoning

    def test_sharpe_improvement_preserved(self):
        row = candidate_record_to_row(FakeCandidateRecord())
        assert row["sharpe_improvement"] == pytest.approx(0.15)

    def test_defaults_when_fields_missing(self):
        row = candidate_record_to_row({
            "id": "H-999",
            "strategy_name": "test",
            "hypothesis": {},
        })
        assert row["status"] == "pending"
        assert row["gates_total"] == 9
        assert row["score"] == 0


# ─── post_mortem_to_row ─────────────────────────────────────────────────

@dataclass
class FakePostMortem:
    category: str = "htf_misread"
    severity: str = "high"
    reason: str = "Entered against weekly bias"
    recommendation: str = "Skip trades when weekly bias diverges from daily"
    pnl: float = -250.0
    timestamp: str = "2025-03-10T15:00:00+00:00"


class TestPostMortemToRow:
    def test_basic_conversion(self):
        row = post_mortem_to_row(FakePostMortem(), trade_id="trade_001")
        assert row["trade_id"] == "trade_001"
        assert row["reason_category"] == "htf_misread"
        assert row["severity"] == "high"
        assert row["pnl"] == -250.0

    def test_invalid_category_maps_to_other(self):
        pm = FakePostMortem(category="made_up_category")
        row = post_mortem_to_row(pm, trade_id="t1")
        assert row["reason_category"] == "other"

    def test_invalid_severity_maps_to_medium(self):
        pm = FakePostMortem(severity="nuclear")
        row = post_mortem_to_row(pm, trade_id="t1")
        assert row["severity"] == "medium"

    def test_analysis_from_reason_field(self):
        row = post_mortem_to_row(FakePostMortem(), trade_id="t1")
        assert "weekly bias" in row["analysis"]

    def test_lesson_from_recommendation_field(self):
        row = post_mortem_to_row(FakePostMortem(), trade_id="t1")
        assert "Skip trades" in row["lesson"]

    def test_auto_id_includes_trade_id(self):
        row = post_mortem_to_row(FakePostMortem(), trade_id="MNQ_001")
        assert "MNQ_001" in row["id"]


# ─── normalize_bot_state ────────────────────────────────────────────────

class TestNormalizeBotState:
    def test_forces_id_to_bot_1(self):
        row = normalize_bot_state({"vpin": 0.5})
        assert row["id"] == "bot_1"

    def test_custom_bot_id(self):
        row = normalize_bot_state({"vpin": 0.5}, bot_id="bot_2")
        assert row["id"] == "bot_2"

    def test_invalid_toxicity_defaults_to_calm(self):
        row = normalize_bot_state({"toxicity_level": "nuclear"})
        assert row["toxicity_level"] == "calm"

    def test_valid_toxicity_passes_through(self):
        row = normalize_bot_state({"toxicity_level": "elevated"})
        assert row["toxicity_level"] == "elevated"

    def test_invalid_swc_mood_defaults_to_choppy(self):
        row = normalize_bot_state({"swc_mood": "euphoric"})
        assert row["swc_mood"] == "choppy"

    def test_invalid_gex_regime_defaults_to_unknown(self):
        row = normalize_bot_state({"gex_regime": "squeeze"})
        assert row["gex_regime"] == "unknown"

    def test_timestamps_converted_to_iso(self):
        row = normalize_bot_state({
            "last_heartbeat": datetime(2025, 3, 10, 14, 30, tzinfo=timezone.utc),
        })
        assert isinstance(row["last_heartbeat"], str)
        assert "2025-03-10" in row["last_heartbeat"]

    def test_updated_at_always_set(self):
        row = normalize_bot_state({})
        assert "updated_at" in row

    def test_rejects_non_dict(self):
        with pytest.raises(TypeError):
            normalize_bot_state("not a dict")  # type: ignore

    def test_passes_through_numeric_fields(self):
        row = normalize_bot_state({
            "vpin": 0.42,
            "pnl_today": 850.50,
            "wins_today": 3,
            "position_count": 1,
        })
        assert row["vpin"] == 0.42
        assert row["pnl_today"] == 850.50
        assert row["wins_today"] == 3
        assert row["position_count"] == 1
