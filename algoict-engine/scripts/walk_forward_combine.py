"""
scripts/walk_forward_combine.py
================================
Walk-Forward Analysis (2019-2022) + Combine Simulator (2023)
for NY AM Reversal with dynamic HTF bias.

Approach (fast):
  - Load Databento data ONCE for 2019-2022
  - Run ONE full backtest (avoids 21x detector rebuilds)
  - Slice trades into 2-month windows post-hoc to get per-window stats
  - Combine Simulator: load nq_1min.csv, run 2023 backtest, sequential attempts
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

os.environ.setdefault("PYTHONUNBUFFERED", "1")

import pandas as pd

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

print("=== AlgoICT Walk-Forward + Combine Simulator ===", flush=True)
print("Importing modules...", flush=True)

from backtest.backtester import Backtester, BacktestResult
from backtest.data_loader import load_data_csv
from backtest.databento_loader import load_databento_ohlcv_1m
from backtest.combine_simulator import simulate_combine

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


# ─── DynamicBiasStrategy ──────────────────────────────────────────────────────

class DynamicBiasStrategy:
    """Lookahead-free dynamic HTF bias wrapper."""

    def __init__(self, inner, df_daily: pd.DataFrame, df_weekly: pd.DataFrame):
        self._inner = inner
        self._df_daily = df_daily
        self._df_weekly = df_weekly
        self._detector = HTFBiasDetector()
        self._current_ts: Optional[pd.Timestamp] = None
        self._inner.htf_bias_fn = self._dynamic_bias

    def _dynamic_bias(self, current_price: float, *_, **__) -> BiasResult:
        if self._current_ts is None:
            self._neutral_count = getattr(self, "_neutral_count", 0) + 1
            return self._detector._neutral_result()
        cutoff = self._current_ts.normalize()
        pd = self._df_daily[self._df_daily.index < cutoff]
        pw = self._df_weekly[self._df_weekly.index < cutoff]
        if pd.empty or pw.empty:
            return self._detector._neutral_result()
        return self._detector.determine_bias(pd, pw, float(current_price))

    def evaluate(self, candles_entry, candles_context):
        if not candles_entry.empty:
            self._current_ts = candles_entry.index[-1]
        return self._inner.evaluate(candles_entry, candles_context)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ─── Build full backtester ────────────────────────────────────────────────────

def build_full_backtester(df_1min: pd.DataFrame, dynamic_bias: bool = True):
    """Build one Backtester for the full dataset."""
    print("  Building detectors...", flush=True)
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
        print(f"  Seeding PDH/PDL from {len(df_daily)} daily bars...", flush=True)
        for i in range(len(df_daily)):
            seeded.extend(liquidity.build_key_levels(df_daily=df_daily.iloc[i:i+1]))
    except Exception as e:
        print(f"  WARN daily seed: {e}", flush=True)
        df_daily = pd.DataFrame()

    try:
        df_weekly = tmp_tf.aggregate(df_1min, "W")
        print(f"  Seeding PWH/PWL from {len(df_weekly)} weekly bars...", flush=True)
        for i in range(len(df_weekly)):
            seeded.extend(liquidity.build_key_levels(df_weekly=df_weekly.iloc[i:i+1]))
    except Exception as e:
        print(f"  WARN weekly seed: {e}", flush=True)
        df_weekly = pd.DataFrame()

    detectors["tracked_levels"] = seeded
    print(f"  Seeded {len(seeded)} tracked levels", flush=True)

    risk_mgr = RiskManager()
    tf_mgr = TimeframeManager()
    session_mgr = SessionManager()

    def static_bullish(*_, **__):
        return BiasResult(direction="bullish", premium_discount="discount",
                          htf_levels={}, confidence="high",
                          weekly_bias="bullish", daily_bias="bullish")

    inner = NYAMReversalStrategy(detectors, risk_mgr, session_mgr, static_bullish)

    if dynamic_bias and not df_daily.empty and not df_weekly.empty:
        strategy = DynamicBiasStrategy(inner, df_daily, df_weekly)
        print("  Dynamic HTF bias: ON", flush=True)
    else:
        strategy = inner
        print("  Dynamic HTF bias: OFF (static bullish)", flush=True)

    return Backtester(strategy, detectors, risk_mgr, tf_mgr, session_mgr)


# ─── Walk-Forward (slice approach) ───────────────────────────────────────────

def run_walk_forward(df_full: pd.DataFrame) -> list[dict]:
    """
    Run walk-forward: one backtest per year (2019, 2020, 2021, 2022),
    then slice each year's trades into 2-month windows.

    Running year-by-year keeps tracked_levels manageable (~500 per year
    instead of 2,908 for all 4 years) and each run finishes in ~10 min.
    """
    print(f"\n{'='*65}", flush=True)
    print("  TAREA 1: Walk-Forward NY AM Reversal 2019-2022", flush=True)
    print("  Year-by-year backtest → slice 2-month windows", flush=True)
    print(f"{'='*65}", flush=True)

    tz = df_full.index.tz
    all_trades = []
    wf_results = []
    window_num = 0

    for year in [2019, 2020, 2021, 2022]:
        year_start = pd.Timestamp(f"{year}-01-01", tz=tz)
        year_end = pd.Timestamp(f"{year+1}-01-01", tz=tz)
        df_year = df_full[(df_full.index >= year_start) & (df_full.index < year_end)]

        if df_year.empty:
            print(f"\n  {year}: no data — skipping", flush=True)
            continue

        print(f"\n  {year}: {len(df_year):,} bars", flush=True)
        backtester = build_full_backtester(df_year, dynamic_bias=True)

        print(f"  Running backtest...", flush=True)
        t0 = time.perf_counter()
        result = backtester.run(df_year)
        elapsed = time.perf_counter() - t0
        print(f"  Done: {result.total_trades} trades, WR={result.win_rate:.1%}, "
              f"P&L=${result.total_pnl:+,.0f}  ({elapsed:.1f}s)", flush=True)

        all_trades.extend(result.trades)

        # Slice into 2-month windows
        for bimester in range(6):  # 6 bimonthly windows per year
            w_start = pd.Timestamp(f"{year}-{bimester*2+1:02d}-01", tz=tz)
            w_end = w_start + pd.DateOffset(months=2)
            window_num += 1

            trades = [t for t in result.trades if w_start <= t.entry_time < w_end]
            total = len(trades)
            wins = sum(1 for t in trades if t.pnl > 0)
            losses = sum(1 for t in trades if t.pnl <= 0)
            wr = wins / total if total > 0 else 0.0
            pnl = sum(t.pnl for t in trades)
            wins_pnl = sum(t.pnl for t in trades if t.pnl > 0)
            loss_pnl = abs(sum(t.pnl for t in trades if t.pnl <= 0))
            pf = wins_pnl / loss_pnl if loss_pnl > 0 else (float("inf") if wins_pnl > 0 else 0.0)
            positive = pnl > 0

            te_s = w_start.strftime("%Y-%m-%d")
            te_e = (w_end - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            ok = "+" if positive else ("-" if total > 0 else " ")
            pf_s = f"{pf:.2f}" if pf != float("inf") else " inf"
            print(f"    W{window_num:02d} [{te_s}→{te_e}]  trd={total:3d}  "
                  f"wr={wr:4.0%}  pnl=${pnl:>+8.0f}  pf={pf_s:>5}  {ok}", flush=True)

            wf_results.append({
                "window": window_num,
                "test_start": te_s, "test_end": te_e,
                "trades": total, "wins": wins, "losses": losses,
                "win_rate": wr, "total_pnl": pnl,
                "wins_pnl": wins_pnl, "losses_pnl": loss_pnl,
                "profit_factor": pf, "positive": positive,
            })

    return wf_results


def print_wf_summary(wf_results: list[dict]) -> None:
    if not wf_results:
        return
    total = len(wf_results)
    pos = sum(1 for r in wf_results if r["positive"])
    pct = pos / total if total else 0.0
    all_t = sum(r["trades"] for r in wf_results)
    all_w = sum(r["wins"] for r in wf_results)
    all_pnl = sum(r["total_pnl"] for r in wf_results)
    all_wp = sum(r["wins_pnl"] for r in wf_results)
    all_lp = sum(r["losses_pnl"] for r in wf_results)
    agg_wr = all_w / all_t if all_t else 0.0
    agg_pf = all_wp / all_lp if all_lp else 0.0

    gate = "PASS ✓" if pct >= 0.70 else "FAIL ✗"
    print(f"\n  {'─'*60}", flush=True)
    print(f"  Walk-Forward Summary", flush=True)
    print(f"  Windows positive   : {pos}/{total}  ({pct:.1%})   Gate>=70%: {gate}", flush=True)
    print(f"  Total trades       : {all_t}  |  Agg WR: {agg_wr:.1%}  |  Agg P&L: ${all_pnl:+,.0f}", flush=True)
    print(f"  Agg profit factor  : {agg_pf:.2f}", flush=True)


# ─── Combine Simulator 2023 ───────────────────────────────────────────────────

def run_combine_2023(df_2023: pd.DataFrame) -> tuple:
    print(f"\n{'='*65}", flush=True)
    print("  TAREA 2: Combine Simulator 2023", flush=True)
    print("  $50K start | $53K target | MLL $2K | DLL $1K", flush=True)
    print(f"{'='*65}", flush=True)

    backtester = build_full_backtester(df_2023, dynamic_bias=True)

    print(f"\n  Running 2023 backtest ({len(df_2023):,} bars)...", flush=True)
    t0 = time.perf_counter()
    result = backtester.run(df_2023, start_date="2023-01-01", end_date="2023-12-31")
    elapsed = time.perf_counter() - t0

    print(f"  Done: {result.total_trades} trades, WR={result.win_rate:.1%}, "
          f"P&L=${result.total_pnl:+,.0f}  ({elapsed:.1f}s)", flush=True)

    if result.total_trades == 0:
        print("  No trades — cannot simulate Combine.", flush=True)
        return result, []

    print("\n  Simulating sequential Combine attempts...", flush=True)
    attempts = _sequential_combine(result.trades)
    return result, attempts


def _sequential_combine(trades: list) -> list[dict]:
    """Simulate sequential $50K Combine attempts on a trade list."""
    remaining = sorted(trades, key=lambda t: t.entry_time)
    attempts = []

    while remaining and len(attempts) < 30:
        num = len(attempts) + 1
        result = simulate_combine(remaining)

        sorted_r = sorted(remaining, key=lambda t: t.entry_time)
        first_date = sorted_r[0].entry_time.date()

        if result.passed:
            # Find exact date profit target was crossed
            balance = cfg.TOPSTEP_ACCOUNT_SIZE
            target = balance + cfg.TOPSTEP_PROFIT_TARGET
            pass_date = None
            for t in sorted_r:
                balance += t.pnl
                if balance >= target:
                    pass_date = t.entry_time.date()
                    break
            if pass_date is None:
                pass_date = sorted_r[-1].entry_time.date()

            cal_days = (pass_date - first_date).days + 1
            attempts.append({
                "attempt": num, "passed": True, "failure_reason": None,
                "start_date": str(first_date), "end_date": str(pass_date),
                "trading_days": result.trading_days, "calendar_days": cal_days,
                "total_pnl": result.total_pnl, "trades": result.total_trades,
            })
            status_s = f"PASS  days={cal_days}"
            remaining = [t for t in remaining if t.entry_time.date() > pass_date]

        else:
            # Find failure cut-off date
            balance = cfg.TOPSTEP_ACCOUNT_SIZE
            peak_eod = cfg.TOPSTEP_ACCOUNT_SIZE
            daily_map: dict = {}
            fail_date = None
            prev_date = None

            for t in sorted_r:
                d = t.entry_time.date()
                if prev_date and d != prev_date:
                    if balance > peak_eod:
                        peak_eod = balance
                daily_map[d] = daily_map.get(d, 0.0) + t.pnl
                balance += t.pnl
                if peak_eod - balance >= cfg.TOPSTEP_MLL:
                    fail_date = d
                    break
                if daily_map[d] < -cfg.TOPSTEP_DLL:
                    fail_date = d
                    break
                prev_date = d

            if fail_date is None:
                fail_date = sorted_r[-1].entry_time.date()

            cal_days = (fail_date - first_date).days + 1
            reason = (result.failure_reason or "unknown")[:40]
            attempts.append({
                "attempt": num, "passed": False, "failure_reason": result.failure_reason,
                "start_date": str(first_date), "end_date": str(fail_date),
                "trading_days": result.trading_days, "calendar_days": cal_days,
                "total_pnl": result.total_pnl, "trades": result.total_trades,
            })
            status_s = f"FAIL  {reason}"
            remaining = [t for t in remaining if t.entry_time.date() > fail_date]

        print(f"  Attempt {num:2d}: {status_s}", flush=True)

    return attempts


def print_combine_summary(br: Optional[BacktestResult], attempts: list[dict]) -> None:
    if not attempts:
        return
    total = len(attempts)
    passes = sum(1 for a in attempts if a["passed"])
    fails = total - passes
    pass_days = [a["calendar_days"] for a in attempts if a["passed"] and a["calendar_days"]]
    avg_days = sum(pass_days) / len(pass_days) if pass_days else None

    print(f"\n  {'─'*60}", flush=True)
    print(f"  Combine Summary (2023)", flush=True)
    print(f"  Attempts: {total}  |  Passes: {passes}  |  Fails: {fails}", flush=True)
    if total:
        print(f"  Pass rate: {passes/total:.1%}", flush=True)
    if avg_days is not None:
        print(f"  Avg calendar days to pass: {avg_days:.1f}", flush=True)
    print(flush=True)
    print(f"  {'#':>2}  {'Result':>6}  {'Period':>24}  {'Trd':>4}  {'P&L':>9}  {'Days'}",
          flush=True)
    print(f"  {'─'*60}", flush=True)
    for a in attempts:
        status = "PASS" if a["passed"] else "FAIL"
        period = f"{a['start_date']} → {a['end_date']}"
        print(f"  {a['attempt']:>2}  {status:>6}  {period:>24}  "
              f"{a['trades']:>4}  ${a['total_pnl']:>+8.0f}  {a['calendar_days']}", flush=True)


# ─── Memory writer ────────────────────────────────────────────────────────────

def write_memory(wf: list[dict], br: Optional[BacktestResult],
                 attempts: list[dict], ts: str) -> None:
    path = ENGINE_ROOT.parent / ".claude" / "memory" / "project" / "backtest-results.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        "name: Walk-Forward + Combine Results (NY AM)",
        "description: Walk-forward 2019-2022 + Combine sim 2023 for NY AM Reversal with dynamic HTF bias",
        "type: project",
        "---",
        "",
        f"# Walk-Forward + Combine Results",
        f"_Run: {ts}_",
        "",
        "**Strategy:** NY AM Reversal + Dynamic HTF Bias (lookahead-free)",
        "**Data:** Databento NQ 1-min 2019-2022 + nq_1min.csv 2023",
        "**Approach:** One full backtest → slice into 2-month windows (fast proxy for walk-forward)",
        "",
    ]

    # Walk-forward section
    lines += ["## Tarea 1: Walk-Forward 2019-2022", ""]
    if wf:
        total = len(wf)
        pos = sum(1 for r in wf if r["positive"])
        pct = pos / total if total else 0.0
        all_t = sum(r["trades"] for r in wf)
        all_w = sum(r["wins"] for r in wf)
        all_pnl = sum(r["total_pnl"] for r in wf)
        all_wp = sum(r["wins_pnl"] for r in wf)
        all_lp = sum(r["losses_pnl"] for r in wf)
        agg_wr = all_w / all_t if all_t else 0.0
        agg_pf = all_wp / all_lp if all_lp else 0.0
        gate = "**PASS**" if pct >= 0.70 else "**FAIL**"

        lines += [
            "| Metric | Value |",
            "|--------|-------|",
            f"| Windows | {total} |",
            f"| Positive | {pos}/{total} ({pct:.1%}) |",
            f"| Gate >=70% | {gate} |",
            f"| Total trades | {all_t} |",
            f"| Agg win rate | {agg_wr:.1%} |",
            f"| Agg P&L | ${all_pnl:+,.0f} |",
            f"| Agg profit factor | {agg_pf:.2f} |",
            "",
            "| # | Test Window | Trades | WR | P&L | PF | + |",
            "|---|-------------|--------|----|-----|----|---|",
        ]
        for r in wf:
            ok = "✓" if r["positive"] else "✗"
            pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] != float("inf") else "inf"
            lines.append(
                f"| {r['window']} | {r['test_start']} → {r['test_end']} "
                f"| {r['trades']} | {r['win_rate']:.0%} "
                f"| ${r['total_pnl']:+,.0f} | {pf} | {ok} |"
            )
    else:
        lines += ["No results (data or strategy issue)."]

    # Combine section
    lines += ["", "## Tarea 2: Combine Simulator 2023", ""]
    if br:
        lines += [
            "### 2023 Full-Year Backtest",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total trades | {br.total_trades} |",
            f"| Win rate | {br.win_rate:.1%} |",
            f"| Total P&L | ${br.total_pnl:+,.0f} |",
            "",
        ]
    if attempts:
        total_a = len(attempts)
        passes_a = sum(1 for a in attempts if a["passed"])
        pass_days_a = [a["calendar_days"] for a in attempts if a["passed"] and a["calendar_days"]]
        avg_d = sum(pass_days_a) / len(pass_days_a) if pass_days_a else None

        lines += [
            "### Sequential Combine Attempts",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Attempts | {total_a} |",
            f"| Passes | {passes_a} |",
            f"| Fails | {total_a - passes_a} |",
            f"| Pass rate | {passes_a/total_a:.1%} |",
            f"| Avg days to pass | {f'{avg_d:.1f}' if avg_d else 'N/A'} |",
            "",
            "| # | Result | Period | Trades | P&L | Days |",
            "|---|--------|--------|--------|-----|------|",
        ]
        for a in attempts:
            status = "PASS" if a["passed"] else "FAIL"
            lines.append(
                f"| {a['attempt']} | {status} | {a['start_date']} → {a['end_date']} "
                f"| {a['trades']} | ${a['total_pnl']:+,.0f} | {a['calendar_days']} |"
            )
    else:
        lines += ["No combine attempts."]

    lines += [
        "",
        "**Why:** Strategy Lab gate 4 requires >=70% walk-forward windows positive.",
        "**How to apply:** Gate FAIL → strategy stays in Lab, not promoted to production.",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Memory written -> {path}", flush=True)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    from datetime import datetime, timezone
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    data_dir = ENGINE_ROOT.parent / "data"
    databento_path = data_dir / "nq_1minute.csv"
    simple_path = data_dir / "nq_1min.csv"

    wf_results = []
    combine_result = None
    combine_attempts = []

    # ── TAREA 1 ───────────────────────────────────────────────────────────
    if databento_path.exists():
        mb = databento_path.stat().st_size / 1024 / 1024
        print(f"\nLoading Databento NQ (2019-2022)  [{mb:.0f} MB, ~90s]...", flush=True)
        t0 = time.perf_counter()
        try:
            df_db = load_databento_ohlcv_1m(
                databento_path,
                start_date="2019-01-01",
                end_date="2022-12-31",
                symbol_prefix="NQ",
            )
            print(f"Loaded {len(df_db):,} bars in {time.perf_counter()-t0:.1f}s", flush=True)
            wf_results = run_walk_forward(df_db)
        except Exception as e:
            print(f"ERROR loading Databento: {e}", flush=True)
            import traceback; traceback.print_exc()
    else:
        print(f"\nWARN: {databento_path} not found — skipping Tarea 1", flush=True)

    print_wf_summary(wf_results)

    # ── TAREA 2 ───────────────────────────────────────────────────────────
    if simple_path.exists():
        print(f"\nLoading 2023 NQ data...", flush=True)
        t0 = time.perf_counter()
        try:
            df_raw = load_data_csv(simple_path)
            tz = df_raw.index.tz
            df_2023 = df_raw[
                (df_raw.index >= pd.Timestamp("2023-01-01", tz=tz)) &
                (df_raw.index < pd.Timestamp("2024-01-01", tz=tz))
            ]
            print(f"Loaded {len(df_2023):,} bars in {time.perf_counter()-t0:.1f}s", flush=True)
            combine_result, combine_attempts = run_combine_2023(df_2023)
        except Exception as e:
            print(f"ERROR loading 2023 data: {e}", flush=True)
            import traceback; traceback.print_exc()
    else:
        print(f"\nWARN: {simple_path} not found — skipping Tarea 2", flush=True)

    print_combine_summary(combine_result, combine_attempts)

    write_memory(wf_results, combine_result, combine_attempts, run_ts)

    print(f"\n{'='*65}", flush=True)
    print("  DONE", flush=True)
    print(f"{'='*65}\n", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
