"""
strategy_lab/walk_forward.py
=============================
Rolling-window walk-forward validation inside the Training Set.

Why this exists
---------------
A hypothesis can look great across the full 2019–2022 Training Set and
still be *temporal overfitting* — it happened to work during specific
volatility regimes. Walk-forward chops the training period into 6-month
"train" windows and 2-month "test" windows that step forward, and asks:
**does the hypothesis still improve the metric in at least 70% of the
held-out test slices?**

Windowing
---------
    train_months = 6
    test_months  = 2
    step_months  = 2

    Window 1: train Jan–Jun 2019 → test Jul–Aug 2019
    Window 2: train Mar–Aug 2019 → test Sep–Oct 2019
    Window 3: train May–Oct 2019 → test Nov–Dec 2019
    ...

Gate 4 — passes if ``positive_percentage >= 0.70``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .types import BacktestMetrics, BacktestRunner

logger = logging.getLogger(__name__)


# ─── Configuration ───────────────────────────────────────────────────────

DEFAULT_TRAIN_MONTHS = 6
DEFAULT_TEST_MONTHS = 2
DEFAULT_STEP_MONTHS = 2

# Gate 4 threshold — see anti_overfit_gates.py
MIN_POSITIVE_WINDOW_PCT = 0.70


@dataclass
class Window:
    """One rolling train/test window."""
    index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp

    def __repr__(self) -> str:
        return (
            f"Window#{self.index}("
            f"train {self.train_start.date()}→{self.train_end.date()}, "
            f"test {self.test_start.date()}→{self.test_end.date()})"
        )


@dataclass
class WindowOutcome:
    """Result of evaluating one window."""
    window: Window
    baseline_sharpe: float
    hypothesis_sharpe: float
    improvement: float
    positive: bool  # True if hypothesis_sharpe > baseline_sharpe


@dataclass
class WalkForwardResult:
    """Aggregate result across all windows."""
    windows_tested: int
    windows_positive: int
    positive_percentage: float
    mean_improvement: float
    median_improvement: float
    passed: bool
    outcomes: list[WindowOutcome] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"WalkForwardResult(\n"
            f"  windows      = {self.windows_tested}\n"
            f"  positive     = {self.windows_positive} "
            f"({self.positive_percentage:.0%})\n"
            f"  mean Δsharpe = {self.mean_improvement:+.3f}\n"
            f"  median       = {self.median_improvement:+.3f}\n"
            f"  passed       = {'✅' if self.passed else '❌'}\n"
            f")"
        )


class WalkForwardValidator:
    """
    Generates rolling windows from training data and evaluates a
    hypothesis against its baseline on each held-out slice.

    Parameters
    ----------
    runner : BacktestRunner
        Callable that runs a backtest on a data slice and returns metrics.
        Signature: ``runner(data, use_hypothesis, hypothesis_config) -> BacktestMetrics``
    train_months : int
        Length of each train slice in months (default 6).
    test_months : int
        Length of each held-out test slice in months (default 2).
    step_months : int
        How far to advance between windows (default 2).
    min_positive_pct : float
        Gate 4 threshold — fraction of windows that must improve.
    """

    def __init__(
        self,
        runner: BacktestRunner,
        train_months: int = DEFAULT_TRAIN_MONTHS,
        test_months: int = DEFAULT_TEST_MONTHS,
        step_months: int = DEFAULT_STEP_MONTHS,
        min_positive_pct: float = MIN_POSITIVE_WINDOW_PCT,
    ):
        if train_months <= 0 or test_months <= 0 or step_months <= 0:
            raise ValueError("All month parameters must be positive.")
        self.runner = runner
        self.train_months = train_months
        self.test_months = test_months
        self.step_months = step_months
        self.min_positive_pct = min_positive_pct

    # ─── Public API ──────────────────────────────────────────────────────

    def generate_windows(self, training_data: pd.DataFrame) -> list[Window]:
        """
        Build rolling windows covering the training period.

        The last window is included even if the test slice is truncated
        at the end of the training range.
        """
        if training_data.empty:
            return []
        if not isinstance(training_data.index, pd.DatetimeIndex):
            raise TypeError("training_data must have a DatetimeIndex")

        start = training_data.index[0].normalize()
        end = training_data.index[-1].normalize()

        windows: list[Window] = []
        cursor = start
        idx = 0
        train_delta = pd.DateOffset(months=self.train_months)
        test_delta = pd.DateOffset(months=self.test_months)
        step_delta = pd.DateOffset(months=self.step_months)

        while True:
            train_start = cursor
            train_end = train_start + train_delta
            test_start = train_end
            test_end = test_start + test_delta

            if train_end > end:
                # No room left for a meaningful train window
                break

            # Clamp test window at data boundary
            if test_end > end:
                test_end = end + pd.Timedelta(seconds=1)

            windows.append(
                Window(
                    index=idx,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )

            if test_end > end:
                break

            cursor = cursor + step_delta
            idx += 1

        return windows

    def validate(
        self,
        training_data: pd.DataFrame,
        hypothesis_config: Optional[dict] = None,
    ) -> WalkForwardResult:
        """
        Run the hypothesis across all rolling windows and aggregate.

        For each window:
          baseline       = runner(test_slice, use_hypothesis=False)
          with_hypothesis = runner(test_slice, use_hypothesis=True, config=...)
          positive       = with_hypothesis.sharpe > baseline.sharpe
        """
        windows = self.generate_windows(training_data)
        if not windows:
            logger.warning("WalkForward: no windows generated from %d bars", len(training_data))
            return WalkForwardResult(
                windows_tested=0,
                windows_positive=0,
                positive_percentage=0.0,
                mean_improvement=0.0,
                median_improvement=0.0,
                passed=False,
            )

        outcomes: list[WindowOutcome] = []
        for w in windows:
            test_slice = training_data[
                (training_data.index >= w.test_start)
                & (training_data.index < w.test_end)
            ]
            if test_slice.empty:
                logger.debug("Window %d test slice empty — skipping", w.index)
                continue

            baseline = self.runner(
                test_slice, use_hypothesis=False, hypothesis_config=None
            )
            with_hyp = self.runner(
                test_slice,
                use_hypothesis=True,
                hypothesis_config=hypothesis_config,
            )

            improvement = with_hyp.sharpe - baseline.sharpe
            outcomes.append(
                WindowOutcome(
                    window=w,
                    baseline_sharpe=baseline.sharpe,
                    hypothesis_sharpe=with_hyp.sharpe,
                    improvement=improvement,
                    positive=with_hyp.sharpe > baseline.sharpe,
                )
            )

        if not outcomes:
            return WalkForwardResult(
                windows_tested=0,
                windows_positive=0,
                positive_percentage=0.0,
                mean_improvement=0.0,
                median_improvement=0.0,
                passed=False,
            )

        positive = sum(1 for o in outcomes if o.positive)
        pct = positive / len(outcomes)
        improvements = [o.improvement for o in outcomes]
        mean_imp = sum(improvements) / len(improvements)
        sorted_imp = sorted(improvements)
        mid = len(sorted_imp) // 2
        median_imp = (
            sorted_imp[mid]
            if len(sorted_imp) % 2 == 1
            else (sorted_imp[mid - 1] + sorted_imp[mid]) / 2
        )

        return WalkForwardResult(
            windows_tested=len(outcomes),
            windows_positive=positive,
            positive_percentage=pct,
            mean_improvement=mean_imp,
            median_improvement=median_imp,
            passed=pct >= self.min_positive_pct,
            outcomes=outcomes,
        )
