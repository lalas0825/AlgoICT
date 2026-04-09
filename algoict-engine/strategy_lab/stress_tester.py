"""
strategy_lab/stress_tester.py
==============================
Intentionally break the strategy to see if the edge survives.

Five stress tests
-----------------
1. **noise**      — add Gaussian noise (±0.1%) to OHLC prices
2. **shift_fwd**  — shift all bars forward by 1 (timing sensitivity)
3. **shift_bwd**  — shift all bars backward by 1
4. **sparse**     — randomly drop 10% of bars (data gap simulation)
5. **slippage**   — stress with doubled spread cost
6. **inversion**  — flip long↔short signals; the result MUST lose money

Gate 6 (noise resilience) — the first 5 tests must degrade Sharpe by less
than 30% vs baseline. Gate 7 (inversion) — the inversion test must produce
a worse-than-baseline Sharpe; if inversion also wins, the strategy was
directionally random.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .types import BacktestMetrics, BacktestRunner

logger = logging.getLogger(__name__)


# ─── Defaults ────────────────────────────────────────────────────────────

DEFAULT_NOISE_STD = 0.001        # 0.1% price noise
DEFAULT_REMOVE_PCT = 0.10        # drop 10% of bars
DEFAULT_SLIPPAGE_MULT = 2.0      # double spread cost
DEFAULT_MAX_DEGRADATION = 0.30   # Gate 6 threshold
DEFAULT_RANDOM_SEED = 42         # reproducible stress runs


# ─── Result containers ──────────────────────────────────────────────────

@dataclass
class StressOutcome:
    """Result of one stress test."""
    name: str
    baseline_sharpe: float
    stressed_sharpe: float
    degradation: float       # (baseline - stressed) / |baseline|  (fraction)
    passed: bool
    notes: str = ""


@dataclass
class StressTestResult:
    """Aggregate result of all 6 stress tests."""
    outcomes: list[StressOutcome] = field(default_factory=list)
    max_degradation: float = 0.0
    inversion_loses: bool = False
    noise_resilience_passed: bool = False  # Gate 6
    inversion_passed: bool = False          # Gate 7

    def summary(self) -> str:
        lines = ["StressTestResult:"]
        for o in self.outcomes:
            mark = "✅" if o.passed else "❌"
            lines.append(
                f"  {mark} {o.name:<12} baseline={o.baseline_sharpe:+.2f} "
                f"stressed={o.stressed_sharpe:+.2f} "
                f"deg={o.degradation:+.0%}"
            )
        lines.append(
            f"  Gate 6 (noise): {'✅' if self.noise_resilience_passed else '❌'}"
        )
        lines.append(
            f"  Gate 7 (inversion loses): {'✅' if self.inversion_passed else '❌'}"
        )
        return "\n".join(lines)


# ─── Stress Tester ──────────────────────────────────────────────────────

class StressTester:
    """
    Runs a suite of stress perturbations against a baseline and the
    hypothesis version. Produces a full degradation report.

    Parameters
    ----------
    runner : BacktestRunner
        Strategy-agnostic backtest callable.
    noise_std : float
        Gaussian noise standard deviation as fraction of price (0.001 = 0.1%).
    remove_pct : float
        Fraction of bars to drop for the sparse test (0.0–1.0).
    slippage_mult : float
        Slippage multiplier applied via ``hypothesis_config['slippage_mult']``.
        Runner is free to interpret this or ignore — we compare Sharpe regardless.
    max_degradation : float
        Gate 6 threshold: if any resilience test degrades Sharpe by more
        than this fraction, the hypothesis fails.
    random_seed : int
        Seed for noise + bar removal (reproducibility).
    """

    def __init__(
        self,
        runner: BacktestRunner,
        noise_std: float = DEFAULT_NOISE_STD,
        remove_pct: float = DEFAULT_REMOVE_PCT,
        slippage_mult: float = DEFAULT_SLIPPAGE_MULT,
        max_degradation: float = DEFAULT_MAX_DEGRADATION,
        random_seed: int = DEFAULT_RANDOM_SEED,
    ):
        if not 0.0 <= remove_pct < 1.0:
            raise ValueError("remove_pct must be in [0, 1)")
        if noise_std < 0:
            raise ValueError("noise_std must be non-negative")
        self.runner = runner
        self.noise_std = noise_std
        self.remove_pct = remove_pct
        self.slippage_mult = slippage_mult
        self.max_degradation = max_degradation
        self.rng = np.random.default_rng(random_seed)

    # ─── Public API ──────────────────────────────────────────────────────

    def run_all_tests(
        self,
        data: pd.DataFrame,
        hypothesis_config: Optional[dict] = None,
    ) -> StressTestResult:
        """
        Run all 6 stress tests against a reference baseline (the hypothesis
        running on clean data) and aggregate the outcomes.
        """
        # Baseline = hypothesis on unstressed data — we measure how much
        # perturbation degrades vs this reference.
        baseline = self.runner(
            data, use_hypothesis=True, hypothesis_config=hypothesis_config
        )
        baseline_sharpe = baseline.sharpe

        outcomes: list[StressOutcome] = []

        # 1. Gaussian noise
        noisy = self._add_price_noise(data, self.noise_std)
        outcomes.append(
            self._run_compare("noise", noisy, baseline_sharpe, hypothesis_config)
        )

        # 2. Shift forward
        shifted_fwd = self._shift_bars(data, 1)
        outcomes.append(
            self._run_compare("shift_fwd", shifted_fwd, baseline_sharpe, hypothesis_config)
        )

        # 3. Shift backward
        shifted_bwd = self._shift_bars(data, -1)
        outcomes.append(
            self._run_compare("shift_bwd", shifted_bwd, baseline_sharpe, hypothesis_config)
        )

        # 4. Sparse (remove random bars)
        sparse = self._remove_random(data, self.remove_pct)
        outcomes.append(
            self._run_compare("sparse", sparse, baseline_sharpe, hypothesis_config)
        )

        # 5. Slippage — pass a modified hypothesis_config
        slip_config = dict(hypothesis_config or {})
        slip_config["slippage_mult"] = self.slippage_mult
        slip_metrics = self.runner(
            data, use_hypothesis=True, hypothesis_config=slip_config
        )
        outcomes.append(
            self._outcome_from_metrics(
                "slippage", baseline_sharpe, slip_metrics.sharpe
            )
        )

        # 6. Inversion — expected to LOSE (Gate 7). Don't mark degradation pass/fail normally.
        inv_config = dict(hypothesis_config or {})
        inv_config["invert_signals"] = True
        inv_metrics = self.runner(
            data, use_hypothesis=True, hypothesis_config=inv_config
        )
        inversion_loses = inv_metrics.sharpe < baseline_sharpe
        outcomes.append(
            StressOutcome(
                name="inversion",
                baseline_sharpe=baseline_sharpe,
                stressed_sharpe=inv_metrics.sharpe,
                degradation=self._safe_degradation(baseline_sharpe, inv_metrics.sharpe),
                passed=inversion_loses,
                notes=(
                    "Inversion should lose vs baseline — confirms directionality"
                    if inversion_loses
                    else "FAIL: inverted strategy also profits — edge is random"
                ),
            )
        )

        # Aggregate: resilience tests are the 5 non-inversion outcomes
        resilience = [o for o in outcomes if o.name != "inversion"]
        max_deg = max((o.degradation for o in resilience), default=0.0)
        noise_ok = all(o.passed for o in resilience)

        return StressTestResult(
            outcomes=outcomes,
            max_degradation=max_deg,
            inversion_loses=inversion_loses,
            noise_resilience_passed=noise_ok,
            inversion_passed=inversion_loses,
        )

    # ─── Perturbations ───────────────────────────────────────────────────

    def _add_price_noise(self, data: pd.DataFrame, std: float) -> pd.DataFrame:
        """
        Multiplicative Gaussian noise on OHLC. Volume is untouched.
        high/low are recomputed so OHLC invariants hold.
        """
        if data.empty:
            return data
        noisy = data.copy()
        cols = [c for c in ("open", "high", "low", "close") if c in noisy.columns]
        if not cols:
            return noisy
        shape = (len(noisy), len(cols))
        factor = 1.0 + self.rng.normal(0.0, std, size=shape)
        noisy[cols] = noisy[cols].values * factor
        # Re-establish OHLC invariants (high >= max(o,c), low <= min(o,c))
        if {"open", "high", "low", "close"}.issubset(noisy.columns):
            o = noisy["open"].values
            c = noisy["close"].values
            noisy["high"] = np.maximum(noisy["high"].values, np.maximum(o, c))
            noisy["low"] = np.minimum(noisy["low"].values, np.minimum(o, c))
        return noisy

    def _shift_bars(self, data: pd.DataFrame, offset: int) -> pd.DataFrame:
        """
        Shift OHLCV values by ``offset`` bars while keeping the original index.
        Edge rows that would read out of range are dropped.
        """
        if data.empty or offset == 0:
            return data
        shifted = data.copy()
        numeric = shifted.select_dtypes(include=[np.number]).columns
        shifted[numeric] = shifted[numeric].shift(offset)
        return shifted.dropna()

    def _remove_random(self, data: pd.DataFrame, pct: float) -> pd.DataFrame:
        """Drop ``pct`` of random bars, preserving original row order."""
        if data.empty or pct <= 0:
            return data
        n = len(data)
        drop_n = int(n * pct)
        if drop_n == 0:
            return data
        keep_mask = np.ones(n, dtype=bool)
        drop_idx = self.rng.choice(n, size=drop_n, replace=False)
        keep_mask[drop_idx] = False
        return data.iloc[keep_mask].copy()

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _run_compare(
        self,
        name: str,
        perturbed: pd.DataFrame,
        baseline_sharpe: float,
        hypothesis_config: Optional[dict],
    ) -> StressOutcome:
        metrics = self.runner(
            perturbed, use_hypothesis=True, hypothesis_config=hypothesis_config
        )
        return self._outcome_from_metrics(name, baseline_sharpe, metrics.sharpe)

    def _outcome_from_metrics(
        self,
        name: str,
        baseline_sharpe: float,
        stressed_sharpe: float,
    ) -> StressOutcome:
        deg = self._safe_degradation(baseline_sharpe, stressed_sharpe)
        passed = deg <= self.max_degradation
        return StressOutcome(
            name=name,
            baseline_sharpe=baseline_sharpe,
            stressed_sharpe=stressed_sharpe,
            degradation=deg,
            passed=passed,
        )

    @staticmethod
    def _safe_degradation(baseline: float, stressed: float) -> float:
        """
        Relative degradation = (baseline - stressed) / |baseline|.

        Positive = worse under stress; negative = actually improved.
        Guarded against baseline≈0 to avoid blow-ups.
        """
        if abs(baseline) < 1e-9:
            # If baseline Sharpe is basically zero, any drop is "infinite".
            # Collapse to a sentinel so downstream math stays sane.
            return 10.0 if stressed < baseline else 0.0
        return (baseline - stressed) / abs(baseline)
