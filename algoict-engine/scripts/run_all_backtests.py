"""
scripts/run_all_backtests.py
=============================
Master backtest suite — runs all phases in sequence.

FASE 1  KZ Matrix 2024    — 8 runs across kill zone combos
FASE 2  Trade Management  — 3 runs (fixed / partials_be / trailing) on best KZ
FASE 3  Multi-Year        — WF 2019-2022, full 2023/2024/2025, Combine 2024/2023
FASE 4  Final Tables      — 4 tables + RECOMMENDATION

Data: nq_1minute.csv (Databento 415 MB, 2019-2025 NQ continuous front-month)

Usage:
    python scripts/run_all_backtests.py [--skip-sb] [--skip-2025] [--no-combine]

Flags:
    --skip-sb       skip Silver Bullet KZ matrix (saves ~3h)
    --skip-2025     skip 2025 backtests (data may be partial)
    --no-combine    skip combine simulator (saves ~30 min each)
    --nyam-only     FASE 1-3 for NY AM only (skip all SB runs)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
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

print("=== AlgoICT Master Backtest Suite ===", flush=True)
print("Loading modules...", flush=True)

import pandas as pd

from backtest.backtester import Backtester, BacktestResult
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
from strategies.silver_bullet import SilverBulletStrategy

import config as cfg

print("OK", flush=True)


# ── Data root ──────────────────────────────────────────────────────────────

DATA_DIR = ENGINE_ROOT.parent / "data"
DATABENTO_PATH = DATA_DIR / "nq_1minute.csv"


# ── DynamicBiasStrategy ───────────────────────────────────────────────────

class DynamicBiasStrategy:
    """Lookahead-free HTF bias wrapper (reuse pattern from walk_forward_combine)."""

    def __init__(self, inner, df_daily: pd.DataFrame, df_weekly: pd.DataFrame):
        self._inner = inner
        self._df_daily = df_daily
        self._df_weekly = df_weekly
        self._detector = HTFBiasDetector()
        self._current_ts: Optional[pd.Timestamp] = None
        self._inner.htf_bias_fn = self._dynamic_bias

    def _dynamic_bias(self, current_price: float, *_, **__) -> BiasResult:
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


# ── Builder ────────────────────────────────────────────────────────────────

def _seed_levels(df_1min: pd.DataFrame, liquidity: LiquidityDetector) -> list:
    """Pre-seed PDH/PDL + PWH/PWL from full dataset."""
    tmp_tf = TimeframeManager()
    seeded = []
    try:
        df_d = tmp_tf.aggregate(df_1min, "D")
        for i in range(len(df_d)):
            seeded.extend(liquidity.build_key_levels(df_daily=df_d.iloc[i:i+1]))
    except Exception:
        pass
    try:
        df_w = tmp_tf.aggregate(df_1min, "W")
        for i in range(len(df_w)):
            seeded.extend(liquidity.build_key_levels(df_weekly=df_w.iloc[i:i+1]))
    except Exception:
        pass
    return seeded


def build_backtester(
    df_1min: pd.DataFrame,
    strategy_name: str = "nyam",
    kill_zones_override: Optional[tuple] = None,
    trade_management: str = "fixed",
    dynamic_bias: bool = True,
) -> Backtester:
    """
    Factory for both NYAM and SB backtester instances.

    Parameters
    ----------
    df_1min            : full data slice for this run (used for seeding + bias)
    strategy_name      : "nyam" | "sb"
    kill_zones_override: tuple of zone names or None (use strategy default)
    trade_management   : "fixed" | "partials_be" | "trailing"
    dynamic_bias       : True = lookahead-free HTF bias from W+D bars
    """
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

    if strategy_name == "nyam":
        inner = NYAMReversalStrategy(detectors, risk_mgr, session_mgr, static_bullish)
    elif strategy_name == "sb":
        inner = SilverBulletStrategy(detectors, risk_mgr, session_mgr, static_bullish)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    # Kill zone override
    if kill_zones_override is not None:
        inner.KILL_ZONES = kill_zones_override
        inner._trades_by_zone = {z: 0 for z in kill_zones_override}

    # Dynamic bias wrap
    if dynamic_bias and not df_1min.empty:
        tmp = TimeframeManager()
        try:
            df_d = tmp.aggregate(df_1min, "D")
            df_w = tmp.aggregate(df_1min, "W")
            if not df_d.empty and not df_w.empty:
                strategy = DynamicBiasStrategy(inner, df_d, df_w)
            else:
                strategy = inner
        except Exception:
            strategy = inner
    else:
        strategy = inner

    return Backtester(strategy, detectors, risk_mgr, tf_mgr, session_mgr,
                      trade_management=trade_management)


# ── Stats helpers ──────────────────────────────────────────────────────────

def compute_stats(trades: list, label: str) -> dict:
    """Compute full stats dict for a list of Trade objects."""
    if not trades:
        return {
            "label": label, "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "total_pnl": 0.0, "profit_factor": 0.0,
            "max_dd": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "best_month": None, "worst_month": None,
        }

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    wins_pnl = sum(t.pnl for t in wins)
    loss_pnl = abs(sum(t.pnl for t in losses))
    pf = wins_pnl / loss_pnl if loss_pnl > 0 else float("inf")
    avg_win = wins_pnl / len(wins) if wins else 0.0
    avg_loss = -loss_pnl / len(losses) if losses else 0.0

    # Max drawdown (peak-to-trough on equity curve)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.entry_time):
        equity += t.pnl
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    # Monthly P&L
    monthly: dict = defaultdict(float)
    for t in trades:
        key = t.entry_time.strftime("%Y-%m")
        monthly[key] += t.pnl
    best_month = max(monthly.items(), key=lambda x: x[1]) if monthly else None
    worst_month = min(monthly.items(), key=lambda x: x[1]) if monthly else None

    return {
        "label": label,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "total_pnl": sum(t.pnl for t in trades),
        "profit_factor": pf,
        "max_dd": max_dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "best_month": best_month,
        "worst_month": worst_month,
    }


def _kz_breakdown(trades: list) -> dict:
    """Per-kill-zone stats {kz: stats_dict}."""
    by_kz: dict = defaultdict(list)
    for t in trades:
        kz = t.kill_zone or "unknown"
        by_kz[kz].append(t)
    return {kz: compute_stats(ts, kz) for kz, ts in by_kz.items()}


def run_single(
    df: pd.DataFrame,
    label: str,
    strategy_name: str,
    kill_zones_override: Optional[tuple] = None,
    trade_management: str = "fixed",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Run one backtest and return stats dict."""
    print(f"\n  [{label}] building...", flush=True)
    t0 = time.perf_counter()
    try:
        bt = build_backtester(
            df, strategy_name=strategy_name,
            kill_zones_override=kill_zones_override,
            trade_management=trade_management,
        )
        result = bt.run(df, start_date=start_date, end_date=end_date)
        elapsed = time.perf_counter() - t0
        stats = compute_stats(result.trades, label)
        print(
            f"  [{label}] {result.total_trades} trades  "
            f"WR={result.win_rate:.1%}  P&L=${result.total_pnl:+,.0f}  "
            f"PF={stats['profit_factor']:.2f}  ({elapsed:.0f}s)",
            flush=True,
        )
        stats["_trades_obj"] = result.trades  # stash for combine / table 4
        stats["elapsed"] = elapsed
        return stats
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  [{label}] ERROR: {e}", flush=True)
        traceback.print_exc()
        empty = compute_stats([], label)
        empty["error"] = str(e)
        empty["elapsed"] = elapsed
        return empty


# ── FASE 1: KZ Matrix 2024 ─────────────────────────────────────────────────

def run_kz_matrix_2024(
    df_2024: pd.DataFrame,
    skip_sb: bool = False,
) -> list[dict]:
    print(f"\n{'='*70}", flush=True)
    print("  FASE 1 — KZ MATRIX 2024", flush=True)
    print(f"{'='*70}", flush=True)

    results = []

    nyam_combos = [
        ("A. NYAM London only",  ("london",)),
        ("B. NYAM NY AM only",   ("ny_am",)),
        ("C. NYAM NY PM only",   ("ny_pm",)),
        ("D. NYAM ALL",          ("london", "ny_am", "ny_pm")),
    ]
    sb_combos = [
        ("E. SB London SB only", ("london_silver_bullet",)),
        ("F. SB NY SB only",     ("silver_bullet",)),
        ("G. SB ALL SB",         ("london_silver_bullet", "silver_bullet")),
    ]

    for label, kz in nyam_combos:
        s = run_single(df_2024, label, "nyam", kill_zones_override=kz,
                       start_date="2024-01-01", end_date="2024-12-31")
        results.append(s)

    if not skip_sb:
        for label, kz in sb_combos:
            s = run_single(df_2024, label, "sb", kill_zones_override=kz,
                           start_date="2024-01-01", end_date="2024-12-31")
            results.append(s)

    # H: Portfolio = D + G (merge trade lists, no extra backtest)
    d_trades = next((r["_trades_obj"] for r in results if r["label"].startswith("D.")), [])
    g_trades = next((r["_trades_obj"] for r in results if r["label"].startswith("G.")), [])
    if d_trades or g_trades:
        combined = sorted(d_trades + g_trades, key=lambda t: t.entry_time)
        s = compute_stats(combined, "H. Portfolio (D+G)")
        s["_trades_obj"] = combined
        s["elapsed"] = 0.0
        results.append(s)
        print(f"\n  [H. Portfolio (D+G)] {s['trades']} trades  "
              f"WR={s['win_rate']:.1%}  P&L=${s['total_pnl']:+,.0f}  "
              f"PF={s['profit_factor']:.2f}", flush=True)

    return results


# ── FASE 2: Trade Management 2024 ─────────────────────────────────────────

def run_trade_management_2024(
    df_2024: pd.DataFrame,
    best_kz: tuple,
    strategy_name: str = "nyam",
) -> list[dict]:
    print(f"\n{'='*70}", flush=True)
    print(f"  FASE 2 — TRADE MANAGEMENT 2024 (strategy={strategy_name}, kz={best_kz})", flush=True)
    print(f"{'='*70}", flush=True)

    results = []
    for mode in ("fixed", "partials_be", "trailing"):
        label = f"TM-{mode}"
        s = run_single(
            df_2024, label, strategy_name,
            kill_zones_override=best_kz,
            trade_management=mode,
            start_date="2024-01-01", end_date="2024-12-31",
        )
        results.append(s)
    return results


# ── FASE 3: Multi-Year Validation ──────────────────────────────────────────

def run_walk_forward(
    df_full: pd.DataFrame,
    strategy_name: str = "nyam",
    kill_zones_override: Optional[tuple] = None,
    trade_management: str = "fixed",
    years: tuple = (2019, 2020, 2021, 2022),
) -> tuple[list[dict], list[dict]]:
    """
    Run one backtest per year, slice into 6 bimonthly windows.
    Returns (wf_window_results, yearly_results).
    """
    tz = df_full.index.tz
    all_windows = []
    yearly = []
    window_num = 0

    for year in years:
        year_start = pd.Timestamp(f"{year}-01-01", tz=tz)
        year_end = pd.Timestamp(f"{year+1}-01-01", tz=tz)
        df_year = df_full[(df_full.index >= year_start) & (df_full.index < year_end)]

        if df_year.empty:
            print(f"  {year}: no data — skipping", flush=True)
            continue

        print(f"\n  WF {year}: {len(df_year):,} bars...", flush=True)
        t0 = time.perf_counter()
        try:
            bt = build_backtester(
                df_year, strategy_name=strategy_name,
                kill_zones_override=kill_zones_override,
                trade_management=trade_management,
            )
            result = bt.run(df_year)
            elapsed = time.perf_counter() - t0
        except Exception as e:
            print(f"  {year}: ERROR — {e}", flush=True)
            traceback.print_exc()
            continue

        stats = compute_stats(result.trades, str(year))
        stats["elapsed"] = elapsed
        yearly.append(stats)

        print(
            f"  {year}: {result.total_trades} trades  WR={result.win_rate:.1%}  "
            f"P&L=${result.total_pnl:+,.0f}  ({elapsed:.0f}s)",
            flush=True,
        )

        # Slice into 2-month windows
        for bimester in range(6):
            w_start = pd.Timestamp(f"{year}-{bimester*2+1:02d}-01", tz=tz)
            w_end = w_start + pd.DateOffset(months=2)
            window_num += 1

            w_trades = [t for t in result.trades if w_start <= t.entry_time < w_end]
            total = len(w_trades)
            wins = sum(1 for t in w_trades if t.pnl > 0)
            losses = total - wins
            wr = wins / total if total > 0 else 0.0
            pnl = sum(t.pnl for t in w_trades)
            wp = sum(t.pnl for t in w_trades if t.pnl > 0)
            lp = abs(sum(t.pnl for t in w_trades if t.pnl <= 0))
            pf = wp / lp if lp > 0 else (float("inf") if wp > 0 else 0.0)
            positive = pnl > 0

            te_s = w_start.strftime("%Y-%m-%d")
            te_e = (w_end - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            ok = "+" if positive else ("-" if total > 0 else " ")
            pf_s = f"{pf:.2f}" if pf != float("inf") else "  inf"
            print(
                f"    W{window_num:02d} [{te_s}→{te_e}]  "
                f"trd={total:3d}  wr={wr:4.0%}  pnl=${pnl:>+8.0f}  "
                f"pf={pf_s:>5}  {ok}",
                flush=True,
            )
            all_windows.append({
                "window": window_num, "year": year,
                "test_start": te_s, "test_end": te_e,
                "trades": total, "wins": wins, "losses": losses,
                "win_rate": wr, "total_pnl": pnl,
                "wins_pnl": wp, "losses_pnl": lp,
                "profit_factor": pf, "positive": positive,
            })

    return all_windows, yearly


def _print_wf_summary(windows: list[dict]) -> None:
    if not windows:
        return
    total = len(windows)
    pos = sum(1 for r in windows if r["positive"])
    pct = pos / total if total else 0.0
    all_t = sum(r["trades"] for r in windows)
    all_w = sum(r["wins"] for r in windows)
    all_pnl = sum(r["total_pnl"] for r in windows)
    all_wp = sum(r["wins_pnl"] for r in windows)
    all_lp = sum(r["losses_pnl"] for r in windows)
    agg_wr = all_w / all_t if all_t else 0.0
    agg_pf = all_wp / all_lp if all_lp else 0.0
    gate = "PASS ✓" if pct >= 0.70 else "FAIL ✗"
    print(f"\n  {'─'*65}", flush=True)
    print(f"  WF Summary: {pos}/{total} ({pct:.1%}) positive  Gate>=70%: {gate}", flush=True)
    print(f"  Total trades: {all_t}  Agg WR: {agg_wr:.1%}  Agg P&L: ${all_pnl:+,.0f}  PF: {agg_pf:.2f}", flush=True)


def run_combine_sim(trades: list, label: str, max_attempts: int = 30) -> list[dict]:
    """Sequential Combine simulator against a trade list."""
    remaining = sorted(trades, key=lambda t: t.entry_time)
    attempts = []

    while remaining and len(attempts) < max_attempts:
        num = len(attempts) + 1
        result = simulate_combine(remaining)
        sorted_r = sorted(remaining, key=lambda t: t.entry_time)
        first_date = sorted_r[0].entry_time.date()

        if result.passed:
            balance = cfg.TOPSTEP_ACCOUNT_SIZE
            target = balance + cfg.TOPSTEP_PROFIT_TARGET
            pass_date = sorted_r[-1].entry_time.date()
            for t in sorted_r:
                balance += t.pnl
                if balance >= target:
                    pass_date = t.entry_time.date()
                    break
            cal_days = (pass_date - first_date).days + 1
            attempts.append({
                "attempt": num, "passed": True, "failure_reason": None,
                "start_date": str(first_date), "end_date": str(pass_date),
                "trading_days": result.trading_days, "calendar_days": cal_days,
                "total_pnl": result.total_pnl, "trades": result.total_trades,
            })
            remaining = [t for t in remaining if t.entry_time.date() > pass_date]
            print(f"  Attempt {num:2d}: PASS  days={cal_days}", flush=True)
        else:
            balance = cfg.TOPSTEP_ACCOUNT_SIZE
            peak_eod = cfg.TOPSTEP_ACCOUNT_SIZE
            daily_map: dict = {}
            fail_date = sorted_r[-1].entry_time.date()
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
            cal_days = (fail_date - first_date).days + 1
            reason = (result.failure_reason or "unknown")[:40]
            attempts.append({
                "attempt": num, "passed": False, "failure_reason": result.failure_reason,
                "start_date": str(first_date), "end_date": str(fail_date),
                "trading_days": result.trading_days, "calendar_days": cal_days,
                "total_pnl": result.total_pnl, "trades": result.total_trades,
            })
            remaining = [t for t in remaining if t.entry_time.date() > fail_date]
            print(f"  Attempt {num:2d}: FAIL  {reason}", flush=True)

    return attempts


def run_multiyear(
    df_full: pd.DataFrame,
    strategy_name: str = "nyam",
    kill_zones_override: Optional[tuple] = None,
    trade_management: str = "fixed",
    skip_2025: bool = False,
    no_combine: bool = False,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Run multi-year validation. Returns (wf_windows, full_year_stats, combine_results).
    """
    print(f"\n{'='*70}", flush=True)
    print(f"  FASE 3 — MULTI-YEAR VALIDATION  (strategy={strategy_name})", flush=True)
    print(f"{'='*70}", flush=True)

    wf_windows, yearly = run_walk_forward(
        df_full, strategy_name=strategy_name,
        kill_zones_override=kill_zones_override,
        trade_management=trade_management,
    )
    _print_wf_summary(wf_windows)

    # Full year runs: 2023, 2024, (2025)
    full_years = [
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
    ]
    if not skip_2025:
        full_years.append(("2025 YTD", "2025-01-01", "2025-12-31"))

    print(f"\n{'─'*70}", flush=True)
    print("  Full-Year Backtests", flush=True)
    for year_label, s_date, e_date in full_years:
        tz = df_full.index.tz
        df_yr = df_full[
            (df_full.index >= pd.Timestamp(s_date, tz=tz)) &
            (df_full.index < pd.Timestamp(e_date, tz=tz) + pd.Timedelta(days=1))
        ]
        if df_yr.empty:
            print(f"  {year_label}: no data", flush=True)
            yearly.append(compute_stats([], year_label))
            continue
        s = run_single(df_yr, year_label, strategy_name,
                       kill_zones_override=kill_zones_override,
                       trade_management=trade_management,
                       start_date=s_date, end_date=e_date)
        s["year"] = year_label
        yearly.append(s)

    # Combine simulator
    combine_results = []
    if not no_combine:
        print(f"\n{'─'*70}", flush=True)
        print("  Combine Simulator", flush=True)
        for year_label, s_date, e_date in [("2024", "2024-01-01", "2024-12-31"),
                                            ("2023", "2023-01-01", "2023-12-31")]:
            year_stats = next((y for y in yearly if y["label"] == year_label), None)
            if year_stats and year_stats.get("_trades_obj"):
                trades_yr = year_stats["_trades_obj"]
                print(f"\n  Combine {year_label}: {len(trades_yr)} trades", flush=True)
                attempts = run_combine_sim(trades_yr, year_label)
                passes = sum(1 for a in attempts if a["passed"])
                combine_results.append({
                    "label": f"Combine {year_label}",
                    "attempts": len(attempts),
                    "passes": passes,
                    "fails": len(attempts) - passes,
                    "pass_rate": passes / len(attempts) if attempts else 0.0,
                    "attempts_detail": attempts,
                })
            else:
                print(f"\n  Combine {year_label}: no trades — skipping", flush=True)

    return wf_windows, yearly, combine_results


# ── FASE 4: Print tables ───────────────────────────────────────────────────

def _pf_str(pf: float) -> str:
    if pf == float("inf"):
        return " inf"
    return f"{pf:.2f}"


def print_table_1_kz_matrix(results: list[dict]) -> None:
    print(f"\n{'='*90}", flush=True)
    print("  TABLE 1 — KZ MATRIX 2024", flush=True)
    print(f"{'='*90}", flush=True)
    hdr = (f"  {'Label':<30} {'Trd':>5} {'WR':>6} {'PF':>6} "
           f"{'P&L':>10} {'MaxDD':>8} {'AvgW':>7} {'AvgL':>7}")
    print(hdr)
    print(f"  {'─'*88}")
    for r in results:
        pf = _pf_str(r["profit_factor"])
        print(
            f"  {r['label']:<30} {r['trades']:>5} {r['win_rate']:>5.0%} "
            f"{pf:>6} ${r['total_pnl']:>+9,.0f} "
            f"${r['max_dd']:>7,.0f} ${r['avg_win']:>6,.0f} ${r['avg_loss']:>6,.0f}"
        )
    print(f"  {'─'*88}", flush=True)


def print_table_2_trade_mgmt(results: list[dict]) -> None:
    print(f"\n{'='*90}", flush=True)
    print("  TABLE 2 — TRADE MANAGEMENT 2024", flush=True)
    print(f"{'='*90}", flush=True)
    hdr = (f"  {'Mode':<20} {'Trd':>5} {'WR':>6} {'PF':>6} "
           f"{'P&L':>10} {'MaxDD':>8} {'AvgW':>7} {'AvgL':>7}")
    print(hdr)
    print(f"  {'─'*75}")
    for r in results:
        pf = _pf_str(r["profit_factor"])
        print(
            f"  {r['label']:<20} {r['trades']:>5} {r['win_rate']:>5.0%} "
            f"{pf:>6} ${r['total_pnl']:>+9,.0f} "
            f"${r['max_dd']:>7,.0f} ${r['avg_win']:>6,.0f} ${r['avg_loss']:>6,.0f}"
        )
    print(f"  {'─'*75}", flush=True)


def print_table_3_multiyear(wf_windows: list[dict], yearly: list[dict]) -> None:
    print(f"\n{'='*90}", flush=True)
    print("  TABLE 3 — MULTI-YEAR VALIDATION", flush=True)
    print(f"{'='*90}", flush=True)

    if wf_windows:
        total = len(wf_windows)
        pos = sum(1 for r in wf_windows if r["positive"])
        pct = pos / total if total else 0.0
        all_t = sum(r["trades"] for r in wf_windows)
        all_w = sum(r["wins"] for r in wf_windows)
        all_pnl = sum(r["total_pnl"] for r in wf_windows)
        all_wp = sum(r["wins_pnl"] for r in wf_windows)
        all_lp = sum(r["losses_pnl"] for r in wf_windows)
        agg_wr = all_w / all_t if all_t else 0.0
        agg_pf = all_wp / all_lp if all_lp else 0.0
        gate = "PASS ✓" if pct >= 0.70 else "FAIL ✗"
        print(f"\n  Walk-Forward 2019-2022 ({total} bimonthly windows):", flush=True)
        print(f"  Positive: {pos}/{total} ({pct:.1%})  Gate: {gate}", flush=True)
        print(f"  Agg trades: {all_t}  WR: {agg_wr:.1%}  P&L: ${all_pnl:+,.0f}  PF: {agg_pf:.2f}", flush=True)
        print(f"\n  Per-window detail:", flush=True)
        for r in wf_windows:
            ok = "+" if r["positive"] else "-"
            pf = _pf_str(r["profit_factor"])
            print(
                f"    W{r['window']:02d} {r['test_start']}→{r['test_end']}  "
                f"trd={r['trades']:3d}  wr={r['win_rate']:4.0%}  "
                f"pnl=${r['total_pnl']:>+8.0f}  pf={pf:>5}  {ok}",
                flush=True,
            )

    if yearly:
        print(f"\n  Full-Year Backtests:", flush=True)
        hdr = (f"  {'Year':<12} {'Trd':>5} {'WR':>6} {'PF':>6} "
               f"{'P&L':>10} {'MaxDD':>8} {'AvgW':>7} {'AvgL':>7}")
        print(hdr)
        print(f"  {'─'*70}")
        for r in yearly:
            pf = _pf_str(r["profit_factor"])
            print(
                f"  {r['label']:<12} {r['trades']:>5} {r['win_rate']:>5.0%} "
                f"{pf:>6} ${r['total_pnl']:>+9,.0f} "
                f"${r['max_dd']:>7,.0f} ${r['avg_win']:>6,.0f} ${r['avg_loss']:>6,.0f}"
            )
    print(f"  {'─'*70}", flush=True)


def print_table_4_combine(combine_results: list[dict]) -> None:
    print(f"\n{'='*70}", flush=True)
    print("  TABLE 4 — COMBINE SIMULATOR", flush=True)
    print(f"{'='*70}", flush=True)
    for cr in combine_results:
        print(f"\n  {cr['label']}:", flush=True)
        print(f"  Attempts: {cr['attempts']}  Passes: {cr['passes']}  "
              f"Fails: {cr['fails']}  Pass rate: {cr['pass_rate']:.1%}", flush=True)
        print(f"\n  {'#':>3}  {'Result':>6}  {'Period':>24}  {'Trd':>4}  "
              f"{'P&L':>9}  {'TradeDays':>9}  {'CalDays':>7}", flush=True)
        print(f"  {'─'*65}", flush=True)
        for a in cr["attempts_detail"]:
            status = "PASS" if a["passed"] else "FAIL"
            period = f"{a['start_date']} → {a['end_date']}"
            print(
                f"  {a['attempt']:>3}  {status:>6}  {period:>24}  "
                f"{a['trades']:>4}  ${a['total_pnl']:>+8.0f}  "
                f"{a['trading_days']:>9}  {a['calendar_days']:>7}",
                flush=True,
            )
    print(f"  {'─'*65}", flush=True)


def print_recommendation(
    kz_results: list[dict],
    tm_results: list[dict],
    wf_windows: list[dict],
    combine_results: list[dict],
) -> None:
    print(f"\n{'='*70}", flush=True)
    print("  RECOMMENDATION", flush=True)
    print(f"{'='*70}", flush=True)

    # Best KZ from Table 1 (highest PF among NYAM runs, excluding portfolio)
    nyam_kz = [r for r in kz_results if r["label"].startswith(("A.", "B.", "C.", "D."))]
    best_kz_row = max(nyam_kz, key=lambda r: (r["trades"] > 0) * r["profit_factor"]) if nyam_kz else None
    if best_kz_row:
        print(f"\n  Best KZ combo (highest PF):  {best_kz_row['label']}", flush=True)
        print(f"    Trades={best_kz_row['trades']}  WR={best_kz_row['win_rate']:.1%}  "
              f"PF={_pf_str(best_kz_row['profit_factor'])}  P&L=${best_kz_row['total_pnl']:+,.0f}", flush=True)

    # Best TM mode (highest P&L with positive PF)
    valid_tm = [r for r in tm_results if r["profit_factor"] > 1.0]
    best_tm = max(valid_tm, key=lambda r: r["total_pnl"]) if valid_tm else None
    if best_tm:
        print(f"\n  Best Trade Management:  {best_tm['label']}", flush=True)
        print(f"    Trades={best_tm['trades']}  WR={best_tm['win_rate']:.1%}  "
              f"PF={_pf_str(best_tm['profit_factor'])}  P&L=${best_tm['total_pnl']:+,.0f}", flush=True)

    # WF gate
    if wf_windows:
        pos = sum(1 for r in wf_windows if r["positive"])
        pct = pos / len(wf_windows)
        gate = "PASS ✓" if pct >= 0.70 else "FAIL ✗"
        print(f"\n  Walk-Forward Gate (>=70% positive windows): {gate}  ({pos}/{len(wf_windows)} = {pct:.0%})", flush=True)

    # Combine pass rate
    for cr in combine_results:
        print(f"\n  {cr['label']}: pass rate = {cr['pass_rate']:.1%}  ({cr['passes']}/{cr['attempts']})", flush=True)

    # Combine-ready verdict
    combine_2024 = next((c for c in combine_results if "2024" in c["label"]), None)
    wf_ok = (sum(1 for r in wf_windows if r["positive"]) / len(wf_windows) >= 0.70) if wf_windows else False
    combine_ok = (combine_2024["pass_rate"] >= 0.40) if combine_2024 else False

    print(f"\n  ─────────────────────────────────────────", flush=True)
    if wf_ok and combine_ok:
        verdict = "READY FOR COMBINE ✓"
        detail = "Walk-forward gate passed and 2024 Combine pass rate >= 40%."
    elif wf_ok:
        verdict = "PROMISING — more data needed"
        detail = "Walk-forward gate passed but Combine pass rate < 40%."
    else:
        verdict = "NOT READY — needs parameter work"
        detail = "Walk-forward gate failed."
    print(f"  VERDICT: {verdict}", flush=True)
    print(f"  {detail}", flush=True)
    print(f"  {'─'*68}\n", flush=True)


# ── Main ───────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_all_backtests",
        description="AlgoICT master backtest suite — FASE 1-4",
    )
    p.add_argument("--skip-sb", action="store_true",
                   help="Skip Silver Bullet KZ matrix (saves ~3h)")
    p.add_argument("--skip-2025", action="store_true",
                   help="Skip 2025 backtests (data may be partial)")
    p.add_argument("--no-combine", action="store_true",
                   help="Skip Combine simulator")
    p.add_argument("--nyam-only", action="store_true",
                   help="Run NYAM only for all phases (implies --skip-sb)")
    p.add_argument("--best-kz", default=None,
                   help="Override best KZ for FASE 2 (e.g. 'london,ny_am'). "
                        "If not set, auto-selected from FASE 1 by highest PF.")
    p.add_argument("--best-strategy", default="nyam",
                   choices=("nyam", "sb"),
                   help="Strategy for FASE 2 trade management variants (default: nyam)")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    skip_sb = args.skip_sb or args.nyam_only
    t_total = time.perf_counter()

    # ── Check data file ────────────────────────────────────────────────────
    if not DATABENTO_PATH.exists():
        print(f"\n✗ Databento file not found: {DATABENTO_PATH}", flush=True)
        print("  Expected: nq_1minute.csv in the data/ directory", flush=True)
        return 1

    mb = DATABENTO_PATH.stat().st_size / 1024 / 1024
    print(f"\nData: {DATABENTO_PATH.name}  ({mb:.0f} MB)", flush=True)

    # ── Load full dataset ONCE ─────────────────────────────────────────────
    print("\nLoading Databento NQ 1-min (2019-2025, ~90s)...", flush=True)
    t0 = time.perf_counter()
    try:
        df_full = load_databento_ohlcv_1m(
            DATABENTO_PATH,
            start_date="2019-01-01",
            end_date="2025-12-31",
            symbol_prefix="NQ",
        )
        print(f"Loaded {len(df_full):,} bars  ({df_full.index[0].date()} → {df_full.index[-1].date()})  "
              f"in {time.perf_counter()-t0:.1f}s", flush=True)
    except Exception as e:
        print(f"✗ Failed to load data: {e}", flush=True)
        traceback.print_exc()
        return 1

    tz = df_full.index.tz

    # 2024 slice (used by FASE 1 + 2)
    df_2024 = df_full[
        (df_full.index >= pd.Timestamp("2024-01-01", tz=tz)) &
        (df_full.index < pd.Timestamp("2025-01-01", tz=tz))
    ]
    print(f"2024 slice: {len(df_2024):,} bars", flush=True)

    # ── FASE 1 ─────────────────────────────────────────────────────────────
    kz_results = run_kz_matrix_2024(df_2024, skip_sb=skip_sb)
    print_table_1_kz_matrix(kz_results)

    # Determine best KZ for FASE 2
    if args.best_kz:
        best_kz = tuple(z.strip() for z in args.best_kz.split(",") if z.strip())
    else:
        # Auto-select: highest PF among NYAM runs (exclude portfolio)
        nyam_runs = [r for r in kz_results
                     if r["label"].startswith(("A.", "B.", "C.", "D.")) and r["trades"] > 0]
        if nyam_runs:
            best_row = max(nyam_runs, key=lambda r: r["profit_factor"])
            # Extract the kz combo from the label mapping
            label_to_kz = {
                "A. NYAM London only": ("london",),
                "B. NYAM NY AM only":  ("ny_am",),
                "C. NYAM NY PM only":  ("ny_pm",),
                "D. NYAM ALL":         ("london", "ny_am", "ny_pm"),
            }
            best_kz = label_to_kz.get(best_row["label"], ("london", "ny_am", "ny_pm"))
            print(f"\n  Auto-selected best KZ: {best_kz}  (from {best_row['label']})", flush=True)
        else:
            best_kz = ("london", "ny_am", "ny_pm")
            print(f"\n  No NYAM results — falling back to default KZ: {best_kz}", flush=True)

    # ── FASE 2 ─────────────────────────────────────────────────────────────
    tm_results = run_trade_management_2024(
        df_2024, best_kz=best_kz, strategy_name=args.best_strategy,
    )
    print_table_2_trade_mgmt(tm_results)

    # Determine best TM for FASE 3
    valid_tm = [r for r in tm_results if r["profit_factor"] > 1.0]
    best_tm = max(valid_tm, key=lambda r: r["total_pnl"])["label"].split("-")[1] if valid_tm else "fixed"
    print(f"\n  Auto-selected best TM: {best_tm}", flush=True)

    # ── FASE 3 ─────────────────────────────────────────────────────────────
    wf_windows, yearly, combine_results = run_multiyear(
        df_full,
        strategy_name=args.best_strategy,
        kill_zones_override=best_kz,
        trade_management=best_tm,
        skip_2025=args.skip_2025,
        no_combine=args.no_combine,
    )
    print_table_3_multiyear(wf_windows, yearly)
    if combine_results:
        print_table_4_combine(combine_results)

    # ── FASE 4: Recommendation ─────────────────────────────────────────────
    print_recommendation(kz_results, tm_results, wf_windows, combine_results)

    elapsed_total = time.perf_counter() - t_total
    h = int(elapsed_total // 3600)
    m = int((elapsed_total % 3600) // 60)
    s = int(elapsed_total % 60)
    print(f"  Total elapsed: {h}h {m}m {s}s\n", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
        sys.exit(130)
