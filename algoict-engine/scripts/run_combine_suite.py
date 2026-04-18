"""
scripts/run_combine_suite.py
============================
Full combine simulator suite: Job 1 ($50K) + Job 2 ($150K).

  Job 1 — 6 runs × 30 attempts = 180 combine attempts
  Job 2 — 4 runs × 30 attempts = 120 combine attempts

Usage:
    cd algoict-engine
    python scripts/run_combine_suite.py

Output is written to both stdout and combine_suite.log in the engine root.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

os.environ.setdefault("PYTHONUNBUFFERED", "1")

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── Logging: stdout + file ─────────────────────────────────────────────────
LOG_FILE = ENGINE_ROOT / "combine_suite.log"
_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8", mode="w"))
except Exception:
    pass
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s",
                    handlers=_handlers)

def p(*args, **kwargs):
    """Print + flush."""
    print(*args, flush=True, **kwargs)

p("=== AlgoICT Combine Suite ===")
p(f"Log: {LOG_FILE}")
p("Loading modules...")

import pandas as pd

from backtest.backtester import Backtester, BacktestResult
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

p("OK")

# ── Account configs ────────────────────────────────────────────────────────

@dataclass
class AccountConfig:
    label: str
    starting_balance: float
    profit_target: float
    mll: float
    dll: float

ACCT_50K = AccountConfig(
    label="$50K", starting_balance=50_000.0,
    profit_target=3_000.0, mll=2_000.0, dll=1_000.0,
)
ACCT_150K = AccountConfig(
    label="$150K", starting_balance=150_000.0,
    profit_target=9_000.0, mll=4_500.0, dll=1_500.0,
)

# ── Data path — search up the tree (handles worktrees and normal layout) ──

def _find_data() -> Path:
    candidates = [
        ENGINE_ROOT.parent / "data" / "nq_1minute.csv",           # normal layout
        ENGINE_ROOT.parent.parent.parent.parent.parent / "data" / "nq_1minute.csv",  # worktree
    ]
    # Walk up looking for a data/nq_1minute.csv sibling
    p_dir = ENGINE_ROOT
    for _ in range(8):
        c = p_dir / "data" / "nq_1minute.csv"
        if c.exists():
            candidates.insert(0, c)
            break
        p_dir = p_dir.parent
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # let it fail with a useful path

DATA_PATH = _find_data()
if not DATA_PATH.exists():
    p(f"ERROR: data not found. Tried: {DATA_PATH}")
    sys.exit(1)

# ── HTF bias wrapper ───────────────────────────────────────────────────────

class DynamicBiasStrategy:
    """Lookahead-free HTF bias (copied from run_all_backtests)."""
    def __init__(self, inner, df_daily, df_weekly):
        self._inner = inner
        self._df_daily = df_daily
        self._df_weekly = df_weekly
        self._detector = HTFBiasDetector()
        self._current_ts = None
        self._inner.htf_bias_fn = self._dynamic_bias

    def _dynamic_bias(self, current_price, *_, **__):
        if self._current_ts is None:
            return self._detector._neutral_result()
        cutoff = self._current_ts.normalize()
        pd_slice = self._df_daily[self._df_daily.index < cutoff]
        pw_slice = self._df_weekly[self._df_weekly.index < cutoff]
        if pd_slice.empty or pw_slice.empty:
            return self._detector._neutral_result()
        return self._detector.determine_bias(pd_slice, pw_slice, float(current_price))

    def evaluate(self, candles_entry, candles_context):
        if not candles_entry.empty:
            self._current_ts = candles_entry.index[-1]
        return self._inner.evaluate(candles_entry, candles_context)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _seed_levels(df_1min, liquidity):
    tmp = TimeframeManager()
    seeded = []
    try:
        df_d = tmp.aggregate(df_1min, "D")
        for i in range(len(df_d)):
            seeded.extend(liquidity.build_key_levels(df_daily=df_d.iloc[i:i+1]))
    except Exception:
        pass
    try:
        df_w = tmp.aggregate(df_1min, "W")
        for i in range(len(df_w)):
            seeded.extend(liquidity.build_key_levels(df_weekly=df_w.iloc[i:i+1]))
    except Exception:
        pass
    return seeded


def build_backtester(
    df_1min: pd.DataFrame,
    trade_management: str = "fixed",
    topstep_mode: bool = False,
    acct: AccountConfig = ACCT_50K,
) -> tuple[Backtester, RiskManager]:
    """Build NY AM backtester. Returns (backtester, risk_mgr)."""
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
        "tracked_levels": _seed_levels(df_1min, liquidity),
    }

    risk_mgr = RiskManager()
    if topstep_mode:
        risk_mgr.enable_topstep_mode(
            starting_balance=acct.starting_balance,
            mll=acct.mll,
            profit_target=acct.profit_target,
            warning_pct=0.40,
            caution_pct=0.60,
            stop_pct=0.85,
        )

    tf_mgr = TimeframeManager()
    session_mgr = SessionManager()

    def static_bullish(*_, **__):
        return BiasResult(direction="bullish", premium_discount="discount",
                          htf_levels={}, confidence="high",
                          weekly_bias="bullish", daily_bias="bullish")

    inner = NYAMReversalStrategy(detectors, risk_mgr, session_mgr, static_bullish)
    # KILL_ZONES already = ("london", "ny_am", "ny_pm") by default

    # Dynamic bias
    strategy = inner
    if not df_1min.empty:
        try:
            tmp = TimeframeManager()
            df_d = tmp.aggregate(df_1min, "D")
            df_w = tmp.aggregate(df_1min, "W")
            if not df_d.empty and not df_w.empty:
                strategy = DynamicBiasStrategy(inner, df_d, df_w)
        except Exception:
            pass

    bt = Backtester(strategy, detectors, risk_mgr, tf_mgr, session_mgr,
                    trade_management=trade_management)
    return bt, risk_mgr


# ── Combine simulator (parameterized — no config monkeypatching) ───────────

def _simulate_combine_params(
    trades: list,
    starting_balance: float,
    profit_target: float,
    mll: float,
    dll: float,
) -> dict:
    """
    Simulate Topstep combine rules with explicit params.
    Returns dict with keys: passed, failure_reason, total_pnl, trading_days,
                            ending_balance, peak_balance.
    """
    import datetime

    if not trades:
        return {"passed": False, "failure_reason": "no_trades",
                "total_pnl": 0.0, "trading_days": 0,
                "ending_balance": starting_balance, "peak_balance": starting_balance}

    sorted_trades = sorted(trades, key=lambda t: t.entry_time)

    days_map: dict = {}
    for t in sorted_trades:
        try:
            d = t.entry_time.date()
        except AttributeError:
            d = t.entry_time.to_pydatetime().date()
        days_map.setdefault(d, []).append(t)

    balance = starting_balance
    peak_eod = starting_balance
    best_day_pnl = 0.0
    failure_reason = None

    for date in sorted(days_map.keys()):
        daily_pnl = 0.0
        for t in days_map[date]:
            daily_pnl += t.pnl
            balance += t.pnl
            if peak_eod - balance >= mll:
                failure_reason = f"mll_breach on {date}: dd=${peak_eod - balance:.0f}"
                return {"passed": False, "failure_reason": failure_reason,
                        "total_pnl": balance - starting_balance, "trading_days": len(days_map),
                        "ending_balance": balance, "peak_balance": peak_eod}
        if daily_pnl < -dll:
            failure_reason = f"dll_breach on {date}: daily=${daily_pnl:.0f}"
            return {"passed": False, "failure_reason": failure_reason,
                    "total_pnl": balance - starting_balance, "trading_days": len(days_map),
                    "ending_balance": balance, "peak_balance": peak_eod}
        if balance > peak_eod:
            peak_eod = balance
        if daily_pnl > best_day_pnl:
            best_day_pnl = daily_pnl

    total_pnl = balance - starting_balance
    trading_days = len(days_map)

    if trading_days < 5:
        return {"passed": False,
                "failure_reason": f"insufficient_days: {trading_days}<5",
                "total_pnl": total_pnl, "trading_days": trading_days,
                "ending_balance": balance, "peak_balance": peak_eod}

    if total_pnl < profit_target:
        return {"passed": False,
                "failure_reason": f"target_not_reached: ${total_pnl:.0f}<${profit_target:.0f}",
                "total_pnl": total_pnl, "trading_days": trading_days,
                "ending_balance": balance, "peak_balance": peak_eod}

    if total_pnl > 0 and best_day_pnl >= 0.5 * total_pnl:
        return {"passed": False,
                "failure_reason": f"consistency: best_day=${best_day_pnl:.0f}>={50:.0f}%",
                "total_pnl": total_pnl, "trading_days": trading_days,
                "ending_balance": balance, "peak_balance": peak_eod}

    return {"passed": True, "failure_reason": None,
            "total_pnl": total_pnl, "trading_days": trading_days,
            "ending_balance": balance, "peak_balance": peak_eod}


def run_combine_attempts(
    trades: list,
    label: str,
    acct: AccountConfig,
    max_attempts: int = 30,
) -> list[dict]:
    """
    Sequential combine simulation: consume windows from the trade list.
    Each attempt starts where the previous ended.
    """
    remaining = sorted(trades, key=lambda t: t.entry_time)
    attempts = []

    while remaining and len(attempts) < max_attempts:
        num = len(attempts) + 1
        res = _simulate_combine_params(
            remaining,
            starting_balance=acct.starting_balance,
            profit_target=acct.profit_target,
            mll=acct.mll,
            dll=acct.dll,
        )
        sorted_r = remaining  # already sorted

        first_date = sorted_r[0].entry_time.date()

        if res["passed"]:
            # Find the date when balance first crossed the target
            bal = acct.starting_balance
            pass_date = sorted_r[-1].entry_time.date()
            for t in sorted_r:
                bal += t.pnl
                if bal >= acct.starting_balance + acct.profit_target:
                    pass_date = t.entry_time.date()
                    break
            cal_days = (pass_date - first_date).days + 1
            attempts.append({
                "attempt": num, "passed": True, "failure_reason": None,
                "start_date": str(first_date), "end_date": str(pass_date),
                "calendar_days": cal_days, "total_pnl": res["total_pnl"],
            })
            remaining = [t for t in remaining if t.entry_time.date() > pass_date]
            p(f"    Attempt {num:2d}: PASS  cal_days={cal_days}  pnl=${res['total_pnl']:+,.0f}")
        else:
            # Find the date of failure
            bal = acct.starting_balance
            peak = acct.starting_balance
            daily_map: dict = {}
            fail_date = sorted_r[-1].entry_time.date()
            prev_date = None
            for t in sorted_r:
                d = t.entry_time.date()
                if prev_date and d != prev_date:
                    if bal > peak:
                        peak = bal
                daily_map[d] = daily_map.get(d, 0.0) + t.pnl
                bal += t.pnl
                if peak - bal >= acct.mll:
                    fail_date = d
                    break
                if daily_map[d] < -acct.dll:
                    fail_date = d
                    break
                prev_date = d
            cal_days = (fail_date - first_date).days + 1
            reason = (res["failure_reason"] or "unknown")[:50]
            attempts.append({
                "attempt": num, "passed": False, "failure_reason": res["failure_reason"],
                "start_date": str(first_date), "end_date": str(fail_date),
                "calendar_days": cal_days, "total_pnl": res["total_pnl"],
            })
            remaining = [t for t in remaining if t.entry_time.date() > fail_date]
            p(f"    Attempt {num:2d}: FAIL  {reason}")

    return attempts


def summarise_attempts(attempts: list[dict]) -> dict:
    """Compute pass_rate and bottleneck breakdown from attempt list."""
    if not attempts:
        return {"passes": 0, "total": 0, "pass_rate": 0.0,
                "avg_days_pass": None, "bottleneck": {}}
    passes = [a for a in attempts if a["passed"]]
    fails  = [a for a in attempts if not a["passed"]]
    bottleneck: dict = defaultdict(int)
    for a in fails:
        r = a.get("failure_reason") or "unknown"
        if "mll_breach" in r:
            bottleneck["mll_breach"] += 1
        elif "dll_breach" in r:
            bottleneck["dll_breach"] += 1
        elif "target_not_reached" in r:
            bottleneck["target_not_reached"] += 1
        elif "consistency" in r:
            bottleneck["consistency"] += 1
        elif "insufficient_days" in r:
            bottleneck["insufficient_days"] += 1
        else:
            bottleneck["other"] += 1
    avg_days = (sum(a["calendar_days"] for a in passes) / len(passes)) if passes else None
    return {
        "passes": len(passes),
        "total": len(attempts),
        "pass_rate": len(passes) / len(attempts),
        "avg_days_pass": avg_days,
        "bottleneck": dict(bottleneck),
    }


# ── Run one configuration ──────────────────────────────────────────────────

def run_config(
    label: str,
    df_slice: pd.DataFrame,
    trade_management: str,
    topstep_mode: bool,
    acct: AccountConfig,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_attempts: int = 30,
) -> dict:
    """
    Build backtester → run backtest → run combine simulation.
    Returns full result dict.
    """
    p(f"\n{'─'*70}")
    p(f"  RUN: {label}")
    p(f"       trade_management={trade_management}  topstep_mode={topstep_mode}")
    p(f"       account={acct.label}  period={start_date or 'all'}→{end_date or 'end'}")
    p(f"{'─'*70}")

    t0 = time.perf_counter()
    bt, _ = build_backtester(df_slice, trade_management=trade_management,
                             topstep_mode=topstep_mode, acct=acct)
    result = bt.run(df_slice, start_date=start_date, end_date=end_date)
    bt_elapsed = time.perf_counter() - t0

    trades = result.trades
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl <= 0)
    win_rate = wins / len(trades) if trades else 0.0
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    p(f"  Backtest: {len(trades)} trades  WR={win_rate:.1%}  PF={pf:.2f}"
      f"  P&L=${result.total_pnl:+,.0f}  ({bt_elapsed:.0f}s)")

    if not trades:
        p("  WARNING: no trades — skipping combine sim")
        return {"label": label, "attempts": [], "summary": summarise_attempts([]),
                "bt_trades": 0, "bt_pnl": 0.0, "bt_win_rate": 0.0, "bt_pf": 0.0}

    p(f"  Running combine sim ({max_attempts} attempts)...")
    c0 = time.perf_counter()
    attempts = run_combine_attempts(trades, label, acct=acct, max_attempts=max_attempts)
    c_elapsed = time.perf_counter() - c0

    summary = summarise_attempts(attempts)
    p(f"  RESULT: {summary['passes']}/{summary['total']} pass"
      f"  rate={summary['pass_rate']:.1%}"
      f"  avg_days_to_pass={summary['avg_days_pass']:.1f}" if summary['avg_days_pass'] else
      f"  RESULT: {summary['passes']}/{summary['total']} pass  rate={summary['pass_rate']:.1%}")
    p(f"  Bottleneck: {summary['bottleneck']}")
    p(f"  ({c_elapsed:.0f}s)")

    return {
        "label": label,
        "attempts": attempts,
        "summary": summary,
        "bt_trades": len(trades),
        "bt_pnl": result.total_pnl,
        "bt_win_rate": win_rate,
        "bt_pf": pf,
    }


def print_summary(all_results: list[dict], job_label: str) -> None:
    p(f"\n{'═'*70}")
    p(f"  SUMMARY — {job_label}")
    p(f"{'═'*70}")
    p(f"  {'Run':<35} {'Trades':>7} {'WR':>6} {'PF':>6} {'Pass':>6} {'Rate':>7} {'AvgDays':>8} {'Bottleneck'}")
    p(f"  {'-'*35} {'-'*7} {'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*8} {'-'*20}")
    for r in all_results:
        s = r["summary"]
        bt_str = f"{s['passes']}/{s['total']}"
        avg = f"{s['avg_days_pass']:.1f}" if s['avg_days_pass'] else "  —"
        bn = ", ".join(f"{k}={v}" for k, v in s["bottleneck"].items())[:30]
        p(f"  {r['label']:<35} {r['bt_trades']:>7} {r['bt_win_rate']:>5.1%}"
          f" {r['bt_pf']:>6.2f} {bt_str:>6} {s['pass_rate']:>7.1%} {avg:>8}  {bn}")


# ── MAIN ───────────────────────────────────────────────────────────────────

def main() -> None:
    wall_start = time.perf_counter()

    p(f"\nLoading data from {DATA_PATH}...")
    t0 = time.perf_counter()
    df_all = load_databento_ohlcv_1m(str(DATA_PATH))
    p(f"Loaded {len(df_all):,} rows  {df_all.index[0].date()} → {df_all.index[-1].date()}"
      f"  ({time.perf_counter() - t0:.0f}s)")

    # Pre-slice full years once to avoid repeated filtering
    def _slice(start: str, end: str) -> pd.DataFrame:
        tz = df_all.index.tz
        return df_all[
            (df_all.index >= pd.Timestamp(start, tz=tz)) &
            (df_all.index < pd.Timestamp(end, tz=tz) + pd.Timedelta(days=1))
        ]

    df_2023 = _slice("2023-01-01", "2023-12-31")
    df_2024 = _slice("2024-01-01", "2024-12-31")
    df_2025 = _slice("2025-01-01", "2025-12-31")

    p(f"  2023: {len(df_2023):,} rows  2024: {len(df_2024):,} rows  2025: {len(df_2025):,} rows")

    # ─────────────────────────────────────────────────────────────────────
    # JOB 1 — $50K COMBINE
    # ─────────────────────────────────────────────────────────────────────
    p(f"\n{'█'*70}")
    p(f"  JOB 1 — $50K COMBINE  (MLL=$2,000  Target=$3,000  DLL=$1,000)")
    p(f"{'█'*70}")

    job1_results = []

    job1_results.append(run_config(
        label="A  $50K | MLL active | fixed   | 2024",
        df_slice=df_2024,
        trade_management="fixed",
        topstep_mode=True,
        acct=ACCT_50K,
    ))

    job1_results.append(run_config(
        label="B  $50K | MLL active | trailing| 2024",
        df_slice=df_2024,
        trade_management="trailing",
        topstep_mode=True,
        acct=ACCT_50K,
    ))

    job1_results.append(run_config(
        label="C  $50K | MLL off    | fixed   | 2024",
        df_slice=df_2024,
        trade_management="fixed",
        topstep_mode=False,
        acct=ACCT_50K,
    ))

    job1_results.append(run_config(
        label="D  $50K | MLL off    | trailing| 2024",
        df_slice=df_2024,
        trade_management="trailing",
        topstep_mode=False,
        acct=ACCT_50K,
    ))

    job1_results.append(run_config(
        label="B2 $50K | MLL active | trailing| 2023",
        df_slice=df_2023,
        trade_management="trailing",
        topstep_mode=True,
        acct=ACCT_50K,
    ))

    job1_results.append(run_config(
        label="B3 $50K | MLL active | trailing| 2025",
        df_slice=df_2025,
        trade_management="trailing",
        topstep_mode=True,
        acct=ACCT_50K,
    ))

    print_summary(job1_results, "JOB 1 — $50K COMBINE")

    p(f"\n>>> JOB 1 COMPLETE — elapsed {(time.perf_counter() - wall_start)/60:.1f} min <<<")

    # ─────────────────────────────────────────────────────────────────────
    # JOB 2 — $150K COMBINE
    # ─────────────────────────────────────────────────────────────────────
    p(f"\n{'█'*70}")
    p(f"  JOB 2 — $150K COMBINE  (MLL=$4,500  Target=$9,000  DLL=$1,500)")
    p(f"{'█'*70}")

    job2_results = []

    job2_results.append(run_config(
        label="E  $150K| MLL active | trailing| 2024",
        df_slice=df_2024,
        trade_management="trailing",
        topstep_mode=True,
        acct=ACCT_150K,
    ))

    job2_results.append(run_config(
        label="F  $150K| MLL active | fixed   | 2024",
        df_slice=df_2024,
        trade_management="fixed",
        topstep_mode=True,
        acct=ACCT_150K,
    ))

    job2_results.append(run_config(
        label="E2 $150K| MLL active | trailing| 2023",
        df_slice=df_2023,
        trade_management="trailing",
        topstep_mode=True,
        acct=ACCT_150K,
    ))

    job2_results.append(run_config(
        label="E3 $150K| MLL active | trailing| 2025",
        df_slice=df_2025,
        trade_management="trailing",
        topstep_mode=True,
        acct=ACCT_150K,
    ))

    print_summary(job2_results, "JOB 2 — $150K COMBINE")

    # ─────────────────────────────────────────────────────────────────────
    # FINAL TABLE
    # ─────────────────────────────────────────────────────────────────────
    all_results = {r["label"].split()[0]: r for r in job1_results + job2_results}
    total_elapsed = (time.perf_counter() - wall_start) / 60

    p(f"\n{'═'*70}")
    p("  FINAL TABLE — ALL RUNS")
    p(f"{'═'*70}")
    p(f"  {'Account':<8} {'MLL':<8} {'Mgmt':<10} {'Year':<6} {'Run':<4}"
      f" {'Pass':>8} {'Rate':>7} {'AvgDays':>8} {'Bottleneck'}")
    p(f"  {'-'*8} {'-'*8} {'-'*10} {'-'*6} {'-'*4}"
      f" {'-'*8} {'-'*7} {'-'*8} {'-'*25}")

    table_rows = [
        ("$50K",  "active", "fixed",    "2024", "A"),
        ("$50K",  "active", "trailing", "2024", "B"),
        ("$50K",  "off",    "fixed",    "2024", "C"),
        ("$50K",  "off",    "trailing", "2024", "D"),
        ("$50K",  "active", "trailing", "2023", "B2"),
        ("$50K",  "active", "trailing", "2025", "B3"),
        ("$150K", "active", "trailing", "2024", "E"),
        ("$150K", "active", "fixed",    "2024", "F"),
        ("$150K", "active", "trailing", "2023", "E2"),
        ("$150K", "active", "trailing", "2025", "E3"),
    ]

    for acct_lbl, mll_lbl, mgmt, year, run_id in table_rows:
        r = all_results.get(run_id)
        if r is None:
            p(f"  {acct_lbl:<8} {mll_lbl:<8} {mgmt:<10} {year:<6} {run_id:<4}  (not run)")
            continue
        s = r["summary"]
        bt_str = f"{s['passes']}/{s['total']}"
        avg = f"{s['avg_days_pass']:.1f}" if s['avg_days_pass'] else "  —"
        bn = ", ".join(f"{k}={v}" for k, v in s["bottleneck"].items())[:28]
        p(f"  {acct_lbl:<8} {mll_lbl:<8} {mgmt:<10} {year:<6} {run_id:<4}"
          f" {bt_str:>8} {s['pass_rate']:>7.1%} {avg:>8}  {bn}")

    p(f"\n{'─'*70}")

    # Recommendation
    p("\n  RECOMMENDATION")
    p("  " + "─"*50)

    # Find best pass rate among trailing runs
    trailing_50k = [r for r in job1_results if "trailing" in r["label"]]
    fixed_50k    = [r for r in job1_results if "fixed" in r["label"]]
    trailing_150k = [r for r in job2_results if "trailing" in r["label"]]
    fixed_150k    = [r for r in job2_results if "fixed" in r["label"]]

    def best(runs):
        if not runs:
            return None, 0.0
        best_r = max(runs, key=lambda r: r["summary"]["pass_rate"])
        return best_r["label"].split()[0], best_r["summary"]["pass_rate"]

    bt_id, bt_rate = best(trailing_50k)
    bf_id, bf_rate = best(fixed_50k)
    et_id, et_rate = best(trailing_150k)
    ef_id, ef_rate = best(fixed_150k)

    p(f"  $50K  trailing: best {bt_id}  {bt_rate:.1%}")
    p(f"  $50K  fixed:    best {bf_id}  {bf_rate:.1%}")
    p(f"  $150K trailing: best {et_id}  {et_rate:.1%}")
    p(f"  $150K fixed:    best {ef_id}  {ef_rate:.1%}")
    p()

    best_50k_rate = max(bt_rate, bf_rate)
    best_150k_rate = max(et_rate, ef_rate)
    recommended_acct = "$50K" if best_50k_rate >= best_150k_rate else "$150K"
    recommended_mgmt = "trailing" if bt_rate >= bf_rate else "fixed"

    p(f"  Recommended account:        {recommended_acct}")
    p(f"  Recommended trade mgmt:     {recommended_mgmt}")

    any_viable = best_50k_rate >= 0.20 or best_150k_rate >= 0.20
    p(f"  Ready for Combine attempt:  {'YES — pass rate > 20%' if any_viable else 'NO — pass rate < 20% on all configs'}")
    p()
    p(f"  Total wall time: {total_elapsed:.1f} min")
    p(f"  Log saved to:    {LOG_FILE}")
    p(f"{'═'*70}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        p("\nInterrupted.")
        sys.exit(130)
    except Exception as exc:
        import traceback
        p(f"\nFATAL: {exc}")
        traceback.print_exc()
        sys.exit(1)
