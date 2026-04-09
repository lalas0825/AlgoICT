"""
strategy_lab/cross_instrument.py
=================================
Cross-instrument validation — Gate 5.

Why this exists
---------------
ICT principles are supposed to describe *institutional order flow*, which
is universal across liquid futures markets. If a hypothesis only improves
NQ and does nothing (or hurts) on ES and YM, then it's probably NQ-
specific microstructure noise — not a real edge.

Gate 5 passes when the hypothesis improves Sharpe over baseline on at
least 2 of 3 instruments (NQ, ES, YM).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .types import BacktestMetrics, BacktestRunner

logger = logging.getLogger(__name__)


DEFAULT_MIN_INSTRUMENTS_PASSING = 2  # Gate 5: must pass on ≥2 of 3


@dataclass
class InstrumentOutcome:
    """Per-instrument hypothesis vs baseline comparison."""
    symbol: str
    baseline_sharpe: float
    hypothesis_sharpe: float
    improvement: float
    passed: bool
    bars: int


@dataclass
class CrossInstrumentResult:
    """Aggregate across all tested instruments."""
    outcomes: list[InstrumentOutcome] = field(default_factory=list)
    instruments_passing: int = 0
    instruments_tested: int = 0
    passed: bool = False

    def summary(self) -> str:
        lines = ["CrossInstrumentResult:"]
        for o in self.outcomes:
            mark = "✅" if o.passed else "❌"
            lines.append(
                f"  {mark} {o.symbol:<4} "
                f"baseline={o.baseline_sharpe:+.2f} "
                f"hyp={o.hypothesis_sharpe:+.2f} "
                f"Δ={o.improvement:+.3f}"
            )
        lines.append(
            f"  Gate 5: {self.instruments_passing}/{self.instruments_tested} "
            f"{'✅' if self.passed else '❌'}"
        )
        return "\n".join(lines)


class CrossInstrumentValidator:
    """
    Runs the hypothesis against baseline on multiple instruments and
    reports how many pass.

    Parameters
    ----------
    runner : BacktestRunner
        Callable — ``runner(data, use_hypothesis, hypothesis_config) -> BacktestMetrics``
    min_passing : int
        Gate 5 threshold — number of instruments the hypothesis must
        improve on. Default 2 (of 3).
    """

    DEFAULT_SYMBOLS = ("NQ", "ES", "YM")

    def __init__(
        self,
        runner: BacktestRunner,
        min_passing: int = DEFAULT_MIN_INSTRUMENTS_PASSING,
    ):
        self.runner = runner
        self.min_passing = min_passing

    def validate(
        self,
        datasets: dict[str, pd.DataFrame],
        hypothesis_config: Optional[dict] = None,
    ) -> CrossInstrumentResult:
        """
        Parameters
        ----------
        datasets : dict[str, pd.DataFrame]
            Maps symbol name ('NQ', 'ES', 'YM') to its 1-min OHLCV frame.
            At least one must be non-empty.
        hypothesis_config : dict, optional
            Runtime config passed to the runner's hypothesis branch.

        Returns
        -------
        CrossInstrumentResult
        """
        if not datasets:
            return CrossInstrumentResult(passed=False)

        outcomes: list[InstrumentOutcome] = []
        for symbol, data in datasets.items():
            if data is None or data.empty:
                logger.info("CrossInstrument: %s has no data — skipping", symbol)
                continue

            baseline = self.runner(
                data, use_hypothesis=False, hypothesis_config=None
            )
            with_hyp = self.runner(
                data,
                use_hypothesis=True,
                hypothesis_config=hypothesis_config,
            )

            improvement = with_hyp.sharpe - baseline.sharpe
            outcomes.append(
                InstrumentOutcome(
                    symbol=symbol,
                    baseline_sharpe=baseline.sharpe,
                    hypothesis_sharpe=with_hyp.sharpe,
                    improvement=improvement,
                    passed=with_hyp.sharpe > baseline.sharpe,
                    bars=len(data),
                )
            )

        passing = sum(1 for o in outcomes if o.passed)
        return CrossInstrumentResult(
            outcomes=outcomes,
            instruments_passing=passing,
            instruments_tested=len(outcomes),
            passed=passing >= self.min_passing,
        )
