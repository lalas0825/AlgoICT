"""
strategy_lab/anti_overfit_gates.py
===================================
The 9 anti-overfit gates consolidated into one evaluator.

Each gate is designed to catch a specific class of false positive:

| Gate | Stage              | Metric                     | Threshold        |
|------|--------------------|-----------------------------|------------------|
|  1   | Training           | Sharpe improvement         | ≥ +0.10          |
|  2   | Training           | Win-rate degradation       | ≤ 2% drop        |
|  3   | Training           | Max drawdown increase      | ≤ +10%           |
|  4   | Walk-forward       | Positive windows %         | ≥ 70%            |
|  5   | Cross-instrument   | Instruments passing        | ≥ 2 of 3         |
|  6   | Stress test        | Max degradation            | ≤ 30%            |
|  7   | Stress test        | Inversion must lose        | strict           |
|  8   | Occam's Razor      | New parameters added       | ≤ 2              |
|  9   | Validation (2023)  | Sharpe improvement         | ≥ +0.05          |

A hypothesis becomes a **candidate** only when ALL 9 gates pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .types import BacktestMetrics, GateResult, Hypothesis
from .walk_forward import WalkForwardResult
from .cross_instrument import CrossInstrumentResult
from .stress_tester import StressTestResult
from .occam_checker import OccamChecker

logger = logging.getLogger(__name__)


# ─── Thresholds (single source of truth) ────────────────────────────────

MIN_SHARPE_IMPROVEMENT = 0.10       # Gate 1
MAX_WINRATE_DEGRADATION = 0.02      # Gate 2 (2% absolute drop)
MAX_DRAWDOWN_INCREASE = 0.10        # Gate 3 (10% absolute)
MIN_POSITIVE_WINDOWS = 0.70         # Gate 4
MIN_INSTRUMENTS_PASSING = 2         # Gate 5
MAX_NOISE_DEGRADATION = 0.30        # Gate 6
INVERSION_MUST_LOSE = True          # Gate 7
MAX_NEW_PARAMETERS = 2              # Gate 8
VALIDATION_MIN_IMPROVEMENT = 0.05   # Gate 9

# Tolerance for float comparisons at threshold boundaries
# (0.5 + 0.1 - 0.5 = 0.09999… in IEEE 754 — we treat exact-threshold as pass)
_EPS = 1e-9


@dataclass
class StageResults:
    """
    Collected inputs from each pipeline stage. Populate whatever is available;
    any gate whose inputs are missing is recorded as FAILED with a clear reason.
    """
    # Gate 1–3: full training-set run
    training_baseline: Optional[BacktestMetrics] = None
    training_hypothesis: Optional[BacktestMetrics] = None
    # Gate 4
    walk_forward: Optional[WalkForwardResult] = None
    # Gate 5
    cross_instrument: Optional[CrossInstrumentResult] = None
    # Gate 6–7
    stress: Optional[StressTestResult] = None
    # Gate 9: validation set (2023) run
    validation_baseline: Optional[BacktestMetrics] = None
    validation_hypothesis: Optional[BacktestMetrics] = None


class AntiOverfitGates:
    """
    Runs the 9 gates against a bundle of stage results. Returns an ordered
    list of GateResult objects so the caller can report which stage failed.
    """

    def __init__(self, occam: Optional[OccamChecker] = None):
        self.occam = occam or OccamChecker(MAX_NEW_PARAMETERS)

    # ─── Public API ──────────────────────────────────────────────────────

    def run_all_gates(
        self,
        hypothesis: Hypothesis,
        results: StageResults,
    ) -> list[GateResult]:
        """
        Execute all 9 gates in order. Always returns exactly 9 GateResults.

        Gates are independent — a failure does not short-circuit the rest.
        This matches the dashboard's need to show WHICH gates failed.
        """
        gates: list[GateResult] = [
            self._gate_1_sharpe(results),
            self._gate_2_winrate(results),
            self._gate_3_drawdown(results),
            self._gate_4_walk_forward(results),
            self._gate_5_cross_instrument(results),
            self._gate_6_noise_resilience(results),
            self._gate_7_inversion(results),
            self._gate_8_occam(hypothesis),
            self._gate_9_validation(results),
        ]
        return gates

    @staticmethod
    def all_passed(gates: list[GateResult]) -> bool:
        return len(gates) > 0 and all(g.passed for g in gates)

    @staticmethod
    def passed_count(gates: list[GateResult]) -> int:
        return sum(1 for g in gates if g.passed)

    # ─── Individual gates ────────────────────────────────────────────────

    def _gate_1_sharpe(self, r: StageResults) -> GateResult:
        """Gate 1: Sharpe improvement on training set."""
        if r.training_baseline is None or r.training_hypothesis is None:
            return GateResult(
                gate_name="sharpe_improvement",
                passed=False,
                metric=0.0,
                threshold=MIN_SHARPE_IMPROVEMENT,
                reason="training metrics not available",
            )
        delta = r.training_hypothesis.sharpe - r.training_baseline.sharpe
        passed = delta >= MIN_SHARPE_IMPROVEMENT - _EPS
        return GateResult(
            gate_name="sharpe_improvement",
            passed=passed,
            metric=delta,
            threshold=MIN_SHARPE_IMPROVEMENT,
            reason=(
                f"Sharpe Δ={delta:+.3f} vs required {MIN_SHARPE_IMPROVEMENT:+.2f}"
            ),
        )

    def _gate_2_winrate(self, r: StageResults) -> GateResult:
        """Gate 2: Win rate must not drop more than 2 percentage points."""
        if r.training_baseline is None or r.training_hypothesis is None:
            return GateResult(
                gate_name="win_rate_delta",
                passed=False,
                metric=0.0,
                threshold=-MAX_WINRATE_DEGRADATION,
                reason="training metrics not available",
            )
        delta = r.training_hypothesis.win_rate - r.training_baseline.win_rate
        passed = delta >= -MAX_WINRATE_DEGRADATION - _EPS
        return GateResult(
            gate_name="win_rate_delta",
            passed=passed,
            metric=delta,
            threshold=-MAX_WINRATE_DEGRADATION,
            reason=(
                f"Win rate Δ={delta:+.2%} vs max drop {MAX_WINRATE_DEGRADATION:.2%}"
            ),
        )

    def _gate_3_drawdown(self, r: StageResults) -> GateResult:
        """Gate 3: Drawdown must not increase by more than 10 percentage points."""
        if r.training_baseline is None or r.training_hypothesis is None:
            return GateResult(
                gate_name="drawdown_delta",
                passed=False,
                metric=0.0,
                threshold=MAX_DRAWDOWN_INCREASE,
                reason="training metrics not available",
            )
        delta = r.training_hypothesis.max_drawdown - r.training_baseline.max_drawdown
        passed = delta <= MAX_DRAWDOWN_INCREASE + _EPS
        return GateResult(
            gate_name="drawdown_delta",
            passed=passed,
            metric=delta,
            threshold=MAX_DRAWDOWN_INCREASE,
            reason=(
                f"Drawdown Δ={delta:+.2%} vs max increase {MAX_DRAWDOWN_INCREASE:.2%}"
            ),
        )

    def _gate_4_walk_forward(self, r: StageResults) -> GateResult:
        """Gate 4: ≥70% of walk-forward windows must be positive."""
        if r.walk_forward is None:
            return GateResult(
                gate_name="walk_forward_pct",
                passed=False,
                metric=0.0,
                threshold=MIN_POSITIVE_WINDOWS,
                reason="walk-forward not executed",
            )
        pct = r.walk_forward.positive_percentage
        passed = pct >= MIN_POSITIVE_WINDOWS - _EPS
        return GateResult(
            gate_name="walk_forward_pct",
            passed=passed,
            metric=pct,
            threshold=MIN_POSITIVE_WINDOWS,
            reason=(
                f"{r.walk_forward.windows_positive}/{r.walk_forward.windows_tested} "
                f"windows positive ({pct:.0%})"
            ),
        )

    def _gate_5_cross_instrument(self, r: StageResults) -> GateResult:
        """Gate 5: pass on ≥2 of 3 instruments (NQ, ES, YM)."""
        if r.cross_instrument is None:
            return GateResult(
                gate_name="cross_instrument_count",
                passed=False,
                metric=0.0,
                threshold=MIN_INSTRUMENTS_PASSING,
                reason="cross-instrument not executed",
            )
        passing = r.cross_instrument.instruments_passing
        passed = passing >= MIN_INSTRUMENTS_PASSING
        return GateResult(
            gate_name="cross_instrument_count",
            passed=passed,
            metric=float(passing),
            threshold=float(MIN_INSTRUMENTS_PASSING),
            reason=(
                f"{passing}/{r.cross_instrument.instruments_tested} instruments improved"
            ),
        )

    def _gate_6_noise_resilience(self, r: StageResults) -> GateResult:
        """Gate 6: all resilience tests degrade Sharpe by ≤30%."""
        if r.stress is None:
            return GateResult(
                gate_name="noise_resilience_pct",
                passed=False,
                metric=1.0,
                threshold=MAX_NOISE_DEGRADATION,
                reason="stress tests not executed",
            )
        max_deg = r.stress.max_degradation
        passed = r.stress.noise_resilience_passed
        return GateResult(
            gate_name="noise_resilience_pct",
            passed=passed,
            metric=max_deg,
            threshold=MAX_NOISE_DEGRADATION,
            reason=(
                f"max degradation {max_deg:.0%} vs limit {MAX_NOISE_DEGRADATION:.0%}"
            ),
        )

    def _gate_7_inversion(self, r: StageResults) -> GateResult:
        """Gate 7: inverted strategy must produce worse-than-baseline Sharpe."""
        if r.stress is None:
            return GateResult(
                gate_name="inversion_loses",
                passed=False,
                metric=0.0,
                threshold=1.0,
                reason="stress tests not executed",
            )
        passed = r.stress.inversion_loses
        return GateResult(
            gate_name="inversion_loses",
            passed=passed,
            metric=1.0 if passed else 0.0,
            threshold=1.0,
            reason=(
                "Inverted strategy loses (direction is real)"
                if passed
                else "Inverted strategy also profits — directionality is random"
            ),
        )

    def _gate_8_occam(self, hypothesis: Hypothesis) -> GateResult:
        """Gate 8: max 2 new parameters."""
        result = self.occam.check(hypothesis)
        return GateResult(
            gate_name="occam_params",
            passed=result.passed,
            metric=float(result.effective_params),
            threshold=float(result.max_allowed),
            reason=result.reason,
        )

    def _gate_9_validation(self, r: StageResults) -> GateResult:
        """Gate 9: validation set (2023) Sharpe improvement."""
        if r.validation_baseline is None or r.validation_hypothesis is None:
            return GateResult(
                gate_name="validation_improves",
                passed=False,
                metric=0.0,
                threshold=VALIDATION_MIN_IMPROVEMENT,
                reason="validation not executed",
            )
        delta = r.validation_hypothesis.sharpe - r.validation_baseline.sharpe
        passed = delta >= VALIDATION_MIN_IMPROVEMENT - _EPS
        return GateResult(
            gate_name="validation_improves",
            passed=passed,
            metric=delta,
            threshold=VALIDATION_MIN_IMPROVEMENT,
            reason=(
                f"Validation Sharpe Δ={delta:+.3f} "
                f"vs required {VALIDATION_MIN_IMPROVEMENT:+.2f}"
            ),
        )
