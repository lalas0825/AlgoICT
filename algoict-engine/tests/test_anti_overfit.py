"""Tests for strategy_lab.anti_overfit_gates — verify each gate triggers correctly."""

from __future__ import annotations

import pytest

from strategy_lab.types import BacktestMetrics, GateResult, Hypothesis
from strategy_lab.anti_overfit_gates import (
    AntiOverfitGates,
    StageResults,
    MIN_SHARPE_IMPROVEMENT,
    MAX_WINRATE_DEGRADATION,
    MAX_DRAWDOWN_INCREASE,
    MIN_POSITIVE_WINDOWS,
    MIN_INSTRUMENTS_PASSING,
    MAX_NOISE_DEGRADATION,
    MAX_NEW_PARAMETERS,
    VALIDATION_MIN_IMPROVEMENT,
)
from strategy_lab.walk_forward import WalkForwardResult
from strategy_lab.cross_instrument import CrossInstrumentResult, InstrumentOutcome
from strategy_lab.stress_tester import StressTestResult, StressOutcome
from strategy_lab.occam_checker import OccamChecker


# ─── Helpers to build fake stage results ────────────────────────────────

def _metrics(sharpe=0.5, win_rate=0.55, max_dd=0.08, pnl=1000.0) -> BacktestMetrics:
    return BacktestMetrics(
        sharpe=sharpe,
        win_rate=win_rate,
        max_drawdown=max_dd,
        total_pnl=pnl,
        total_trades=100,
    )


def _hypothesis(params: int = 1, condition: str = "x > 5") -> Hypothesis:
    return Hypothesis(
        id="H-TEST",
        name="test hypothesis",
        ict_reasoning="ICT order flow creates mechanism...",
        condition=condition,
        parameters_added=params,
        expected_impact="win rate +3%",
        risk="might be overfitting",
    )


def _perfect_stage() -> StageResults:
    """Stage results where every gate should pass."""
    return StageResults(
        training_baseline=_metrics(sharpe=0.50, win_rate=0.55, max_dd=0.08),
        training_hypothesis=_metrics(sharpe=0.75, win_rate=0.56, max_dd=0.09),
        walk_forward=WalkForwardResult(
            windows_tested=10,
            windows_positive=8,
            positive_percentage=0.80,
            mean_improvement=0.15,
            median_improvement=0.12,
            passed=True,
        ),
        cross_instrument=CrossInstrumentResult(
            outcomes=[
                InstrumentOutcome("NQ", 0.5, 0.7, 0.2, True, 1000),
                InstrumentOutcome("ES", 0.5, 0.65, 0.15, True, 1000),
                InstrumentOutcome("YM", 0.5, 0.45, -0.05, False, 1000),
            ],
            instruments_passing=2,
            instruments_tested=3,
            passed=True,
        ),
        stress=StressTestResult(
            outcomes=[
                StressOutcome("noise", 0.75, 0.72, 0.04, True),
                StressOutcome("shift_fwd", 0.75, 0.70, 0.07, True),
                StressOutcome("shift_bwd", 0.75, 0.73, 0.03, True),
                StressOutcome("sparse", 0.75, 0.71, 0.05, True),
                StressOutcome("slippage", 0.75, 0.68, 0.09, True),
                StressOutcome("inversion", 0.75, -0.40, 1.5, True),
            ],
            max_degradation=0.09,
            inversion_loses=True,
            noise_resilience_passed=True,
            inversion_passed=True,
        ),
        validation_baseline=_metrics(sharpe=0.45),
        validation_hypothesis=_metrics(sharpe=0.60),
    )


# ─── Tests ──────────────────────────────────────────────────────────────

class TestAllGatesPass:
    def test_perfect_candidate_passes_all_9_gates(self):
        gates = AntiOverfitGates()
        hyp = _hypothesis(params=1, condition="entry.inside_ob == True")
        results = gates.run_all_gates(hyp, _perfect_stage())
        assert len(results) == 9
        assert all(r.passed for r in results), [
            (r.gate_name, r.reason) for r in results if not r.passed
        ]
        assert gates.all_passed(results)
        assert gates.passed_count(results) == 9

    def test_gate_names_are_in_order(self):
        gates = AntiOverfitGates()
        results = gates.run_all_gates(_hypothesis(), _perfect_stage())
        names = [r.gate_name for r in results]
        assert names == [
            "sharpe_improvement",
            "win_rate_delta",
            "drawdown_delta",
            "walk_forward_pct",
            "cross_instrument_count",
            "noise_resilience_pct",
            "inversion_loses",
            "occam_params",
            "validation_improves",
        ]


class TestGate1Sharpe:
    def test_fails_when_sharpe_barely_improves(self):
        stage = _perfect_stage()
        # Only +0.05 improvement vs 0.10 required
        stage.training_hypothesis = _metrics(sharpe=0.55)
        gates = AntiOverfitGates()
        r = gates._gate_1_sharpe(stage)
        assert not r.passed
        assert r.gate_name == "sharpe_improvement"

    def test_passes_at_exact_threshold(self):
        stage = _perfect_stage()
        stage.training_hypothesis = _metrics(sharpe=0.50 + MIN_SHARPE_IMPROVEMENT)
        gates = AntiOverfitGates()
        r = gates._gate_1_sharpe(stage)
        assert r.passed

    def test_fails_when_sharpe_gets_worse(self):
        stage = _perfect_stage()
        stage.training_hypothesis = _metrics(sharpe=0.40)
        gates = AntiOverfitGates()
        r = gates._gate_1_sharpe(stage)
        assert not r.passed

    def test_fails_when_metrics_missing(self):
        stage = StageResults()  # empty
        gates = AntiOverfitGates()
        r = gates._gate_1_sharpe(stage)
        assert not r.passed
        assert "not available" in r.reason


class TestGate2WinRate:
    def test_fails_when_winrate_drops_over_2pct(self):
        stage = _perfect_stage()
        stage.training_hypothesis = _metrics(win_rate=0.52)  # -3%
        gates = AntiOverfitGates()
        r = gates._gate_2_winrate(stage)
        assert not r.passed

    def test_passes_when_winrate_drops_less_than_2pct(self):
        stage = _perfect_stage()
        stage.training_hypothesis = _metrics(win_rate=0.54)  # -1%
        gates = AntiOverfitGates()
        r = gates._gate_2_winrate(stage)
        assert r.passed

    def test_passes_when_winrate_improves(self):
        stage = _perfect_stage()
        stage.training_hypothesis = _metrics(win_rate=0.60)  # +5%
        gates = AntiOverfitGates()
        r = gates._gate_2_winrate(stage)
        assert r.passed


class TestGate3Drawdown:
    def test_fails_when_drawdown_increases_over_10pct(self):
        stage = _perfect_stage()
        stage.training_hypothesis = _metrics(max_dd=0.20)  # +12% from 0.08
        gates = AntiOverfitGates()
        r = gates._gate_3_drawdown(stage)
        assert not r.passed

    def test_passes_when_drawdown_modestly_increases(self):
        stage = _perfect_stage()
        stage.training_hypothesis = _metrics(max_dd=0.12)  # +4%
        gates = AntiOverfitGates()
        r = gates._gate_3_drawdown(stage)
        assert r.passed


class TestGate4WalkForward:
    def test_fails_below_70pct_positive(self):
        stage = _perfect_stage()
        stage.walk_forward = WalkForwardResult(
            windows_tested=10,
            windows_positive=6,
            positive_percentage=0.60,
            mean_improvement=0.05,
            median_improvement=0.02,
            passed=False,
        )
        gates = AntiOverfitGates()
        r = gates._gate_4_walk_forward(stage)
        assert not r.passed

    def test_passes_at_exact_threshold(self):
        stage = _perfect_stage()
        stage.walk_forward = WalkForwardResult(
            windows_tested=10,
            windows_positive=7,
            positive_percentage=0.70,
            mean_improvement=0.05,
            median_improvement=0.02,
            passed=True,
        )
        gates = AntiOverfitGates()
        r = gates._gate_4_walk_forward(stage)
        assert r.passed


class TestGate5CrossInstrument:
    def test_fails_when_only_one_instrument_passes(self):
        stage = _perfect_stage()
        stage.cross_instrument = CrossInstrumentResult(
            outcomes=[
                InstrumentOutcome("NQ", 0.5, 0.7, 0.2, True, 1000),
                InstrumentOutcome("ES", 0.5, 0.45, -0.05, False, 1000),
                InstrumentOutcome("YM", 0.5, 0.40, -0.10, False, 1000),
            ],
            instruments_passing=1,
            instruments_tested=3,
            passed=False,
        )
        gates = AntiOverfitGates()
        r = gates._gate_5_cross_instrument(stage)
        assert not r.passed

    def test_passes_on_three_of_three(self):
        stage = _perfect_stage()
        stage.cross_instrument.instruments_passing = 3
        gates = AntiOverfitGates()
        r = gates._gate_5_cross_instrument(stage)
        assert r.passed


class TestGate6Noise:
    def test_fails_when_max_degradation_exceeds_30pct(self):
        stage = _perfect_stage()
        stage.stress = StressTestResult(
            outcomes=[],
            max_degradation=0.40,
            inversion_loses=True,
            noise_resilience_passed=False,
            inversion_passed=True,
        )
        gates = AntiOverfitGates()
        r = gates._gate_6_noise_resilience(stage)
        assert not r.passed


class TestGate7Inversion:
    def test_fails_when_inversion_profits(self):
        stage = _perfect_stage()
        stage.stress.inversion_loses = False
        stage.stress.inversion_passed = False
        gates = AntiOverfitGates()
        r = gates._gate_7_inversion(stage)
        assert not r.passed
        assert "random" in r.reason.lower()

    def test_passes_when_inversion_loses(self):
        stage = _perfect_stage()
        gates = AntiOverfitGates()
        r = gates._gate_7_inversion(stage)
        assert r.passed


class TestGate8Occam:
    def test_fails_when_declared_params_over_2(self):
        hyp = _hypothesis(params=5, condition="x > 5")
        gates = AntiOverfitGates()
        r = gates._gate_8_occam(hyp)
        assert not r.passed

    def test_passes_at_exact_limit(self):
        hyp = _hypothesis(params=MAX_NEW_PARAMETERS, condition="x > 0")
        gates = AntiOverfitGates()
        r = gates._gate_8_occam(hyp)
        assert r.passed

    def test_estimator_catches_underreport(self):
        """If LLM says 0 but condition has 3 numeric thresholds, fail."""
        hyp = Hypothesis(
            id="H-999",
            name="sneaky",
            ict_reasoning="...",
            condition="volume > 1000 AND atr > 2.5 AND streak < 3",
            parameters_added=0,  # lying!
            expected_impact="x",
            risk="y",
        )
        gates = AntiOverfitGates()
        r = gates._gate_8_occam(hyp)
        assert not r.passed


class TestGate9Validation:
    def test_fails_when_validation_barely_improves(self):
        stage = _perfect_stage()
        stage.validation_hypothesis = _metrics(sharpe=0.46)  # +0.01 vs 0.05 required
        gates = AntiOverfitGates()
        r = gates._gate_9_validation(stage)
        assert not r.passed

    def test_passes_at_threshold(self):
        stage = _perfect_stage()
        stage.validation_hypothesis = _metrics(sharpe=0.45 + VALIDATION_MIN_IMPROVEMENT)
        gates = AntiOverfitGates()
        r = gates._gate_9_validation(stage)
        assert r.passed

    def test_fails_when_validation_worsens(self):
        stage = _perfect_stage()
        stage.validation_hypothesis = _metrics(sharpe=0.30)
        gates = AntiOverfitGates()
        r = gates._gate_9_validation(stage)
        assert not r.passed


class TestAggregation:
    def test_one_failure_prevents_all_passed(self):
        stage = _perfect_stage()
        stage.training_hypothesis = _metrics(sharpe=0.40)  # Gate 1 fails
        gates = AntiOverfitGates()
        results = gates.run_all_gates(_hypothesis(), stage)
        assert not gates.all_passed(results)
        assert gates.passed_count(results) == 8

    def test_all_gates_evaluated_even_when_some_fail(self):
        """Gates should not short-circuit — caller needs full picture."""
        stage = StageResults()  # completely empty
        gates = AntiOverfitGates()
        results = gates.run_all_gates(_hypothesis(), stage)
        assert len(results) == 9
        # Gate 8 (occam) still runs since hypothesis is always provided
        occam = next(r for r in results if r.gate_name == "occam_params")
        assert occam.passed  # Default hypothesis has 1 param

    def test_empty_stage_fails_data_dependent_gates(self):
        stage = StageResults()
        gates = AntiOverfitGates()
        results = gates.run_all_gates(_hypothesis(), stage)
        data_gates = [
            r for r in results
            if r.gate_name != "occam_params"
        ]
        assert all(not r.passed for r in data_gates)
