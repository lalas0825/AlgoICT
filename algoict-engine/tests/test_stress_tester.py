"""Tests for strategy_lab.stress_tester — verify each perturbation runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from strategy_lab.types import BacktestMetrics
from strategy_lab.stress_tester import (
    StressTester,
    StressOutcome,
    StressTestResult,
    DEFAULT_NOISE_STD,
    DEFAULT_REMOVE_PCT,
    DEFAULT_MAX_DEGRADATION,
)


# ─── Fixtures ───────────────────────────────────────────────────────────

def _ohlc_data(n: int = 500) -> pd.DataFrame:
    """Synthetic 1-min OHLCV data."""
    idx = pd.date_range("2020-01-01 09:30", periods=n, freq="1min", tz="US/Central")
    rng = np.random.default_rng(1)
    closes = 100.0 + np.cumsum(rng.normal(0, 0.1, n))
    opens = closes + rng.normal(0, 0.05, n)
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, 0.1, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, 0.1, n))
    volumes = rng.integers(100, 1000, n).astype(float)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


@dataclass
class ConfigurableRunner:
    """
    Stub runner that computes a deterministic Sharpe from the data
    so we can verify perturbations actually change the input.
    """
    calls: list[tuple] = field(default_factory=list)
    baseline_sharpe: float = 0.5
    # Per-perturbation override map (keyed by detecting data characteristics)
    custom_sharpe: Optional[dict] = None

    def __call__(
        self,
        data: pd.DataFrame,
        *,
        use_hypothesis: bool,
        hypothesis_config: Optional[dict] = None,
    ) -> BacktestMetrics:
        self.calls.append(
            (
                len(data),
                use_hypothesis,
                dict(hypothesis_config or {}),
                float(data["close"].iloc[0]) if not data.empty else 0.0,
            )
        )

        # Inversion test
        if hypothesis_config and hypothesis_config.get("invert_signals"):
            return BacktestMetrics(
                sharpe=-self.baseline_sharpe,  # Lose money when inverted
                win_rate=0.2,
                max_drawdown=0.15,
                total_pnl=-1000.0,
                total_trades=50,
            )
        # Slippage test
        if hypothesis_config and hypothesis_config.get("slippage_mult"):
            return BacktestMetrics(
                sharpe=self.baseline_sharpe * 0.9,  # 10% degradation
                win_rate=0.52,
                max_drawdown=0.09,
                total_pnl=900.0,
                total_trades=50,
            )
        return BacktestMetrics(
            sharpe=self.baseline_sharpe,
            win_rate=0.55,
            max_drawdown=0.08,
            total_pnl=1000.0,
            total_trades=50,
        )


# ─── Construction ───────────────────────────────────────────────────────

class TestConstruction:
    def test_rejects_negative_noise(self):
        with pytest.raises(ValueError):
            StressTester(ConfigurableRunner(), noise_std=-0.1)

    def test_rejects_remove_pct_ge_1(self):
        with pytest.raises(ValueError):
            StressTester(ConfigurableRunner(), remove_pct=1.0)

    def test_defaults_match_spec(self):
        st = StressTester(ConfigurableRunner())
        assert st.noise_std == DEFAULT_NOISE_STD
        assert st.remove_pct == DEFAULT_REMOVE_PCT
        assert st.max_degradation == DEFAULT_MAX_DEGRADATION


# ─── Perturbation functions ────────────────────────────────────────────

class TestPerturbations:
    def test_noise_changes_price_values(self):
        data = _ohlc_data()
        st = StressTester(ConfigurableRunner(), noise_std=0.01)  # 1% noise for visibility
        noisy = st._add_price_noise(data, 0.01)
        # Closes should differ
        assert not (noisy["close"].values == data["close"].values).all()
        # OHLC invariants must still hold
        assert (noisy["high"] >= noisy["low"]).all()
        assert (noisy["high"] >= noisy[["open", "close"]].max(axis=1)).all()
        assert (noisy["low"] <= noisy[["open", "close"]].min(axis=1)).all()

    def test_noise_preserves_length(self):
        data = _ohlc_data()
        st = StressTester(ConfigurableRunner())
        noisy = st._add_price_noise(data, 0.001)
        assert len(noisy) == len(data)

    def test_shift_forward_drops_edge_rows(self):
        data = _ohlc_data(100)
        st = StressTester(ConfigurableRunner())
        shifted = st._shift_bars(data, 1)
        assert len(shifted) < len(data)

    def test_shift_backward_drops_edge_rows(self):
        data = _ohlc_data(100)
        st = StressTester(ConfigurableRunner())
        shifted = st._shift_bars(data, -1)
        assert len(shifted) < len(data)

    def test_shift_zero_is_identity(self):
        data = _ohlc_data(100)
        st = StressTester(ConfigurableRunner())
        shifted = st._shift_bars(data, 0)
        pd.testing.assert_frame_equal(shifted, data)

    def test_remove_random_drops_expected_fraction(self):
        data = _ohlc_data(1000)
        st = StressTester(ConfigurableRunner(), remove_pct=0.10)
        sparse = st._remove_random(data, 0.10)
        # 1000 * 0.10 = 100 removed
        assert len(sparse) == 900

    def test_remove_zero_is_identity(self):
        data = _ohlc_data(100)
        st = StressTester(ConfigurableRunner())
        sparse = st._remove_random(data, 0.0)
        assert len(sparse) == 100


# ─── Degradation math ──────────────────────────────────────────────────

class TestDegradationMath:
    def test_zero_degradation_when_equal(self):
        deg = StressTester._safe_degradation(0.5, 0.5)
        assert deg == 0.0

    def test_positive_when_stressed_worse(self):
        deg = StressTester._safe_degradation(1.0, 0.7)
        assert deg == pytest.approx(0.30)

    def test_negative_when_stressed_better(self):
        deg = StressTester._safe_degradation(1.0, 1.2)
        assert deg == pytest.approx(-0.20)

    def test_baseline_near_zero_uses_sentinel(self):
        deg = StressTester._safe_degradation(0.0, -1.0)
        assert deg > 1.0  # Sentinel


# ─── Full run_all_tests ────────────────────────────────────────────────

class TestRunAllTests:
    def test_produces_six_outcomes(self):
        data = _ohlc_data()
        runner = ConfigurableRunner(baseline_sharpe=0.5)
        st = StressTester(runner)
        result = st.run_all_tests(data)
        assert len(result.outcomes) == 6
        names = {o.name for o in result.outcomes}
        assert names == {
            "noise", "shift_fwd", "shift_bwd", "sparse", "slippage", "inversion"
        }

    def test_runner_called_for_every_test_plus_baseline(self):
        data = _ohlc_data()
        runner = ConfigurableRunner()
        st = StressTester(runner)
        st.run_all_tests(data)
        # 1 baseline + 6 stress runs
        assert len(runner.calls) == 7

    def test_inversion_passes_when_inverted_loses(self):
        """Runner returns negative sharpe when invert_signals=True → should pass."""
        data = _ohlc_data()
        runner = ConfigurableRunner(baseline_sharpe=0.5)
        st = StressTester(runner)
        result = st.run_all_tests(data)
        assert result.inversion_loses is True
        assert result.inversion_passed is True

    def test_inversion_fails_when_inverted_profits(self):
        """If inverted strategy also profits, Gate 7 must fail."""
        @dataclass
        class ProfitsBothWaysRunner:
            def __call__(self, data, *, use_hypothesis, hypothesis_config=None):
                # Profits no matter what — inversion is random
                return BacktestMetrics(sharpe=1.0, total_pnl=1000.0, total_trades=50)

        data = _ohlc_data()
        st = StressTester(ProfitsBothWaysRunner())
        result = st.run_all_tests(data)
        assert result.inversion_loses is False
        assert result.inversion_passed is False

    def test_noise_resilience_passes_with_stable_runner(self):
        """Constant-sharpe runner → 0% degradation → Gate 6 passes."""
        data = _ohlc_data()
        runner = ConfigurableRunner(baseline_sharpe=0.5)
        st = StressTester(runner)
        result = st.run_all_tests(data)
        # Non-inversion outcomes are slippage (10% deg) + others (0% deg).
        # All well under 30%.
        assert result.noise_resilience_passed is True

    def test_noise_resilience_fails_with_large_degradation(self):
        """Runner that returns zero under stress should cause Gate 6 to fail."""
        @dataclass
        class CollapsingRunner:
            call_count: int = 0

            def __call__(self, data, *, use_hypothesis, hypothesis_config=None):
                self.call_count += 1
                # First call is baseline — return high sharpe
                if self.call_count == 1:
                    return BacktestMetrics(sharpe=1.0, total_pnl=1000.0, total_trades=50)
                # Inversion test
                if hypothesis_config and hypothesis_config.get("invert_signals"):
                    return BacktestMetrics(sharpe=-1.0, total_pnl=-1000.0, total_trades=50)
                # All other stress runs collapse
                return BacktestMetrics(sharpe=0.0, total_pnl=0.0, total_trades=50)

        data = _ohlc_data()
        st = StressTester(CollapsingRunner())
        result = st.run_all_tests(data)
        assert result.noise_resilience_passed is False
        assert result.max_degradation >= 1.0

    def test_summary_string(self):
        data = _ohlc_data()
        result = StressTester(ConfigurableRunner()).run_all_tests(data)
        s = result.summary()
        assert "StressTestResult" in s
        assert "Gate 6" in s
        assert "Gate 7" in s
