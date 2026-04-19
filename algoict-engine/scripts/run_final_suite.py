"""
scripts/run_final_suite.py
===========================
SUITE FINAL DEFINITIVO — AlgoICT complete validation.

Parts
-----
PARTE 1  KZ Matrix 2024        — 8 runs across kill zone combos
PARTE 2  Trade Management 2024 — fixed vs trailing (London + NY AM)
PARTE 3  Multi-Year 2019-2025  — full year per year + WF 2019-2022
PARTE 4  Combine Simulator     — $50K and $150K, 2023/2024/2025 × 30 attempts
PARTE 5  IFVG Validation 2024  — IFVG ON vs OFF, all KZ, trailing
PARTE 6  Comparativa           — summary table before vs after

Data:    nq_1minute.csv (Databento, 2019-2025)
Config:  ALL KZ for NYAM = (london, ny_am, ny_pm)
         ALL SB = (london_silver_bullet, silver_bullet)
         PARTE 4: topstep_mode=True (MLL v1 warning=40% caution=60% stop=85%)

Usage:
    cd algoict-engine
    python scripts/run_final_suite.py > final_suite_output.log 2>&1 &
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import time
import traceback
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

# ── Log to stdout + file simultaneously ───────────────────────────────────────
LOG_FILE = ENGINE_ROOT / "final_suite_output.log"
_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8", mode="w"))
except Exception:
    pass
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
    handlers=_handlers,
)


def p(*args, **kwargs):
    """Print flushed — goes to both stdout and the log via Tee below."""
    kwargs["flush"] = True
    print(*args, **kwargs)


class _Tee:
    """Write every p() call to both the original stdout and the log file."""
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass


_orig_stdout = sys.stdout
try:
    _log_fh = open(LOG_FILE, "w", encoding="utf-8")
    sys.stdout = _Tee(_orig_stdout, _log_fh)
except Exception:
    _log_fh = None


p("=" * 70)
p("  AlgoICT SUITE FINAL DEFINITIVO")
p(f"  Log: {LOG_FILE}")
p("=" * 70)
p("Loading modules...")

import pandas as pd

from backtest.backtester import Backtester, BacktestResult
from backtest.databento_loader import load_databento_ohlcv_1m
from backtest.combine_simulator import simulate_combine, CombineResult

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

p("OK")


# ── Data root ──────────────────────────────────────────────────────────────────
DATA_DIR = ENGINE_ROOT.parent / "data"
DATABENTO_PATH = DATA_DIR / "nq_1minute.csv"

# ── Kill zone constants ────────────────────────────────────────────────────────
ALL_NYAM_KZ = ("london", "ny_am", "ny_pm")
ALL_SB_KZ   = ("london_silver_bullet", "silver_bullet")
BEST_KZ     = ("london", "ny_am")          # used for PARTE 2/4/5 (London+NY AM)


# ── $150K Combine parameters ───────────────────────────────────────────────────
COMBINE_150K_ACCOUNT  = 150_000.0
COMBINE_150K_TARGET   = 9_000.0
COMBINE_150K_MLL      = 4_500.0
COMBINE_150K_DLL      = 2_250.0


# =============================================================================
# INFRASTRUCTURE — copied + extended from run_all_backtests.py
# =============================================================================

class DynamicBiasStrategy:
    """Lookahead-free HTF bias wrapper."""

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


def _seed_levels(df_1min: pd.DataFrame, liquidity: LiquidityDetector) -> list:
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
    topstep_mode: bool = False,
    ifvg_enabled: bool = True,
) -> Backtester:
    """
    Factory for NYAM and SB backtester instances.

    Parameters
    ----------
    topstep_mode : bool — enable MLL zone reductions (warning 40%/caution 60%/stop 85%)
    ifvg_enabled : bool — NYAM only; set False to disable IFVG fallback
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
    if topstep_mode:
        risk_mgr.enable_topstep_mode(
            warning_pct=0.40, caution_pct=0.60, stop_pct=0.85
        )

    tf_mgr = TimeframeManager()
    session_mgr = SessionManager()

    def static_bullish(*_, **__):
        return BiasResult(
            direction="bullish", premium_discount="discount",
            htf_levels={}, confidence="high",
            weekly_bias="bullish", daily_bias="bullish",
        )

    if strategy_name == "nyam":
        inner = NYAMReversalStrategy(detectors, risk_mgr, session_mgr, static_bullish)
        inner._ifvg_enabled = ifvg_enabled
    elif strategy_name == "sb":
        inner = SilverBulletStrategy(detectors, risk_mgr, session_mgr, static_bullish)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    if kill_zones_override is not None:
        inner.KILL_ZONES = kill_zones_override
        inner._trades_by_zone = {z: 0 for z in kill_zones_override}

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

    return Backtester(
        strategy, detectors, risk_mgr, tf_mgr, session_mgr,
        trade_management=trade_management,
    )


# ── Stats ──────────────────────────────────────────────────────────────────────

def compute_stats(trades: list, label: str) -> dict:
    if not trades:
        return {
            "label": label, "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "total_pnl": 0.0, "profit_factor": 0.0,
            "max_dd": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        }
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    wins_pnl = sum(t.pnl for t in wins)
    loss_pnl = abs(sum(t.pnl for t in losses))
    pf = wins_pnl / loss_pnl if loss_pnl > 0 else float("inf")
    avg_win = wins_pnl / len(wins) if wins else 0.0
    avg_loss = -loss_pnl / len(losses) if losses else 0.0

    equity = peak = max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.entry_time):
        equity += t.pnl
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        "label": label,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades),
        "total_pnl": sum(t.pnl for t in trades),
        "profit_factor": pf,
        "max_dd": max_dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "_trades_obj": trades,
    }


def run_single(
    df: pd.DataFrame,
    label: str,
    strategy_name: str,
    kill_zones_override: Optional[tuple] = None,
    trade_management: str = "fixed",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    topstep_mode: bool = False,
    ifvg_enabled: bool = True,
) -> dict:
    p(f"\n  [{label}] building...", end="", flush=True)
    t0 = time.perf_counter()
    try:
        bt = build_backtester(
            df, strategy_name=strategy_name,
            kill_zones_override=kill_zones_override,
            trade_management=trade_management,
            topstep_mode=topstep_mode,
            ifvg_enabled=ifvg_enabled,
        )
        result = bt.run(df, start_date=start_date, end_date=end_date)
        elapsed = time.perf_counter() - t0
        stats = compute_stats(result.trades, label)
        pf_s = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] != float("inf") else "inf"
        p(
            f" {result.total_trades} trades  "
            f"WR={result.win_rate:.1%}  P&L=${result.total_pnl:+,.0f}  "
            f"PF={pf_s}  ({elapsed:.0f}s)"
        )
        stats["elapsed"] = elapsed
        return stats
    except Exception as e:
        elapsed = time.perf_counter() - t0
        p(f" ERROR: {e}")
        traceback.print_exc()
        empty = compute_stats([], label)
        empty["error"] = str(e)
        empty["elapsed"] = elapsed
        return empty


def _pf_str(pf: float) -> str:
    return " inf" if pf == float("inf") else f"{pf:.2f}"


# =============================================================================
# PARTE 1 — KZ MATRIX 2024
# =============================================================================

def run_parte1_kz_matrix(df_2024: pd.DataFrame) -> list[dict]:
    p(f"\n{'='*70}")
    p("  PARTE 1 — KZ MATRIX 2024")
    p(f"{'='*70}")

    nyam_combos = [
        ("A. NYAM London only",  ("london",)),
        ("B. NYAM NY AM only",   ("ny_am",)),
        ("C. NYAM NY PM only",   ("ny_pm",)),
        ("D. NYAM ALL KZ",       ALL_NYAM_KZ),
    ]
    sb_combos = [
        ("E. SB London SB only", ("london_silver_bullet",)),
        ("F. SB NY SB only",     ("silver_bullet",)),
        ("G. SB ALL SB",         ALL_SB_KZ),
    ]

    results = []
    for label, kz in nyam_combos:
        s = run_single(df_2024, label, "nyam", kill_zones_override=kz,
                       start_date="2024-01-01", end_date="2024-12-31")
        results.append(s)

    for label, kz in sb_combos:
        s = run_single(df_2024, label, "sb", kill_zones_override=kz,
                       start_date="2024-01-01", end_date="2024-12-31")
        results.append(s)

    # H: Portfolio = D + G (merged trade list, no extra backtest)
    d_trades = next((r["_trades_obj"] for r in results if r["label"].startswith("D.")), [])
    g_trades = next((r["_trades_obj"] for r in results if r["label"].startswith("G.")), [])
    if d_trades or g_trades:
        combined = sorted(d_trades + g_trades, key=lambda t: t.entry_time)
        s = compute_stats(combined, "H. Portfolio (D+G)")
        s["elapsed"] = 0.0
        results.append(s)
        pf_s = _pf_str(s["profit_factor"])
        p(f"\n  [H. Portfolio (D+G)] {s['trades']} trades  "
          f"WR={s['win_rate']:.1%}  P&L=${s['total_pnl']:+,.0f}  PF={pf_s}")

    _print_table_kz(results)
    return results


def _print_table_kz(results: list[dict]) -> None:
    p(f"\n  {'='*90}")
    p("  TABLE 1 — KZ MATRIX 2024")
    p(f"  {'='*90}")
    p(f"  {'Label':<30} {'Trd':>5} {'WR':>6} {'PF':>6} "
      f"{'P&L':>10} {'MaxDD':>8} {'AvgW':>7} {'AvgL':>7}")
    p(f"  {'─'*88}")
    for r in results:
        p(f"  {r['label']:<30} {r['trades']:>5} {r['win_rate']:>5.0%} "
          f"{_pf_str(r['profit_factor']):>6} ${r['total_pnl']:>+9,.0f} "
          f"${r['max_dd']:>7,.0f} ${r['avg_win']:>6,.0f} ${r['avg_loss']:>6,.0f}")
    p(f"  {'─'*88}")


# =============================================================================
# PARTE 2 — TRADE MANAGEMENT 2024 (London + NY AM, fixed vs trailing)
# =============================================================================

def run_parte2_trade_management(df_2024: pd.DataFrame) -> list[dict]:
    p(f"\n{'='*70}")
    p(f"  PARTE 2 — TRADE MANAGEMENT 2024  kz={BEST_KZ}")
    p(f"{'='*70}")

    results = []
    for mode in ("fixed", "trailing"):
        label = f"TM-{mode}"
        s = run_single(
            df_2024, label, "nyam",
            kill_zones_override=BEST_KZ,
            trade_management=mode,
            start_date="2024-01-01", end_date="2024-12-31",
        )
        results.append(s)

    p(f"\n  {'='*75}")
    p("  TABLE 2 — TRADE MANAGEMENT 2024")
    p(f"  {'='*75}")
    p(f"  {'Mode':<20} {'Trd':>5} {'WR':>6} {'PF':>6} "
      f"{'P&L':>10} {'MaxDD':>8} {'AvgW':>7} {'AvgL':>7}")
    p(f"  {'─'*73}")
    for r in results:
        p(f"  {r['label']:<20} {r['trades']:>5} {r['win_rate']:>5.0%} "
          f"{_pf_str(r['profit_factor']):>6} ${r['total_pnl']:>+9,.0f} "
          f"${r['max_dd']:>7,.0f} ${r['avg_win']:>6,.0f} ${r['avg_loss']:>6,.0f}")
    p(f"  {'─'*73}")
    return results


# =============================================================================
# PARTE 3 — MULTI-YEAR 2019-2025 + Walk-Forward 2019-2022
# =============================================================================

def run_parte3_multiyear(
    df_full: pd.DataFrame,
    kill_zones_override: tuple = BEST_KZ,
    trade_management: str = "trailing",
) -> tuple[list[dict], list[dict]]:
    p(f"\n{'='*70}")
    p(f"  PARTE 3 — MULTI-YEAR  kz={kill_zones_override}  tm={trade_management}")
    p(f"{'='*70}")

    tz = df_full.index.tz

    # ── Walk-Forward 2019-2022 (24 bimonthly windows) ─────────────────────────
    p("\n  Walk-Forward 2019-2022 (24 bimonthly windows)")
    wf_windows = []
    wf_yearly_stats = []
    window_num = 0

    for year in (2019, 2020, 2021, 2022):
        y_start = pd.Timestamp(f"{year}-01-01", tz=tz)
        y_end   = pd.Timestamp(f"{year+1}-01-01", tz=tz)
        df_yr = df_full[(df_full.index >= y_start) & (df_full.index < y_end)]
        if df_yr.empty:
            p(f"  {year}: no data — skipping")
            continue

        p(f"\n  WF {year}: {len(df_yr):,} bars...", end="", flush=True)
        t0 = time.perf_counter()
        try:
            bt = build_backtester(
                df_yr, strategy_name="nyam",
                kill_zones_override=kill_zones_override,
                trade_management=trade_management,
            )
            result = bt.run(df_yr)
            elapsed = time.perf_counter() - t0
        except Exception as e:
            p(f" ERROR — {e}")
            traceback.print_exc()
            continue

        stats = compute_stats(result.trades, str(year))
        stats["elapsed"] = elapsed
        wf_yearly_stats.append(stats)
        p(
            f" {result.total_trades} trades  WR={result.win_rate:.1%}  "
            f"P&L=${result.total_pnl:+,.0f}  ({elapsed:.0f}s)"
        )

        # 6 bimonthly windows per year
        for bimester in range(6):
            w_start = pd.Timestamp(f"{year}-{bimester*2+1:02d}-01", tz=tz)
            w_end   = w_start + pd.DateOffset(months=2)
            window_num += 1
            w_trades = [t for t in result.trades if w_start <= t.entry_time < w_end]
            total = len(w_trades)
            wins  = sum(1 for t in w_trades if t.pnl > 0)
            pnl   = sum(t.pnl for t in w_trades)
            wp    = sum(t.pnl for t in w_trades if t.pnl > 0)
            lp    = abs(sum(t.pnl for t in w_trades if t.pnl <= 0))
            wr    = wins / total if total else 0.0
            pf    = wp / lp if lp > 0 else (float("inf") if wp > 0 else 0.0)
            pos   = pnl > 0
            ok    = "+" if pos else ("-" if total > 0 else " ")
            te_s  = w_start.strftime("%Y-%m-%d")
            te_e  = (w_end - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            p(
                f"    W{window_num:02d} [{te_s}→{te_e}]  "
                f"trd={total:3d}  wr={wr:4.0%}  pnl=${pnl:>+8.0f}  "
                f"pf={_pf_str(pf):>5}  {ok}"
            )
            wf_windows.append({
                "window": window_num, "year": year,
                "test_start": te_s, "test_end": te_e,
                "trades": total, "wins": wins, "losses": total - wins,
                "win_rate": wr, "total_pnl": pnl,
                "wins_pnl": wp, "losses_pnl": lp,
                "profit_factor": pf, "positive": pos,
            })

    # WF summary
    if wf_windows:
        total_w = len(wf_windows)
        pos_w   = sum(1 for r in wf_windows if r["positive"])
        pct_w   = pos_w / total_w
        gate    = "PASS ✓" if pct_w >= 0.70 else "FAIL ✗"
        agg_t   = sum(r["trades"] for r in wf_windows)
        agg_wins = sum(r["wins"] for r in wf_windows)
        agg_pnl = sum(r["total_pnl"] for r in wf_windows)
        agg_wp  = sum(r["wins_pnl"] for r in wf_windows)
        agg_lp  = sum(r["losses_pnl"] for r in wf_windows)
        agg_wr  = agg_wins / agg_t if agg_t else 0.0
        agg_pf  = agg_wp / agg_lp if agg_lp else 0.0
        p(f"\n  {'─'*65}")
        p(f"  WF Summary: {pos_w}/{total_w} ({pct_w:.1%}) positive  Gate>=70%: {gate}")
        p(f"  Total trades: {agg_t}  Agg WR: {agg_wr:.1%}  "
          f"Agg P&L: ${agg_pnl:+,.0f}  PF: {agg_pf:.2f}")

    # ── Full-year backtests 2019-2025 ──────────────────────────────────────────
    p(f"\n{'─'*70}")
    p("  Full-Year Backtests 2019-2025")
    full_year_stats = []

    for year in (2019, 2020, 2021, 2022, 2023, 2024):
        s_date = f"{year}-01-01"
        e_date = f"{year}-12-31"
        y_start = pd.Timestamp(s_date, tz=tz)
        y_end   = pd.Timestamp(e_date, tz=tz) + pd.Timedelta(days=1)
        df_yr = df_full[(df_full.index >= y_start) & (df_full.index < y_end)]
        if df_yr.empty:
            p(f"  {year}: no data")
            full_year_stats.append(compute_stats([], str(year)))
            continue
        s = run_single(df_yr, str(year), "nyam",
                       kill_zones_override=kill_zones_override,
                       trade_management=trade_management,
                       start_date=s_date, end_date=e_date)
        full_year_stats.append(s)

    # 2025 YTD
    df_25 = df_full[df_full.index >= pd.Timestamp("2025-01-01", tz=tz)]
    if not df_25.empty:
        s = run_single(df_25, "2025 YTD", "nyam",
                       kill_zones_override=kill_zones_override,
                       trade_management=trade_management,
                       start_date="2025-01-01", end_date="2025-12-31")
        full_year_stats.append(s)
    else:
        p("  2025: no data")

    # Table 3
    p(f"\n  {'='*80}")
    p("  TABLE 3 — MULTI-YEAR VALIDATION")
    p(f"  {'='*80}")
    if wf_windows:
        p(f"\n  Walk-Forward 2019-2022  ({total_w} bimonthly windows):")
        p(f"  Positive: {pos_w}/{total_w} ({pct_w:.1%})  Gate: {gate}")
        p(f"  Agg trades: {agg_t}  WR: {agg_wr:.1%}  P&L: ${agg_pnl:+,.0f}  PF: {agg_pf:.2f}")

    p(f"\n  {'Year':<12} {'Trd':>5} {'WR':>6} {'PF':>6} "
      f"{'P&L':>10} {'MaxDD':>8} {'AvgW':>7} {'AvgL':>7}")
    p(f"  {'─'*70}")
    for r in full_year_stats:
        p(f"  {r['label']:<12} {r['trades']:>5} {r['win_rate']:>5.0%} "
          f"{_pf_str(r['profit_factor']):>6} ${r['total_pnl']:>+9,.0f} "
          f"${r['max_dd']:>7,.0f} ${r['avg_win']:>6,.0f} ${r['avg_loss']:>6,.0f}")
    p(f"  {'─'*70}")

    return wf_windows, full_year_stats


# =============================================================================
# PARTE 4 — COMBINE SIMULATOR (topstep_mode=True)
# =============================================================================

def _simulate_combine_custom(
    trades: list,
    account_size: float,
    profit_target: float,
    mll: float,
    dll: float,
    max_attempts: int = 30,
    account_label: str = "",
) -> list[dict]:
    """
    Run up to max_attempts sequential combine attempts on a trade stream.
    Uses custom account/MLL/DLL instead of the global config values.
    """
    import config as _cfg
    # Temporarily patch config for simulate_combine
    _orig = (
        _cfg.TOPSTEP_ACCOUNT_SIZE,
        _cfg.TOPSTEP_PROFIT_TARGET,
        _cfg.TOPSTEP_MLL,
        _cfg.TOPSTEP_DLL,
    )
    _cfg.TOPSTEP_ACCOUNT_SIZE  = account_size
    _cfg.TOPSTEP_PROFIT_TARGET = profit_target
    _cfg.TOPSTEP_MLL           = mll
    _cfg.TOPSTEP_DLL           = dll

    remaining = sorted(trades, key=lambda t: t.entry_time)
    attempts  = []

    try:
        while remaining and len(attempts) < max_attempts:
            num = len(attempts) + 1
            result = simulate_combine(remaining, starting_balance=account_size)
            sorted_r = sorted(remaining, key=lambda t: t.entry_time)
            first_date = sorted_r[0].entry_time.date()

            if result.passed:
                pass_date = sorted_r[-1].entry_time.date()
                bal = account_size
                tgt = account_size + profit_target
                for t in sorted_r:
                    bal += t.pnl
                    if bal >= tgt:
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
                p(f"  Attempt {num:2d}: PASS  days={cal_days}")
            else:
                fail_date = sorted_r[-1].entry_time.date()
                bal = account_size
                peak_eod = account_size
                daily_map: dict = {}
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
                reason = (result.failure_reason or "unknown")[:50]
                attempts.append({
                    "attempt": num, "passed": False, "failure_reason": result.failure_reason,
                    "start_date": str(first_date), "end_date": str(fail_date),
                    "trading_days": result.trading_days, "calendar_days": cal_days,
                    "total_pnl": result.total_pnl, "trades": result.total_trades,
                })
                remaining = [t for t in remaining if t.entry_time.date() > fail_date]
                p(f"  Attempt {num:2d}: FAIL  {reason}")
    finally:
        # Restore config
        (
            _cfg.TOPSTEP_ACCOUNT_SIZE,
            _cfg.TOPSTEP_PROFIT_TARGET,
            _cfg.TOPSTEP_MLL,
            _cfg.TOPSTEP_DLL,
        ) = _orig

    return attempts


def _print_combine_attempts(attempts: list[dict]) -> None:
    p(f"  {'#':>3}  {'Result':>6}  {'Period':>24}  "
      f"{'Trd':>4}  {'P&L':>9}  {'TradeDays':>9}  {'CalDays':>7}")
    p(f"  {'─'*68}")
    for a in attempts:
        status = "PASS" if a["passed"] else "FAIL"
        period = f"{a['start_date']} → {a['end_date']}"
        p(
            f"  {a['attempt']:>3}  {status:>6}  {period:>24}  "
            f"{a['trades']:>4}  ${a['total_pnl']:>+8.0f}  "
            f"{a['trading_days']:>9}  {a['calendar_days']:>7}"
        )


def run_parte4_combine(
    df_full: pd.DataFrame,
    kill_zones_override: tuple = BEST_KZ,
    trade_management: str = "trailing",
) -> dict:
    p(f"\n{'='*70}")
    p(f"  PARTE 4 — COMBINE SIMULATOR  topstep_mode=True")
    p(f"  kz={kill_zones_override}  tm={trade_management}")
    p(f"{'='*70}")

    tz = df_full.index.tz
    combine_results = {}

    for year in (2023, 2024, 2025):
        if year == 2025:
            df_yr = df_full[df_full.index >= pd.Timestamp("2025-01-01", tz=tz)]
        else:
            df_yr = df_full[
                (df_full.index >= pd.Timestamp(f"{year}-01-01", tz=tz)) &
                (df_full.index < pd.Timestamp(f"{year+1}-01-01", tz=tz))
            ]
        if df_yr.empty:
            p(f"\n  {year}: no data — skipping")
            continue

        p(f"\n  Running {year} with topstep_mode=True...")
        s = run_single(
            df_yr, f"{year}-topstep", "nyam",
            kill_zones_override=kill_zones_override,
            trade_management=trade_management,
            start_date=f"{year}-01-01", end_date=f"{year}-12-31",
            topstep_mode=True,
        )
        trades = s.get("_trades_obj", [])
        if not trades:
            p(f"  {year}: 0 trades — skipping combine")
            continue

        combine_results[year] = {}

        # $50K Combine
        p(f"\n  {'─'*60}")
        p(f"  ${50}K Combine {year}  ({len(trades)} trades, 30 attempts)")
        p(f"  Account=$50K  Target=$3K  MLL=$2K  DLL=$1K")
        attempts_50k = _simulate_combine_custom(
            trades,
            account_size=50_000.0,
            profit_target=3_000.0,
            mll=2_000.0,
            dll=1_000.0,
            max_attempts=30,
        )
        passes_50k = sum(1 for a in attempts_50k if a["passed"])
        pr_50k = passes_50k / len(attempts_50k) if attempts_50k else 0.0
        avg_days_50k = (
            sum(a["calendar_days"] for a in attempts_50k if a["passed"]) / passes_50k
            if passes_50k else 0.0
        )
        fails_by_reason_50k: dict = defaultdict(int)
        for a in attempts_50k:
            if not a["passed"]:
                reason = (a["failure_reason"] or "unknown").split(":")[0].split(" on ")[0]
                fails_by_reason_50k[reason] += 1
        p(f"\n  RESULT: {passes_50k}/{len(attempts_50k)} PASS  ({pr_50k:.1%})  "
          f"avg_days={avg_days_50k:.1f}")
        _print_combine_attempts(attempts_50k)
        combine_results[year]["50k"] = {
            "attempts": attempts_50k, "passes": passes_50k,
            "pass_rate": pr_50k, "avg_days": avg_days_50k,
            "fails_by_reason": dict(fails_by_reason_50k),
        }

        # $150K Combine
        p(f"\n  {'─'*60}")
        p(f"  $150K Combine {year}  ({len(trades)} trades, 30 attempts)")
        p(f"  Account=$150K  Target=$9K  MLL=$4.5K  DLL=$2.25K")
        attempts_150k = _simulate_combine_custom(
            trades,
            account_size=COMBINE_150K_ACCOUNT,
            profit_target=COMBINE_150K_TARGET,
            mll=COMBINE_150K_MLL,
            dll=COMBINE_150K_DLL,
            max_attempts=30,
        )
        passes_150k = sum(1 for a in attempts_150k if a["passed"])
        pr_150k = passes_150k / len(attempts_150k) if attempts_150k else 0.0
        avg_days_150k = (
            sum(a["calendar_days"] for a in attempts_150k if a["passed"]) / passes_150k
            if passes_150k else 0.0
        )
        fails_by_reason_150k: dict = defaultdict(int)
        for a in attempts_150k:
            if not a["passed"]:
                reason = (a["failure_reason"] or "unknown").split(":")[0].split(" on ")[0]
                fails_by_reason_150k[reason] += 1
        p(f"\n  RESULT: {passes_150k}/{len(attempts_150k)} PASS  ({pr_150k:.1%})  "
          f"avg_days={avg_days_150k:.1f}")
        _print_combine_attempts(attempts_150k)
        combine_results[year]["150k"] = {
            "attempts": attempts_150k, "passes": passes_150k,
            "pass_rate": pr_150k, "avg_days": avg_days_150k,
            "fails_by_reason": dict(fails_by_reason_150k),
        }

    # Summary Table 4
    p(f"\n  {'='*80}")
    p("  TABLE 4 — COMBINE SIMULATOR SUMMARY (topstep_mode=True)")
    p(f"  {'='*80}")
    p(f"  {'Config':<25} {'Year':>6} {'Pass/Att':>9} {'Rate':>6} "
      f"{'AvgDays':>8} {'Bottleneck':<30}")
    p(f"  {'─'*80}")
    for year, yr_data in sorted(combine_results.items()):
        for acct_label, data in (("$50K (MLL=$2K)", yr_data.get("50k")),
                                  ("$150K (MLL=$4.5K)", yr_data.get("150k"))):
            if data is None:
                continue
            bottleneck = max(data["fails_by_reason"].items(),
                             key=lambda x: x[1])[0] if data["fails_by_reason"] else "—"
            p(f"  {acct_label:<25} {year:>6}  "
              f"{data['passes']:>2}/{len(data['attempts']):>2}     "
              f"{data['pass_rate']:>5.1%}  {data['avg_days']:>7.1f}  {bottleneck}")
    p(f"  {'─'*80}")

    return combine_results


# =============================================================================
# PARTE 5 — IFVG VALIDATION 2024
# =============================================================================

def run_parte5_ifvg(df_2024: pd.DataFrame) -> list[dict]:
    p(f"\n{'='*70}")
    p(f"  PARTE 5 — IFVG VALIDATION 2024  kz={ALL_NYAM_KZ}  tm=trailing")
    p(f"{'='*70}")

    results = []
    for ifvg_on in (True, False):
        label = "I. IFVG ON" if ifvg_on else "J. IFVG OFF"
        s = run_single(
            df_2024, label, "nyam",
            kill_zones_override=ALL_NYAM_KZ,
            trade_management="trailing",
            start_date="2024-01-01", end_date="2024-12-31",
            ifvg_enabled=ifvg_on,
        )
        results.append(s)

    if len(results) == 2:
        on_r, off_r = results
        delta_trades = on_r["trades"] - off_r["trades"]
        delta_wr     = on_r["win_rate"] - off_r["win_rate"]
        delta_pf     = on_r["profit_factor"] - off_r["profit_factor"] if (
            on_r["profit_factor"] != float("inf") and off_r["profit_factor"] != float("inf")
        ) else float("nan")
        delta_pnl    = on_r["total_pnl"] - off_r["total_pnl"]

    p(f"\n  {'='*75}")
    p("  TABLE 5 — IFVG VALIDATION 2024")
    p(f"  {'='*75}")
    p(f"  {'Config':<20} {'Trd':>5} {'WR':>6} {'PF':>6} "
      f"{'P&L':>10} {'MaxDD':>8} {'AvgW':>7} {'AvgL':>7}")
    p(f"  {'─'*73}")
    for r in results:
        p(f"  {r['label']:<20} {r['trades']:>5} {r['win_rate']:>5.0%} "
          f"{_pf_str(r['profit_factor']):>6} ${r['total_pnl']:>+9,.0f} "
          f"${r['max_dd']:>7,.0f} ${r['avg_win']:>6,.0f} ${r['avg_loss']:>6,.0f}")
    p(f"  {'─'*73}")
    if len(results) == 2:
        dpf_s = f"{delta_pf:+.2f}" if delta_pf == delta_pf else "  n/a"
        p(f"  {'DELTA (ON-OFF)':<20} {delta_trades:>+5} {delta_wr:>+5.0%} "
          f"{dpf_s:>6} ${delta_pnl:>+9,.0f}")

    return results


# =============================================================================
# PARTE 6 — COMPARATIVA (summary table before vs after)
# =============================================================================

def print_parte6_comparativa(
    kz_results: list[dict],
    tm_results: list[dict],
    full_year_stats: list[dict],
    wf_windows: list[dict],
    combine_results: dict,
    ifvg_results: list[dict],
) -> None:
    p(f"\n{'='*90}")
    p("  PARTE 6 — COMPARATIVA FINAL")
    p(f"{'='*90}")

    # Best KZ from PARTE 1
    nyam_runs = [r for r in kz_results if r["label"].startswith(("A.", "B.", "C.", "D."))]
    best_kz_row = max(nyam_runs, key=lambda r: (r["trades"] > 0) * r["profit_factor"]) if nyam_runs else None

    p("\n  ── Best KZ (highest PF, NYAM 2024) ──────────────────────────────────")
    if best_kz_row:
        p(f"  {best_kz_row['label']}: trades={best_kz_row['trades']}  "
          f"WR={best_kz_row['win_rate']:.1%}  "
          f"PF={_pf_str(best_kz_row['profit_factor'])}  "
          f"P&L=${best_kz_row['total_pnl']:+,.0f}")

    p("\n  ── Trade Management (NYAM 2024, London+NY AM) ───────────────────────")
    for r in tm_results:
        p(f"  {r['label']:<20}: trades={r['trades']}  WR={r['win_rate']:.1%}  "
          f"PF={_pf_str(r['profit_factor'])}  P&L=${r['total_pnl']:+,.0f}")

    p("\n  ── Multi-Year Full-Year (trailing, London+NY AM) ────────────────────")
    p(f"  {'Year':<12} {'Trd':>5} {'WR':>6} {'PF':>6} {'P&L':>10} {'MaxDD':>8}")
    p(f"  {'─'*55}")
    for r in full_year_stats:
        p(f"  {r['label']:<12} {r['trades']:>5} {r['win_rate']:>5.0%} "
          f"{_pf_str(r['profit_factor']):>6} ${r['total_pnl']:>+9,.0f} "
          f"${r['max_dd']:>7,.0f}")

    p("\n  ── Walk-Forward 2019-2022 ────────────────────────────────────────────")
    if wf_windows:
        pos = sum(1 for r in wf_windows if r["positive"])
        pct = pos / len(wf_windows)
        gate = "PASS ✓" if pct >= 0.70 else "FAIL ✗"
        p(f"  {pos}/{len(wf_windows)} ({pct:.1%}) positive windows  Gate: {gate}")

    p("\n  ── Combine Summary (topstep_mode=True) ─────────────────────────────")
    p(f"  {'Config':<25} {'Year':>6} {'Pass/Att':>9} {'Rate':>6} {'AvgDays':>8}")
    p(f"  {'─'*60}")
    for year, yr_data in sorted(combine_results.items()):
        for acct_label, data in (("$50K (MLL=$2K)", yr_data.get("50k")),
                                  ("$150K (MLL=$4.5K)", yr_data.get("150k"))):
            if data is None:
                continue
            p(f"  {acct_label:<25} {year:>6}  "
              f"{data['passes']:>2}/{len(data['attempts']):>2}     "
              f"{data['pass_rate']:>5.1%}  {data['avg_days']:>7.1f}")

    p("\n  ── IFVG Impact (2024 ALL KZ trailing) ──────────────────────────────")
    if len(ifvg_results) == 2:
        for r in ifvg_results:
            p(f"  {r['label']:<20}: trades={r['trades']}  WR={r['win_rate']:.1%}  "
              f"PF={_pf_str(r['profit_factor'])}  P&L=${r['total_pnl']:+,.0f}")

    p("\n  ── VERDICT ──────────────────────────────────────────────────────────")
    # Combine-ready check
    c24 = combine_results.get(2024, {}).get("50k")
    wf_ok = (sum(1 for r in wf_windows if r["positive"]) / len(wf_windows) >= 0.70
             if wf_windows else False)
    combine_ok = (c24["pass_rate"] >= 0.40) if c24 else False

    if wf_ok and combine_ok:
        verdict = "READY FOR COMBINE ✓"
        detail  = "Walk-forward gate PASSED and 2024 $50K Combine pass rate >= 40%."
    elif wf_ok:
        verdict = "PROMISING — Combine pass rate below 40%"
        detail  = "Walk-forward gate PASSED. Need higher combine pass rate."
    elif combine_ok:
        verdict = "PARTIAL — WF gate failed"
        detail  = "2024 Combine pass rate OK but walk-forward gate FAILED."
    else:
        verdict = "NOT READY — both gates failed"
        detail  = "Walk-forward and Combine gates both FAILED."

    p(f"\n  VERDICT: {verdict}")
    p(f"  {detail}")
    p(f"  {'─'*68}\n")


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    t_total = time.perf_counter()

    if not DATABENTO_PATH.exists():
        p(f"\n✗ Databento file not found: {DATABENTO_PATH}")
        return 1

    mb = DATABENTO_PATH.stat().st_size / 1024 / 1024
    p(f"\nData: {DATABENTO_PATH.name}  ({mb:.0f} MB)")

    # ── Load full dataset ONCE ─────────────────────────────────────────────────
    p("\nLoading Databento NQ 1-min (2019-2025)...", end="", flush=True)
    t0 = time.perf_counter()
    try:
        df_full = load_databento_ohlcv_1m(
            DATABENTO_PATH,
            start_date="2019-01-01",
            end_date="2025-12-31",
            symbol_prefix="NQ",
        )
        tz = df_full.index.tz
        p(
            f" {len(df_full):,} bars  "
            f"({df_full.index[0].date()} → {df_full.index[-1].date()})  "
            f"({time.perf_counter()-t0:.1f}s)"
        )
    except Exception as e:
        p(f" ERROR: {e}")
        traceback.print_exc()
        return 1

    # 2024 slice
    df_2024 = df_full[
        (df_full.index >= pd.Timestamp("2024-01-01", tz=tz)) &
        (df_full.index < pd.Timestamp("2025-01-01", tz=tz))
    ]
    p(f"2024 slice: {len(df_2024):,} bars")

    # ── PARTE 1 ────────────────────────────────────────────────────────────────
    kz_results = run_parte1_kz_matrix(df_2024)

    # ── PARTE 2 ────────────────────────────────────────────────────────────────
    tm_results = run_parte2_trade_management(df_2024)

    # ── PARTE 3 ────────────────────────────────────────────────────────────────
    wf_windows, full_year_stats = run_parte3_multiyear(
        df_full,
        kill_zones_override=BEST_KZ,
        trade_management="trailing",
    )

    # ── PARTE 4 ────────────────────────────────────────────────────────────────
    combine_results = run_parte4_combine(
        df_full,
        kill_zones_override=BEST_KZ,
        trade_management="trailing",
    )

    # ── PARTE 5 ────────────────────────────────────────────────────────────────
    ifvg_results = run_parte5_ifvg(df_2024)

    # ── PARTE 6 ────────────────────────────────────────────────────────────────
    print_parte6_comparativa(
        kz_results=kz_results,
        tm_results=tm_results,
        full_year_stats=full_year_stats,
        wf_windows=wf_windows,
        combine_results=combine_results,
        ifvg_results=ifvg_results,
    )

    elapsed_total = time.perf_counter() - t_total
    h = int(elapsed_total // 3600)
    m = int((elapsed_total % 3600) // 60)
    s = int(elapsed_total % 60)
    p(f"\n  {'='*70}")
    p(f"  Suite complete: {h}h {m}m {s}s")
    p(f"  Output: {LOG_FILE}")
    p(f"  {'='*70}\n")

    if _log_fh:
        try:
            _log_fh.flush()
            _log_fh.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        p("\nInterrupted.")
        sys.exit(130)
