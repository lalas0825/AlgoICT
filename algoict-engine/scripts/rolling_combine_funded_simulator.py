"""
scripts/rolling_combine_funded_simulator.py
============================================
Two-state Topstep $50K simulator: COMBINE then FUNDED.

State machine
-------------
COMBINE state:
  - Balance starts at $50,000
  - Daily profit cap: +$1,500 (self-imposed risk rule)
  - Daily loss limit: -$1,000 → stop day (not Combine fail)
  - MLL trail: $2,000 from peak EOD → FAIL Combine, pay reset fee, stay in COMBINE
  - PASS condition: balance >= $53,000 AND days_traded >= 5
    On PASS: switch to FUNDED state. New $50K account opens.

FUNDED state:
  - Balance starts at $50,000 (separate from Combine — fresh account)
  - NO daily profit cap (Topstep Express Funded removed it)
  - Daily loss limit: -$1,000 → stop day
  - MLL trail: $2,000 from peak EOD → FAIL Funded, lose account, switch back to COMBINE
  - Profit accumulates (no target, runs until MLL fail or end of data)
  - Payouts:
      * First $10K of profit: 50% to trader (real Topstep starts ~50/50)
      * After $10K: 90% to trader
      * Topstep keeps the rest

Output
------
Per Funded period:
  - Days alive
  - Trades taken
  - Peak P&L
  - Final P&L
  - Reason ended (MLL_fail | end_of_data)
  - Trader payout (after split)

Aggregate:
  - Total Combines passed (becomes Funded count)
  - Total Funded periods
  - Funded periods that survived (didn't blow MLL)
  - Funded MLL failure rate
  - Total trader payout (after splits)
  - Average funded survival days

Usage
-----
    python -m scripts.rolling_combine_funded_simulator \
        --trades "analysis/sb_v19a_wide_*.json" \
        --output analysis/v19a_wide_combine_funded_sim.md
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional


START_BALANCE = 50_000.0
PROFIT_TARGET = 3_000.0
MLL = 2_000.0
DLL = 1_000.0
DAILY_PROFIT_CAP = 1_500.0
RESET_FEE = 50.0
MIN_TRADING_DAYS = 5
PAYOUT_TIER1_LIMIT = 10_000.0   # First $10K of profit: 50/50
PAYOUT_TIER1_SPLIT = 0.50
PAYOUT_TIER2_SPLIT = 0.90       # After tier 1: 90/10


@dataclass
class CombineRecord:
    n: int
    start_date: date
    end_date: date
    days: int
    trades: int
    final_pnl: float
    status: str             # 'passed' | 'failed_mll'


@dataclass
class FundedRecord:
    n: int
    parent_combine_n: int
    start_date: date
    end_date: date
    days: int
    trades: int
    peak_pnl: float
    final_pnl: float
    raw_profit: float       # gross profit accumulated
    trader_payout: float    # after splits
    topstep_kept: float
    status: str             # 'mll_fail' | 'end_of_data'


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def split_profit(raw_profit: float) -> tuple[float, float]:
    """Apply 50/50 first $10K, 90/10 after. Returns (trader, topstep)."""
    if raw_profit <= 0:
        return (0.0, 0.0)
    if raw_profit <= PAYOUT_TIER1_LIMIT:
        trader = raw_profit * PAYOUT_TIER1_SPLIT
    else:
        tier1 = PAYOUT_TIER1_LIMIT * PAYOUT_TIER1_SPLIT
        tier2 = (raw_profit - PAYOUT_TIER1_LIMIT) * PAYOUT_TIER2_SPLIT
        trader = tier1 + tier2
    return (trader, raw_profit - trader)


def simulate(
    trades: list[dict],
    start_balance: float = START_BALANCE,
    profit_target: float = PROFIT_TARGET,
    mll: float = MLL,
    dll: float = DLL,
    daily_cap: float = DAILY_PROFIT_CAP,
    reset_fee: float = RESET_FEE,
    min_trading_days: int = MIN_TRADING_DAYS,
):
    combines: list[CombineRecord] = []
    funded_records: list[FundedRecord] = []
    total_reset_fees = 0.0
    pnl_lost_to_cap = 0.0

    # Combine state
    in_combine = True
    combine_n = 1
    combine_balance = start_balance
    combine_peak_eod = start_balance
    combine_days: dict[date, float] = {}
    combine_capped: set[date] = set()
    combine_dll: set[date] = set()
    combine_trades: list = []
    combine_start: Optional[date] = None

    # Funded state
    funded_n = 0
    funded_balance = start_balance
    funded_peak_eod = start_balance
    funded_days: dict[date, float] = {}
    funded_dll: set[date] = set()
    funded_trades: list = []
    funded_start: Optional[date] = None
    funded_peak_profit = 0.0

    last_date: Optional[date] = None

    def reset_combine():
        nonlocal combine_balance, combine_peak_eod, combine_days
        nonlocal combine_capped, combine_dll, combine_trades, combine_start
        nonlocal combine_n
        combine_n += 1
        combine_balance = start_balance
        combine_peak_eod = start_balance
        combine_days = {}
        combine_capped = set()
        combine_dll = set()
        combine_trades = []
        combine_start = None

    def reset_funded():
        nonlocal funded_balance, funded_peak_eod, funded_days
        nonlocal funded_dll, funded_trades, funded_start, funded_peak_profit
        nonlocal funded_n
        funded_n += 1
        funded_balance = start_balance
        funded_peak_eod = start_balance
        funded_days = {}
        funded_dll = set()
        funded_trades = []
        funded_start = None
        funded_peak_profit = 0.0

    def end_of_combine_day(d: date):
        nonlocal combine_peak_eod
        if combine_balance > combine_peak_eod:
            combine_peak_eod = combine_balance

    def end_of_funded_day(d: date):
        nonlocal funded_peak_eod, funded_peak_profit
        if funded_balance > funded_peak_eod:
            funded_peak_eod = funded_balance
        profit = funded_balance - start_balance
        if profit > funded_peak_profit:
            funded_peak_profit = profit

    def finalize_combine_pass(end_date: date):
        nonlocal in_combine
        cr = CombineRecord(
            n=combine_n,
            start_date=combine_start or end_date,
            end_date=end_date,
            days=len(combine_days),
            trades=len(combine_trades),
            final_pnl=combine_balance - start_balance,
            status="passed",
        )
        combines.append(cr)
        # Switch to FUNDED
        in_combine = False
        reset_funded()  # initialize funded state

    def finalize_combine_fail(end_date: date):
        nonlocal total_reset_fees
        cr = CombineRecord(
            n=combine_n,
            start_date=combine_start or end_date,
            end_date=end_date,
            days=len(combine_days),
            trades=len(combine_trades),
            final_pnl=combine_balance - start_balance,
            status="failed_mll",
        )
        combines.append(cr)
        total_reset_fees += reset_fee
        reset_combine()

    def finalize_funded(end_date: date, status: str):
        nonlocal in_combine
        raw = funded_balance - start_balance
        trader, topstep_kept = split_profit(raw)
        fr = FundedRecord(
            n=funded_n,
            parent_combine_n=combine_n,
            start_date=funded_start or end_date,
            end_date=end_date,
            days=len(funded_days),
            trades=len(funded_trades),
            peak_pnl=funded_peak_profit,
            final_pnl=raw,
            raw_profit=max(0, raw),
            trader_payout=trader,
            topstep_kept=topstep_kept,
            status=status,
        )
        funded_records.append(fr)
        # Switch back to COMBINE (next combine)
        if status == "mll_fail":
            in_combine = True
            reset_combine()
        # If end_of_data, just return — no more switching

    # ─── Main loop ────────────────────────────────────────────────────────
    for trade in trades:
        entry = parse_dt(trade["entry_time"]).date()
        raw_pnl = float(trade.get("pnl", 0.0))

        if in_combine:
            # End of day boundary
            if last_date is not None and entry != last_date:
                end_of_combine_day(last_date)
                # EOD pass check
                if (len(combine_days) >= min_trading_days
                        and combine_balance - start_balance >= profit_target):
                    finalize_combine_pass(last_date)
                    last_date = entry
                    # Re-enter logic for funded since we're now in funded state
                    # The current trade will be processed in funded branch.
                    pass  # continues below in funded branch
            # Update last_date even if we switched
            last_date = entry

        if in_combine:
            # Process trade in COMBINE
            if entry not in combine_days:
                combine_days[entry] = 0.0
                if combine_start is None:
                    combine_start = entry

            if entry in combine_capped or entry in combine_dll:
                continue

            running = combine_days[entry]
            new_day = running + raw_pnl

            if new_day >= daily_cap:
                eff = daily_cap - running
                pnl_lost_to_cap += max(0, raw_pnl - eff)
                combine_days[entry] = daily_cap
                combine_balance += eff
                combine_capped.add(entry)
                combine_trades.append(trade)
            elif new_day <= -dll:
                eff = -dll - running
                combine_days[entry] = -dll
                combine_balance += eff
                combine_dll.add(entry)
                combine_trades.append(trade)
            else:
                combine_days[entry] = new_day
                combine_balance += raw_pnl
                combine_trades.append(trade)

            # MLL check
            mll_floor = combine_peak_eod - mll
            if combine_balance < mll_floor:
                finalize_combine_fail(entry)
                continue
        else:
            # Process trade in FUNDED
            if last_date is not None and entry != last_date:
                end_of_funded_day(last_date)
            last_date = entry

            if entry not in funded_days:
                funded_days[entry] = 0.0
                if funded_start is None:
                    funded_start = entry

            if entry in funded_dll:
                continue

            running = funded_days[entry]
            new_day = running + raw_pnl

            # NO daily profit cap in Funded
            if new_day <= -dll:
                eff = -dll - running
                funded_days[entry] = -dll
                funded_balance += eff
                funded_dll.add(entry)
                funded_trades.append(trade)
            else:
                funded_days[entry] = new_day
                funded_balance += raw_pnl
                funded_trades.append(trade)

            # MLL check
            mll_floor = funded_peak_eod - mll
            if funded_balance < mll_floor:
                finalize_funded(entry, "mll_fail")
                continue

    # End of data
    if last_date is not None:
        if in_combine:
            end_of_combine_day(last_date)
            # Final pass check
            if (len(combine_days) >= min_trading_days
                    and combine_balance - start_balance >= profit_target):
                finalize_combine_pass(last_date)
                if not in_combine:
                    finalize_funded(last_date, "end_of_data")
        else:
            end_of_funded_day(last_date)
            finalize_funded(last_date, "end_of_data")

    return {
        "combines": combines,
        "funded": funded_records,
        "reset_fees": total_reset_fees,
        "pnl_lost_to_cap": pnl_lost_to_cap,
    }


def format_report(result: dict) -> str:
    lines = []
    combines = result["combines"]
    funded = result["funded"]

    passed = [c for c in combines if c.status == "passed"]
    failed = [c for c in combines if c.status == "failed_mll"]
    mll_fail_funded = [f for f in funded if f.status == "mll_fail"]
    surviving_funded = [f for f in funded if f.status == "end_of_data"]

    total_trader_payout = sum(f.trader_payout for f in funded)
    total_topstep_kept = sum(f.topstep_kept for f in funded)
    total_raw_profit = sum(f.raw_profit for f in funded)

    lines.append("=" * 72)
    lines.append("  ROLLING COMBINE -> FUNDED SIMULATION")
    lines.append("=" * 72)
    lines.append("")

    lines.append("--- COMBINE PHASE ---")
    lines.append(f"  Combines started:        {len(combines)}")
    lines.append(f"  Combines passed:         {len(passed)} ({len(passed)/max(1,len(combines))*100:.1f}%)")
    lines.append(f"  Combines failed (MLL):   {len(failed)}")
    lines.append(f"  Reset fees paid:         ${result['reset_fees']:,.0f}")
    lines.append(f"  P&L lost to daily cap:   ${result['pnl_lost_to_cap']:,.0f}")
    lines.append("")

    lines.append("--- FUNDED PHASE ---")
    lines.append(f"  Funded accounts opened:  {len(funded)}")
    lines.append(f"  Funded MLL failures:     {len(mll_fail_funded)} ({len(mll_fail_funded)/max(1,len(funded))*100:.1f}%)")
    lines.append(f"  Surviving (end of data): {len(surviving_funded)}")
    if funded:
        avg_days = sum(f.days for f in funded) / len(funded)
        avg_peak = sum(f.peak_pnl for f in funded) / len(funded)
        avg_final = sum(f.final_pnl for f in funded) / len(funded)
        max_peak = max(f.peak_pnl for f in funded)
        lines.append(f"  Avg days alive:          {avg_days:.1f}")
        lines.append(f"  Avg peak P&L:            ${avg_peak:,.0f}")
        lines.append(f"  Avg final P&L:           ${avg_final:,.0f}")
        lines.append(f"  Max peak P&L (single):   ${max_peak:,.0f}")
    lines.append("")

    lines.append("--- THE MONEY ---")
    lines.append(f"  Total raw profit (Funded):   ${total_raw_profit:>12,.0f}")
    lines.append(f"  Topstep keeps (split):       ${total_topstep_kept:>12,.0f}")
    lines.append(f"  TRADER PAYOUT:               ${total_trader_payout:>12,.0f}")
    lines.append(f"  + Combine reset fees paid:   ${-result['reset_fees']:>12,.0f}")
    lines.append(f"  = NET TO TRADER:             ${total_trader_payout - result['reset_fees']:>12,.0f}")
    if combines:
        first_date = combines[0].start_date
        last_date = max(
            (max(c.end_date for c in combines), max(f.end_date for f in funded) if funded else combines[0].end_date)
        )
        years = max(1, (last_date - first_date).days / 365.25)
        lines.append(f"  Period covered:              {first_date} to {last_date} ({years:.1f} years)")
        lines.append(f"  Annual avg trader payout:    ${(total_trader_payout - result['reset_fees'])/years:,.0f}")
        lines.append(f"  Monthly avg trader payout:   ${(total_trader_payout - result['reset_fees'])/years/12:,.0f}")
    lines.append("")

    # By year
    lines.append("--- FUNDED P&L BY YEAR ---")
    by_year_funded: dict[int, list[FundedRecord]] = defaultdict(list)
    for f in funded:
        by_year_funded[f.end_date.year].append(f)
    lines.append(f"  {'Year':>5} | {'#Funded':>7} | {'#MLL fail':>9} | {'Raw profit':>11} | {'Trader payout':>14}")
    lines.append("  " + "-" * 64)
    for year in sorted(by_year_funded):
        fs = by_year_funded[year]
        n = len(fs)
        fails = sum(1 for f in fs if f.status == "mll_fail")
        raw = sum(f.raw_profit for f in fs)
        payout = sum(f.trader_payout for f in fs)
        lines.append(f"  {year:>5} | {n:>7} | {fails:>9} | ${raw:>+9,.0f} | ${payout:>+12,.0f}")
    lines.append("")

    # Sample funded records
    lines.append("--- FIRST 10 FUNDED PERIODS ---")
    for f in funded[:10]:
        lines.append(
            f"  Funded #{f.n:>2} (Combine #{f.parent_combine_n:>2}) "
            f"{f.start_date} -> {f.end_date} ({f.days:>3}d, {f.trades:>4}t) "
            f"raw=${f.raw_profit:>+8,.0f} payout=${f.trader_payout:>+7,.0f} {f.status}"
        )
    if len(funded) > 10:
        lines.append(f"  ... ({len(funded) - 10} more)")
    lines.append("")

    return "\n".join(lines)


def load_trades(pattern: str) -> list[dict]:
    paths = sorted(glob.glob(pattern))
    if not paths:
        print(f"No files match: {pattern}")
        sys.exit(1)
    all_trades = []
    for p in paths:
        with open(p) as f:
            d = json.load(f)
        all_trades.extend(d.get("trades", []))
        print(f"  loaded {len(d.get('trades', []))} from {Path(p).name}")
    all_trades.sort(key=lambda t: t.get("entry_time", ""))
    print(f"  total: {len(all_trades)} trades sorted")
    return all_trades


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--trades", required=True)
    p.add_argument("--output", default=None)
    args = p.parse_args()

    print(f"\n=== Combine -> Funded Rolling Simulator ===\n")
    print(f"Loading trades from: {args.trades}")
    trades = load_trades(args.trades)

    print(f"\nRunning two-state simulation...")
    result = simulate(trades)
    report = format_report(result)
    print(report)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"\n+ Report written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
