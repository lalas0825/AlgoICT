"""Test: let pending limits persist across KZ boundaries (contiguous KZs = one
window) vs the shipped per-KZ cancel. Cross-period 2023/24/25.

Motivated by a live NY-AM limit cancelled at the KZ boundary that would have
filled +133pts 11 min later. Question: does capturing those cross-KZ fills beat
the cost (zombie limits filling in stale conditions), net cross-period?
"""
import json, subprocess, sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
RUNNER = ENGINE / "scripts" / "run_backtest.py"
DATA = ENGINE.parent / "data" / "mnq_1min.csv"
OUT = Path(__file__).parent / "kz_carry_crossperiod"
OUT.mkdir(parents=True, exist_ok=True)
PERIODS = [("2023", "2023-01-01", "2023-12-31"),
           ("2024", "2024-01-01", "2024-12-31"),
           ("2025", "2025-01-01", "2025-12-31")]

def run(year, start, end, treat):
    out = OUT / f"{year}_{'treat' if treat else 'base'}.json"
    cmd = [sys.executable, str(RUNNER), "--strategy", "silver_bullet",
           "--csv", str(DATA), "--start", start, "--end", end,
           "--dynamic-bias", "--wide-kz", "--trade-management", "trailing",
           "--no-supabase", "--export-json", str(out)]
    if treat:
        cmd += ["--config-override", "CARRY_LIMITS_ACROSS_KZ=True"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        print(f"  FAIL {year} treat={treat} rc={p.returncode}\n{p.stderr[-1200:]}")
        return None
    return json.load(open(out, encoding="utf-8"))

print(f"{'KZ-CARRY: limits persist across contiguous KZs vs per-KZ cancel':^74}")
print("=" * 74)
ab = at = 0.0
for year, s, e in PERIODS:
    print(f"\n=> {year} ...", flush=True)
    base = run(year, s, e, False)
    treat = run(year, s, e, True)
    if not base or not treat:
        continue
    bp, tp = base["total_pnl"], treat["total_pnl"]
    bt, tt = base["total_trades"], treat["total_trades"]
    bw, tw = base["win_rate"], treat["win_rate"]
    ab += bp; at += tp
    print(f"  baseline : ${bp:>10,.0f} | {bt} trades | WR {bw:.1f}%")
    print(f"  treatment: ${tp:>10,.0f} | {tt} trades | WR {tw:.1f}%")
    print(f"  delta    : ${tp-bp:>+10,.0f} ({100*(tp-bp)/bp if bp else 0:+.1f}%) | "
          f"trades {tt-bt:+d}")
d = at - ab
print("\n" + "=" * 74)
print(f"AGG baseline ${ab:,.0f} | treatment ${at:,.0f} | delta ${d:+,.0f} ({100*d/ab if ab else 0:+.1f}%)")
print(f">>> {'SHIP IT — carry helps cross-period' if d > 0 else 'THROW-OUT-WINNER — per-KZ cancel is correct'}")
