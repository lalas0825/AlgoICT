"""
A/B compare: v8 baseline (no equal_levels) vs v9 equal_levels — Q1 2024.

Loads both JSONs, slices v8 to Q1 2024, and prints side-by-side stats:
  - total trades / wins / losses / WR
  - total P&L, profit factor
  - avg win, avg loss
  - per-KZ breakdown (london / ny_am / ny_pm)
  - combine resets
  - max DD
  - extra v9-only signals that v8 didn't take (count by reason/KZ)
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASELINE = Path("C:/AI Projects/AlgoICT/algoict-engine/analysis/sb_v8_2024.json")
CANDIDATE = Path("C:/AI Projects/AlgoICT/algoict-engine/analysis/sb_v9_eql_q1.json")


def q1_slice(trades):
    return [t for t in trades if t["entry_time"] <= "2024-03-31T23:59:59"]


def stats(trades):
    if not trades:
        return dict(n=0)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = sum(t["pnl"] for t in losses)
    pf = abs(gross_win / gross_loss) if gross_loss else float("inf")
    kz_counts = Counter(t["kill_zone"] for t in trades)
    kz_pnl = {}
    kz_wins = {}
    for t in trades:
        kz_pnl.setdefault(t["kill_zone"], 0.0)
        kz_pnl[t["kill_zone"]] += t["pnl"]
        if t["pnl"] > 0:
            kz_wins[t["kill_zone"]] = kz_wins.get(t["kill_zone"], 0) + 1
    return dict(
        n=len(trades),
        wins=len(wins),
        losses=len(losses),
        wr=len(wins) / len(trades),
        pnl=sum(t["pnl"] for t in trades),
        pf=pf,
        avg_win=gross_win / len(wins) if wins else 0.0,
        avg_loss=gross_loss / len(losses) if losses else 0.0,
        kz_counts=dict(kz_counts),
        kz_pnl=kz_pnl,
        kz_wins=kz_wins,
    )


def print_block(label, s):
    print(f"=== {label} ===")
    if s.get("n", 0) == 0:
        print("  (no trades)")
        return
    print(f"  trades       : {s['n']}")
    print(f"  wins         : {s['wins']}")
    print(f"  losses       : {s['losses']}")
    print(f"  win_rate     : {s['wr']:.1%}")
    print(f"  total_pnl    : ${s['pnl']:,.2f}")
    print(f"  profit_factor: {s['pf']:.2f}")
    print(f"  avg_win      : ${s['avg_win']:,.2f}")
    print(f"  avg_loss     : ${s['avg_loss']:,.2f}")
    print("  by KZ:")
    for kz in ("london", "ny_am", "ny_pm"):
        n = s["kz_counts"].get(kz, 0)
        pnl = s["kz_pnl"].get(kz, 0.0)
        wins = s["kz_wins"].get(kz, 0)
        wr = wins / n if n else 0.0
        print(f"    {kz:10} trades={n:3} pnl=${pnl:>10,.2f} wr={wr:.0%}")
    print()


def main():
    if not BASELINE.exists():
        sys.exit(f"Missing baseline: {BASELINE}")
    if not CANDIDATE.exists():
        sys.exit(f"Missing candidate: {CANDIDATE} (still running?)")

    v8 = json.loads(BASELINE.read_text())
    v9 = json.loads(CANDIDATE.read_text())

    v8_q1 = q1_slice(v8["trades"])
    v9_q1 = v9["trades"]  # already Q1 only

    s8 = stats(v8_q1)
    s9 = stats(v9_q1)

    print_block("V8 BASELINE Q1 2024 (no equal_levels)", s8)
    print_block("V9 CANDIDATE Q1 2024 (WITH equal_levels)", s9)

    print("=== DELTA (v9 - v8) ===")
    print(f"  trades       : {s9['n'] - s8['n']:+d}")
    print(f"  wins         : {s9['wins'] - s8['wins']:+d}")
    print(f"  win_rate     : {(s9['wr'] - s8['wr']) * 100:+.1f} pp")
    print(f"  total_pnl    : ${s9['pnl'] - s8['pnl']:+,.2f}")
    print(f"  profit_factor: {s9['pf'] - s8['pf']:+.2f}")
    print(f"  combine_resets: v8={v8.get('combine_resets','?')} v9={v9.get('combine_resets','?')}")
    print(f"  max_dd       : v8=${v8.get('max_drawdown_dollars',0):,.2f} v9=${v9.get('max_drawdown_dollars',0):,.2f}")
    print()

    print("=== VERDICT ===")
    if s9["n"] > s8["n"] and s9["pnl"] > s8["pnl"] and s9["wr"] >= s8["wr"] - 0.02:
        print("  [PASS] More trades, more P&L, WR within 2pp -> wire equal_levels to live")
    elif s9["pnl"] > s8["pnl"] * 1.10:
        print("  [PASS] >10% P&L improvement -> wire equal_levels to live")
    elif s9["pnl"] < s8["pnl"] * 0.90:
        print("  [FAIL] >10% P&L degradation -> keep equal_levels OFF")
    else:
        print("  [MARGINAL] Mixed signal -> need more quarters before deciding")


if __name__ == "__main__":
    main()
