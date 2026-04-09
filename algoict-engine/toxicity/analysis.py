"""
toxicity/analysis.py
=====================
End-to-end VPIN analysis for a backtest run.

Pipeline:
    1. Load 1-min OHLCV data (NQ/MNQ)
    2. Compute rolling VPIN across the full period
    3. Tag each Trade in a BacktestResult with the VPIN reading at entry time
    4. Compare win rate / PnL across VPIN bands
    5. Report $ lost during VPIN > 0.70 periods

Usage:
    from toxicity.analysis import run_vpin_analysis

    report = run_vpin_analysis(
        df_1min=candles,
        trades=backtest_result.trades,
        daily_volume=500_000,
    )
    print(format_report(report))
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .vpin_calculator import (
    VPINCalculator,
    VPINImpactReport,
    tag_trades_with_vpin,
    analyze_vpin_impact,
)

logger = logging.getLogger(__name__)


@dataclass
class VPINAnalysisResult:
    """Full result of run_vpin_analysis()."""
    vpin_series: pd.DataFrame
    tagged_trades: list[dict]
    impact: VPINImpactReport
    # Time stats
    total_readings: int
    extreme_periods: int          # VPIN > 0.70
    high_or_worse_periods: int    # VPIN > 0.55
    max_vpin: float
    mean_vpin: float


def run_vpin_analysis(
    df_1min: pd.DataFrame,
    trades: list,
    daily_volume: float = 500_000,
    buckets_per_day: int = 50,
    rolling_window: int = 50,
) -> VPINAnalysisResult:
    """
    Run the full VPIN analysis pipeline on a 1-min DataFrame + trade list.

    Returns
    -------
    VPINAnalysisResult with vpin_series, tagged_trades, and impact report.
    """
    # 1. Compute VPIN series
    calc = VPINCalculator(num_buckets=rolling_window)
    vpin_df = calc.process_series(
        df_1min,
        daily_volume=daily_volume,
        buckets_per_day=buckets_per_day,
    )

    if vpin_df.empty:
        logger.warning("VPIN series is empty — check data volume vs bucket config")

    # 2. Tag trades
    tagged = tag_trades_with_vpin(trades, vpin_df)

    # 3. Impact report
    impact = analyze_vpin_impact(tagged)

    # 4. Time-based stats
    max_vpin = float(vpin_df["vpin"].max()) if not vpin_df.empty else 0.0
    mean_vpin = float(vpin_df["vpin"].mean()) if not vpin_df.empty else 0.0
    extreme = int((vpin_df["vpin"] > 0.70).sum()) if not vpin_df.empty else 0
    high_plus = int((vpin_df["vpin"] > 0.55).sum()) if not vpin_df.empty else 0

    return VPINAnalysisResult(
        vpin_series=vpin_df,
        tagged_trades=tagged,
        impact=impact,
        total_readings=len(vpin_df),
        extreme_periods=extreme,
        high_or_worse_periods=high_plus,
        max_vpin=max_vpin,
        mean_vpin=mean_vpin,
    )


def format_report(result: VPINAnalysisResult) -> str:
    """Human-readable text report."""
    r = result
    imp = result.impact

    lines: list[str] = []
    _h = lines.append

    _h("=" * 70)
    _h("  VPIN Analysis Report")
    _h("=" * 70)
    _h(f"  Total VPIN readings : {r.total_readings:,}")
    _h(f"  Mean VPIN           : {r.mean_vpin:.3f}")
    _h(f"  Max VPIN            : {r.max_vpin:.3f}")
    _h(f"  High+ periods (>0.55): {r.high_or_worse_periods:,}")
    _h(f"  Extreme periods (>0.70): {r.extreme_periods:,}")
    _h("")
    _h("-- Trade Distribution by Toxicity ------------------")
    _h(f"  Total trades         : {imp.total_trades}")
    _h(f"  Trades with VPIN tag : {imp.trades_with_vpin}")
    _h("")
    _h(f"  {'Level':<10} {'Count':>6} {'Wins':>6} {'WinRate':>8} {'Total P&L':>12}")
    for level in ("calm", "normal", "elevated", "high", "extreme"):
        d = imp.by_toxicity[level]
        _h(
            f"  {level:<10} {d['count']:>6} {d['wins']:>6} "
            f"{d['win_rate']:>7.1%} ${d['total_pnl']:>+11,.2f}"
        )
    _h("")
    _h("-- High VPIN (>0.55) vs Low VPIN (<=0.45) ---------")
    _h(f"  High VPIN trades  : {imp.high_vpin_trades}")
    _h(f"  High VPIN P&L     : ${imp.high_vpin_pnl:+,.2f}")
    _h(f"  High VPIN win rate: {imp.high_vpin_win_rate:.1%}")
    _h("")
    _h(f"  Low VPIN trades   : {imp.low_vpin_trades}")
    _h(f"  Low VPIN P&L      : ${imp.low_vpin_pnl:+,.2f}")
    _h(f"  Low VPIN win rate : {imp.low_vpin_win_rate:.1%}")
    _h("")
    _h("-- Extreme VPIN (>0.70) -- Shield would BLOCK --")
    _h(f"  Extreme trades    : {imp.extreme_vpin_trades}")
    _h(f"  Extreme P&L       : ${imp.extreme_vpin_pnl:+,.2f}")
    if imp.extreme_vpin_pnl < 0:
        _h(f"  >>> Shield would have saved ${-imp.extreme_vpin_pnl:,.2f} <<<")
    _h("=" * 70)

    return "\n".join(lines)
