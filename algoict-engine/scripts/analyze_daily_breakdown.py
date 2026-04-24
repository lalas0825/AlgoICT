"""
scripts/analyze_daily_breakdown.py
====================================
Per-day breakdown of a backtest run. Answers:

  - How many trades per day? Distribution.
  - Win rate per day? How many days profitable vs losing?
  - Longest profitable / losing streaks in days.
  - Intraday max drawdown per day.
  - Kill switch triggers (3 consecutive losses within a day).
  - Weekly aggregates.
  - Combine fitness metrics (days to $3K target, max DD).

Usage:
    python scripts/analyze_daily_breakdown.py analysis/sb_v5_2024_q1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path


def _fmt_money(x: float, width: int = 9) -> str:
    s = f"${x:+,.0f}"
    return f"{s:>{width}}"


def _fmt_pct(wins: int, total: int, width: int = 5) -> str:
    if total == 0:
        return f"{'':<{width}}"
    wr = wins / total * 100
    return f"{wr:>{width-1}.0f}%"


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _intraday_max_dd(trades_of_day: list) -> tuple[float, float]:
    """Intraday max drawdown from trade sequence (sorted by entry_time).
    Returns (max_dd, final_pnl)."""
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades_of_day:
        eq += t["pnl"]
        peak = max(peak, eq)
        dd = peak - eq
        max_dd = max(max_dd, dd)
    return max_dd, eq


def _consecutive_losses_in_day(trades_of_day: list) -> int:
    """Max consecutive loss streak within a single day."""
    max_streak = 0
    cur = 0
    for t in trades_of_day:
        if t["pnl"] <= 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    return max_streak


def analyze(payload: dict) -> None:
    trades = sorted(payload["trades"], key=lambda t: t["entry_time"])
    if not trades:
        print("No trades to analyze.")
        return

    # Group by CT day (based on entry_time).
    by_day: dict = defaultdict(list)
    for t in trades:
        day = _parse_ts(t["entry_time"]).date().isoformat()
        by_day[day].append(t)

    # Sort days chronologically.
    days = sorted(by_day.keys())

    # ── HEADER ─────────────────────────────────────────────────────────
    print("=" * 110)
    print(f"DAILY BREAKDOWN — {payload['start_date'][:10]} → {payload['end_date'][:10]}")
    print(f"Total trades: {len(trades)} | "
          f"Win rate: {payload['win_rate']*100:.1f}% | "
          f"Total P&L: ${payload['total_pnl']:+,.2f} | "
          f"Max DD: ${payload.get('max_drawdown_dollars', 0):,.2f}")
    print(f"Trading days: {len(days)} | "
          f"Avg trades/day: {len(trades)/len(days):.1f}")
    print("=" * 110)
    print()

    # ── PER-DAY TABLE ──────────────────────────────────────────────────
    print(f"{'Date':<12} {'DoW':<4} {'#':>3} {'W':>3} {'L':>3} {'WR':>4} "
          f"{'P&L':>10} {'Best':>8} {'Worst':>8} {'IntraDD':>8} {'CL':>3} {'KS':>3}")
    print("-" * 110)

    weekly_pnl = defaultdict(float)
    weekly_trades = defaultdict(int)
    day_pnls = []
    day_wrs = []
    win_days = 0
    loss_days = 0
    ks_days = 0   # days where kill switch would have triggered (3+ consecutive losses)
    kz_counts = Counter()

    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for day in days:
        ts_list = by_day[day]
        wins = [t for t in ts_list if t["pnl"] > 0]
        losses = [t for t in ts_list if t["pnl"] <= 0]
        pnl = sum(t["pnl"] for t in ts_list)
        best = max((t["pnl"] for t in ts_list), default=0)
        worst = min((t["pnl"] for t in ts_list), default=0)
        intra_dd, _ = _intraday_max_dd(ts_list)
        cl = _consecutive_losses_in_day(ts_list)
        ks_triggered = cl >= 3

        day_pnls.append((day, pnl))
        day_wrs.append((day, len(wins) / len(ts_list) if ts_list else 0))
        if pnl > 0:
            win_days += 1
        elif pnl < 0:
            loss_days += 1
        if ks_triggered:
            ks_days += 1

        for t in ts_list:
            kz_counts[t.get("kill_zone", "?")] += 1

        dt = datetime.fromisoformat(day)
        dow = dow_names[dt.weekday()]
        iso_week = dt.isocalendar()
        wk_key = f"{iso_week.year}-W{iso_week.week:02d}"
        weekly_pnl[wk_key] += pnl
        weekly_trades[wk_key] += len(ts_list)

        print(f"{day:<12} {dow:<4} {len(ts_list):>3} {len(wins):>3} {len(losses):>3} "
              f"{_fmt_pct(len(wins), len(ts_list), 4)} "
              f"{_fmt_money(pnl)} {_fmt_money(best,8)} {_fmt_money(worst,8)} "
              f"{_fmt_money(intra_dd,8)} {cl:>3} {'YES' if ks_triggered else ' - ':>3}")

    print("-" * 110)
    print("CL = max consecutive losses in day   KS = kill switch triggered (>=3 consecutive)")
    print()

    # ── WEEKLY AGGREGATE ───────────────────────────────────────────────
    print("── WEEKLY ─────────────────────────────────────────────────────────────")
    print(f"{'Week':<10} {'Trades':>8} {'P&L':>12}")
    for wk in sorted(weekly_pnl.keys()):
        print(f"{wk:<10} {weekly_trades[wk]:>8} {_fmt_money(weekly_pnl[wk], 12)}")
    print()

    # ── DAY-LEVEL STATS ────────────────────────────────────────────────
    print("── DAY-LEVEL STATS ────────────────────────────────────────────────────")
    total_days = len(days)
    print(f"  Winning days:        {win_days:>3} / {total_days}  ({win_days/total_days*100:.1f}%)")
    print(f"  Losing days:         {loss_days:>3} / {total_days}  ({loss_days/total_days*100:.1f}%)")
    print(f"  Breakeven days:      {total_days - win_days - loss_days:>3} / {total_days}")
    print(f"  Kill switch days:    {ks_days:>3} / {total_days}  ({ks_days/total_days*100:.1f}%)")

    win_day_pnls = [p for _, p in day_pnls if p > 0]
    loss_day_pnls = [p for _, p in day_pnls if p < 0]
    if win_day_pnls:
        print(f"  Avg winning day:     ${sum(win_day_pnls)/len(win_day_pnls):+,.0f}")
        print(f"  Best day:            ${max(win_day_pnls):+,.0f}")
    if loss_day_pnls:
        print(f"  Avg losing day:      ${sum(loss_day_pnls)/len(loss_day_pnls):+,.0f}")
        print(f"  Worst day:           ${min(loss_day_pnls):+,.0f}")
    print()

    # ── DAY STREAKS ────────────────────────────────────────────────────
    print("── DAY-LEVEL STREAKS ──────────────────────────────────────────────────")
    win_streak = 0
    loss_streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    cur_win = 0
    cur_loss = 0
    for _, pnl in day_pnls:
        if pnl > 0:
            cur_win += 1
            cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
        elif pnl < 0:
            cur_loss += 1
            cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)
        else:
            cur_win = 0
            cur_loss = 0
    print(f"  Max winning-day streak:  {max_win_streak} days")
    print(f"  Max losing-day streak:   {max_loss_streak} days")
    print()

    # ── TRADES PER DAY DISTRIBUTION ────────────────────────────────────
    print("── TRADES-PER-DAY DISTRIBUTION ────────────────────────────────────────")
    tpd = [len(by_day[d]) for d in days]
    tpd_counter = Counter(tpd)
    for n in sorted(tpd_counter.keys()):
        bar = "█" * tpd_counter[n]
        print(f"  {n} trades/day: {tpd_counter[n]:>3} days  {bar}")
    print()

    # ── KILL ZONE DISTRIBUTION ─────────────────────────────────────────
    print("── TRADES BY KILL ZONE ────────────────────────────────────────────────")
    for kz, count in kz_counts.most_common():
        pct = count / len(trades) * 100
        print(f"  {kz:<28} {count:>4}  ({pct:.1f}%)")
    print()

    # ── COMBINE FITNESS ────────────────────────────────────────────────
    print("── COMBINE FITNESS (simulate $50K/$2K MLL/$3K target) ─────────────────")
    # Running equity from day 1
    cum = 0.0
    peak = 0.0
    max_dd_running = 0.0
    target_hit_day = None
    mll_breach_day = None
    for i, (day, p) in enumerate(day_pnls, 1):
        cum += p
        peak = max(peak, cum)
        dd = peak - cum
        max_dd_running = max(max_dd_running, dd)
        if target_hit_day is None and cum >= 3000:
            target_hit_day = (i, day)
        if mll_breach_day is None and dd >= 2000:
            mll_breach_day = (i, day, dd)

    print(f"  Starting equity: $0 (profit frame)")
    print(f"  Final equity:    ${cum:+,.2f}")
    print(f"  Peak equity:     ${peak:+,.2f}")
    print(f"  Max running DD:  ${max_dd_running:,.2f}")
    print()
    if target_hit_day:
        i, day = target_hit_day
        print(f"  🎯 $3K profit target: HIT on day {i} ({day})")
    else:
        print(f"  🎯 $3K profit target: NOT HIT in {total_days} trading days")
    if mll_breach_day:
        i, day, dd = mll_breach_day
        print(f"  💥 MLL $2K breach:   YES on day {i} ({day}, dd=${dd:,.0f}) — would need reset")
    else:
        print(f"  💥 MLL $2K breach:   NO — safe")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("json_path")
    args = ap.parse_args()
    p = Path(args.json_path)
    if not p.exists():
        print(f"File not found: {p}")
        return 1
    payload = json.loads(p.read_text())
    analyze(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
