"""
Day-by-day diff between v8 baseline and v9 equal_levels on Q1 2024.

Goal: find days where v9 took MORE trades than v8 — those are the days
the extra equal_highs/lows detection actually added. Also find days where
v9 took FEWER trades, if any (strategy drift from extra levels confusing
confluence scoring).
"""

import json
from collections import defaultdict
from pathlib import Path

v8 = json.loads(Path("C:/AI Projects/AlgoICT/algoict-engine/analysis/sb_v8_2024.json").read_text())
v9 = json.loads(Path("C:/AI Projects/AlgoICT/algoict-engine/analysis/sb_v9_eql_q1.json").read_text())

def by_day(trades):
    d = defaultdict(list)
    for t in trades:
        date = t["entry_time"][:10]
        d[date].append(t)
    return d

v8_days = by_day([t for t in v8["trades"] if t["entry_time"] <= "2024-03-31T23:59:59"])
v9_days = by_day(v9["trades"])

all_days = sorted(set(v8_days) | set(v9_days))

diffs_plus = []  # v9 took more
diffs_minus = []  # v9 took fewer
same_count = 0

for d in all_days:
    n8 = len(v8_days.get(d, []))
    n9 = len(v9_days.get(d, []))
    p8 = sum(t["pnl"] for t in v8_days.get(d, []))
    p9 = sum(t["pnl"] for t in v9_days.get(d, []))
    if n9 > n8:
        diffs_plus.append((d, n8, n9, p8, p9))
    elif n9 < n8:
        diffs_minus.append((d, n8, n9, p8, p9))
    else:
        same_count += 1

print(f"=== Day-by-day diff Q1 2024 ===")
print(f"Total trading days: {len(all_days)}")
print(f"Same trade count:  {same_count}")
print(f"v9 more trades:    {len(diffs_plus)}")
print(f"v9 fewer trades:   {len(diffs_minus)}")
print()

if diffs_plus:
    print(f"=== Days where v9 (equal_levels) added trades ===")
    print(f"{'date':12} {'v8_n':>5} {'v9_n':>5} {'v8_pnl':>10} {'v9_pnl':>10} {'delta_pnl':>11}")
    for d, n8, n9, p8, p9 in sorted(diffs_plus, key=lambda x: x[2] - x[1], reverse=True)[:15]:
        print(f"{d:12} {n8:>5} {n9:>5} ${p8:>8,.0f}  ${p9:>8,.0f}  ${p9-p8:>+9,.0f}")
    total_extra = sum(n9-n8 for _, n8, n9, _, _ in diffs_plus)
    total_pnl_delta = sum(p9-p8 for _, _, _, p8, p9 in diffs_plus)
    print(f"  TOTAL extra trades on these days: {total_extra}, P&L delta: ${total_pnl_delta:+,.2f}")
    print()

if diffs_minus:
    print(f"=== Days where v9 dropped trades (unexpected) ===")
    print(f"{'date':12} {'v8_n':>5} {'v9_n':>5} {'v8_pnl':>10} {'v9_pnl':>10} {'delta_pnl':>11}")
    for d, n8, n9, p8, p9 in sorted(diffs_minus, key=lambda x: x[2] - x[1])[:15]:
        print(f"{d:12} {n8:>5} {n9:>5} ${p8:>8,.0f}  ${p9:>8,.0f}  ${p9-p8:>+9,.0f}")
    total_lost = sum(n8-n9 for _, n8, n9, _, _ in diffs_minus)
    total_pnl_delta = sum(p9-p8 for _, _, _, p8, p9 in diffs_minus)
    print(f"  TOTAL dropped trades: {total_lost}, P&L delta: ${total_pnl_delta:+,.2f}")
    print()

# Check: are same_count days identical trades or different trades same count?
different_same = 0
for d in all_days:
    n8 = len(v8_days.get(d, []))
    n9 = len(v9_days.get(d, []))
    if n8 != n9:
        continue
    p8 = sum(t["pnl"] for t in v8_days.get(d, []))
    p9 = sum(t["pnl"] for t in v9_days.get(d, []))
    if abs(p8 - p9) > 0.01:
        different_same += 1

print(f"Days with same count but different trades (strategy drift): {different_same}")
