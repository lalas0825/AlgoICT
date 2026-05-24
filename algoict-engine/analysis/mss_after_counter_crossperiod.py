"""Cross-period: SB_REQUIRE_MSS_AFTER_COUNTER gate on 2023-2024-2025.

Fix #3 hypothesis: pure BOS chain after counter-direction event = recovery
rally / continuation of OPPOSITE trend (not real flip). Forensic from
Thu 5/21 trade #2 (-$143 WTF LONG) where aligned=[BOS,BOS,BOS] after
250pt bearish drop fired LONG and lost.

Decision criteria (mirrors c3 cross-period):
- 3/3 wins:    PROMOTE (ship in shadow first, then active)
- 2/3 wins:    PROMOTE with caveats
- 1/3 or 0/3:  KILL — same regime trap as the FVG quality trio
"""
import subprocess
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ENGINE_ROOT = Path(__file__).resolve().parent.parent
RUNNER = ENGINE_ROOT / "scripts" / "run_backtest.py"
DATA = ENGINE_ROOT.parent / "data" / "mnq_1min.csv"
OUT_DIR = Path(__file__).parent / "mss_after_counter_crossperiod"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PERIODS = [
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
]

VARIANTS = [
    ("baseline", []),
    ("flip_required", [
        "--config-override", "SB_REQUIRE_MSS_AFTER_COUNTER=True",
    ]),
]


def base_args(start, end):
    return [
        sys.executable, str(RUNNER),
        "--strategy", "silver_bullet",
        "--csv", str(DATA),
        "--start", start,
        "--end", end,
        "--dynamic-bias",
        "--wide-kz",
        "--trade-management", "trailing",
        "--no-supabase",
    ]


def run_one(year, variant_label, overrides, start, end):
    label = f"{year}_{variant_label}"
    out_json = OUT_DIR / f"{label}.json"
    cmd = base_args(start, end) + overrides + ["--export-json", str(out_json)]
    print(f"\n{'='*70}\n=> {label}  ({start} -> {end})\n{'='*70}")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(f"FAIL rc={proc.returncode}")
        print(proc.stderr[-1500:])
        return {"label": label, "error": True}
    print("\n".join(proc.stdout.splitlines()[-8:]))
    if not out_json.exists():
        return {"label": label, "error": True}
    with open(out_json, "r", encoding="utf-8") as f:
        p = json.load(f)
    return {
        "label": label,
        "year": year,
        "variant": variant_label,
        "trades": p.get("total_trades", 0),
        "wins": p.get("wins", 0),
        "losses": p.get("losses", 0),
        "wr": p.get("win_rate", 0.0),
        "pnl": p.get("total_pnl", 0.0),
        "max_dd": p.get("max_drawdown_dollars", 0.0),
    }


def summarize(results):
    print()
    print("=" * 100)
    print(" CROSS-PERIOD — SB_REQUIRE_MSS_AFTER_COUNTER (2023-2024-2025)")
    print("=" * 100)
    print()
    print(f"{'Year':<6} {'Variant':<14} {'Trades':>7} {'WR':>7} {'P&L':>13} "
          f"{'MaxDD':>10} {'deltaP&L_vs_baseline':>22}")
    print("-" * 100)

    by_year = {}
    for r in results:
        if r.get("error"):
            print(f"{r['label']}  FAILED")
            continue
        by_year.setdefault(r["year"], {})[r["variant"]] = r

    treatment_wins = 0
    treatment_losses = 0
    agg_baseline_pnl = 0.0
    agg_treatment_pnl = 0.0

    for year in sorted(by_year.keys()):
        v = by_year[year]
        base = v.get("baseline")
        treat = v.get("flip_required")
        if not base or not treat:
            continue
        delta = treat["pnl"] - base["pnl"]
        delta_pct = (delta / base["pnl"] * 100) if base["pnl"] else 0
        agg_baseline_pnl += base["pnl"]
        agg_treatment_pnl += treat["pnl"]
        if delta > 0:
            treatment_wins += 1
        else:
            treatment_losses += 1
        print(
            f"{year:<6} {'baseline':<14} {base['trades']:>7} "
            f"{base['wr']*100:>6.1f}% ${base['pnl']:>+11,.0f} "
            f"${base['max_dd']:>8,.0f}"
        )
        print(
            f"{'':<6} {'flip_required':<14} {treat['trades']:>7} "
            f"{treat['wr']*100:>6.1f}% ${treat['pnl']:>+11,.0f} "
            f"${treat['max_dd']:>8,.0f}  "
            f"${delta:>+9,.0f} ({delta_pct:>+5.1f}%)"
        )
        print()

    print("-" * 100)
    agg_delta = agg_treatment_pnl - agg_baseline_pnl
    agg_delta_pct = (agg_delta / agg_baseline_pnl * 100) if agg_baseline_pnl else 0
    print(f"3-year aggregate baseline:       ${agg_baseline_pnl:>+12,.0f}")
    print(f"3-year aggregate flip_required:  ${agg_treatment_pnl:>+12,.0f}")
    print(f"3-year aggregate delta:          ${agg_delta:>+12,.0f} ({agg_delta_pct:>+5.1f}%)")
    print()
    print(f"Treatment beats baseline: {treatment_wins}/3 years")
    print()
    print("VERDICT:")
    if treatment_wins >= 2:
        print("  -> PROMOTE — beats baseline in 2/3 years. Ship in shadow,")
        print("              accumulate live data, then active.")
    elif treatment_wins == 0:
        print("  -> KILL — loses in 3/3 years. The pure BOS chains the gate")
        print("           rejects ARE net-profitable across regimes.")
    else:
        print("  -> MIXED — regime-dependent. Consider regime-aware variant")
        print("           or ship in shadow mode for live counterfactual.")


def main():
    print("CROSS-PERIOD — SB_REQUIRE_MSS_AFTER_COUNTER (Fix #3)")
    print("Forensic: Thu 5/21 trade #2 — pure BOS bull chain after bear drop")
    print()
    results = []
    for year, start, end in PERIODS:
        for variant, overrides in VARIANTS:
            results.append(run_one(year, variant, overrides, start, end))
    summarize(results)


if __name__ == "__main__":
    main()
