"""
scripts/combine_mll_protected.py
=================================
2023 Combine Simulator with M14 MLL-aware risk manager ACTIVE during
the backtest (not just post-hoc).

Key difference from the unprotected run:
  - Caution zone (80% MLL = $1,600 DD): position size halved, min_confluence +2
  - Stop zone (95% MLL = $1,900 DD): no new trades until next session
  - Protective mode after target reached

Each sequential attempt gets a FRESH backtester with topstep_mode=True.
The risk manager actively prevents trades near the MLL boundary.

Usage:
    cd algoict-engine
    python -u scripts/combine_mll_protected.py
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

print("=== Combine Simulator 2023 — MLL-Protected (M14) ===", flush=True)
print("Importing...", flush=True)

from backtest.backtester import Backtester, BacktestResult
from backtest.data_loader import load_data_csv

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
    def __init__(self, inner, df_daily, df_weekly):
        self._inner = inner
        self._df_daily = df_daily
        self._df_weekly = df_weekly
        self._detector = HTFBiasDetector()
        self._current_ts = None
        self._inner.htf_bias_fn = self._dynamic_bias

    def _dynamic_bias(self, price, *_, **__):
        if self._current_ts is None:
            return self._detector._neutral_result()
        cutoff = self._current_ts.normalize()
        pd_ = self._df_daily[self._df_daily.index < cutoff]
        pw_ = self._df_weekly[self._df_weekly.index < cutoff]
        if pd_.empty or pw_.empty:
            return self._detector._neutral_result()
        return self._detector.determine_bias(pd_, pw_, float(price))

    def evaluate(self, ce, cc):
        if not ce.empty:
            self._current_ts = ce.index[-1]
        return self._inner.evaluate(ce, cc)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ─── Build backtester WITH topstep mode ───────────────────────────────────────

def build_mll_backtester(df_1min: pd.DataFrame):
    """Build backtester with M14 MLL-aware risk protection enabled."""
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

    # MLL-aware risk manager WITH cruise mode
    risk_mgr = RiskManager()
    risk_mgr.enable_topstep_mode(
        starting_balance=cfg.TOPSTEP_ACCOUNT_SIZE,  # $50,000
        mll=cfg.TOPSTEP_MLL,                        # $2,000
        profit_target=cfg.TOPSTEP_PROFIT_TARGET,     # $3,000
        caution_pct=0.80,                            # 80% = $1,600 DD
        stop_pct=0.95,                               # 95% = $1,900 DD
        protective_after_target=False,
        cruise_mode=True,                            # NEW: cruise after target
    )

    tf_mgr = TimeframeManager()
    session_mgr = SessionManager()

    def static_bullish(*_, **__):
        return BiasResult(direction="bullish", premium_discount="discount",
                          htf_levels={}, confidence="high",
                          weekly_bias="bullish", daily_bias="bullish")

    inner = NYAMReversalStrategy(detectors, risk_mgr, session_mgr, static_bullish)

    if not df_daily.empty and not df_weekly.empty:
        strategy = DynamicBiasStrategy(inner, df_daily, df_weekly)
    else:
        strategy = inner

    return Backtester(strategy, detectors, risk_mgr, tf_mgr, session_mgr)


# ─── Sequential Combine attempts (MLL-protected) ─────────────────────────────

def run_sequential_attempts(df_2023: pd.DataFrame) -> list[dict]:
    """
    Run sequential Combine attempts with MLL protection active.

    Each attempt:
    1. Build FRESH backtester with topstep_mode=True ($50K start)
    2. Run backtest on remaining 2023 data
    3. Walk trades to find if/when target reached ($53K)
    4. If reached: PASS → next attempt starts after pass date
    5. If not reached: FAIL → next attempt starts after last trade
    """
    tz = df_2023.index.tz
    attempts = []
    attempt_start = pd.Timestamp("2023-01-01", tz=tz)
    year_end = pd.Timestamp("2024-01-01", tz=tz)

    while attempt_start < year_end and len(attempts) < 30:
        num = len(attempts) + 1
        df_remaining = df_2023[df_2023.index >= attempt_start]

        if len(df_remaining) < 100:  # Not enough data for meaningful attempt
            break

        print(f"\n  Attempt {num}: starting {attempt_start.strftime('%Y-%m-%d')} "
              f"({len(df_remaining):,} bars)...", flush=True)

        t0 = time.perf_counter()

        # Build FRESH backtester with MLL protection
        backtester = build_mll_backtester(df_remaining)
        result = backtester.run(df_remaining)
        rm = backtester.risk  # Access risk manager state

        elapsed = time.perf_counter() - t0

        print(f"    {result.total_trades} trades, WR={result.win_rate:.1%}, "
              f"P&L=${result.total_pnl:+,.0f}  ({elapsed:.1f}s)", flush=True)
        print(f"    RM: balance=${rm.current_balance:,.0f}, "
              f"peak=${rm.peak_balance_eod:,.0f}, "
              f"DD=${rm.current_drawdown:,.0f}, zone={rm.mll_zone}, "
              f"cruise={rm.cruise_mode}, days={rm.trading_days_count}", flush=True)

        if result.total_trades == 0:
            attempts.append({
                "attempt": num, "passed": False,
                "failure_reason": "no_trades",
                "start_date": attempt_start.strftime("%Y-%m-%d"),
                "end_date": attempt_start.strftime("%Y-%m-%d"),
                "trades": 0, "wins": 0, "win_rate": 0.0,
                "total_pnl": 0.0, "calendar_days": 0,
                "final_balance": cfg.TOPSTEP_ACCOUNT_SIZE,
                "peak_balance": cfg.TOPSTEP_ACCOUNT_SIZE,
                "max_drawdown": 0.0,
            })
            print(f"    → FAIL (no trades)", flush=True)
            break

        # Walk trades to find the pass/fail point.
        # With cruise mode, a PASS requires BOTH:
        #   1. balance >= $53K at some point
        #   2. trading_days >= 5
        # Cruise mode keeps trading after target to accumulate days.
        balance = cfg.TOPSTEP_ACCOUNT_SIZE
        target = balance + cfg.TOPSTEP_PROFIT_TARGET  # $53,000
        peak_eod = balance
        max_dd = 0.0
        target_date = None
        pass_date = None
        last_date = None
        daily_pnl = {}
        trading_days = set()

        sorted_trades = sorted(result.trades, key=lambda t: t.entry_time)
        for t in sorted_trades:
            d = t.entry_time.date()
            trading_days.add(d)
            daily_pnl[d] = daily_pnl.get(d, 0.0) + t.pnl
            balance += t.pnl

            # Track max drawdown from EOD peak
            dd = peak_eod - balance
            if dd > max_dd:
                max_dd = dd

            # Track when target was first reached
            if balance >= target and target_date is None:
                target_date = d

            # PASS = target reached AND 5+ trading days
            if target_date and len(trading_days) >= 5 and balance >= target:
                pass_date = d
                break

            last_date = d

            # EOD peak update (simplified)
            if last_date and d != last_date and balance > peak_eod:
                peak_eod = balance

        if balance > peak_eod:
            peak_eod = balance

        first_date = sorted_trades[0].entry_time.date()
        end_date = pass_date or last_date or first_date
        cal_days = (end_date - first_date).days + 1
        n_trade_days = len([d for d in trading_days if d <= end_date])

        wins = sum(1 for t in sorted_trades if t.pnl > 0 and t.entry_time.date() <= end_date)
        total_counted = sum(1 for t in sorted_trades if t.entry_time.date() <= end_date)
        wr = wins / total_counted if total_counted > 0 else 0.0
        final_pnl = sum(t.pnl for t in sorted_trades if t.entry_time.date() <= end_date)

        if pass_date is not None:
            passed = True
            reason = None
            # Consistency check
            if daily_pnl:
                best_day = max(v for d, v in daily_pnl.items() if d <= pass_date)
                total_profit = sum(v for d, v in daily_pnl.items() if d <= pass_date)
                if total_profit > 0 and best_day >= 0.5 * total_profit:
                    passed = False
                    reason = f"consistency (best=${best_day:+,.0f} >= 50% of ${total_profit:+,.0f})"
            if passed:
                print(f"    → PASS on {pass_date} ({cal_days}d, "
                      f"{n_trade_days} trading days"
                      f"{', via cruise' if target_date != pass_date else ''})",
                      flush=True)
            else:
                print(f"    → FAIL ({reason})", flush=True)
        elif target_date is not None:
            # Target was hit but never had 5 days with balance >= target
            passed = False
            reason = (f"target_hit_{target_date}_but_{n_trade_days}_days"
                      f"_bal=${balance - cfg.TOPSTEP_ACCOUNT_SIZE + cfg.TOPSTEP_ACCOUNT_SIZE:,.0f}")
            print(f"    → FAIL (target hit {target_date} but only "
                  f"{n_trade_days} trading days, cruise couldn't finish)", flush=True)
        else:
            passed = False
            reason = f"target_not_reached (pnl=${final_pnl:+,.0f})"
            print(f"    → FAIL ({reason})", flush=True)

        attempts.append({
            "attempt": num,
            "passed": passed,
            "failure_reason": reason,
            "start_date": first_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "trades": total_counted,
            "wins": wins,
            "win_rate": wr,
            "total_pnl": final_pnl,
            "calendar_days": cal_days,
            "final_balance": cfg.TOPSTEP_ACCOUNT_SIZE + final_pnl,
            "peak_balance": peak_eod,
            "max_drawdown": max_dd,
            "trading_days": n_trade_days,
            "cruise_used": target_date is not None and target_date != pass_date,
        })

        # Next attempt starts after the pass/fail date
        if end_date:
            attempt_start = pd.Timestamp(str(end_date), tz=tz) + pd.Timedelta(days=1)
        else:
            break

    return attempts


# ─── Reporting ────────────────────────────────────────────────────────────────

def print_summary(attempts: list[dict]) -> None:
    total = len(attempts)
    passes = sum(1 for a in attempts if a["passed"])
    fails = total - passes
    pass_days = [a["calendar_days"] for a in attempts if a["passed"]]
    avg_days = sum(pass_days) / len(pass_days) if pass_days else None

    all_trades = sum(a["trades"] for a in attempts)
    all_wins = sum(a["wins"] for a in attempts)
    agg_wr = all_wins / all_trades if all_trades > 0 else 0.0

    print(f"\n{'='*65}", flush=True)
    print(f"  Combine 2023 — MLL-Protected (M14) Summary", flush=True)
    print(f"{'='*65}", flush=True)
    print(f"  Attempts          : {total}", flush=True)
    print(f"  Passes            : {passes}", flush=True)
    print(f"  Fails             : {fails}", flush=True)
    print(f"  Pass rate         : {passes/total:.1%}" if total else "", flush=True)
    print(f"  Agg win rate      : {agg_wr:.1%}", flush=True)
    if avg_days is not None:
        print(f"  Avg days to pass  : {avg_days:.1f}", flush=True)
    print(flush=True)

    cruise_passes = sum(1 for a in attempts if a["passed"] and a.get("cruise_used"))
    print(f"  Cruise-assisted passes: {cruise_passes}", flush=True)
    print(flush=True)

    print(f"  {'#':>2}  {'Res':>4}  {'Period':>24}  {'Trd':>4}  {'WR':>4}  "
          f"{'P&L':>9}  {'Days':>4}  {'TDays':>5}  {'MaxDD':>7}  {'Note'}", flush=True)
    print(f"  {'─'*95}", flush=True)

    for a in attempts:
        status = "PASS" if a["passed"] else "FAIL"
        period = f"{a['start_date']} → {a['end_date']}"
        note = ""
        if a["passed"] and a.get("cruise_used"):
            note = "cruise"
        elif a["passed"]:
            note = "direct"
        else:
            note = (a.get("failure_reason") or "")[:30]
        td = a.get("trading_days", "?")
        print(f"  {a['attempt']:>2}  {status:>4}  {period:>24}  {a['trades']:>4}  "
              f"{a['win_rate']:>3.0%}  ${a['total_pnl']:>+8.0f}  {a['calendar_days']:>4}  "
              f"{td:>5}  ${a['max_drawdown']:>6.0f}  {note}", flush=True)

    # Compare
    print(f"\n  Comparison:", flush=True)
    print(f"    Unprotected:         0/18 passes — all MLL breaches", flush=True)
    print(f"    MLL-protected:       2/13 passes — 6 hit target but <5 days", flush=True)
    print(f"    MLL + Cruise:        {passes}/{total} passes ({cruise_passes} via cruise)", flush=True)


def update_memory(attempts: list[dict]) -> None:
    """Append MLL-protected results to the existing memory file."""
    path = ENGINE_ROOT.parent / ".claude" / "memory" / "project" / "backtest-results.md"
    if not path.exists():
        print(f"  WARN: {path} not found — skipping memory update", flush=True)
        return

    total = len(attempts)
    passes = sum(1 for a in attempts if a["passed"])
    pass_days = [a["calendar_days"] for a in attempts if a["passed"]]
    avg_days = sum(pass_days) / len(pass_days) if pass_days else None

    cruise_passes = sum(1 for a in attempts if a["passed"] and a.get("cruise_used"))

    lines = [
        "",
        "## Tarea 2c: Combine 2023 — MLL + Cruise Mode",
        "",
        "MLL protection + cruise mode after target reached:",
        "- Caution zone (80% MLL): size halved, min_confluence +2",
        "- Stop zone (95% MLL): no new trades until next session",
        "- **Cruise mode**: after target hit with <5 trading days:",
        "  - Max 1 trade/day, 1 MNQ, confluence >= 12, max risk $100",
        "  - Continues until 5 trading days accumulated",
        "",
        "| Metric | Unprotected | MLL Only | MLL + Cruise |",
        "|--------|-------------|----------|--------------|",
        f"| Attempts | 18 | 13 | {total} |",
        f"| Passes | 0 | 2 | {passes} |",
        f"| Pass rate | 0% | 15% | {passes/total:.0%} |",
        f"| Avg days to pass | N/A | 8.5 | {f'{avg_days:.1f}' if avg_days else 'N/A'} |",
        f"| Cruise-assisted | — | — | {cruise_passes} |",
        "",
        "### Attempt Log (MLL + Cruise)",
        "",
        "| # | Result | Period | Trades | WR | P&L | Days | TDays | MaxDD | Note |",
        "|---|--------|--------|--------|----|-----|------|-------|-------|------|",
    ]
    for a in attempts:
        status = "PASS" if a["passed"] else "FAIL"
        note = "cruise" if a.get("cruise_used") else ("direct" if a["passed"] else "")
        td = a.get("trading_days", "?")
        lines.append(
            f"| {a['attempt']} | {status} | {a['start_date']} → {a['end_date']} "
            f"| {a['trades']} | {a['win_rate']:.0%} "
            f"| ${a['total_pnl']:+,.0f} | {a['calendar_days']} | {td} "
            f"| ${a['max_drawdown']:,.0f} | {note} |"
        )

    existing = path.read_text(encoding="utf-8")
    path.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n  Memory updated: {path}", flush=True)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    data_dir = ENGINE_ROOT.parent / "data"
    csv_path = data_dir / "nq_1min.csv"

    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", flush=True)
        return 1

    print(f"\nLoading 2023 NQ data...", flush=True)
    t0 = time.perf_counter()
    df_raw = load_data_csv(csv_path)
    tz = df_raw.index.tz
    df_2023 = df_raw[
        (df_raw.index >= pd.Timestamp("2023-01-01", tz=tz)) &
        (df_raw.index < pd.Timestamp("2024-01-01", tz=tz))
    ]
    print(f"Loaded {len(df_2023):,} bars in {time.perf_counter()-t0:.1f}s", flush=True)

    print(f"\n{'='*65}", flush=True)
    print(f"  Combine Simulator 2023 — MLL-Protected (M14)", flush=True)
    print(f"  $50K | $53K target | MLL $2K | Caution@80% | Stop@95% | Cruise ON", flush=True)
    print(f"{'='*65}", flush=True)

    attempts = run_sequential_attempts(df_2023)
    print_summary(attempts)
    update_memory(attempts)

    print(f"\n{'='*65}", flush=True)
    print("  DONE", flush=True)
    print(f"{'='*65}\n", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
