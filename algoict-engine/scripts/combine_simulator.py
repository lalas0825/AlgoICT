"""
scripts/combine_simulator.py
==============================
Topstep $50K Combine simulator. For a given trades JSON (one year of
Silver Bullet trades), run N random-start simulations where each
simulates a fresh Combine attempt:

  - Starting balance: $50,000
  - Profit target:    +$3,000 (balance reaches $53K)
  - MLL trailing:     $2,000 from peak balance
  - Daily loss limit: $1,000
  - Min trading days: 5 days with >=$200 profit each (we don't enforce
    here — assumed trivially met once target is hit, based on Q1 data)

Each simulation:
  - Picks a random start DAY in the year
  - Runs the trades sequentially from that day
  - PASS: balance hits $53K before MLL breach
  - FAIL: MLL trailing drawdown hits $2K before target
  - STILL_RUNNING: neither hit in remaining days (counts as fail/incomplete)

Output:
  - Pass rate per year
  - Avg days to pass
  - Per-year aggregate stats

Usage:
    python scripts/combine_simulator.py analysis/sb_v8_2024.json --attempts 30
    python scripts/combine_simulator.py --multi 2023:json1 2024:json2 2025:json3
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median


STARTING_BALANCE = 50_000
PROFIT_TARGET = 3_000
MLL_LIMIT = 2_000          # trailing drawdown
DLL_LIMIT = 1_000          # daily max loss
MIN_DAYS_MINIMUM_PROFIT = 200   # $200 minimum profit per day for a day to "count"
MIN_TRADING_DAYS = 5


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def simulate_one_combine(
    trades_from_start: list,
    max_days: int = None,
) -> dict:
    """Simulate one Combine attempt starting with $50K, walking through
    the given trades in chronological order. Stops at first PASS or FAIL.

    Returns dict with keys: outcome, days_elapsed, final_balance, peak,
    max_dd, trades_count, qualifying_days, pnl.
    """
    balance = STARTING_BALANCE
    peak = STARTING_BALANCE
    max_dd = 0.0
    total_days = set()
    qualifying_days = set()
    daily_pnl_map = defaultdict(float)
    trades_taken = 0

    for t in trades_from_start:
        trade_day = _parse_ts(t["entry_time"]).date().isoformat()
        total_days.add(trade_day)
        daily_pnl_map[trade_day] += t["pnl"]

        # Daily loss limit check — if today's accumulated loss exceeds DLL,
        # this day is a violation (Combine failed).
        if daily_pnl_map[trade_day] <= -DLL_LIMIT:
            return {
                "outcome": "FAIL_DLL",
                "days_elapsed": len(total_days),
                "final_balance": balance,
                "peak": peak,
                "max_dd": max_dd,
                "trades_count": trades_taken,
                "fail_day": trade_day,
                "pnl": balance - STARTING_BALANCE,
            }

        balance += t["pnl"]
        trades_taken += 1
        peak = max(peak, balance)
        dd = peak - balance
        max_dd = max(max_dd, dd)

        # MLL trailing drawdown violation.
        if dd >= MLL_LIMIT:
            return {
                "outcome": "FAIL_MLL",
                "days_elapsed": len(total_days),
                "final_balance": balance,
                "peak": peak,
                "max_dd": max_dd,
                "trades_count": trades_taken,
                "fail_day": trade_day,
                "pnl": balance - STARTING_BALANCE,
            }

        # Track qualifying day at end of day (once day closes).
        if daily_pnl_map[trade_day] >= MIN_DAYS_MINIMUM_PROFIT:
            qualifying_days.add(trade_day)

        # Target hit — check if we also meet min trading days.
        if balance >= STARTING_BALANCE + PROFIT_TARGET:
            if len(qualifying_days) >= MIN_TRADING_DAYS:
                return {
                    "outcome": "PASS",
                    "days_elapsed": len(total_days),
                    "final_balance": balance,
                    "peak": peak,
                    "max_dd": max_dd,
                    "trades_count": trades_taken,
                    "pass_day": trade_day,
                    "pnl": balance - STARTING_BALANCE,
                    "qualifying_days": len(qualifying_days),
                }
            # else: hit target but not enough qualifying days — keep going.

        if max_days is not None and len(total_days) >= max_days:
            break

    # Ran out of trades without passing or failing.
    return {
        "outcome": "INCOMPLETE",
        "days_elapsed": len(total_days),
        "final_balance": balance,
        "peak": peak,
        "max_dd": max_dd,
        "trades_count": trades_taken,
        "pnl": balance - STARTING_BALANCE,
        "qualifying_days": len(qualifying_days),
    }


def run_year_simulations(year: int, payload: dict, n_attempts: int, seed: int = 42) -> list:
    """Run N simulations for a given year's trades, each starting on a
    random day from the first 75% of the year (so there's runway)."""
    random.seed(seed + year)
    trades = sorted(payload["trades"], key=lambda t: t["entry_time"])

    # Group by day
    days_index = {}
    all_days = []
    for i, t in enumerate(trades):
        day = _parse_ts(t["entry_time"]).date().isoformat()
        if day not in days_index:
            days_index[day] = i
            all_days.append(day)

    if len(all_days) < 20:
        return []

    # Select random start days from the first 75% of the year (so at
    # least ~25% of the year's trades remain after start).
    valid_start_indices = list(range(0, int(len(all_days) * 0.75)))
    if len(valid_start_indices) < n_attempts:
        # Sample with replacement if too few start days
        start_indices = [random.choice(valid_start_indices) for _ in range(n_attempts)]
    else:
        start_indices = random.sample(valid_start_indices, n_attempts)

    results = []
    for start_idx in sorted(start_indices):
        start_day = all_days[start_idx]
        start_trade_idx = days_index[start_day]
        trades_from_start = trades[start_trade_idx:]
        result = simulate_one_combine(trades_from_start)
        result["start_day"] = start_day
        result["start_idx"] = start_idx
        results.append(result)

    return results


def print_year_summary(year: int, results: list) -> dict:
    if not results:
        print(f"Year {year}: no results (not enough data)")
        return {}
    outcomes = defaultdict(int)
    for r in results:
        outcomes[r["outcome"]] += 1
    passes = [r for r in results if r["outcome"] == "PASS"]
    pass_rate = outcomes["PASS"] / len(results) * 100

    print(f"\n=== Year {year} — {len(results)} attempts ===")
    print(f"  PASS:        {outcomes['PASS']:>3}  ({pass_rate:.1f}%)")
    print(f"  FAIL_MLL:    {outcomes['FAIL_MLL']:>3}  ({outcomes['FAIL_MLL']/len(results)*100:.1f}%)")
    print(f"  FAIL_DLL:    {outcomes['FAIL_DLL']:>3}  ({outcomes['FAIL_DLL']/len(results)*100:.1f}%)")
    print(f"  INCOMPLETE:  {outcomes['INCOMPLETE']:>3}  ({outcomes['INCOMPLETE']/len(results)*100:.1f}%)")
    if passes:
        days = [p["days_elapsed"] for p in passes]
        print(f"  Pass days: median={median(days):.0f}, mean={mean(days):.1f}, min={min(days)}, max={max(days)}")
    ddm = [r["max_dd"] for r in results if r["outcome"] != "PASS"]
    if ddm:
        print(f"  Max DD of fails: median=${median(ddm):,.0f}, max=${max(ddm):,.0f}")

    return {
        "year": year,
        "attempts": len(results),
        "passes": outcomes["PASS"],
        "pass_rate": pass_rate,
        "fail_mll": outcomes["FAIL_MLL"],
        "fail_dll": outcomes["FAIL_DLL"],
        "incomplete": outcomes["INCOMPLETE"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("json_path", nargs="?", default=None)
    ap.add_argument("--attempts", type=int, default=30,
                    help="Number of combine attempts per year (default 30)")
    ap.add_argument("--multi", nargs="+",
                    help="Multiple years: format YEAR:PATH YEAR:PATH ...")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    multi_years = []
    if args.multi:
        for pair in args.multi:
            if ":" not in pair:
                print(f"Invalid --multi arg (expect YEAR:PATH): {pair}")
                return 1
            year_str, path = pair.split(":", 1)
            multi_years.append((int(year_str), Path(path)))
    elif args.json_path:
        # Single-year mode; infer year from trades
        p = Path(args.json_path)
        payload = json.loads(p.read_text())
        year = _parse_ts(payload["trades"][0]["entry_time"]).year if payload["trades"] else 0
        multi_years = [(year, p)]
    else:
        print("Supply json_path or --multi")
        return 1

    summaries = []
    for year, path in multi_years:
        if not path.exists():
            print(f"Missing: {path}")
            continue
        payload = json.loads(path.read_text())
        results = run_year_simulations(year, payload, args.attempts, args.seed)
        summary = print_year_summary(year, results)
        if summary:
            summaries.append(summary)

    if len(summaries) > 1:
        total_attempts = sum(s["attempts"] for s in summaries)
        total_passes = sum(s["passes"] for s in summaries)
        print(f"\n=== AGGREGATE ({len(summaries)} years, {total_attempts} attempts) ===")
        print(f"  Total PASSES: {total_passes} / {total_attempts} ({total_passes/total_attempts*100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
