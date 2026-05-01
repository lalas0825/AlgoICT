"""
scripts/rolling_combine_simulator.py
=====================================
Rolling Topstep $50K Combine simulator.

Processes a list of backtest trades chronologically, simulating the
FULL Topstep enforcement chain: pass on profit target → start new
Combine, fail on MLL/DLL → start new Combine.

Rules enforced
--------------
- Starting balance:      $50,000
- Profit target:         +$3,000  (reach $53,000) → PASS, new Combine
- Maximum Loss Limit:    -$2,000  trailing from peak EOD balance → FAIL, new Combine
- Daily Loss Limit:      -$1,000  (intraday) → STOP day (not Combine fail)
- Daily Profit Cap:      +$1,500  (intraday, self-imposed risk rule) → STOP day
- Consistency Rule:      Best day < 50% of total profit (only checked at PASS)
                          → if violated, Combine passes but is flagged
- Minimum trading days:  5 (only checked at PASS)
- Hard close:            15:00 CT (no overnight; backtest already enforces)
- Reset fee:             $50 per failed Combine (Topstep current fee)

Output
------
Per-year + per-month + 7-year aggregate stats:
  - Combines started / passed / failed
  - Pass rate
  - Avg / min / max days to pass
  - Daily profit cap hits (P&L "left on table")
  - DLL hits (days halted)
  - Consistency rule violations (PASS but flagged)
  - Net "real" P&L = sum of pass profits - reset fees - capped P&L lost

Usage
-----
    python -m scripts.rolling_combine_simulator \
        --trades "analysis/sb_v19a_wide_*.json" \
        --start-balance 50000 \
        --profit-target 3000 \
        --mll 2000 \
        --dll 1000 \
        --daily-cap 1500 \
        --reset-fee 50 \
        --min-trading-days 5 \
        --output analysis/v19a_wide_combine_sim.md
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional


# ─── Defaults (Topstep $50K Combine current rules) ──────────────────────────
START_BALANCE = 50_000.0
PROFIT_TARGET = 3_000.0
MLL = 2_000.0
DLL = 1_000.0
DAILY_PROFIT_CAP = 1_500.0
RESET_FEE = 50.0
MIN_TRADING_DAYS = 5
CONSISTENCY_PCT = 0.50


@dataclass
class CombineResult:
    combine_n: int
    status: str           # 'passed' | 'failed_mll' | 'in_progress'
    start_date: date
    end_date: date
    days_traded: int
    trades_taken: int
    final_balance: float
    pnl: float
    best_day_pnl: float
    worst_day_pnl: float
    consistency_violation: bool
    min_days_violation: bool
    fail_reason: str = ""


@dataclass
class SimResult:
    combines: list[CombineResult] = field(default_factory=list)
    daily_pnl_history: list[tuple[date, float]] = field(default_factory=list)
    days_capped: list[date] = field(default_factory=list)
    days_dll_hit: list[date] = field(default_factory=list)
    pnl_lost_to_cap: float = 0.0
    pnl_saved_by_dll: float = 0.0   # how much extra loss DLL prevented
    total_reset_fees: float = 0.0
    total_payout: float = 0.0       # sum of passed combines' profits


def parse_dt(s: str) -> datetime:
    """Parse ISO timestamp from trade JSON (handles tz suffix)."""
    return datetime.fromisoformat(s)


def simulate_rolling_combines(
    trades: list[dict],
    start_balance: float = START_BALANCE,
    profit_target: float = PROFIT_TARGET,
    mll: float = MLL,
    dll: float = DLL,
    daily_cap: float = DAILY_PROFIT_CAP,
    reset_fee: float = RESET_FEE,
    min_trading_days: int = MIN_TRADING_DAYS,
    consistency_pct: float = CONSISTENCY_PCT,
) -> SimResult:
    """Run rolling Combine simulation. trades MUST be sorted by entry_time."""

    result = SimResult()

    # Per-Combine state
    balance = start_balance
    peak_eod_balance = start_balance
    combine_n = 1
    combine_start_date: Optional[date] = None
    combine_trades: list[dict] = []
    combine_daily_pnl: dict[date, float] = {}
    combine_capped_days: set[date] = set()
    combine_dll_days: set[date] = set()
    last_processed_date: Optional[date] = None

    def reset_combine(new_balance: float = start_balance):
        """Reset state for a new Combine."""
        nonlocal balance, peak_eod_balance, combine_n
        nonlocal combine_start_date, combine_trades, combine_daily_pnl
        nonlocal combine_capped_days, combine_dll_days
        balance = new_balance
        peak_eod_balance = new_balance
        combine_n += 1
        combine_start_date = None
        combine_trades = []
        combine_daily_pnl = {}
        combine_capped_days = set()
        combine_dll_days = set()

    def end_of_day_update(d: date):
        """Update peak_eod_balance after day d closes."""
        nonlocal peak_eod_balance
        if balance > peak_eod_balance:
            peak_eod_balance = balance

    def finalize_combine(end_date: date, status: str, fail_reason: str = ""):
        """Record current Combine result and reset."""
        days_traded = len(combine_daily_pnl)
        best_day = max(combine_daily_pnl.values()) if combine_daily_pnl else 0.0
        worst_day = min(combine_daily_pnl.values()) if combine_daily_pnl else 0.0
        pnl = balance - start_balance

        # Consistency rule (only relevant on PASS)
        consistency_viol = False
        if status == "passed" and pnl > 0:
            if best_day > consistency_pct * pnl:
                consistency_viol = True
        # Min trading days (only relevant on PASS)
        min_days_viol = (status == "passed" and days_traded < min_trading_days)

        cr = CombineResult(
            combine_n=combine_n,
            status=status,
            start_date=combine_start_date or end_date,
            end_date=end_date,
            days_traded=days_traded,
            trades_taken=len(combine_trades),
            final_balance=balance,
            pnl=pnl,
            best_day_pnl=best_day,
            worst_day_pnl=worst_day,
            consistency_violation=consistency_viol,
            min_days_violation=min_days_viol,
            fail_reason=fail_reason,
        )
        result.combines.append(cr)
        if status.startswith("failed"):
            result.total_reset_fees += reset_fee
        elif status == "passed" and not consistency_viol and not min_days_viol:
            # Funded payout = the +$3,000 target you "earned"
            # (in real Topstep, this becomes the funded account starting capital)
            result.total_payout += pnl
        # Daily history
        for d, p in sorted(combine_daily_pnl.items()):
            result.daily_pnl_history.append((d, p))
        result.days_capped.extend(sorted(combine_capped_days))
        result.days_dll_hit.extend(sorted(combine_dll_days))
        reset_combine()

    # ─── Main loop ──────────────────────────────────────────────────────
    for trade in trades:
        entry_dt = parse_dt(trade["entry_time"])
        d = entry_dt.date()

        # End-of-day update when crossing into a new day
        if last_processed_date is not None and d != last_processed_date:
            end_of_day_update(last_processed_date)
            # 2026-05-01 — EOD pass check: only after min trading days reached.
            # Topstep rule: balance must be >= start + target AND >= min days.
            # If both true at EOD, PASS the Combine (even if more trades pending
            # later that day — those would count for next Combine).
            days_traded = len(combine_daily_pnl)
            net_pnl_eod = balance - start_balance
            if (days_traded >= min_trading_days
                    and net_pnl_eod >= profit_target):
                finalize_combine(last_processed_date, "passed")
                # Note: this trade we're about to process belongs to the
                # NEXT Combine. Reset state already done in finalize.
        last_processed_date = d

        # Set Combine start date on first trade
        if combine_start_date is None:
            combine_start_date = d

        # Track day in Combine
        if d not in combine_daily_pnl:
            combine_daily_pnl[d] = 0.0

        # Skip day if already DLL or daily-cap hit
        if d in combine_capped_days:
            # Still track this trade as "would have been skipped"
            # Not added to combine_trades (didn't execute)
            continue
        if d in combine_dll_days:
            continue

        raw_pnl = float(trade.get("pnl", 0.0))
        running_day = combine_daily_pnl[d]
        new_day = running_day + raw_pnl

        # Daily PROFIT CAP: +$1,500 → cap and stop day
        if new_day >= daily_cap:
            effective_pnl = daily_cap - running_day
            lost_to_cap = raw_pnl - effective_pnl
            combine_daily_pnl[d] = daily_cap
            balance += effective_pnl
            combine_capped_days.add(d)
            result.pnl_lost_to_cap += max(0, lost_to_cap)
            # Mark trade as capped
            t_copy = dict(trade)
            t_copy["pnl_effective"] = effective_pnl
            t_copy["capped"] = True
            combine_trades.append(t_copy)
        # Daily LOSS LIMIT: -$1,000 → cap loss and stop day (not a Combine fail)
        elif new_day <= -dll:
            effective_pnl = -dll - running_day
            saved_from_loss = effective_pnl - raw_pnl  # negative number; this is what DLL saved
            combine_daily_pnl[d] = -dll
            balance += effective_pnl
            combine_dll_days.add(d)
            result.pnl_saved_by_dll += abs(saved_from_loss)
            t_copy = dict(trade)
            t_copy["pnl_effective"] = effective_pnl
            t_copy["dll_capped"] = True
            combine_trades.append(t_copy)
        else:
            combine_daily_pnl[d] = new_day
            balance += raw_pnl
            combine_trades.append(trade)

        # 2026-05-01 — REMOVED intraday PASS. Pass only triggers on EOD
        # (when day boundary crosses) AFTER min_trading_days reached.
        # See top-of-loop EOD check.
        # Old code would pass on day 3 hitting +$3K and lose to min-days
        # rule (114 violations / 348 passes = 33% wasted).

        # Check Combine FAIL via MLL (intraday)
        mll_floor = peak_eod_balance - mll
        if balance < mll_floor:
            finalize_combine(d, "failed_mll", f"balance ${balance:,.0f} < MLL floor ${mll_floor:,.0f}")
            continue

    # End-of-data: do final EOD check + handle any in-progress Combine
    if last_processed_date is not None:
        end_of_day_update(last_processed_date)
        days_traded_final = len(combine_daily_pnl)
        net_pnl_final = balance - start_balance
        if (days_traded_final >= min_trading_days
                and net_pnl_final >= profit_target):
            finalize_combine(last_processed_date, "passed")
        elif combine_trades:
            finalize_combine(
                last_processed_date, "in_progress",
            )

    return result


# ─── Reporting ──────────────────────────────────────────────────────────────


def format_report(sim: SimResult) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("  ROLLING TOPSTEP $50K COMBINE SIMULATION")
    lines.append("=" * 72)
    lines.append("")

    # Aggregate metrics
    passed = [c for c in sim.combines if c.status == "passed"]
    failed = [c for c in sim.combines if c.status.startswith("failed")]
    in_progress = [c for c in sim.combines if c.status == "in_progress"]
    valid_passes = [c for c in passed if not c.consistency_violation and not c.min_days_violation]
    consist_viol = [c for c in passed if c.consistency_violation]
    min_days_viol = [c for c in passed if c.min_days_violation]

    total = len(sim.combines)
    pass_rate = len(passed) / total * 100 if total else 0
    valid_pass_rate = len(valid_passes) / total * 100 if total else 0

    lines.append("--- AGGREGATE 7-YEAR ---")
    lines.append(f"  Combines started:           {total}")
    lines.append(f"  Combines passed:            {len(passed)} ({pass_rate:.1f}%)")
    lines.append(f"  Combines passed + valid:    {len(valid_passes)} ({valid_pass_rate:.1f}%)")
    lines.append(f"    consistency violations:   {len(consist_viol)}")
    lines.append(f"    min-days violations:      {len(min_days_viol)}")
    lines.append(f"  Combines failed (MLL):      {len(failed)}")
    if in_progress:
        lines.append(f"  In progress (end of data):  {len(in_progress)}")
    lines.append(f"  Total reset fees paid:      ${sim.total_reset_fees:,.0f}")
    lines.append(f"  Total funded payout est:    ${sim.total_payout:,.0f} (sum of valid pass profits)")
    lines.append(f"  P&L lost to daily cap:      ${sim.pnl_lost_to_cap:,.0f}")
    lines.append(f"  P&L saved by DLL:           ${sim.pnl_saved_by_dll:,.0f}")
    lines.append(f"  Days hit profit cap:        {len(set(sim.days_capped))}")
    lines.append(f"  Days hit DLL:               {len(set(sim.days_dll_hit))}")
    lines.append("")

    # Days-to-pass distribution
    if valid_passes:
        days = sorted(c.days_traded for c in valid_passes)
        lines.append("--- DAYS-TO-PASS distribution (valid passes) ---")
        lines.append(f"  min: {days[0]} days")
        lines.append(f"  median: {days[len(days)//2]} days")
        lines.append(f"  avg: {sum(days)/len(days):.1f} days")
        lines.append(f"  max: {days[-1]} days")
        lines.append("")

    # Year-by-year
    lines.append("--- BY YEAR ---")
    by_year: dict[int, list[CombineResult]] = defaultdict(list)
    for c in sim.combines:
        # Use end_date as the "Combine year"
        by_year[c.end_date.year].append(c)
    lines.append(f"  {'Year':>5} | {'Started':>7} | {'Passed':>6} | {'Failed':>6} | {'Valid':>6} | {'Avg days':>8} | {'Net payout':>11}")
    lines.append("  " + "-" * 72)
    for year in sorted(by_year):
        cs = by_year[year]
        n = len(cs)
        p = sum(1 for c in cs if c.status == "passed")
        v = sum(1 for c in cs if c.status == "passed" and not c.consistency_violation and not c.min_days_violation)
        f = sum(1 for c in cs if c.status.startswith("failed"))
        valid_cs = [c for c in cs if c.status == "passed" and not c.consistency_violation and not c.min_days_violation]
        avg_days = sum(c.days_traded for c in valid_cs) / len(valid_cs) if valid_cs else 0
        payout = sum(c.pnl for c in valid_cs) - sum(1 for c in cs if c.status.startswith("failed")) * RESET_FEE
        lines.append(f"  {year:>5} | {n:>7} | {p:>6} | {f:>6} | {v:>6} | {avg_days:>8.1f} | ${payout:>+10,.0f}")
    lines.append("")

    # Month-by-month (last 24 months for brevity)
    lines.append("--- BY MONTH (recent 24 months) ---")
    by_month: dict[str, list[CombineResult]] = defaultdict(list)
    for c in sim.combines:
        key = c.end_date.strftime("%Y-%m")
        by_month[key].append(c)
    months_sorted = sorted(by_month)
    if len(months_sorted) > 24:
        months_sorted = months_sorted[-24:]
    lines.append(f"  {'Month':>9} | {'Pass':>4} | {'Fail':>4} | {'Days cap':>8} | {'Days DLL':>8} | {'Net':>10}")
    lines.append("  " + "-" * 60)
    cap_set = set(sim.days_capped)
    dll_set = set(sim.days_dll_hit)
    for m in months_sorted:
        cs = by_month[m]
        p = sum(1 for c in cs if c.status == "passed" and not c.consistency_violation and not c.min_days_violation)
        f = sum(1 for c in cs if c.status.startswith("failed"))
        valid_cs = [c for c in cs if c.status == "passed" and not c.consistency_violation and not c.min_days_violation]
        net = sum(c.pnl for c in valid_cs) - sum(1 for c in cs if c.status.startswith("failed")) * RESET_FEE
        cap_in_m = sum(1 for d in cap_set if d.strftime("%Y-%m") == m)
        dll_in_m = sum(1 for d in dll_set if d.strftime("%Y-%m") == m)
        lines.append(f"  {m:>9} | {p:>4} | {f:>4} | {cap_in_m:>8} | {dll_in_m:>8} | ${net:>+9,.0f}")
    lines.append("")

    # Sample of combine results
    lines.append("--- FIRST 10 COMBINES ---")
    for c in sim.combines[:10]:
        flags = []
        if c.consistency_violation: flags.append("CONSISTENCY!")
        if c.min_days_violation: flags.append("MIN-DAYS!")
        flag_str = " " + " ".join(flags) if flags else ""
        lines.append(
            f"  #{c.combine_n:>2} {c.status:>11} {c.start_date} -> {c.end_date} "
            f"({c.days_traded:>3}d, {c.trades_taken:>3}t) "
            f"P&L=${c.pnl:>+8,.0f} best=${c.best_day_pnl:>+5,.0f}{flag_str}"
        )
    lines.append("")
    return "\n".join(lines)


# ─── CLI ────────────────────────────────────────────────────────────────────


def load_trades(pattern: str) -> list[dict]:
    """Load trades from one or more JSON files matching pattern."""
    paths = sorted(glob.glob(pattern))
    if not paths:
        print(f"❌ No files match pattern: {pattern}")
        sys.exit(1)
    all_trades = []
    for p in paths:
        try:
            with open(p) as f:
                d = json.load(f)
            all_trades.extend(d.get("trades", []))
            print(f"  loaded {len(d.get('trades', []))} trades from {Path(p).name}")
        except Exception as e:
            print(f"⚠ Failed to load {p}: {e}")
    # Sort by entry_time
    all_trades.sort(key=lambda t: t.get("entry_time", ""))
    print(f"  total: {len(all_trades)} trades sorted")
    return all_trades


def main() -> int:
    # Force UTF-8 stdout on Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--trades", required=True, help="Glob pattern for trade JSON files")
    p.add_argument("--start-balance", type=float, default=START_BALANCE)
    p.add_argument("--profit-target", type=float, default=PROFIT_TARGET)
    p.add_argument("--mll", type=float, default=MLL)
    p.add_argument("--dll", type=float, default=DLL)
    p.add_argument("--daily-cap", type=float, default=DAILY_PROFIT_CAP)
    p.add_argument("--reset-fee", type=float, default=RESET_FEE)
    p.add_argument("--min-trading-days", type=int, default=MIN_TRADING_DAYS)
    p.add_argument("--consistency-pct", type=float, default=CONSISTENCY_PCT)
    p.add_argument("--output", default=None, help="Optional output file for the report")
    args = p.parse_args()

    print(f"\n=== Rolling Combine Simulator ===\n")
    print(f"Loading trades from: {args.trades}")
    trades = load_trades(args.trades)

    print(f"\nRunning simulation (balance=${args.start_balance:,.0f}, target=${args.profit_target:,.0f}, "
          f"MLL=${args.mll:,.0f}, DLL=${args.dll:,.0f}, cap=${args.daily_cap:,.0f})...")

    sim = simulate_rolling_combines(
        trades,
        start_balance=args.start_balance,
        profit_target=args.profit_target,
        mll=args.mll,
        dll=args.dll,
        daily_cap=args.daily_cap,
        reset_fee=args.reset_fee,
        min_trading_days=args.min_trading_days,
        consistency_pct=args.consistency_pct,
    )

    report = format_report(sim)
    print(report)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"\n✓ Report written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
