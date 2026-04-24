"""
scripts/analyze_1r_touches.py
==============================
For a trades JSON export, estimate how many LOSERS actually touched the
1R profit level before reversing. This is the critical question for
deciding if a "partials at 1R + move to BE" change can substantially
improve the win rate.

Without bar-level intrabar data we can't confirm every touch, but we can
infer: if target_price > entry (long) and the trade's exit_reason is
'stop' (not 'target' / 'hard_close'), we measure the best-case intrabar
assumption (price went some distance toward target before reversing).

Since our JSON doesn't carry intrabar MFE/MAE, we use a simpler proxy:
  - For losers: compute distance entry → target. If 1R (= stop distance)
    would be between entry and the eventual exit path, we know 1R was
    likely touched IF the trade held for more than a few minutes.
  - Short hold times (<5 min) = likely no 1R touch (immediate stop-out).
  - Longer holds (>10 min) = likely moved against position THEN reversed,
    so some chance 1R was touched in the intermediate move.

This is an approximation. A full analysis would require the backtester
to emit MFE/MAE per trade.

Usage:
    python scripts/analyze_1r_touches.py analysis/sb_v2_2024_q1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def analyze(payload: dict) -> None:
    trades = payload["trades"]
    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] <= 0]

    print(f"Total: {len(trades)}   winners: {len(winners)}   losers: {len(losers)}")
    print()

    # Categorize losers by hold time (proxy for MFE chance).
    print("── Losers by hold time (proxy for 1R touch probability) ──")
    buckets = [
        (0, 5, "very fast stop-out"),
        (5, 15, "normal stop-out"),
        (15, 30, "slow stop / possible 1R touch"),
        (30, 60, "long grind / likely 1R touch"),
        (60, 9999, "very long / very likely touched 1R or more"),
    ]
    holdtime_dist = {label: 0 for _, _, label in buckets}
    for t in losers:
        try:
            hold = (_parse_ts(t["exit_time"]) - _parse_ts(t["entry_time"])).total_seconds() / 60
        except Exception:
            continue
        for lo, hi, label in buckets:
            if lo <= hold < hi:
                holdtime_dist[label] += 1
                break

    for _, _, label in buckets:
        n = holdtime_dist[label]
        pct = n / len(losers) * 100 if losers else 0
        bar = "█" * int(pct / 2)
        print(f"  {label:<42} {n:>3} ({pct:5.1f}%) {bar}")
    print()

    # Estimate: how many losers held > 15 min (likely touched 1R)
    likely_touched = sum(
        n for label, n in holdtime_dist.items()
        if "1R" in label or "likely" in label
    )
    likely_not = sum(
        n for label, n in holdtime_dist.items()
        if "fast" in label or "normal" in label
    )
    print(f"Likely touched 1R (held > 15 min): {likely_touched}")
    print(f"Likely did NOT touch 1R (held < 15 min): {likely_not}")
    print()

    # Project WR improvement
    current_wr = len(winners) / len(trades) if trades else 0
    # Scenario A: 50% of "likely touched 1R" losers would be BE-saved
    saved_a = likely_touched * 0.50
    new_wr_a = (len(winners) + saved_a) / len(trades) if trades else 0
    # Scenario B: 80% of "likely touched 1R" + 30% of "slow" losers
    # (more optimistic)
    saved_b = likely_touched * 0.75
    new_wr_b = (len(winners) + saved_b) / len(trades) if trades else 0

    print(f"Current WR: {current_wr*100:.1f}%")
    print(f"Projected WR with partials+BE (50% of likely-touchers saved): {new_wr_a*100:.1f}%")
    print(f"Projected WR with partials+BE (75% of likely-touchers saved): {new_wr_b*100:.1f}%")
    print()

    # Also: rough avg P&L impact. Partials take 1/3 at 1R = +0.33R per saved trade,
    # minus the remaining 2/3 that get BE-stopped (= 0$).
    # Net effect per "saved" trade: +0.33R (compared to -1R = -$200)
    # So per saved trade: +$67 (instead of -$200), delta $267
    saved_trades = (saved_a + saved_b) / 2   # mid estimate
    delta_pnl = saved_trades * 267   # rough
    print(f"Rough P&L improvement estimate: +${delta_pnl:,.0f} on {saved_trades:.0f} saved trades")
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
