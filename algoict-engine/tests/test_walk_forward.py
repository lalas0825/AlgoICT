"""Tests for strategy_lab.walk_forward."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import pytest

from strategy_lab.types import BacktestMetrics
from strategy_lab.walk_forward import (
    WalkForwardValidator,
    Window,
    DEFAULT_TRAIN_MONTHS,
    DEFAULT_TEST_MONTHS,
    DEFAULT_STEP_MONTHS,
    MIN_POSITIVE_WINDOW_PCT,
)


# ─── Fixtures ───────────────────────────────────────────────────────────

def _daily_data(start: str = "2019-01-01", months: int = 24) -> pd.DataFrame:
    """Daily bars covering ``months`` months of data."""
    end = pd.Timestamp(start) + pd.DateOffset(months=months) - pd.Timedelta(days=1)
    idx = pd.date_range(start=start, end=end, freq="D", tz="US/Central")
    return pd.DataFrame(
        {
            "open": [100.0] * len(idx),
            "high": [101.0] * len(idx),
            "low": [99.0] * len(idx),
            "close": [100.5] * len(idx),
            "volume": [1000] * len(idx),
        },
        index=idx,
    )


@dataclass
class StubRunner:
    """
    Deterministic runner for tests.

    ``hypothesis_sharpe`` and ``baseline_sharpe`` can be:
      * a single float  → used for every call
      * a callable(data) → computed per window
    """
    baseline_sharpe: float = 0.5
    hypothesis_sharpe: float = 0.7

    def __call__(
        self,
        data: pd.DataFrame,
        *,
        use_hypothesis: bool,
        hypothesis_config: Optional[dict] = None,
    ) -> BacktestMetrics:
        val = self.hypothesis_sharpe if use_hypothesis else self.baseline_sharpe
        if callable(val):
            val = val(data)
        return BacktestMetrics(
            sharpe=val,
            win_rate=0.55,
            max_drawdown=0.08,
            total_pnl=1000.0 * val,
            total_trades=100,
        )


# ─── Construction ───────────────────────────────────────────────────────

class TestConstruction:
    def test_rejects_zero_months(self):
        with pytest.raises(ValueError):
            WalkForwardValidator(StubRunner(), train_months=0)

    def test_rejects_negative_step(self):
        with pytest.raises(ValueError):
            WalkForwardValidator(StubRunner(), step_months=-1)

    def test_defaults_match_spec(self):
        wf = WalkForwardValidator(StubRunner())
        assert wf.train_months == DEFAULT_TRAIN_MONTHS
        assert wf.test_months == DEFAULT_TEST_MONTHS
        assert wf.step_months == DEFAULT_STEP_MONTHS
        assert wf.min_positive_pct == MIN_POSITIVE_WINDOW_PCT


# ─── Window generation ─────────────────────────────────────────────────

class TestWindowGeneration:
    def test_empty_data_returns_empty(self):
        wf = WalkForwardValidator(StubRunner())
        windows = wf.generate_windows(pd.DataFrame())
        assert windows == []

    def test_requires_datetime_index(self):
        wf = WalkForwardValidator(StubRunner())
        df = pd.DataFrame({"close": [1, 2, 3]})
        with pytest.raises(TypeError):
            wf.generate_windows(df)

    def test_generates_expected_number_of_windows(self):
        # 24 months, train=6, test=2, step=2
        # Windows: train [0-6] test [6-8], step 2 → train [2-8] test [8-10] …
        # Last train window must end by month 24
        data = _daily_data(months=24)
        wf = WalkForwardValidator(StubRunner())
        windows = wf.generate_windows(data)
        assert len(windows) >= 8  # At least 8 rolling windows in 24 months

    def test_windows_are_ordered_and_step_correctly(self):
        data = _daily_data(months=18)
        wf = WalkForwardValidator(
            StubRunner(), train_months=6, test_months=2, step_months=2
        )
        windows = wf.generate_windows(data)
        assert len(windows) > 1
        # Each window should advance by the step
        for a, b in zip(windows, windows[1:]):
            delta = (b.train_start - a.train_start).days
            # Approximately 2 months ≈ 60 days (can vary 59-62)
            assert 55 <= delta <= 65

    def test_train_window_is_6_months(self):
        data = _daily_data(months=18)
        wf = WalkForwardValidator(
            StubRunner(), train_months=6, test_months=2, step_months=2
        )
        windows = wf.generate_windows(data)
        w = windows[0]
        delta = (w.train_end - w.train_start).days
        assert 175 <= delta <= 190  # ~6 months

    def test_test_window_is_2_months(self):
        data = _daily_data(months=18)
        wf = WalkForwardValidator(
            StubRunner(), train_months=6, test_months=2, step_months=2
        )
        windows = wf.generate_windows(data)
        w = windows[0]
        delta = (w.test_end - w.test_start).days
        assert 55 <= delta <= 65  # ~2 months

    def test_window_has_index_field(self):
        data = _daily_data(months=12)
        wf = WalkForwardValidator(StubRunner())
        windows = wf.generate_windows(data)
        for i, w in enumerate(windows):
            assert w.index == i


# ─── Validation logic ──────────────────────────────────────────────────

class TestValidation:
    def test_empty_data_produces_failed_result(self):
        wf = WalkForwardValidator(StubRunner())
        result = wf.validate(pd.DataFrame())
        assert result.windows_tested == 0
        assert result.passed is False

    def test_all_positive_windows_pass(self):
        """hypothesis = 0.9, baseline = 0.5 → all windows positive → pass."""
        data = _daily_data(months=18)
        wf = WalkForwardValidator(
            StubRunner(baseline_sharpe=0.5, hypothesis_sharpe=0.9)
        )
        result = wf.validate(data)
        assert result.windows_tested > 0
        assert result.positive_percentage == 1.0
        assert result.passed is True

    def test_all_negative_windows_fail_gate_4(self):
        """hypothesis = 0.1, baseline = 0.5 → all windows negative → fail."""
        data = _daily_data(months=18)
        wf = WalkForwardValidator(
            StubRunner(baseline_sharpe=0.5, hypothesis_sharpe=0.1)
        )
        result = wf.validate(data)
        assert result.positive_percentage == 0.0
        assert result.passed is False

    def test_mixed_results_use_70pct_threshold(self):
        """Create a runner where exactly half the windows are positive — should fail."""
        call_count = [0]

        def alternating(data):
            call_count[0] += 1
            return 0.6 if call_count[0] % 4 <= 1 else 0.4  # half positive

        wf = WalkForwardValidator(
            StubRunner(baseline_sharpe=0.5, hypothesis_sharpe=alternating)
        )
        data = _daily_data(months=18)
        result = wf.validate(data)
        # ~50% positive — below 70% threshold
        assert result.passed is False

    def test_improvement_fields_populated(self):
        data = _daily_data(months=12)
        wf = WalkForwardValidator(
            StubRunner(baseline_sharpe=0.5, hypothesis_sharpe=0.8)
        )
        result = wf.validate(data)
        assert result.mean_improvement > 0
        assert result.median_improvement > 0

    def test_outcomes_have_full_detail(self):
        data = _daily_data(months=12)
        wf = WalkForwardValidator(
            StubRunner(baseline_sharpe=0.5, hypothesis_sharpe=0.7)
        )
        result = wf.validate(data)
        for outcome in result.outcomes:
            assert outcome.window is not None
            assert outcome.baseline_sharpe == 0.5
            assert outcome.hypothesis_sharpe == 0.7
            assert outcome.improvement == pytest.approx(0.2)
            assert outcome.positive is True

    def test_summary_is_string(self):
        data = _daily_data(months=12)
        wf = WalkForwardValidator(StubRunner())
        result = wf.validate(data)
        summary = result.summary()
        assert isinstance(summary, str)
        assert "WalkForwardResult" in summary
