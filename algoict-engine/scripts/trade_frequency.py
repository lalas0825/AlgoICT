"""
scripts/trade_frequency.py
===========================
How often does the strategy fire trades? Analyzes one or multiple
backtest JSONs and prints trade frequency metrics.

Metrics:
  - Total trades / trading days
  - Trades per day (mean, median, std, min, max)
  - Gap between trades (mean, median, longest quiet stretch)
  - Per-KZ frequency (trades per KZ per day active)
  - Distribution buckets (days with 0, 1, 2-3, 4-5, 6-10, 10+ trades)
  - Per-hour density inside active KZs

Usage:
    python scripts/trade_frequency.py analysis/sb_v9_session_recency_2024.json
    python scripts/trade_frequency.py --pattern sb_v9_session_recency_
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev

ANALYSIS = Path("C:/AI Projects/AlgoICT/algoict-engine/analysis")


def analyze(json_path: Path) -> dict:
    data = json.loads(json_path.read_text())
    trades = data.get("trades", [])
    if not trades:
        return {"year": json_path.stem, "n": 0}

    # Parse timestamps + sort
    for t in trades:
        t["_dt"] = datetime.fromisoformat(t["entry_time"].replace("Z", "+00:00"))
    trades.sort(key=lambda t: t["_dt"])

    # Per day
    by_day = defaultdict(list)
    for t in trades:
        by_day[t["_dt"].date()].append(t)

    counts_per_day = [len(ts) for ts in by_day.values()]

    # Gap distribution (minutes between consecutive trades, SAME day only)
    gaps_min = []
    for day_ts in by_day.values():
        if len(day_ts) < 2:
            continue
        for i in range(1, len(day_ts)):
            gap = (day_ts[i]["_dt"] - day_ts[i - 1]["_dt"]).total_seconds() / 60
            gaps_min.append(gap)

    # Per KZ
    kz_counts = defaultdict(list)    # kz -> per-day counts
    by_day_kz = defaultdict(lambda: defaultdict(int))
    for t in trades:
        by_day_kz[t["_dt"].date()][t["kill_zone"]] += 1
    for day, kzmap in by_day_kz.items():
        for kz, cnt in kzmap.items():
            kz_counts[kz].append(cnt)

    # Hourly density (inside KZ hours only)
    hour_counts = defaultdict(int)
    for t in trades:
        hour_counts[t["_dt"].hour] += 1

    # Distribution buckets
    buckets = {"0 trades": 0, "1 trade": 0, "2-3 trades": 0,
               "4-5 trades": 0, "6-10 trades": 0, "10+ trades": 0}

    # Include ALL calendar days in range with 0 trades
    first = min(by_day.keys())
    last = max(by_day.keys())
    days_total = (last - first).days + 1
    # Only count weekdays for "trading days"
    weekdays_in_range = sum(
        1 for d in (first + __import__("datetime").timedelta(days=i)
                    for i in range(days_total))
        if d.weekday() < 5
    )

    for day, ts_list in by_day.items():
        n = len(ts_list)
        if n == 0:
            buckets["0 trades"] += 1
        elif n == 1:
            buckets["1 trade"] += 1
        elif n <= 3:
            buckets["2-3 trades"] += 1
        elif n <= 5:
            buckets["4-5 trades"] += 1
        elif n <= 10:
            buckets["6-10 trades"] += 1
        else:
            buckets["10+ trades"] += 1

    zero_days = weekdays_in_range - len(by_day)
    buckets["0 trades"] += max(0, zero_days)

    return {
        "year": json_path.stem.split("_")[-1],
        "path": str(json_path),
        "n_trades": len(trades),
        "n_trading_days": len(by_day),
        "n_weekdays_in_range": weekdays_in_range,
        "trades_per_day_mean": mean(counts_per_day),
        "trades_per_day_median": median(counts_per_day),
        "trades_per_day_std": stdev(counts_per_day) if len(counts_per_day) > 1 else 0,
        "trades_per_day_min": min(counts_per_day),
        "trades_per_day_max": max(counts_per_day),
        "gap_minutes_mean": mean(gaps_min) if gaps_min else 0,
        "gap_minutes_median": median(gaps_min) if gaps_min else 0,
        "gap_minutes_max": max(gaps_min) if gaps_min else 0,
        "kz_trades_per_active_day": {
            kz: mean(counts) for kz, counts in kz_counts.items()
        },
        "kz_total_trades": {
            kz: sum(counts) for kz, counts in kz_counts.items()
        },
        "kz_active_days": {
            kz: len(counts) for kz, counts in kz_counts.items()
        },
        "hour_counts": dict(hour_counts),
        "buckets": buckets,
    }


def print_summary(s: dict):
    if s.get("n_trades", 0) == 0:
        print(f"[{s['year']}] No trades")
        return

    print(f"\n=== {s['year']} ===")
    print(f"  Total trades       : {s['n_trades']}")
    print(f"  Trading days       : {s['n_trading_days']} (weekdays in range: {s['n_weekdays_in_range']})")
    print(f"  Trades/day mean    : {s['trades_per_day_mean']:.2f}")
    print(f"  Trades/day median  : {s['trades_per_day_median']:.1f}")
    print(f"  Trades/day min/max : {s['trades_per_day_min']} / {s['trades_per_day_max']}")
    print(f"  Trades/day std dev : {s['trades_per_day_std']:.2f}")
    print(f"  Gap between trades (min, same day):")
    print(f"    mean={s['gap_minutes_mean']:.1f}min  median={s['gap_minutes_median']:.1f}min  max={s['gap_minutes_max']:.0f}min")
    print(f"  Per-KZ frequency:")
    for kz, rate in sorted(s["kz_trades_per_active_day"].items()):
        total = s["kz_total_trades"][kz]
        active_days = s["kz_active_days"][kz]
        print(f"    {kz:10}: {rate:.2f} trades/day (active {active_days} days, total {total} trades)")
    print(f"  Day distribution:")
    total_days = sum(s["buckets"].values())
    for label, n in s["buckets"].items():
        pct = n / total_days * 100 if total_days else 0
        bar = "#" * int(pct / 2)
        print(f"    {label:13}: {n:>4}  ({pct:>5.1f}%)  {bar}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", nargs="?", default=None)
    ap.add_argument("--pattern", default=None,
                    help="Glob pattern prefix (e.g. 'sb_v9_session_recency_')")
    args = ap.parse_args()

    paths = []
    if args.json_path:
        paths = [Path(args.json_path)]
    elif args.pattern:
        paths = sorted(ANALYSIS.glob(f"{args.pattern}*.json"))
        paths = [p for p in paths
                 if p.stem.split("_")[-1].isdigit() and len(p.stem.split("_")[-1]) == 4]
    else:
        print("Usage: trade_frequency.py <json> OR --pattern prefix")
        return

    all_stats = []
    for p in paths:
        if not p.exists():
            print(f"Missing: {p}")
            continue
        s = analyze(p)
        all_stats.append(s)
        print_summary(s)

    # Aggregate across all years
    if len(all_stats) > 1:
        print("\n" + "=" * 60)
        print("  AGGREGATE ACROSS ALL FILES")
        print("=" * 60)
        total_trades = sum(s["n_trades"] for s in all_stats)
        total_days = sum(s["n_trading_days"] for s in all_stats)
        all_trades_per_day = []
        for s in all_stats:
            all_trades_per_day.append(s["trades_per_day_mean"])
        print(f"  Total trades        : {total_trades}")
        print(f"  Total trading days  : {total_days}")
        print(f"  Avg trades/day      : {total_trades / total_days:.2f}")
        print(f"  Year-to-year std dev: {stdev(all_trades_per_day):.2f}" if len(all_trades_per_day) > 1 else "")


if __name__ == "__main__":
    main()
