"""
scripts/analyze_sb_trades.py
=============================
Deep-dive on Silver Bullet trades exported via --export-json. Answers:

  1. Are losers disproportionately in a specific KZ / time-of-day?
  2. How does confluence score correlate with outcome?
  3. Is direction (long/short) skewed?
  4. What's the relationship between stop distance and outcome?
  5. What's the distribution of exit reasons (stop / target / hard_close)?
  6. Are losers happening early in the window (fast stops) or late (grind)?
  7. Is there a pattern in daily-trade-sequence (first trade of day vs later)?

Usage
-----
    python scripts/analyze_sb_trades.py analysis/sb_2024_q1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median


def _fmt_money(x: float) -> str:
    return f"${x:+,.0f}"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _parse_ts(s: str) -> datetime:
    # "2024-01-02 09:15:00-06:00" → aware datetime.
    return datetime.fromisoformat(s)


def _bucket_min_in_kz(t: dict) -> int | None:
    """Return minutes since KZ start. None if kz_start unknown."""
    kz_starts = {
        "london_silver_bullet": (2, 0),
        "silver_bullet": (9, 0),
        "pm_silver_bullet": (13, 0),
    }
    kz = t.get("kill_zone", "")
    if kz not in kz_starts:
        return None
    h, m = kz_starts[kz]
    et = _parse_ts(t["entry_time"])
    delta_min = (et.hour - h) * 60 + (et.minute - m)
    if delta_min < 0 or delta_min > 60:
        return None   # shouldn't happen, but skip
    return delta_min


def analyze(payload: dict) -> None:
    trades = payload["trades"]
    print("=" * 70)
    print(f"  Silver Bullet Trade Analysis — {payload['start_date']} → {payload['end_date']}")
    print("=" * 70)
    print(f"  Total trades: {len(trades)}  (wins: {payload['wins']}, losses: {payload['losses']})")
    print(f"  Win rate:     {_fmt_pct(payload['win_rate'])}")
    print(f"  Total P&L:    {_fmt_money(payload['total_pnl'])}")
    print(f"  Max DD:       {_fmt_money(-payload['max_drawdown_dollars'])}")
    print()

    # ── 1. Exit reason distribution ────────────────────────────────────
    print("── 1. Exit Reason ─────────────────────────────────────────────────")
    by_reason = defaultdict(list)
    for t in trades:
        by_reason[t.get("reason", "unknown")].append(t)
    print(f"  {'Reason':<15} {'Count':>6} {'Win%':>6} {'Avg PnL':>10} {'Total':>12}")
    for reason, bucket in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        wins = sum(1 for t in bucket if t["pnl"] > 0)
        wr = wins / len(bucket) if bucket else 0
        avg_p = mean(t["pnl"] for t in bucket)
        total = sum(t["pnl"] for t in bucket)
        print(f"  {reason:<15} {len(bucket):>6} {_fmt_pct(wr):>6} {_fmt_money(avg_p):>10} {_fmt_money(total):>12}")
    print()

    # ── 2. By Kill Zone ───────────────────────────────────────────────
    print("── 2. By Kill Zone ────────────────────────────────────────────────")
    by_kz = defaultdict(list)
    for t in trades:
        by_kz[t.get("kill_zone", "unknown")].append(t)
    print(f"  {'KZ':<25} {'Count':>6} {'Win%':>6} {'Avg PnL':>10} {'Total':>12}")
    for kz, bucket in sorted(by_kz.items(), key=lambda kv: -len(kv[1])):
        wins = sum(1 for t in bucket if t["pnl"] > 0)
        wr = wins / len(bucket) if bucket else 0
        avg_p = mean(t["pnl"] for t in bucket)
        total = sum(t["pnl"] for t in bucket)
        print(f"  {kz:<25} {len(bucket):>6} {_fmt_pct(wr):>6} {_fmt_money(avg_p):>10} {_fmt_money(total):>12}")
    print()

    # ── 3. By direction ────────────────────────────────────────────────
    print("── 3. By Direction ────────────────────────────────────────────────")
    by_dir = defaultdict(list)
    for t in trades:
        by_dir[t["direction"]].append(t)
    print(f"  {'Direction':<10} {'Count':>6} {'Win%':>6} {'Avg PnL':>10} {'Total':>12}")
    for d in ("long", "short"):
        bucket = by_dir.get(d, [])
        wins = sum(1 for t in bucket if t["pnl"] > 0)
        wr = wins / len(bucket) if bucket else 0
        avg_p = mean(t["pnl"] for t in bucket) if bucket else 0
        total = sum(t["pnl"] for t in bucket)
        print(f"  {d:<10} {len(bucket):>6} {_fmt_pct(wr):>6} {_fmt_money(avg_p):>10} {_fmt_money(total):>12}")
    print()

    # ── 4. Confluence score correlation ─────────────────────────────────
    print("── 4. Confluence Score → Outcome ──────────────────────────────────")
    by_conf = defaultdict(list)
    for t in trades:
        c = int(t.get("confluence_score", 0) or 0)
        by_conf[c].append(t)
    print(f"  {'Score':<6} {'Count':>6} {'Win%':>6} {'Avg PnL':>10} {'Total':>12}")
    for c in sorted(by_conf.keys()):
        bucket = by_conf[c]
        wins = sum(1 for t in bucket if t["pnl"] > 0)
        wr = wins / len(bucket) if bucket else 0
        avg_p = mean(t["pnl"] for t in bucket)
        total = sum(t["pnl"] for t in bucket)
        print(f"  {c:<6} {len(bucket):>6} {_fmt_pct(wr):>6} {_fmt_money(avg_p):>10} {_fmt_money(total):>12}")
    print()

    # ── 5. Stop distance buckets ────────────────────────────────────────
    print("── 5. Stop Distance (entry-stop, pts) → Outcome ──────────────────")
    stop_dists = []
    for t in trades:
        dist = abs(t["entry_price"] - t["stop_price"])
        stop_dists.append((dist, t))
    # Buckets: 0-5, 5-10, 10-15, 15-25, 25+
    buckets = [(0, 5), (5, 10), (10, 15), (15, 25), (25, 1000)]
    print(f"  {'Range (pts)':<15} {'Count':>6} {'Win%':>6} {'Avg PnL':>10} {'Total':>12}")
    for lo, hi in buckets:
        bucket = [t for d, t in stop_dists if lo <= d < hi]
        if not bucket:
            continue
        wins = sum(1 for t in bucket if t["pnl"] > 0)
        wr = wins / len(bucket) if bucket else 0
        avg_p = mean(t["pnl"] for t in bucket)
        total = sum(t["pnl"] for t in bucket)
        label = f"{lo}-{hi if hi < 1000 else '+'}"
        print(f"  {label:<15} {len(bucket):>6} {_fmt_pct(wr):>6} {_fmt_money(avg_p):>10} {_fmt_money(total):>12}")
    print()

    # ── 6. Time-in-window buckets (minutes after KZ start) ─────────────
    print("── 6. Time After KZ Start → Outcome ──────────────────────────────")
    buckets_time = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60)]
    print(f"  {'KZ+min':<10} {'Count':>6} {'Win%':>6} {'Avg PnL':>10} {'Total':>12}")
    for lo, hi in buckets_time:
        bucket = []
        for t in trades:
            m = _bucket_min_in_kz(t)
            if m is not None and lo <= m < hi:
                bucket.append(t)
        if not bucket:
            continue
        wins = sum(1 for t in bucket if t["pnl"] > 0)
        wr = wins / len(bucket) if bucket else 0
        avg_p = mean(t["pnl"] for t in bucket)
        total = sum(t["pnl"] for t in bucket)
        print(f"  {lo}-{hi:<6} {len(bucket):>6} {_fmt_pct(wr):>6} {_fmt_money(avg_p):>10} {_fmt_money(total):>12}")
    print()

    # ── 7. Stop-distance vs win/loss (avg of each) ─────────────────────
    print("── 7. Winners vs Losers — Stop / Hold-Time / KZ ──────────────────")
    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] <= 0]

    def _hold_min(t: dict) -> float:
        try:
            return (_parse_ts(t["exit_time"]) - _parse_ts(t["entry_time"])).total_seconds() / 60
        except Exception:
            return -1

    if winners:
        w_stop = mean(abs(t["entry_price"] - t["stop_price"]) for t in winners)
        w_hold = mean(_hold_min(t) for t in winners if _hold_min(t) >= 0)
        print(f"  Winners: avg stop_dist={w_stop:.2f}pts, avg hold={w_hold:.1f}min, n={len(winners)}")
    if losers:
        l_stop = mean(abs(t["entry_price"] - t["stop_price"]) for t in losers)
        l_hold = mean(_hold_min(t) for t in losers if _hold_min(t) >= 0)
        print(f"  Losers:  avg stop_dist={l_stop:.2f}pts, avg hold={l_hold:.1f}min, n={len(losers)}")
    print()

    # ── 8. Day-of-week pattern ─────────────────────────────────────────
    print("── 8. Day of Week → Outcome ──────────────────────────────────────")
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_dow = defaultdict(list)
    for t in trades:
        dow = _parse_ts(t["entry_time"]).weekday()
        by_dow[dow].append(t)
    print(f"  {'Day':<6} {'Count':>6} {'Win%':>6} {'Avg PnL':>10} {'Total':>12}")
    for dow in range(7):
        bucket = by_dow.get(dow, [])
        if not bucket:
            continue
        wins = sum(1 for t in bucket if t["pnl"] > 0)
        wr = wins / len(bucket) if bucket else 0
        avg_p = mean(t["pnl"] for t in bucket)
        total = sum(t["pnl"] for t in bucket)
        print(f"  {dow_names[dow]:<6} {len(bucket):>6} {_fmt_pct(wr):>6} {_fmt_money(avg_p):>10} {_fmt_money(total):>12}")
    print()

    # ── 9. Reason × outcome cross-tab ──────────────────────────────────
    print("── 9. Distribution Summary ───────────────────────────────────────")
    stops = [t for t in trades if "stop" in (t.get("reason") or "").lower()]
    targets = [t for t in trades if "target" in (t.get("reason") or "").lower()]
    hard_closes = [t for t in trades if "hard_close" in (t.get("reason") or "").lower()]
    print(f"  Stops:        {len(stops):>4} ({_fmt_pct(len(stops)/max(1,len(trades)))})")
    print(f"  Targets:      {len(targets):>4} ({_fmt_pct(len(targets)/max(1,len(trades)))})")
    print(f"  Hard closes:  {len(hard_closes):>4} ({_fmt_pct(len(hard_closes)/max(1,len(trades)))})")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("json_path", help="Path to exported trades JSON")
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
