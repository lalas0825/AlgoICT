"""
scripts/detailed_report.py
===========================
Detailed breakdown of any run_backtest export JSON.

Usage:
    python scripts/detailed_report.py analysis/sb_v8_2024.json
    python scripts/detailed_report.py analysis/sb_v8_2024.json --save report_v8_2024.txt

Sections:
  1. Overall summary (trades, WR, PF, P&L, max DD, Combine resets)
  2. Monthly breakdown (Jan, Feb, Mar, …)
  3. Per-day stats (winning/losing/BE days, best/worst day, daily P&L std)
  4. Kill Zone breakdown (trades, WR, P&L per KZ)
  5. Day-of-week breakdown (Mon/Tue/Wed/Thu/Fri)
  6. Streaks (longest winning/losing streak, max consecutive losses daily)
  7. Distribution stats (trade P&L histogram, trade duration)
  8. Combine-relevant (resets, DLL-breach days, MLL-zone time)

All reads the same `run_backtest.py --export-json` schema.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev


def _pct(wins, total):
    return f"{wins/total:.1%}" if total else "n/a"


def _pf(gross_win, gross_loss):
    return f"{abs(gross_win/gross_loss):.2f}" if gross_loss else "inf"


# ─── Section 1: Overall summary ────────────────────────────────────────

def summary(data, trades):
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    bes = [t for t in trades if t["pnl"] == 0]
    gw = sum(t["pnl"] for t in wins)
    gl = sum(t["pnl"] for t in losses)
    avg_w = gw / len(wins) if wins else 0
    avg_l = gl / len(losses) if losses else 0
    expectancy = sum(t["pnl"] for t in trades) / len(trades) if trades else 0

    print("=" * 74)
    print(f"  SUMMARY — {data.get('strategy','?')} "
          f"| period {data.get('start_date','?')} → {data.get('end_date','?')}")
    print("=" * 74)
    print(f"  Total trades      : {len(trades)}")
    print(f"  Wins / Losses / BE: {len(wins)} / {len(losses)} / {len(bes)}")
    print(f"  Win rate          : {_pct(len(wins), len(trades))}")
    print(f"  Total P&L         : ${data.get('total_pnl', sum(t['pnl'] for t in trades)):,.2f}")
    print(f"  Profit factor     : {_pf(gw, gl)}")
    print(f"  Avg win / loss    : ${avg_w:,.2f} / ${avg_l:,.2f}")
    print(f"  Expectancy/trade  : ${expectancy:,.2f}")
    print(f"  Best trade        : ${max((t['pnl'] for t in trades), default=0):,.2f}")
    print(f"  Worst trade       : ${min((t['pnl'] for t in trades), default=0):,.2f}")
    print(f"  Max drawdown      : ${data.get('max_drawdown_dollars', 0):,.2f}")
    print(f"  Peak equity       : ${data.get('peak_equity', 0):,.2f}")
    print(f"  Combine resets    : {data.get('combine_resets', 0)}")
    print()


# ─── Section 2: Monthly breakdown ──────────────────────────────────────

def monthly(trades):
    by_month = defaultdict(list)
    for t in trades:
        month = t["entry_time"][:7]  # YYYY-MM
        by_month[month].append(t)

    print("=" * 74)
    print("  MONTHLY BREAKDOWN")
    print("=" * 74)
    print(f"  {'Month':8} {'Trades':>7} {'Wins':>6} {'WR':>6} "
          f"{'P&L':>12} {'PF':>6} {'AvgW':>8} {'AvgL':>8}")
    print("  " + "-" * 70)
    totals = {"trades": 0, "wins": 0, "pnl": 0.0}
    for month in sorted(by_month):
        mt = by_month[month]
        w = [t for t in mt if t["pnl"] > 0]
        l = [t for t in mt if t["pnl"] < 0]
        pnl = sum(t["pnl"] for t in mt)
        gw = sum(t["pnl"] for t in w)
        gl = sum(t["pnl"] for t in l)
        aw = gw / len(w) if w else 0
        al = gl / len(l) if l else 0
        print(f"  {month:8} {len(mt):>7} {len(w):>6} {_pct(len(w), len(mt)):>6} "
              f"${pnl:>10,.0f} {_pf(gw, gl):>6} "
              f"${aw:>6,.0f} ${al:>6,.0f}")
        totals["trades"] += len(mt)
        totals["wins"] += len(w)
        totals["pnl"] += pnl
    print("  " + "-" * 70)
    print(f"  {'TOTAL':8} {totals['trades']:>7} {totals['wins']:>6} "
          f"{_pct(totals['wins'], totals['trades']):>6} ${totals['pnl']:>10,.0f}")
    print()


# ─── Section 3: Per-day stats ──────────────────────────────────────────

def daily(trades):
    by_day = defaultdict(list)
    for t in trades:
        day = t["entry_time"][:10]
        by_day[day].append(t)

    day_pnls = {d: sum(t["pnl"] for t in ts) for d, ts in by_day.items()}
    winning_days = [(d, p) for d, p in day_pnls.items() if p > 0]
    losing_days = [(d, p) for d, p in day_pnls.items() if p < 0]
    be_days = [(d, p) for d, p in day_pnls.items() if p == 0]

    dll_breaches = [(d, p) for d, p in day_pnls.items() if p <= -1000]
    big_wins = sorted(winning_days, key=lambda x: -x[1])[:5]
    big_losses = sorted(losing_days, key=lambda x: x[1])[:5]

    print("=" * 74)
    print("  PER-DAY BREAKDOWN")
    print("=" * 74)
    print(f"  Trading days        : {len(by_day)}")
    print(f"  Winning days        : {len(winning_days)}  ({_pct(len(winning_days), len(by_day))})")
    print(f"  Losing days         : {len(losing_days)}  ({_pct(len(losing_days), len(by_day))})")
    print(f"  Breakeven days      : {len(be_days)}")
    print(f"  DLL-breach days (≤-$1000): {len(dll_breaches)}")
    print(f"  Avg daily P&L       : ${mean(day_pnls.values()):,.2f}")
    if len(day_pnls) > 1:
        print(f"  Daily P&L std dev   : ${stdev(day_pnls.values()):,.2f}")
    print(f"  Best day            : ${max(day_pnls.values()):,.2f} "
          f"on {max(day_pnls, key=day_pnls.get)}")
    print(f"  Worst day           : ${min(day_pnls.values()):,.2f} "
          f"on {min(day_pnls, key=day_pnls.get)}")
    print()
    print("  Top 5 winning days:")
    for d, p in big_wins:
        print(f"    {d}  ${p:>+10,.2f}  ({len(by_day[d])} trades)")
    print()
    print("  Top 5 losing days:")
    for d, p in big_losses:
        n = len(by_day[d])
        wd = sum(1 for t in by_day[d] if t["pnl"] > 0)
        print(f"    {d}  ${p:>+10,.2f}  ({n} trades, {wd}W)")
    print()


# ─── Section 4: Kill Zone breakdown ────────────────────────────────────

def kill_zones(trades):
    by_kz = defaultdict(list)
    for t in trades:
        by_kz[t.get("kill_zone", "unknown")].append(t)

    print("=" * 74)
    print("  KILL ZONE BREAKDOWN")
    print("=" * 74)
    print(f"  {'KZ':12} {'Trades':>7} {'W':>4} {'L':>4} {'WR':>6} "
          f"{'P&L':>12} {'PF':>6} {'AvgW':>8} {'AvgL':>8}")
    print("  " + "-" * 70)
    for kz in sorted(by_kz):
        tk = by_kz[kz]
        w = [t for t in tk if t["pnl"] > 0]
        l = [t for t in tk if t["pnl"] < 0]
        pnl = sum(t["pnl"] for t in tk)
        gw = sum(t["pnl"] for t in w)
        gl = sum(t["pnl"] for t in l)
        aw = gw / len(w) if w else 0
        al = gl / len(l) if l else 0
        print(f"  {kz:12} {len(tk):>7} {len(w):>4} {len(l):>4} "
              f"{_pct(len(w), len(tk)):>6} ${pnl:>10,.0f} "
              f"{_pf(gw, gl):>6} ${aw:>6,.0f} ${al:>6,.0f}")
    print()


# ─── Section 5: Day-of-week ────────────────────────────────────────────

_DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def dow(trades):
    by_dow = defaultdict(list)
    for t in trades:
        try:
            dt = datetime.fromisoformat(t["entry_time"].replace("Z", "+00:00"))
            dow_i = dt.weekday()
            by_dow[dow_i].append(t)
        except Exception:
            pass

    print("=" * 74)
    print("  DAY-OF-WEEK BREAKDOWN")
    print("=" * 74)
    print(f"  {'Day':6} {'Trades':>7} {'Wins':>6} {'WR':>6} {'P&L':>12} {'PF':>6}")
    print("  " + "-" * 60)
    for i in range(5):
        td = by_dow.get(i, [])
        if not td:
            print(f"  {_DOW_NAMES[i]:6} {'0':>7}")
            continue
        w = [t for t in td if t["pnl"] > 0]
        l = [t for t in td if t["pnl"] < 0]
        pnl = sum(t["pnl"] for t in td)
        gw = sum(t["pnl"] for t in w)
        gl = sum(t["pnl"] for t in l)
        print(f"  {_DOW_NAMES[i]:6} {len(td):>7} {len(w):>6} "
              f"{_pct(len(w), len(td)):>6} ${pnl:>10,.0f} {_pf(gw, gl):>6}")
    print()


# ─── Section 6: Streaks ────────────────────────────────────────────────

def streaks(trades):
    trades_sorted = sorted(trades, key=lambda t: t["entry_time"])
    cur_win = cur_loss = 0
    max_win = max_loss = 0
    max_win_streak_pnl = 0
    max_loss_streak_pnl = 0
    cur_win_pnl = cur_loss_pnl = 0

    for t in trades_sorted:
        if t["pnl"] > 0:
            cur_win += 1
            cur_win_pnl += t["pnl"]
            if cur_win > max_win:
                max_win = cur_win
                max_win_streak_pnl = cur_win_pnl
            cur_loss = 0
            cur_loss_pnl = 0
        elif t["pnl"] < 0:
            cur_loss += 1
            cur_loss_pnl += t["pnl"]
            if cur_loss > max_loss:
                max_loss = cur_loss
                max_loss_streak_pnl = cur_loss_pnl
            cur_win = 0
            cur_win_pnl = 0

    # Per-day max consecutive losses (daily rhythm matters for Topstep DLL)
    by_day = defaultdict(list)
    for t in trades_sorted:
        by_day[t["entry_time"][:10]].append(t)

    daily_max_streaks = []
    for d, ts in by_day.items():
        cl = cml = 0
        for t in ts:
            if t["pnl"] < 0:
                cl += 1
                cml = max(cml, cl)
            else:
                cl = 0
        daily_max_streaks.append(cml)

    print("=" * 74)
    print("  STREAKS")
    print("=" * 74)
    print(f"  Longest winning streak : {max_win} trades  (${max_win_streak_pnl:+,.2f})")
    print(f"  Longest losing streak  : {max_loss} trades (${max_loss_streak_pnl:+,.2f})")
    if daily_max_streaks:
        print(f"  Max consec losses/day  : {max(daily_max_streaks)}")
        print(f"  Median consec losses/day: {median(daily_max_streaks)}")
        cnt_geq5 = sum(1 for s in daily_max_streaks if s >= 5)
        cnt_geq4 = sum(1 for s in daily_max_streaks if s >= 4)
        cnt_geq3 = sum(1 for s in daily_max_streaks if s >= 3)
        print(f"  Days with ≥3 consec losses: {cnt_geq3}")
        print(f"  Days with ≥4 consec losses: {cnt_geq4}")
        print(f"  Days with ≥5 consec losses: {cnt_geq5}")
    print()


# ─── Section 7: Distribution ───────────────────────────────────────────

def distribution(trades):
    pnls = [t["pnl"] for t in trades]
    if not pnls:
        return
    print("=" * 74)
    print("  TRADE P&L DISTRIBUTION")
    print("=" * 74)
    print(f"  Min / Median / Mean / Max : "
          f"${min(pnls):,.0f} / ${median(pnls):,.0f} / "
          f"${mean(pnls):,.0f} / ${max(pnls):,.0f}")
    if len(pnls) > 1:
        print(f"  Std dev               : ${stdev(pnls):,.0f}")

    # Buckets
    buckets = [
        ("<= -$500",     lambda p: p <= -500),
        ("-$500..-250",  lambda p: -500 < p <= -250),
        ("-$250..-1",    lambda p: -250 < p < 0),
        ("$0 (BE)",      lambda p: p == 0),
        ("$1..$250",     lambda p: 0 < p <= 250),
        ("$250..$500",   lambda p: 250 < p <= 500),
        (">$500",        lambda p: p > 500),
    ]
    print()
    print("  P&L buckets:")
    for label, pred in buckets:
        n = sum(1 for p in pnls if pred(p))
        bar = "#" * int(n / max(1, len(pnls) / 40))
        print(f"    {label:15} {n:>5}  {bar}")
    print()


# ─── Section 8: Combine-specific ───────────────────────────────────────

def combine_metrics(data, trades):
    by_day = defaultdict(list)
    for t in trades:
        by_day[t["entry_time"][:10]].append(t)

    day_pnls = {d: sum(t["pnl"] for t in ts) for d, ts in by_day.items()}
    dll_breaches = sum(1 for p in day_pnls.values() if p <= -1000)
    close_to_dll = sum(1 for p in day_pnls.values() if -1000 < p <= -700)
    daily_worst = min(day_pnls.values()) if day_pnls else 0

    resets = data.get("combine_resets", 0)
    reset_events = data.get("combine_reset_events", []) or []

    print("=" * 74)
    print("  COMBINE-SPECIFIC METRICS")
    print("=" * 74)
    print(f"  Topstep Combine resets       : {resets}")
    print(f"  Days with daily P&L ≤ -$1000 : {dll_breaches}  (DLL HIT in live)")
    print(f"  Days with -$1000 < P&L ≤ -$700: {close_to_dll}  (close to DLL)")
    print(f"  Worst single day P&L         : ${daily_worst:,.2f}")
    if reset_events:
        print(f"  Reset events detail (first 5):")
        for ev in reset_events[:5]:
            print(f"    reset #{ev.get('reset_n','?')}: "
                  f"dd=${ev.get('dd_at_reset',0):,.0f} "
                  f"bal_before=${ev.get('balance_before',0):,.0f}")
    print()


# ─── Driver ────────────────────────────────────────────────────────────

def run(json_path: Path, save_to: Path = None):
    data = json.loads(json_path.read_text())
    trades = data.get("trades", [])
    if not trades:
        print(f"No trades in {json_path}")
        return

    # If requested, tee output to file
    if save_to:
        orig_stdout = sys.stdout
        sys.stdout = open(save_to, "w", encoding="utf-8")

    try:
        summary(data, trades)
        monthly(trades)
        daily(trades)
        kill_zones(trades)
        dow(trades)
        streaks(trades)
        distribution(trades)
        combine_metrics(data, trades)
    finally:
        if save_to:
            sys.stdout.close()
            sys.stdout = orig_stdout
            print(f"Report saved to {save_to}")


def main():
    p = argparse.ArgumentParser(description="Detailed backtest report")
    p.add_argument("json_path", help="Path to export JSON from run_backtest.py")
    p.add_argument("--save", help="Save report to file (optional)", default=None)
    args = p.parse_args()

    path = Path(args.json_path)
    if not path.exists():
        sys.exit(f"Not found: {path}")

    save_path = Path(args.save) if args.save else None
    run(path, save_path)


if __name__ == "__main__":
    main()
