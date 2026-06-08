"""Camino B — per-KZ instant-adverse circuit-breaker, cross-period post-hoc test.

Rule: within a trading day, track consecutive losses per kill_zone. Once a KZ
hits N consecutive losses, HALT that KZ for the rest of the day (skip all later
trades in that KZ). Reset every new CT day.

Post-hoc over the existing 3-year baseline trade logs. Decisive question:
are the SKIPPED trades net-negative (breaker helps) or net-positive
(throw-out-winner, like the 6 prior rejected filters)?

NOTE: post-hoc approximation. Skipping a trade would in reality shift downstream
state (consec counter, kill_switch, opportunity-replace). This is a first-pass
signal: if it doesn't help even here, kill it; if it helps, build + backtest
properly with the breaker wired into the engine.
"""
import json
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent / "sweep_diagnostic_crossperiod"
YEARS = ["2023", "2024", "2025"]

def load(year):
    d = json.load(open(BASE / f"{year}.json", encoding="utf-8"))
    return d.get("trades", [])

def day_of(t):
    s = t["entry_time"].replace(" ", "T")
    return datetime.fromisoformat(s).date()

def simulate(trades, n_consec, variant="consecutive"):
    """Return (treatment_pnl, skipped_trades). variant: consecutive | total."""
    # group counters per (day, kz)
    consec = {}    # (day,kz) -> current consecutive losses
    total_loss = {}  # (day,kz) -> total losses in kz that day
    halted = set()  # (day,kz) halted
    kept, skipped = [], []
    for t in sorted(trades, key=lambda x: x["entry_time"]):
        key = (day_of(t), t.get("kill_zone"))
        if key in halted:
            skipped.append(t)
            continue
        kept.append(t)
        pnl = float(t["pnl"])
        if pnl <= 0:
            consec[key] = consec.get(key, 0) + 1
            total_loss[key] = total_loss.get(key, 0) + 1
        else:
            consec[key] = 0
        trig = consec.get(key, 0) if variant == "consecutive" else total_loss.get(key, 0)
        if trig >= n_consec:
            halted.add(key)
    return sum(float(t["pnl"]) for t in kept), kept, skipped

print(f"{'CAMINO B — per-KZ consecutive-loss circuit-breaker':^72}")
print("="*72)
for variant in ("consecutive", "total"):
    print(f"\n########## variant = {variant} losses per KZ/day ##########")
    for n in (2, 3):
        print(f"\n--- halt KZ after {n} {variant} losses ---")
        agg_base = agg_treat = agg_skip = 0.0
        agg_nskip = 0
        for year in YEARS:
            trades = load(year)
            base = sum(float(t["pnl"]) for t in trades)
            treat, kept, skipped = simulate(trades, n, variant)
            skip_pnl = sum(float(t["pnl"]) for t in skipped)
            sk_w = sum(1 for t in skipped if float(t["pnl"]) > 0)
            delta = treat - base
            agg_base += base; agg_treat += treat; agg_skip += skip_pnl; agg_nskip += len(skipped)
            print(f"  {year}: base ${base:>10,.0f} | treat ${treat:>10,.0f} | "
                  f"delta ${delta:>+8,.0f} ({100*delta/base if base else 0:>+5.1f}%) | "
                  f"skipped {len(skipped):>3} trades worth ${skip_pnl:>+8,.0f} "
                  f"({sk_w}W/{len(skipped)-sk_w}L)")
        d = agg_treat - agg_base
        print(f"  AGG : base ${agg_base:>10,.0f} | treat ${agg_treat:>10,.0f} | "
              f"delta ${d:>+8,.0f} ({100*d/agg_base:>+5.1f}%) | skipped {agg_nskip} worth ${agg_skip:>+,.0f}")
        verdict = "HELPS (skipped trades net-negative)" if agg_skip < 0 else "THROW-OUT-WINNER (skipped trades net-POSITIVE)"
        print(f"  >>> {verdict}")
