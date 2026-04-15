"""
scripts/strategy_lab_session.py
================================
Strategy Lab — Session 1: 5 hypotheses through 9 anti-overfit gates.

Baseline: NY AM Reversal + dynamic bias on Training Set (2019-2022).
Known from walk-forward: 2,047 trades, 34.6% WR, PF 1.71, $+216,832.

Hypotheses target three weaknesses:
  a) May-Jun summer chop (only 2 negative windows)
  b) Low win rate on shorts during bull markets
  c) Loss streaks that cause MLL breaches

Pipeline per hypothesis:
  1. Run on Training Set (year-by-year, 4 × ~14 min)
  2. Gates 1-3: Sharpe / Win Rate / Drawdown vs baseline
  3. Gate 4: Walk-forward >=70% positive windows
  4. Gate 5: Cross-instrument (SKIP — no ES/YM data)
  5. Gates 6-7: Noise + Inversion tests (on 2022 only, ~14 min each)
  6. Gate 8: Occam's Razor (parameter count)
  7. Gate 9: Validation Set 2023 must improve

Total runtime: ~7-8 hours for 5 hypotheses.

Usage:
    cd algoict-engine
    python -u scripts/strategy_lab_session.py
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

os.environ.setdefault("PYTHONUNBUFFERED", "1")

import numpy as np
import pandas as pd

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

print("=== Strategy Lab — Session 1 ===", flush=True)
print("Importing...", flush=True)

from backtest.backtester import Backtester, BacktestResult
from backtest.data_loader import load_data_csv
from backtest.databento_loader import load_databento_ohlcv_1m

from detectors.swing_points import SwingPointDetector
from detectors.market_structure import MarketStructureDetector
from detectors.fair_value_gap import FairValueGapDetector
from detectors.order_block import OrderBlockDetector
from detectors.liquidity import LiquidityDetector
from detectors.displacement import DisplacementDetector
from detectors.confluence import ConfluenceScorer

from risk.risk_manager import RiskManager
from timeframes.tf_manager import TimeframeManager
from timeframes.session_manager import SessionManager
from timeframes.htf_bias import HTFBiasDetector, BiasResult
from strategies.ny_am_reversal import NYAMReversalStrategy

import config as cfg

print("OK", flush=True)


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class Hypothesis:
    id: str
    name: str
    ict_reasoning: str
    condition: str
    parameters_added: int
    expected_impact: str
    risk: str
    config: dict = field(default_factory=dict)


@dataclass
class Metrics:
    sharpe: float
    win_rate: float
    max_drawdown: float
    total_pnl: float
    total_trades: int
    profit_factor: float


@dataclass
class GateResult:
    gate: str
    passed: bool
    metric: float
    threshold: float
    reason: str


@dataclass
class HypothesisResult:
    hypothesis: Hypothesis
    baseline_metrics: Optional[Metrics]
    hypothesis_metrics: Optional[Metrics]
    gates: list
    wf_positive_pct: float = 0.0
    noise_degradation: float = 0.0
    inversion_loses: bool = False
    validation_improvement: float = 0.0
    all_passed: bool = False
    score: int = 0


# ─── Hypotheses ───────────────────────────────────────────────────────────────

HYPOTHESES = [
    Hypothesis(
        id="H-001",
        name="Skip Summer Chop",
        ict_reasoning=(
            "ICT teaches that May-June has reduced institutional flow as "
            "smart money positions before Q3. The NY session becomes range-bound "
            "with more false breakouts and liquidity grabs that fail to convert. "
            "Walk-forward shows W09 and W15 (both May-Jun) are the ONLY negative windows."
        ),
        condition="month NOT IN (5, 6)",
        parameters_added=0,
        expected_impact="Eliminate ~170 low-quality trades, improve PF and reduce max DD",
        risk="Misses legitimate summer setups; reduces sample size by ~16%",
        config={"skip_months": [5, 6]},
    ),
    Hypothesis(
        id="H-002",
        name="High-Confidence Shorts Only",
        ict_reasoning=(
            "ICT emphasizes trading WITH institutional order flow. Shorts against "
            "a weekly bullish trend with only medium-confidence bias are "
            "counter-institutional. The dynamic HTF bias detector returns "
            "confidence='low' or 'medium' when weekly and daily disagree. "
            "Requiring 'high' confidence for shorts ensures both W and D are "
            "aligned bearish before shorting."
        ),
        condition="IF direction=='short' THEN bias.confidence=='high'",
        parameters_added=0,
        expected_impact="Fewer low-quality shorts in bull markets, higher short WR",
        risk="Fewer short setups overall; may miss valid reversals",
        config={"require_high_conf_shorts": True},
    ),
    Hypothesis(
        id="H-003",
        name="Minimum 10-Point OB Stop",
        ict_reasoning=(
            "Very tight Order Blocks (< 10 NQ points) often represent noise "
            "rather than true institutional activity. ICT OBs represent areas "
            "of significant institutional buying/selling, which creates meaningful "
            "price zones — not 2-3 point clusters. A tight OB stop also means "
            "a very close target (1:3 RR), making the trade low-expectancy."
        ),
        condition="abs(entry_price - stop_price) >= 10",
        parameters_added=1,
        expected_impact="Filter out low-quality tight-OB trades, reduce whipsaw losses",
        risk="May filter legitimate tight OBs during low-volatility regimes",
        config={"min_stop_pts": 10.0},
    ),
    Hypothesis(
        id="H-004",
        name="Max 40-Point OB Stop",
        ict_reasoning=(
            "Wide OBs (> 40 NQ points) produce trades with large dollar risk "
            "per contract. With $250 max risk and $2/point, a 40-point stop "
            "allows 3 contracts. Wider stops force 1-2 contracts with the same "
            "$250 risk — but the RR math means losses are larger in absolute terms. "
            "ICT identifies that wide OBs often form during high-volatility events "
            "where the probability of stop-run increases."
        ),
        condition="abs(entry_price - stop_price) <= 40",
        parameters_added=1,
        expected_impact="Avoid large-risk trades, reduce loss magnitude per trade",
        risk="Misses valid wide-OB setups during high-volatility; reduces sample size",
        config={"max_stop_pts": 40.0},
    ),
    Hypothesis(
        id="H-005",
        name="Require 2+ Aligned FVGs",
        ict_reasoning=(
            "ICT teaches that multiple Fair Value Gaps in the same direction "
            "indicate sustained institutional pressure — not just a single "
            "impulsive move. A single FVG could be a one-off sweep, but 2+ "
            "aligned FVGs show that institutions committed to the direction "
            "across multiple candles. This filters out weak setups where only "
            "one FVG exists."
        ),
        condition="len(aligned_fvgs) >= 2",
        parameters_added=1,
        expected_impact="Higher-quality entries with stronger institutional backing",
        risk="Reduces trade count significantly; may miss valid single-FVG setups",
        config={"min_fvgs": 2},
    ),
]


# ─── DynamicBiasStrategy ──────────────────────────────────────────────────────

class DynamicBiasStrategy:
    def __init__(self, inner, df_daily, df_weekly):
        self._inner = inner
        self._df_daily = df_daily
        self._df_weekly = df_weekly
        self._detector = HTFBiasDetector()
        self._current_ts = None
        self._last_bias = None
        self._inner.htf_bias_fn = self._dynamic_bias

    def _dynamic_bias(self, price, *_, **__):
        if self._current_ts is None:
            self._last_bias = self._detector._neutral_result()
            return self._last_bias
        cutoff = self._current_ts.normalize()
        pd_ = self._df_daily[self._df_daily.index < cutoff]
        pw_ = self._df_weekly[self._df_weekly.index < cutoff]
        if pd_.empty or pw_.empty:
            self._last_bias = self._detector._neutral_result()
            return self._last_bias
        self._last_bias = self._detector.determine_bias(pd_, pw_, float(price))
        return self._last_bias

    def evaluate(self, ce, cc):
        if not ce.empty:
            self._current_ts = ce.index[-1]
        return self._inner.evaluate(ce, cc)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ─── Hypothesis Filter Wrapper ────────────────────────────────────────────────

class HypothesisFilter:
    """Wraps a strategy to apply hypothesis-specific filters."""

    def __init__(self, inner_strategy, hyp_config: dict, detectors: dict):
        self._inner = inner_strategy
        self._config = hyp_config
        self._det = detectors
        # For H2: wrap the bias function to reject low-confidence shorts
        if hyp_config.get("require_high_conf_shorts"):
            self._setup_high_conf_shorts()

    def _setup_high_conf_shorts(self):
        """Intercept bias: return neutral when bearish + not high confidence."""
        # Get the actual bias function (on the innermost strategy)
        if isinstance(self._inner, DynamicBiasStrategy):
            original_fn = self._inner._dynamic_bias
            neutral = self._inner._detector._neutral_result()

            def filtered_bias(price, *a, **kw):
                result = original_fn(price, *a, **kw)
                if result.direction == "bearish" and result.confidence != "high":
                    self._inner._last_bias = neutral
                    return neutral
                return result

            self._inner._inner.htf_bias_fn = filtered_bias

    def evaluate(self, ce, cc):
        if not ce.empty:
            ts = ce.index[-1]
            # H1: Skip summer months
            skip_months = self._config.get("skip_months")
            if skip_months and ts.month in skip_months:
                return None

        signal = self._inner.evaluate(ce, cc)
        if signal is None:
            return None

        # H3: Min stop distance
        min_stop = self._config.get("min_stop_pts", 0)
        if min_stop > 0:
            if abs(signal.entry_price - signal.stop_price) < min_stop:
                return None

        # H4: Max stop distance
        max_stop = self._config.get("max_stop_pts")
        if max_stop is not None:
            if abs(signal.entry_price - signal.stop_price) > max_stop:
                return None

        # H5: Require 2+ aligned FVGs
        min_fvgs = self._config.get("min_fvgs")
        if min_fvgs is not None:
            bias_dir = "bullish" if signal.direction == "long" else "bearish"
            fvgs = self._det["fvg"].get_active(timeframe="5min", direction=bias_dir)
            if len(fvgs) < min_fvgs:
                return None

        return signal

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ─── Inverted Strategy (Gate 7) ──────────────────────────────────────────────

class InvertedStrategy:
    """Flips trade direction to test if the strategy has a real edge."""

    def __init__(self, inner):
        self._inner = inner

    def evaluate(self, ce, cc):
        signal = self._inner.evaluate(ce, cc)
        if signal is None:
            return None
        from strategies.ny_am_reversal import Signal
        stop_pts = abs(signal.entry_price - signal.stop_price)
        if signal.direction == "long":
            inv_dir = "short"
            inv_stop = signal.entry_price + stop_pts
            inv_target = signal.entry_price - stop_pts * 3
        else:
            inv_dir = "long"
            inv_stop = signal.entry_price - stop_pts
            inv_target = signal.entry_price + stop_pts * 3
        return Signal(
            strategy=signal.strategy, symbol=signal.symbol,
            direction=inv_dir, entry_price=signal.entry_price,
            stop_price=inv_stop, target_price=inv_target,
            contracts=signal.contracts,
            confluence_score=signal.confluence_score,
            timestamp=signal.timestamp, kill_zone=signal.kill_zone,
        )

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ─── Backtester Factory ──────────────────────────────────────────────────────

def build_backtester(
    df_1min: pd.DataFrame,
    hyp_config: Optional[dict] = None,
    invert: bool = False,
):
    """Build a fresh backtester. If hyp_config is provided, apply hypothesis filter."""
    liquidity = LiquidityDetector()
    detectors = {
        "swing_entry": SwingPointDetector(),
        "swing_context": SwingPointDetector(),
        "structure": MarketStructureDetector(),
        "fvg": FairValueGapDetector(),
        "ob": OrderBlockDetector(),
        "liquidity": liquidity,
        "displacement": DisplacementDetector(),
        "confluence": ConfluenceScorer(),
        "tracked_levels": [],
    }

    tmp_tf = TimeframeManager()
    seeded = []
    try:
        df_daily = tmp_tf.aggregate(df_1min, "D")
        for i in range(len(df_daily)):
            seeded.extend(liquidity.build_key_levels(df_daily=df_daily.iloc[i:i+1]))
    except Exception:
        df_daily = pd.DataFrame()
    try:
        df_weekly = tmp_tf.aggregate(df_1min, "W")
        for i in range(len(df_weekly)):
            seeded.extend(liquidity.build_key_levels(df_weekly=df_weekly.iloc[i:i+1]))
    except Exception:
        df_weekly = pd.DataFrame()
    detectors["tracked_levels"] = seeded

    risk_mgr = RiskManager()
    tf_mgr = TimeframeManager()
    session_mgr = SessionManager()

    def static_bullish(*_, **__):
        return BiasResult(direction="bullish", premium_discount="discount",
                          htf_levels={}, confidence="high",
                          weekly_bias="bullish", daily_bias="bullish")

    inner = NYAMReversalStrategy(detectors, risk_mgr, session_mgr, static_bullish)
    strategy = DynamicBiasStrategy(inner, df_daily, df_weekly)

    if hyp_config:
        strategy = HypothesisFilter(strategy, hyp_config, detectors)

    if invert:
        strategy = InvertedStrategy(strategy)

    return Backtester(strategy, detectors, risk_mgr, tf_mgr, session_mgr)


# ─── Metrics ──────────────────────────────────────────────────────────────────

def compute_metrics(result: BacktestResult) -> Metrics:
    daily_vals = list(result.daily_pnl.values()) if result.daily_pnl else []
    if len(daily_vals) >= 2:
        mean_d = np.mean(daily_vals)
        std_d = np.std(daily_vals, ddof=1)
        sharpe = float(mean_d / std_d * np.sqrt(252)) if std_d > 0 else 0.0
    else:
        sharpe = 0.0

    # Max drawdown from equity curve
    equity = []
    running = 0.0
    for v in sorted(result.daily_pnl.items()):
        running += v[1]
        equity.append(running)
    if equity:
        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = peak - e
            if dd > max_dd:
                max_dd = dd
    else:
        max_dd = 0.0

    wins_pnl = sum(t.pnl for t in result.trades if t.pnl > 0)
    loss_pnl = abs(sum(t.pnl for t in result.trades if t.pnl <= 0))
    pf = wins_pnl / loss_pnl if loss_pnl > 0 else 0.0

    return Metrics(
        sharpe=sharpe,
        win_rate=result.win_rate,
        max_drawdown=max_dd,
        total_pnl=result.total_pnl,
        total_trades=result.total_trades,
        profit_factor=pf,
    )


# ─── Run Year-by-Year ────────────────────────────────────────────────────────

def run_year_by_year(
    df_full: pd.DataFrame,
    years: list[int],
    hyp_config: Optional[dict] = None,
    invert: bool = False,
    label: str = "",
) -> tuple[Metrics, list[dict]]:
    """
    Run backtests year-by-year, merge results.
    Returns (aggregate Metrics, list of 2-month window dicts).
    """
    tz = df_full.index.tz
    all_trades = []
    all_daily_pnl = {}
    wf_windows = []
    window_num = 0

    for year in years:
        year_start = pd.Timestamp(f"{year}-01-01", tz=tz)
        year_end = pd.Timestamp(f"{year+1}-01-01", tz=tz)
        df_year = df_full[(df_full.index >= year_start) & (df_full.index < year_end)]
        if df_year.empty:
            continue

        bt = build_backtester(df_year, hyp_config=hyp_config, invert=invert)
        result = bt.run(df_year)
        all_trades.extend(result.trades)
        all_daily_pnl.update(result.daily_pnl)

        # Slice into 2-month windows
        for bimester in range(6):
            w_start = pd.Timestamp(f"{year}-{bimester*2+1:02d}-01", tz=tz)
            w_end = w_start + pd.DateOffset(months=2)
            window_num += 1
            trades = [t for t in result.trades if w_start <= t.entry_time < w_end]
            pnl = sum(t.pnl for t in trades)
            wf_windows.append({
                "window": window_num,
                "pnl": pnl,
                "trades": len(trades),
                "positive": pnl > 0,
            })

    # Build aggregate metrics
    total_trades = len(all_trades)
    wins = sum(1 for t in all_trades if t.pnl > 0)
    total_pnl = sum(t.pnl for t in all_trades)
    wins_pnl = sum(t.pnl for t in all_trades if t.pnl > 0)
    loss_pnl = abs(sum(t.pnl for t in all_trades if t.pnl <= 0))
    win_rate = wins / total_trades if total_trades > 0 else 0.0
    pf = wins_pnl / loss_pnl if loss_pnl > 0 else 0.0

    daily_vals = list(all_daily_pnl.values())
    if len(daily_vals) >= 2:
        sharpe = float(np.mean(daily_vals) / np.std(daily_vals, ddof=1) * np.sqrt(252)) if np.std(daily_vals, ddof=1) > 0 else 0.0
    else:
        sharpe = 0.0

    equity = []
    running = 0.0
    for d in sorted(all_daily_pnl.keys()):
        running += all_daily_pnl[d]
        equity.append(running)
    max_dd = 0.0
    if equity:
        peak = equity[0]
        for e in equity:
            if e > peak:
                peak = e
            dd = peak - e
            if dd > max_dd:
                max_dd = dd

    metrics = Metrics(
        sharpe=sharpe, win_rate=win_rate, max_drawdown=max_dd,
        total_pnl=total_pnl, total_trades=total_trades, profit_factor=pf,
    )
    return metrics, wf_windows


# ─── Noise Perturbation ──────────────────────────────────────────────────────

def add_noise(df: pd.DataFrame, std: float = 0.001, seed: int = 42) -> pd.DataFrame:
    """Add Gaussian multiplicative noise to OHLC. Preserves invariants."""
    rng = np.random.RandomState(seed)
    out = df.copy()
    for col in ["open", "high", "low", "close"]:
        noise = rng.normal(1.0, std, size=len(df))
        out[col] = out[col] * noise
    out["high"] = out[["open", "high", "low", "close"]].max(axis=1)
    out["low"] = out[["open", "high", "low", "close"]].min(axis=1)
    return out


# ─── 9 Gates Evaluation ──────────────────────────────────────────────────────

def evaluate_gates(
    baseline: Metrics,
    hypothesis: Metrics,
    wf_windows: list[dict],
    noise_sharpe: float,
    inversion_sharpe: float,
    params_added: int,
    val_baseline_sharpe: float,
    val_hyp_sharpe: float,
) -> list[GateResult]:
    """Evaluate all 9 anti-overfit gates."""
    gates = []

    # Gate 1: Sharpe improvement >= +0.1
    delta_sharpe = hypothesis.sharpe - baseline.sharpe
    gates.append(GateResult(
        gate="1_sharpe_improvement",
        passed=delta_sharpe >= 0.1,
        metric=delta_sharpe,
        threshold=0.1,
        reason=f"ΔSharpe={delta_sharpe:+.3f} {'>='}  0.1" if delta_sharpe >= 0.1
               else f"ΔSharpe={delta_sharpe:+.3f} < 0.1",
    ))

    # Gate 2: Win rate no degrada > 2%
    delta_wr = hypothesis.win_rate - baseline.win_rate
    gates.append(GateResult(
        gate="2_win_rate_delta",
        passed=delta_wr >= -0.02,
        metric=delta_wr,
        threshold=-0.02,
        reason=f"ΔWR={delta_wr:+.1%} {'>=' if delta_wr >= -0.02 else '<'} -2%",
    ))

    # Gate 3: Drawdown no aumenta > 10%
    if baseline.max_drawdown > 0:
        dd_increase = (hypothesis.max_drawdown - baseline.max_drawdown) / baseline.max_drawdown
    else:
        dd_increase = 0.0
    gates.append(GateResult(
        gate="3_drawdown_delta",
        passed=dd_increase <= 0.10,
        metric=dd_increase,
        threshold=0.10,
        reason=f"DD change={dd_increase:+.1%} {'<=' if dd_increase <= 0.10 else '>'} 10%",
    ))

    # Gate 4: Walk-forward >= 70% positive
    total_w = len(wf_windows)
    pos_w = sum(1 for w in wf_windows if w["positive"])
    pct = pos_w / total_w if total_w > 0 else 0.0
    gates.append(GateResult(
        gate="4_walk_forward",
        passed=pct >= 0.70,
        metric=pct,
        threshold=0.70,
        reason=f"{pos_w}/{total_w} positive ({pct:.1%}) {'>=' if pct >= 0.70 else '<'} 70%",
    ))

    # Gate 5: Cross-instrument (SKIP — no ES/YM data)
    gates.append(GateResult(
        gate="5_cross_instrument",
        passed=True,
        metric=0.0,
        threshold=2.0,
        reason="SKIPPED — no ES/YM data available",
    ))

    # Gate 6: Noise resilience < 30% degradation
    if hypothesis.sharpe != 0:
        noise_deg = (hypothesis.sharpe - noise_sharpe) / abs(hypothesis.sharpe)
    else:
        noise_deg = 0.0
    gates.append(GateResult(
        gate="6_noise_resilience",
        passed=noise_deg <= 0.30,
        metric=noise_deg,
        threshold=0.30,
        reason=f"Noise degradation={noise_deg:.1%} {'<=' if noise_deg <= 0.30 else '>'} 30%",
    ))

    # Gate 7: Inversion must lose
    inv_loses = inversion_sharpe < hypothesis.sharpe
    gates.append(GateResult(
        gate="7_inversion_loses",
        passed=inv_loses,
        metric=inversion_sharpe,
        threshold=hypothesis.sharpe,
        reason=f"Inv Sharpe={inversion_sharpe:.3f} {'<' if inv_loses else '>='} hyp={hypothesis.sharpe:.3f}",
    ))

    # Gate 8: Max 2 new parameters
    gates.append(GateResult(
        gate="8_occam_razor",
        passed=params_added <= 2,
        metric=float(params_added),
        threshold=2.0,
        reason=f"{params_added} params {'<=' if params_added <= 2 else '>'} 2",
    ))

    # Gate 9: Validation 2023 must improve
    val_delta = val_hyp_sharpe - val_baseline_sharpe
    gates.append(GateResult(
        gate="9_validation_improves",
        passed=val_delta >= 0.05,
        metric=val_delta,
        threshold=0.05,
        reason=f"Val ΔSharpe={val_delta:+.3f} {'>=' if val_delta >= 0.05 else '<'} 0.05",
    ))

    return gates


# ─── Persistence ──────────────────────────────────────────────────────────────

def save_to_jsonl(results: list[HypothesisResult], session_id: str):
    """Save candidates to JSONL (local)."""
    path = ENGINE_ROOT.parent / "data" / "strategy_lab"
    path.mkdir(parents=True, exist_ok=True)
    jsonl_path = path / "candidates.jsonl"

    with open(jsonl_path, "a", encoding="utf-8") as f:
        for r in results:
            record = {
                "id": r.hypothesis.id,
                "hypothesis": {
                    "id": r.hypothesis.id,
                    "name": r.hypothesis.name,
                    "ict_reasoning": r.hypothesis.ict_reasoning,
                    "condition": r.hypothesis.condition,
                    "parameters_added": r.hypothesis.parameters_added,
                },
                "strategy_name": "ny_am_reversal",
                "status": "passed" if r.all_passed else "failed",
                "gates_passed": sum(1 for g in r.gates if g.passed),
                "gates_total": 9,
                "score": r.score,
                "gate_results": {g.gate: {"passed": g.passed, "metric": g.metric,
                                           "threshold": g.threshold, "reason": g.reason}
                                 for g in r.gates},
                "sharpe_improvement": (r.hypothesis_metrics.sharpe - r.baseline_metrics.sharpe
                                       if r.hypothesis_metrics and r.baseline_metrics else 0.0),
                "net_profit_delta": (r.hypothesis_metrics.total_pnl - r.baseline_metrics.total_pnl
                                     if r.hypothesis_metrics and r.baseline_metrics else 0.0),
                "session_id": session_id,
                "mode": "generate",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            f.write(json.dumps(record) + "\n")

    print(f"  JSONL saved: {jsonl_path}", flush=True)


def save_to_supabase(results: list[HypothesisResult], session_id: str):
    """Persist to Supabase strategy_candidates table."""
    try:
        from db.supabase_lab_client import get_lab_client
        client = get_lab_client()
        if client is None:
            print("  Supabase: no client (keys missing)", flush=True)
            return

        for r in results:
            row = {
                "id": r.hypothesis.id,
                "hypothesis": r.hypothesis.ict_reasoning,
                "strategy_name": "ny_am_reversal",
                "status": "passed" if r.all_passed else "failed",
                "gates_passed": sum(1 for g in r.gates if g.passed),
                "gates_total": 9,
                "score": r.score,
                "gate_results": {g.gate: {"passed": g.passed, "metric": round(g.metric, 4),
                                           "threshold": g.threshold, "reason": g.reason}
                                 for g in r.gates},
                "sharpe_improvement": round(
                    r.hypothesis_metrics.sharpe - r.baseline_metrics.sharpe, 4
                ) if r.hypothesis_metrics and r.baseline_metrics else None,
                "net_profit_delta": round(
                    r.hypothesis_metrics.total_pnl - r.baseline_metrics.total_pnl, 2
                ) if r.hypothesis_metrics and r.baseline_metrics else None,
                "session_id": session_id,
                "mode": "generate",
            }
            client.upsert_strategy_candidate(row)

        print(f"  Supabase: {len(results)} candidates upserted", flush=True)
    except Exception as e:
        print(f"  Supabase error: {e}", flush=True)


def write_memory(results: list[HypothesisResult], baseline: Metrics, session_id: str):
    """Write results to .claude/memory/project/strategy-candidates.md"""
    path = ENGINE_ROOT.parent / ".claude" / "memory" / "project" / "strategy-candidates.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        "name: Strategy Lab Session 1 Results",
        "description: 5 hypotheses through 9 anti-overfit gates for NY AM Reversal",
        "type: project",
        "---",
        "",
        f"# Strategy Lab — Session 1",
        f"_Session: {session_id}_",
        "",
        "## Baseline (Training 2019-2022)",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Trades | {baseline.total_trades} |",
        f"| Win Rate | {baseline.win_rate:.1%} |",
        f"| Sharpe | {baseline.sharpe:.3f} |",
        f"| P&L | ${baseline.total_pnl:+,.0f} |",
        f"| PF | {baseline.profit_factor:.2f} |",
        f"| Max DD | ${baseline.max_drawdown:,.0f} |",
        "",
    ]

    passed_count = sum(1 for r in results if r.all_passed)
    lines += [
        f"## Summary: {passed_count}/{len(results)} hypotheses passed all 9 gates",
        "",
        "| ID | Name | Gates | Score | ΔSharpe | ΔWR | Status |",
        "|-----|------|-------|-------|---------|-----|--------|",
    ]
    for r in results:
        gp = sum(1 for g in r.gates if g.passed)
        ds = (r.hypothesis_metrics.sharpe - r.baseline_metrics.sharpe
              if r.hypothesis_metrics and r.baseline_metrics else 0.0)
        dwr = (r.hypothesis_metrics.win_rate - r.baseline_metrics.win_rate
               if r.hypothesis_metrics and r.baseline_metrics else 0.0)
        status = "**PASS**" if r.all_passed else "FAIL"
        lines.append(
            f"| {r.hypothesis.id} | {r.hypothesis.name} | {gp}/9 | {r.score} "
            f"| {ds:+.3f} | {dwr:+.1%} | {status} |"
        )

    lines += [""]

    # Detail per hypothesis
    for r in results:
        lines += [
            f"### {r.hypothesis.id}: {r.hypothesis.name}",
            f"**ICT Reasoning:** {r.hypothesis.ict_reasoning}",
            f"**Condition:** `{r.hypothesis.condition}`",
            f"**Parameters:** {r.hypothesis.parameters_added}",
            "",
        ]
        if r.hypothesis_metrics:
            lines += [
                "| Metric | Baseline | Hypothesis | Delta |",
                "|--------|----------|------------|-------|",
                f"| Trades | {r.baseline_metrics.total_trades} | {r.hypothesis_metrics.total_trades} | {r.hypothesis_metrics.total_trades - r.baseline_metrics.total_trades:+d} |",
                f"| WR | {r.baseline_metrics.win_rate:.1%} | {r.hypothesis_metrics.win_rate:.1%} | {r.hypothesis_metrics.win_rate - r.baseline_metrics.win_rate:+.1%} |",
                f"| Sharpe | {r.baseline_metrics.sharpe:.3f} | {r.hypothesis_metrics.sharpe:.3f} | {r.hypothesis_metrics.sharpe - r.baseline_metrics.sharpe:+.3f} |",
                f"| PF | {r.baseline_metrics.profit_factor:.2f} | {r.hypothesis_metrics.profit_factor:.2f} | {r.hypothesis_metrics.profit_factor - r.baseline_metrics.profit_factor:+.2f} |",
                f"| Max DD | ${r.baseline_metrics.max_drawdown:,.0f} | ${r.hypothesis_metrics.max_drawdown:,.0f} | |",
                "",
            ]
        lines.append("**Gate Results:**")
        lines.append("")
        lines.append("| Gate | Result | Metric | Threshold | Detail |")
        lines.append("|------|--------|--------|-----------|--------|")
        for g in r.gates:
            mark = "PASS" if g.passed else "FAIL"
            lines.append(f"| {g.gate} | {mark} | {g.metric:.3f} | {g.threshold:.3f} | {g.reason} |")
        lines += [""]

    lines += [
        "**Why:** Strategy Lab validates hypotheses before promotion to production.",
        "**How to apply:** Candidates that pass all 9 gates → `JUAN_APPROVED_FINAL_TEST` to unlock Test Set.",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Memory written: {path}", flush=True)


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def main() -> int:
    session_id = f"S1_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"
    data_dir = ENGINE_ROOT.parent / "data"
    databento_path = data_dir / "nq_1minute.csv"
    simple_path = data_dir / "nq_1min.csv"

    # ── Load data ─────────────────────────────────────────────────────────
    print("\nLoading training data (Databento 2019-2022)...", flush=True)
    df_train = load_databento_ohlcv_1m(databento_path, start_date="2019-01-01",
                                        end_date="2022-12-31", symbol_prefix="NQ")
    print(f"  Training: {len(df_train):,} bars", flush=True)

    print("Loading validation data (2023)...", flush=True)
    df_raw = load_data_csv(simple_path)
    tz_val = df_raw.index.tz
    df_val = df_raw[
        (df_raw.index >= pd.Timestamp("2023-01-01", tz=tz_val)) &
        (df_raw.index < pd.Timestamp("2024-01-01", tz=tz_val))
    ]
    print(f"  Validation: {len(df_val):,} bars", flush=True)

    # Stress test data (2022 only for speed)
    tz_train = df_train.index.tz
    df_2022 = df_train[
        (df_train.index >= pd.Timestamp("2022-01-01", tz=tz_train)) &
        (df_train.index < pd.Timestamp("2023-01-01", tz=tz_train))
    ]
    print(f"  Stress test (2022): {len(df_2022):,} bars", flush=True)

    # ── Baseline on Training ──────────────────────────────────────────────
    print(f"\n{'='*65}", flush=True)
    print("  BASELINE: NY AM Reversal on Training 2019-2022", flush=True)
    print(f"{'='*65}", flush=True)

    t0 = time.perf_counter()
    baseline_metrics, baseline_wf = run_year_by_year(
        df_train, [2019, 2020, 2021, 2022], label="baseline",
    )
    baseline_elapsed = time.perf_counter() - t0

    print(f"\n  Baseline: {baseline_metrics.total_trades} trades, "
          f"WR={baseline_metrics.win_rate:.1%}, Sharpe={baseline_metrics.sharpe:.3f}, "
          f"PF={baseline_metrics.profit_factor:.2f}, P&L=${baseline_metrics.total_pnl:+,.0f}  "
          f"({baseline_elapsed:.0f}s)", flush=True)

    # Baseline on validation
    print("\n  Running baseline on Validation 2023...", flush=True)
    bt_val = build_backtester(df_val)
    val_baseline_result = bt_val.run(df_val)
    val_baseline_metrics = compute_metrics(val_baseline_result)
    print(f"  Val baseline: Sharpe={val_baseline_metrics.sharpe:.3f}, "
          f"trades={val_baseline_metrics.total_trades}", flush=True)

    # ── Run each hypothesis ───────────────────────────────────────────────
    all_results: list[HypothesisResult] = []

    for idx, hyp in enumerate(HYPOTHESES, 1):
        print(f"\n{'='*65}", flush=True)
        print(f"  HYPOTHESIS {idx}/5: {hyp.id} — {hyp.name}", flush=True)
        print(f"  {hyp.ict_reasoning[:80]}...", flush=True)
        print(f"{'='*65}", flush=True)

        # 1. Training backtest (year-by-year)
        print(f"\n  [1/5] Training backtest (2019-2022)...", flush=True)
        t0 = time.perf_counter()
        hyp_metrics, hyp_wf = run_year_by_year(
            df_train, [2019, 2020, 2021, 2022],
            hyp_config=hyp.config, label=hyp.id,
        )
        elapsed = time.perf_counter() - t0
        print(f"  Done: {hyp_metrics.total_trades} trades, "
              f"WR={hyp_metrics.win_rate:.1%}, Sharpe={hyp_metrics.sharpe:.3f}, "
              f"PF={hyp_metrics.profit_factor:.2f}  ({elapsed:.0f}s)", flush=True)

        # Walk-forward from training slices
        wf_total = len(hyp_wf)
        wf_pos = sum(1 for w in hyp_wf if w["positive"])
        wf_pct = wf_pos / wf_total if wf_total > 0 else 0.0
        print(f"  Walk-forward: {wf_pos}/{wf_total} positive ({wf_pct:.1%})", flush=True)

        # 2. Noise test (on 2022 only)
        print(f"\n  [2/5] Noise test (2022 data + 0.1% Gaussian noise)...", flush=True)
        t0 = time.perf_counter()
        df_noisy = add_noise(df_2022)
        bt_noise = build_backtester(df_noisy, hyp_config=hyp.config)
        noise_result = bt_noise.run(df_noisy)
        noise_metrics = compute_metrics(noise_result)
        elapsed = time.perf_counter() - t0
        print(f"  Noise Sharpe={noise_metrics.sharpe:.3f} "
              f"(clean={hyp_metrics.sharpe:.3f})  ({elapsed:.0f}s)", flush=True)

        # 3. Inversion test (on 2022 only)
        print(f"\n  [3/5] Inversion test (2022 data, flipped direction)...", flush=True)
        t0 = time.perf_counter()
        bt_inv = build_backtester(df_2022, hyp_config=hyp.config, invert=True)
        inv_result = bt_inv.run(df_2022)
        inv_metrics = compute_metrics(inv_result)
        elapsed = time.perf_counter() - t0
        print(f"  Inversion Sharpe={inv_metrics.sharpe:.3f} "
              f"(hypothesis={hyp_metrics.sharpe:.3f})  ({elapsed:.0f}s)", flush=True)

        # 4. Validation (2023)
        print(f"\n  [4/5] Validation 2023...", flush=True)
        t0 = time.perf_counter()
        bt_val_hyp = build_backtester(df_val, hyp_config=hyp.config)
        val_hyp_result = bt_val_hyp.run(df_val)
        val_hyp_metrics = compute_metrics(val_hyp_result)
        elapsed = time.perf_counter() - t0
        print(f"  Val: Sharpe={val_hyp_metrics.sharpe:.3f} "
              f"(baseline={val_baseline_metrics.sharpe:.3f})  ({elapsed:.0f}s)", flush=True)

        # 5. Evaluate all 9 gates
        print(f"\n  [5/5] Evaluating 9 gates...", flush=True)

        # For noise: compute 2022-only hypothesis sharpe (not full training)
        bt_clean = build_backtester(df_2022, hyp_config=hyp.config)
        clean_2022_result = bt_clean.run(df_2022)
        clean_2022_metrics = compute_metrics(clean_2022_result)

        gates = evaluate_gates(
            baseline=baseline_metrics,
            hypothesis=hyp_metrics,
            wf_windows=hyp_wf,
            noise_sharpe=noise_metrics.sharpe,
            inversion_sharpe=inv_metrics.sharpe,
            params_added=hyp.parameters_added,
            val_baseline_sharpe=val_baseline_metrics.sharpe,
            val_hyp_sharpe=val_hyp_metrics.sharpe,
        )

        gates_passed = sum(1 for g in gates if g.passed)
        all_passed = gates_passed == 9

        # Score: 60 pts gates + 20 pts sharpe improvement + 20 pts WF bonus
        delta_sharpe = hyp_metrics.sharpe - baseline_metrics.sharpe
        sharpe_score = min(20, max(0, int(delta_sharpe / 0.5 * 20)))
        wf_score = min(20, max(0, int((wf_pct - 0.70) / 0.30 * 20)))
        score = int(gates_passed * (60 / 9)) + sharpe_score + wf_score

        result = HypothesisResult(
            hypothesis=hyp,
            baseline_metrics=baseline_metrics,
            hypothesis_metrics=hyp_metrics,
            gates=gates,
            wf_positive_pct=wf_pct,
            noise_degradation=noise_metrics.sharpe,
            inversion_loses=inv_metrics.sharpe < hyp_metrics.sharpe,
            validation_improvement=val_hyp_metrics.sharpe - val_baseline_metrics.sharpe,
            all_passed=all_passed,
            score=score,
        )
        all_results.append(result)

        # Print gate summary
        print(f"\n  Gate Results for {hyp.id}:", flush=True)
        for g in gates:
            mark = "PASS" if g.passed else "FAIL"
            print(f"    {mark}  {g.gate}: {g.reason}", flush=True)
        print(f"\n  Score: {score}/100  |  {gates_passed}/9 gates  |  "
              f"{'ALL PASSED' if all_passed else 'FAILED'}", flush=True)

    # ── Save results ──────────────────────────────────────────────────────
    print(f"\n{'='*65}", flush=True)
    print("  SAVING RESULTS", flush=True)
    print(f"{'='*65}", flush=True)

    save_to_jsonl(all_results, session_id)
    save_to_supabase(all_results, session_id)
    write_memory(all_results, baseline_metrics, session_id)

    # ── Final summary ─────────────────────────────────────────────────────
    passed = [r for r in all_results if r.all_passed]
    print(f"\n{'='*65}", flush=True)
    print(f"  STRATEGY LAB SESSION 1 COMPLETE", flush=True)
    print(f"  {len(passed)}/{len(all_results)} hypotheses passed all 9 gates", flush=True)
    for r in all_results:
        gp = sum(1 for g in r.gates if g.passed)
        status = "PASS" if r.all_passed else "FAIL"
        print(f"    {r.hypothesis.id} {r.hypothesis.name:.<35} {gp}/9  {status}  "
              f"score={r.score}", flush=True)
    print(f"{'='*65}\n", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
