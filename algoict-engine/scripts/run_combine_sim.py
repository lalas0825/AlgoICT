"""
scripts/run_combine_sim.py
===========================
Runs the Topstep $50K Combine Simulator on trades from a backtest run
stored in Supabase.

Usage:
    python scripts/run_combine_sim.py --strategy ny_am_reversal
    python scripts/run_combine_sim.py --strategy silver_bullet --starting-balance 50000
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

import pandas as pd
from db.supabase_lab_client import get_lab_client
from backtest.backtester import Trade
from backtest.combine_simulator import simulate_combine


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(prog="run_combine_sim")
    p.add_argument("--strategy", default="ny_am_reversal")
    p.add_argument("--starting-balance", type=float, default=50000.0)
    args = p.parse_args()

    client = get_lab_client()
    if client is None:
        print("No Supabase client. Check .env")
        return 1

    # Fetch trades
    print(f"Loading {args.strategy} trades from Supabase...")
    res = client._client.table("trades") \
        .select("*") \
        .eq("strategy", args.strategy) \
        .order("entry_time", desc=False) \
        .limit(10000) \
        .execute()

    rows = res.data or []
    print(f"Fetched {len(rows)} trades")

    if not rows:
        print("No trades found. Run a backtest first.")
        return 1

    # Convert rows → Trade objects
    trades = []
    for r in rows:
        t = Trade(
            strategy=r["strategy"],
            symbol=r.get("symbol", "MNQ"),
            direction=r["direction"],
            entry_time=pd.Timestamp(r["entry_time"]),
            exit_time=pd.Timestamp(r["exit_time"]) if r.get("exit_time") else pd.Timestamp(r["entry_time"]),
            entry_price=float(r["entry_price"]),
            stop_price=float(r.get("stop_loss", 0)),
            target_price=float(r.get("take_profit", 0)),
            exit_price=float(r.get("exit_price", 0) or 0),
            contracts=int(r["contracts"]),
            pnl=float(r["pnl"] or 0),
            reason=r.get("reason", ""),
            confluence_score=int(r.get("confluence_score", 0)),
            duration_bars=int(r.get("duration_bars", 0) or 0),
        )
        trades.append(t)

    total_pnl = sum(t.pnl for t in trades)
    print(f"Date range: {trades[0].entry_time.date()} -> {trades[-1].entry_time.date()}")
    print(f"Total P&L:  ${total_pnl:+,.2f}")
    print()

    # Run simulation
    sb = args.starting_balance
    result = simulate_combine(trades, starting_balance=sb)

    # ── Main result ──────────────────────────────────────────────────────
    print("=" * 70)
    print(f"  TOPSTEP $50K COMBINE SIMULATION")
    print(f"  {args.strategy} — {len(trades)} trades")
    print("=" * 70)
    print()

    status = "PASSED ✅" if result.passed else "FAILED ❌"
    print(f"  Result            : {status}")
    if result.failure_reason:
        print(f"  Failure reason    : {result.failure_reason}")
    print()
    print(f"  Starting balance  : ${result.starting_balance:>10,.2f}")
    print(f"  Ending balance    : ${result.ending_balance:>10,.2f}")
    print(f"  Peak balance      : ${result.peak_balance:>10,.2f}")
    print(f"  Total P&L         : ${result.total_pnl:>+10,.2f}")
    print()
    print(f"  Profit target     : ${result.profit_target:>10,.2f}")
    print(f"  MLL limit         : ${result.mll_limit:>10,.2f}")
    print(f"  DLL limit         : ${result.dll_limit:>10,.2f}")
    print()
    print(f"  Trading days      : {result.trading_days}")
    print(f"  Calendar days     : {result.total_days}")
    print(f"  Total trades      : {result.total_trades}")
    print()
    print(f"  Best day          : ${result.best_day_pnl:>+10,.2f}  ({result.best_day_date})")

    if result.consistency_ok is not None:
        cons_label = "PASS ✅" if result.consistency_ok else "FAIL ❌"
        print(f"  Consistency rule  : {cons_label}")
        if result.total_pnl > 0:
            pct = result.best_day_pnl / result.total_pnl
            print(f"    (best day = {pct:.1%} of total profit, limit = 50%)")

    # ── Detailed analysis ────────────────────────────────────────────────
    if result.days:
        print()
        print("=" * 70)
        print("  DETAILED ANALYSIS")
        print("=" * 70)
        print()

        # Worst day
        worst_day = min(result.days, key=lambda d: d.pnl)
        print(f"  Worst day         : ${worst_day.pnl:>+10,.2f}  ({worst_day.date})")

        # Max drawdown from peak
        max_dd = 0.0
        max_dd_date = None
        running_peak = result.starting_balance
        for day in result.days:
            if day.balance_eod > running_peak:
                running_peak = day.balance_eod
            dd = running_peak - day.balance_eod
            if dd > max_dd:
                max_dd = dd
                max_dd_date = day.date
        print(f"  Max drawdown $    : ${max_dd:>10,.2f}  ({max_dd_date})")
        if running_peak > 0:
            print(f"  Max DD % of peak  : {max_dd / running_peak:.2%}")

        # Days that violated or came close to DLL
        dll_close = [d for d in result.days if d.pnl < -800]
        print()
        print(f"  Days with daily loss > $800: {len(dll_close)}")
        for d in dll_close[:10]:
            marker = " ❌ DLL BREACH" if d.pnl < -1000 else " ⚠️  close"
            print(f"    {d.date}  ${d.pnl:>+10,.2f}{marker}")

        # Days close to MLL breach
        print()
        close_to_mll = []
        running_peak = result.starting_balance
        for day in result.days:
            if day.balance_eod > running_peak:
                running_peak = day.balance_eod
            gap = running_peak - day.balance_eod
            if gap >= result.mll_limit * 0.7:  # within 30% of breach
                close_to_mll.append((day.date, gap, running_peak, day.balance_eod))

        print(f"  Days within 30% of MLL breach ($2,000): {len(close_to_mll)}")
        for date, gap, peak, bal in close_to_mll[:10]:
            pct = gap / result.mll_limit * 100
            marker = " ❌ MLL BREACH" if gap >= result.mll_limit else ""
            print(f"    {date}  dd=${gap:>8,.2f} ({pct:.0f}% of limit)  peak=${peak:,.2f}  bal=${bal:,.2f}{marker}")

        # When was profit target first reached?
        print()
        running_bal = result.starting_balance
        target_reached = False
        for i, day in enumerate(result.days):
            running_bal += day.pnl
            if running_bal >= result.starting_balance + result.profit_target:
                days_elapsed = (day.date - result.days[0].date).days
                print(f"  Profit target first reached: {day.date} (calendar day {days_elapsed}, trading day {i + 1})")
                target_reached = True
                break
        if not target_reached:
            print("  Profit target never reached during the simulation")

        # Win/loss day streaks
        print()
        streak = 0
        worst_loss_streak = 0
        best_win_streak = 0
        for day in result.days:
            if day.pnl > 0:
                if streak < 0:
                    streak = 0
                streak += 1
                best_win_streak = max(best_win_streak, streak)
            elif day.pnl < 0:
                if streak > 0:
                    streak = 0
                streak -= 1
                worst_loss_streak = min(worst_loss_streak, streak)
        print(f"  Best winning streak : {best_win_streak} days")
        print(f"  Worst losing streak : {abs(worst_loss_streak)} days")

        # Monthly breakdown
        print()
        print("  Monthly breakdown:")
        print(f"  {'Month':<10} {'Trades':>7} {'P&L':>12} {'Win days':>10} {'Loss days':>10}")
        print(f"  {'-' * 10} {'-' * 7} {'-' * 12} {'-' * 10} {'-' * 10}")

        from collections import defaultdict
        monthly = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "win_days": 0, "loss_days": 0})
        for day in result.days:
            key = day.date.strftime("%Y-%m")
            monthly[key]["trades"] += day.trades
            monthly[key]["pnl"] += day.pnl
            if day.pnl > 0:
                monthly[key]["win_days"] += 1
            elif day.pnl < 0:
                monthly[key]["loss_days"] += 1

        for month in sorted(monthly.keys()):
            m = monthly[month]
            pnl_marker = "+" if m["pnl"] >= 0 else ""
            print(f"  {month:<10} {m['trades']:>7} ${pnl_marker}{m['pnl']:>10,.2f} {m['win_days']:>10} {m['loss_days']:>10}")

        # Equity curve: first 15 + last 10 days
        print()
        print("  Equity curve (first 15 + last 10):")
        print(f"  {'Date':<12} {'Daily P&L':>12} {'Balance':>14} {'Peak':>14} {'DD from peak':>14}")
        print(f"  {'-' * 12} {'-' * 12} {'-' * 14} {'-' * 14} {'-' * 14}")

        running_peak = result.starting_balance
        show = result.days[:15]
        if len(result.days) > 25:
            show = show + [None] + result.days[-10:]  # type: ignore
        elif len(result.days) > 15:
            show = show + result.days[15:]

        for day in show:
            if day is None:
                print(f"  {'...':^66}")
                continue
            if day.balance_eod > running_peak:
                running_peak = day.balance_eod
            dd = running_peak - day.balance_eod
            print(
                f"  {str(day.date):<12} "
                f"${day.pnl:>+11,.2f} "
                f"${day.balance_eod:>13,.2f} "
                f"${running_peak:>13,.2f} "
                f"${dd:>13,.2f}"
            )

    print()
    print("=" * 70)
    return 0 if result.passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
