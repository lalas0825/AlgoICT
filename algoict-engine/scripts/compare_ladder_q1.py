"""
A/B compare: v8 baseline (flat $250) vs v10 (ladder 250/200/150/100/50 +
London 2-loss cap) — Q1 2024.

Loads both JSONs, slices v8 to Q1 2024, prints side-by-side stats +
per-KZ + per-day breakdown, and highlights Combine-relevant metrics
(daily DLL breaches, combine resets).
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASELINE = Path("C:/AI Projects/AlgoICT/algoict-engine/analysis/sb_v8_2024.json")
CANDIDATE = Path("C:/AI Projects/AlgoICT/algoict-engine/analysis/sb_v10_ladder_q1.json")


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
    kz_pnl = defaultdict(float)
    kz_wins = defaultdict(int)
    kz_losses = defaultdict(int)
    for t in trades:
        kz_pnl[t["kill_zone"]] += t["pnl"]
        if t["pnl"] > 0:
            kz_wins[t["kill_zone"]] += 1
        else:
            kz_losses[t["kill_zone"]] += 1
    # Per-day DLL breach count (proxy: day's total loss <= -1000)
    day_pnl = defaultdict(float)
    for t in trades:
        day_pnl[t["entry_time"][:10]] += t["pnl"]
    dll_breaches = sum(1 for p in day_pnl.values() if p <= -1000)
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
        kz_pnl=dict(kz_pnl),
        kz_wins=dict(kz_wins),
        kz_losses=dict(kz_losses),
        dll_breach_days=dll_breaches,
        trading_days=len(day_pnl),
        worst_day=min(day_pnl.values()) if day_pnl else 0.0,
        best_day=max(day_pnl.values()) if day_pnl else 0.0,
    )


def print_block(label, s, extra=None):
    print(f"=== {label} ===")
    if s.get("n", 0) == 0:
        print("  (no trades)")
        return
    print(f"  trades       : {s['n']}")
    print(f"  wins/losses  : {s['wins']} / {s['losses']}")
    print(f"  win_rate     : {s['wr']:.1%}")
    print(f"  total_pnl    : ${s['pnl']:,.2f}")
    print(f"  profit_factor: {s['pf']:.2f}")
    print(f"  avg_win      : ${s['avg_win']:,.2f}")
    print(f"  avg_loss     : ${s['avg_loss']:,.2f}")
    print(f"  trading_days : {s['trading_days']}")
    print(f"  DLL breach days (<= -$1000): {s['dll_breach_days']}")
    print(f"  worst day    : ${s['worst_day']:,.2f}")
    print(f"  best day     : ${s['best_day']:,.2f}")
    if extra:
        for k, v in extra.items():
            print(f"  {k:13}: {v}")
    print("  by KZ:")
    for kz in ("london", "ny_am", "ny_pm"):
        n = s["kz_counts"].get(kz, 0)
        pnl = s["kz_pnl"].get(kz, 0.0)
        wins = s["kz_wins"].get(kz, 0)
        losses = s["kz_losses"].get(kz, 0)
        wr = wins / n if n else 0.0
        print(f"    {kz:10} trades={n:3} ({wins}W/{losses}L) pnl=${pnl:>10,.2f} wr={wr:.0%}")
    print()


def main():
    if not BASELINE.exists():
        sys.exit(f"Missing baseline: {BASELINE}")
    if not CANDIDATE.exists():
        sys.exit(f"Missing candidate: {CANDIDATE} (still running?)")

    v8 = json.loads(BASELINE.read_text())
    v10 = json.loads(CANDIDATE.read_text())

    v8_q1 = q1_slice(v8["trades"])
    v10_q1 = v10["trades"]  # already Q1 only

    s8 = stats(v8_q1)
    s10 = stats(v10_q1)

    v8_extra = {
        "combine_resets": v8.get("combine_resets", 0),
        "max_dd": f"${v8.get('max_drawdown_dollars', 0):,.2f}",
        "peak_equity": f"${v8.get('peak_equity', 0):,.2f}",
    }
    v10_extra = {
        "combine_resets": v10.get("combine_resets", 0),
        "max_dd": f"${v10.get('max_drawdown_dollars', 0):,.2f}",
        "peak_equity": f"${v10.get('peak_equity', 0):,.2f}",
    }

    print_block(
        "V8 BASELINE Q1 2024 (flat $250, 3-consec kill switch, per-KZ reset)",
        s8, v8_extra,
    )
    print_block(
        "V10 Q1 2024 (ladder 250/200/150/100/50 + London 2L cap)",
        s10, v10_extra,
    )

    print("=== DELTA (v10 - v8) ===")
    print(f"  trades          : {s10['n'] - s8['n']:+d}")
    print(f"  wins            : {s10['wins'] - s8['wins']:+d}")
    print(f"  win_rate        : {(s10['wr'] - s8['wr']) * 100:+.1f} pp")
    print(f"  total_pnl       : ${s10['pnl'] - s8['pnl']:+,.2f}")
    print(f"  profit_factor   : {s10['pf'] - s8['pf']:+.2f}")
    print(f"  DLL breach days : {s10['dll_breach_days'] - s8['dll_breach_days']:+d}  "
          f"(v8={s8['dll_breach_days']} v10={s10['dll_breach_days']})")
    print(f"  combine_resets  : {v10.get('combine_resets',0) - v8.get('combine_resets',0):+d}  "
          f"(v8={v8.get('combine_resets',0)} v10={v10.get('combine_resets',0)})")
    print(f"  max_dd          : v8={v8_extra['max_dd']} v10={v10_extra['max_dd']}")
    print(f"  worst_day       : ${s10['worst_day'] - s8['worst_day']:+,.2f}  "
          f"(v8=${s8['worst_day']:,.2f} v10=${s10['worst_day']:,.2f})")
    print()

    print("=== VERDICT ===")
    # Ladder's job: survive Combine. Three key metrics:
    #   1. Does ladder reduce DLL breaches?
    #   2. Does PF stay >= baseline?
    #   3. Is P&L improvement >0 OR combine_resets down >=30%?
    dll_better = s10["dll_breach_days"] < s8["dll_breach_days"]
    pf_ok = s10["pf"] >= s8["pf"] * 0.92   # tolerate -8% PF
    pnl_ok = s10["pnl"] >= s8["pnl"] * 0.80
    resets_better = v10.get("combine_resets", 0) < v8.get("combine_resets", 0)
    if dll_better and pf_ok and pnl_ok:
        print("  [PASS] Ladder reduces DLL breaches without killing edge "
              "-> wire to live for Combine")
    elif dll_better and resets_better:
        print("  [PASS-LITE] Fewer breaches + fewer resets, edge slightly degraded "
              "-> ladder is Combine-safer, consider live")
    elif s10["pnl"] < s8["pnl"] * 0.50:
        print("  [FAIL] Ladder cuts P&L too aggressively -> need to tune schedule")
    else:
        print("  [MARGINAL] Check per-KZ + per-day splits before deciding")


if __name__ == "__main__":
    main()
