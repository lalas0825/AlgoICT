"""
scripts/run_combine_extended.py
================================
Extended Combine Simulator — $50K and $150K variants.

Loads 2023 and 2024 trades using best config (NYAM London, trailing).
Runs sequential combine attempts for both account sizes.

Usage:
    python scripts/run_combine_extended.py
    python scripts/run_combine_extended.py --years 2024
    python scripts/run_combine_extended.py --max-attempts 20
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import defaultdict
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

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

import pandas as pd

from backtest.backtester import Backtester
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

DATA_DIR = ENGINE_ROOT.parent / "data"
DATABENTO_PATH = DATA_DIR / "nq_1minute.csv"

# ── Best config from FASE 1/2 ──────────────────────────────────────────────
BEST_KZ = ("london",)
BEST_TM = "trailing"
BEST_STRATEGY = "nyam"

# ── $150K Combine params ──────────────────────────────────────────────────
ACCOUNT_150K = 150_000.0
MLL_150K     =   4_500.0   # 3% of $150K  (vs 4% for $50K)
DLL_150K     =   3_000.0   # scaled 3× from $1K
PT_150K      =   9_000.0   # 6% of $150K  (vs 6% for $50K)


# ---------------------------------------------------------------------------
# Dynamic bias (lookahead-free) — copied from run_all_backtests.py
# ---------------------------------------------------------------------------
class DynamicBiasStrategy:
    def __init__(self, inner, df_daily, df_weekly):
        self._inner  = inner
        self._detector = HTFBiasDetector()
        self._df_daily = df_daily
        self._df_weekly = df_weekly
        self._current_ts = None
        self._inner.htf_bias_fn = self._dynamic_bias

    def _dynamic_bias(self, current_price, *_, **__):
        if self._current_ts is None:
            return self._detector._neutral_result()
        cutoff = self._current_ts.normalize()
        pd_sl = self._df_daily[self._df_daily.index < cutoff]
        pw_sl = self._df_weekly[self._df_weekly.index < cutoff]
        if pd_sl.empty or pw_sl.empty:
            return self._detector._neutral_result()
        return self._detector.determine_bias(pd_sl, pw_sl, float(current_price))

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


def build_backtester(df_1min, kill_zones_override=BEST_KZ,
                     trade_management=BEST_TM) -> Backtester:
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
    tf_mgr = TimeframeManager()
    session_mgr = SessionManager()

    def static_bullish(*_, **__):
        return BiasResult(direction="bullish", premium_discount="discount",
                          htf_levels={}, confidence="high",
                          weekly_bias="bullish", daily_bias="bullish")

    inner = NYAMReversalStrategy(detectors, risk_mgr, session_mgr, static_bullish)
    if kill_zones_override:
        inner.KILL_ZONES = kill_zones_override
        inner._trades_by_zone = {z: 0 for z in kill_zones_override}

    tmp = TimeframeManager()
    try:
        df_d = tmp.aggregate(df_1min, "D")
        df_w = tmp.aggregate(df_1min, "W")
        strategy = DynamicBiasStrategy(inner, df_d, df_w) if (not df_d.empty and not df_w.empty) else inner
    except Exception:
        strategy = inner

    return Backtester(strategy, detectors, risk_mgr, tf_mgr, session_mgr,
                      trade_management=trade_management)


# ---------------------------------------------------------------------------
# Generalised sequential combine sim
# ---------------------------------------------------------------------------
def simulate_combine_custom(
    trades: list,
    account_size: float,
    mll: float,
    dll: float,
    profit_target: float,
    min_trading_days: int = 5,
    consistency_pct: float = 0.50,
):
    """
    Replicate simulate_combine logic but with explicit params.
    Returns a CombineResult-like dict.
    """
    if not trades:
        return {"passed": False, "failure_reason": "no_trades",
                "starting_balance": account_size, "ending_balance": account_size,
                "peak_balance": account_size, "total_pnl": 0.0,
                "total_trades": 0, "trading_days": 0, "total_days": 0,
                "best_day_pnl": 0.0, "best_day_date": None,
                "profit_target": profit_target, "mll_limit": mll, "dll_limit": dll}

    sorted_trades = sorted(trades, key=lambda t: t.entry_time)

    days_map: dict = {}
    for t in sorted_trades:
        try:
            d = t.entry_time.date()
        except AttributeError:
            d = t.entry_time.to_pydatetime().date()
        days_map.setdefault(d, []).append(t)

    balance = account_size
    peak_eod = account_size
    day_records = []
    failure_reason = None
    best_day_pnl = 0.0
    best_day_date = None

    for date in sorted(days_map.keys()):
        day_trades = days_map[date]
        daily_pnl = 0.0
        for t in day_trades:
            daily_pnl += t.pnl
            balance += t.pnl
            if peak_eod - balance >= mll:
                failure_reason = (
                    f"mll_breach on {date}: "
                    f"balance=${balance:.2f} "
                    f"(peak_eod=${peak_eod:.2f}, "
                    f"drawdown=${peak_eod - balance:.2f} >= mll=${mll})"
                )
                day_records.append({"date": date, "pnl": daily_pnl, "balance_eod": balance})
                return _build(False, failure_reason, account_size, balance, peak_eod,
                               day_records, sorted_trades, best_day_pnl, best_day_date,
                               profit_target, mll, dll)

        if daily_pnl < -dll:
            failure_reason = f"dll_breach on {date}: daily_pnl=${daily_pnl:.2f} < -dll=${dll}"
            day_records.append({"date": date, "pnl": daily_pnl, "balance_eod": balance})
            return _build(False, failure_reason, account_size, balance, peak_eod,
                           day_records, sorted_trades, best_day_pnl, best_day_date,
                           profit_target, mll, dll)

        if balance > peak_eod:
            peak_eod = balance
        if daily_pnl > best_day_pnl:
            best_day_pnl = daily_pnl
            best_day_date = date
        day_records.append({"date": date, "pnl": daily_pnl, "balance_eod": balance})

    total_pnl = balance - account_size
    trading_days = len(days_map)

    if trading_days < min_trading_days:
        failure_reason = f"insufficient_trading_days: {trading_days} < {min_trading_days}"
        return _build(False, failure_reason, account_size, balance, peak_eod,
                       day_records, sorted_trades, best_day_pnl, best_day_date,
                       profit_target, mll, dll)

    if total_pnl < profit_target:
        failure_reason = f"profit_target_not_reached: pnl=${total_pnl:.2f} < target=${profit_target}"
        return _build(False, failure_reason, account_size, balance, peak_eod,
                       day_records, sorted_trades, best_day_pnl, best_day_date,
                       profit_target, mll, dll)

    if best_day_pnl >= consistency_pct * total_pnl:
        failure_reason = (
            f"consistency_rule_violated: best_day=${best_day_pnl:.0f} "
            f">= {consistency_pct:.0%} of total_pnl=${total_pnl:.0f}"
        )
        return _build(False, failure_reason, account_size, balance, peak_eod,
                       day_records, sorted_trades, best_day_pnl, best_day_date,
                       profit_target, mll, dll)

    return _build(True, None, account_size, balance, peak_eod,
                   day_records, sorted_trades, best_day_pnl, best_day_date,
                   profit_target, mll, dll)


def _build(passed, failure_reason, account_size, balance, peak_eod,
           day_records, sorted_trades, best_day_pnl, best_day_date,
           profit_target, mll, dll):
    total_days = 0
    if day_records:
        first_d = day_records[0]["date"]
        last_d = day_records[-1]["date"]
        total_days = (last_d - first_d).days + 1
    return {
        "passed": passed,
        "failure_reason": failure_reason,
        "starting_balance": account_size,
        "ending_balance": balance,
        "peak_balance": peak_eod,
        "total_pnl": balance - account_size,
        "total_trades": len(sorted_trades),
        "trading_days": len(day_records),
        "total_days": total_days,
        "best_day_pnl": best_day_pnl,
        "best_day_date": best_day_date,
        "profit_target": profit_target,
        "mll_limit": mll,
        "dll_limit": dll,
        "days": day_records,
    }


def run_sequential(
    trades: list,
    label: str,
    account_size: float,
    mll: float,
    dll: float,
    profit_target: float,
    max_attempts: int = 30,
) -> list[dict]:
    """Run sequential combine attempts; each restart after a PASS or FAIL."""
    remaining = sorted(trades, key=lambda t: t.entry_time)
    attempts = []

    while remaining and len(attempts) < max_attempts:
        num = len(attempts) + 1
        result = simulate_combine_custom(remaining, account_size, mll, dll, profit_target)
        sorted_r = sorted(remaining, key=lambda t: t.entry_time)
        first_date = sorted_r[0].entry_time.date()

        if result["passed"]:
            # Find the date target was crossed
            bal = account_size
            target = account_size + profit_target
            pass_date = sorted_r[-1].entry_time.date()
            for t in sorted_r:
                bal += t.pnl
                if bal >= target:
                    pass_date = t.entry_time.date()
                    break
            cal_days = (pass_date - first_date).days + 1
            attempts.append({
                "attempt": num, "passed": True, "failure_reason": None,
                "start_date": str(first_date), "end_date": str(pass_date),
                "trading_days": result["trading_days"], "calendar_days": cal_days,
                "total_pnl": result["total_pnl"], "trades": result["total_trades"],
            })
            remaining = [t for t in remaining if t.entry_time.date() > pass_date]
            print(f"    Attempt {num:2d}: PASS  cal_days={cal_days}  pnl=${result['total_pnl']:+,.0f}", flush=True)
        else:
            # Find exact fail date
            bal = account_size
            peak_eod = account_size
            daily_map: dict = {}
            fail_date = sorted_r[-1].entry_time.date()
            prev_date = None
            for t in sorted_r:
                d = t.entry_time.date()
                if prev_date and d != prev_date:
                    if bal > peak_eod:
                        peak_eod = bal
                daily_map[d] = daily_map.get(d, 0.0) + t.pnl
                bal += t.pnl
                if peak_eod - bal >= mll:
                    fail_date = d
                    break
                if daily_map[d] < -dll:
                    fail_date = d
                    break
                prev_date = d
            cal_days = (fail_date - first_date).days + 1
            reason = (result["failure_reason"] or "unknown")[:50]
            attempts.append({
                "attempt": num, "passed": False, "failure_reason": result["failure_reason"],
                "start_date": str(first_date), "end_date": str(fail_date),
                "trading_days": result["trading_days"], "calendar_days": cal_days,
                "total_pnl": result["total_pnl"], "trades": result["total_trades"],
            })
            remaining = [t for t in remaining if t.entry_time.date() > fail_date]
            print(f"    Attempt {num:2d}: FAIL  {reason}", flush=True)

    return attempts


def print_combine_table(
    label: str,
    attempts: list[dict],
    account_size: float,
    mll: float,
    dll: float,
    profit_target: float,
) -> None:
    passes = [a for a in attempts if a["passed"]]
    fails  = [a for a in attempts if not a["passed"]]
    pass_rate = len(passes) / len(attempts) * 100 if attempts else 0.0

    # Fail reasons breakdown
    reasons: dict[str, int] = defaultdict(int)
    for a in fails:
        r = (a["failure_reason"] or "unknown")
        if "mll_breach" in r:
            reasons["mll_breach"] += 1
        elif "dll_breach" in r:
            reasons["dll_breach"] += 1
        elif "consistency" in r:
            reasons["consistency_rule"] += 1
        elif "profit_target" in r:
            reasons["profit_target_not_reached"] += 1
        else:
            reasons["other"] += 1

    avg_pass_days = (sum(a["calendar_days"] for a in passes) / len(passes)) if passes else 0.0

    print(f"\n  {label}")
    print(f"  Account: ${account_size:,.0f}  MLL: ${mll:,.0f}  DLL: ${dll:,.0f}  PT: ${profit_target:,.0f}")
    print(f"  Attempts: {len(attempts)}  Passes: {len(passes)}  Fails: {len(fails)}  Pass rate: {pass_rate:.1f}%")
    if passes:
        print(f"  Avg calendar days to pass: {avg_pass_days:.1f}")
    if reasons:
        print(f"  Fail reasons: {dict(reasons)}")
    print()
    print(f"    {'#':>3}  {'Result':<6}  {'Period':<34}  {'Trd':>4}  {'P&L':>10}  {'TradDays':>8}  {'CalDays':>7}")
    print(f"  {'─' * 78}")
    for a in attempts:
        res = "PASS" if a["passed"] else "FAIL"
        pnl_str = f"${a['total_pnl']:>+10,.0f}"
        print(
            f"    {a['attempt']:>3}  {res:<6}  "
            f"{a['start_date']} → {a['end_date']}  "
            f"{a['trades']:>4}  {pnl_str}  "
            f"{a['trading_days']:>8}  {a['calendar_days']:>7}"
        )
    print(f"  {'─' * 78}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--years", default="2023,2024,2025", help="Comma-separated years")
    p.add_argument("--max-attempts", type=int, default=30)
    args = p.parse_args()
    years = [int(y.strip()) for y in args.years.split(",")]

    print(f"\n=== AlgoICT Extended Combine Simulator ===", flush=True)
    print(f"Config: NYAM London-only, trailing stop", flush=True)
    print(f"Years: {years}", flush=True)

    # Load data
    print(f"\nLoading {DATABENTO_PATH}...", flush=True)
    t0 = time.perf_counter()
    df_full = load_databento_ohlcv_1m(str(DATABENTO_PATH))
    print(f"Loaded {len(df_full):,} bars in {time.perf_counter()-t0:.1f}s", flush=True)

    all_results: dict[int, list] = {}  # year → trades

    for year in years:
        start = f"{year}-01-01"
        end   = f"{year}-04-18" if year == 2025 else f"{year}-12-31"
        print(f"\n  [Running backtest {year}]...", flush=True)
        t0 = time.perf_counter()
        bt = build_backtester(df_full)
        result = bt.run(df_full, start_date=start, end_date=end)
        elapsed = time.perf_counter() - t0
        trades = result.trades
        total_pnl = sum(t.pnl for t in trades)
        print(f"  {year}: {len(trades)} trades  WR={result.win_rate:.1%}  P&L=${total_pnl:+,.0f}  ({elapsed:.0f}s)", flush=True)
        all_results[year] = trades

    # ── COMBINE RUNS ──────────────────────────────────────────────────────
    print("\n" + "=" * 80, flush=True)
    print("  COMBINE SIMULATOR RESULTS", flush=True)
    print("=" * 80, flush=True)

    table_50k  = []
    table_150k = []

    for year, trades in sorted(all_results.items()):
        label_50  = f"$50K  Combine {year}"
        label_150 = f"$150K Combine {year}"

        print(f"\n  ── {label_50} ({len(trades)} trades) ──", flush=True)
        r50 = run_sequential(
            trades, label_50,
            account_size=cfg.TOPSTEP_ACCOUNT_SIZE,  # $50,000
            mll=cfg.TOPSTEP_MLL,                    # $2,000
            dll=cfg.TOPSTEP_DLL,                    # $1,000
            profit_target=cfg.TOPSTEP_PROFIT_TARGET, # $3,000
            max_attempts=args.max_attempts,
        )
        table_50k.append((label_50, r50))

        print(f"\n  ── {label_150} ({len(trades)} trades) ──", flush=True)
        r150 = run_sequential(
            trades, label_150,
            account_size=ACCOUNT_150K,
            mll=MLL_150K,
            dll=DLL_150K,
            profit_target=PT_150K,
            max_attempts=args.max_attempts,
        )
        table_150k.append((label_150, r150))

    # ── Print tables ──────────────────────────────────────────────────────
    print("\n\n" + "=" * 80)
    print("  TABLE A — $50K COMBINE  (MLL=$2K trailing, DLL=$1K, PT=$3K)")
    print("=" * 80)
    for label, attempts in table_50k:
        print_combine_table(label, attempts,
                            cfg.TOPSTEP_ACCOUNT_SIZE, cfg.TOPSTEP_MLL,
                            cfg.TOPSTEP_DLL, cfg.TOPSTEP_PROFIT_TARGET)

    print("\n\n" + "=" * 80)
    print("  TABLE B — $150K COMBINE  (MLL=$4.5K trailing, DLL=$3K, PT=$9K)")
    print("=" * 80)
    for label, attempts in table_150k:
        print_combine_table(label, attempts,
                            ACCOUNT_150K, MLL_150K, DLL_150K, PT_150K)

    # ── Summary comparison ────────────────────────────────────────────────
    print("\n\n" + "=" * 80)
    print("  COMPARISON SUMMARY")
    print("=" * 80)
    print(f"\n  {'Scenario':<30} {'Attempts':>8} {'Passes':>7} {'Fails':>6} {'PassRate':>9} {'AvgDaysPass':>12}")
    print(f"  {'─' * 75}")
    for label, attempts in table_50k + table_150k:
        passes = [a for a in attempts if a["passed"]]
        fails  = [a for a in attempts if not a["passed"]]
        rate   = len(passes) / len(attempts) * 100 if attempts else 0.0
        avg_d  = (sum(a["calendar_days"] for a in passes) / len(passes)) if passes else 0.0
        print(f"  {label:<30} {len(attempts):>8} {len(passes):>7} {len(fails):>6} {rate:>8.1f}% {avg_d:>11.1f}")
    print()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
