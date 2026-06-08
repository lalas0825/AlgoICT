"""Camino B — two remaining variants: (1) instant-adverse (quick-stop) halt,
(2) cross-KZ cascade. Same 3-year post-hoc throw-out-winner test."""
import json
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent / "sweep_diagnostic_crossperiod"
YEARS = ["2023", "2024", "2025"]
load = lambda y: json.load(open(BASE / f"{y}.json", encoding="utf-8")).get("trades", [])
pt = lambda s: datetime.fromisoformat(s.replace(" ", "T"))
day_of = lambda t: pt(t["entry_time"]).date()
def dur_min(t):
    return (pt(t["exit_time"]) - pt(t["entry_time"])).total_seconds() / 60.0

# ---------- (1) instant-adverse: quick-stop loss (loss AND duration < QMIN) ----------
QMIN = 8
def is_quick_stop(t):
    return float(t["pnl"]) <= 0 and dur_min(t) <= QMIN

print(f"{'(1) INSTANT-ADVERSE halt: KZ after N quick-stop (<%dmin) losses' % QMIN:^72}")
print("="*72)
for n in (2, 3):
    print(f"\n--- halt KZ after {n} quick-stop losses ---")
    ab = at = ask = 0.0; ns = 0
    for year in YEARS:
        trades = sorted(load(year), key=lambda x: x["entry_time"])
        base = sum(float(t["pnl"]) for t in trades)
        cnt = {}; halted = set(); kept = []; skipped = []
        for t in trades:
            key = (day_of(t), t.get("kill_zone"))
            if key in halted:
                skipped.append(t); continue
            kept.append(t)
            if is_quick_stop(t):
                cnt[key] = cnt.get(key, 0) + 1
                if cnt[key] >= n: halted.add(key)
            elif float(t["pnl"]) > 0:
                cnt[key] = 0
        treat = sum(float(t["pnl"]) for t in kept)
        sp = sum(float(t["pnl"]) for t in skipped)
        sw = sum(1 for t in skipped if float(t["pnl"]) > 0)
        ab += base; at += treat; ask += sp; ns += len(skipped)
        print(f"  {year}: delta ${treat-base:>+8,.0f} ({100*(treat-base)/base:>+5.1f}%) | "
              f"skipped {len(skipped):>3} worth ${sp:>+8,.0f} ({sw}W/{len(skipped)-sw}L)")
    print(f"  AGG : delta ${at-ab:>+8,.0f} ({100*(at-ab)/ab:>+5.1f}%) | skipped {ns} worth ${ask:>+,.0f}"
          f"  >>> {'HELPS' if ask < 0 else 'THROW-OUT-WINNER'}")

# ---------- (2) cross-KZ cascade: are trades in a KZ that FOLLOWS a net-neg KZ same day net-pos or net-neg? ----------
ORDER = {"london": 0, "ny_am": 1, "ny_pm": 2}
print(f"\n\n{'(2) CROSS-KZ CASCADE: P&L of a KZ that follows a net-NEGATIVE KZ same day':^72}")
print("="*72)
for year in YEARS:
    trades = load(year)
    bydaykz = {}
    for t in trades:
        bydaykz.setdefault((day_of(t), t.get("kill_zone")), []).append(t)
    after_neg = []  # trades in a KZ whose PRIOR same-day KZ was net-negative
    for (day, kz), ts in bydaykz.items():
        o = ORDER.get(kz, 9)
        prior = [(k2, sum(float(x["pnl"]) for x in v2)) for (d2, k2), v2 in bydaykz.items()
                 if d2 == day and ORDER.get(k2, 9) < o]
        if prior and any(p < 0 for _, p in prior):
            after_neg.extend(ts)
    pnl = sum(float(t["pnl"]) for t in after_neg)
    w = sum(1 for t in after_neg if float(t["pnl"]) > 0)
    print(f"  {year}: trades after a net-neg KZ = {len(after_neg):>4} | P&L ${pnl:>+10,.0f} "
          f"({w}W/{len(after_neg)-w}L, avg ${pnl/len(after_neg) if after_neg else 0:>+6.0f}/trade)"
          f"  >>> {'cascade real (net-neg)' if pnl < 0 else 'net-POSITIVE (no cascade to gate)'}")
