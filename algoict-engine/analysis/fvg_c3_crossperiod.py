"""Cross-period validation: c3 close confirmation filter on 2023-2024-2025.

Phase 1 Q1 2025 alone said kill (-14.7% P&L). But Q1 is a single quarter
in a bull regime, exactly the kind of A/B sample that historically misled
us (see SB_MIN_LIVE_CONFLUENCE post-mortem in CLAUDE.md). Cross-period is
required before final decision.

Run baseline + c3-strict for each full year. Decision rules:
- If treatment beats baseline in 2/3 years: PROMOTE to ship (shadow → active)
- If treatment loses in 3/3 years: KILL
- If mixed (1/3 or 2/3 negative): consider regime-aware variant or ship shadow
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
OUT_DIR = Path(__file__).parent / "fvg_c3_crossperiod"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PERIODS = [
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
]

VARIANTS = [
    ("baseline", []),
    ("c3_strict", [
        "--config-override", "SB_FVG_REQUIRE_C3_CONFIRMATION=True",
        "--config-override", "SB_FVG_QUALITY_SHADOW_MODE=False",
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
    print(f"\n{'='*70}\n=> {label}  ({start} → {end})\n{'='*70}")
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
    print(" CROSS-PERIOD — C3 CLOSE CONFIRMATION (2023-2024-2025)")
    print("=" * 100)
    print()
    print(f"{'Year':<6} {'Variant':<10} {'Trades':>7} {'WR':>7} {'P&L':>13} "
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
        treat = v.get("c3_strict")
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
            f"{year:<6} {'baseline':<10} {base['trades']:>7} "
            f"{base['wr']*100:>6.1f}% ${base['pnl']:>+11,.0f} "
            f"${base['max_dd']:>8,.0f}"
        )
        print(
            f"{'':<6} {'c3_strict':<10} {treat['trades']:>7} "
            f"{treat['wr']*100:>6.1f}% ${treat['pnl']:>+11,.0f} "
            f"${treat['max_dd']:>8,.0f}  "
            f"${delta:>+9,.0f} ({delta_pct:>+5.1f}%)"
        )
        print()

    print("-" * 100)
    agg_delta = agg_treatment_pnl - agg_baseline_pnl
    agg_delta_pct = (agg_delta / agg_baseline_pnl * 100) if agg_baseline_pnl else 0
    print(f"3-year aggregate baseline:  ${agg_baseline_pnl:>+12,.0f}")
    print(f"3-year aggregate c3_strict: ${agg_treatment_pnl:>+12,.0f}")
    print(f"3-year aggregate delta:     ${agg_delta:>+12,.0f} ({agg_delta_pct:>+5.1f}%)")
    print()
    print(f"Treatment beats baseline: {treatment_wins}/3 years")
    print()
    print("VERDICT (matches CLAUDE.md ship criteria):")
    if treatment_wins >= 2:
        print("  -> PROMOTE — beats baseline in 2/3 years. Ship in shadow mode,")
        print("              accumulate live data 1-2 weeks before active.")
    elif treatment_wins == 0:
        print("  -> KILL — loses in 3/3 years. Same regime-dependent trap as the")
        print("           displacement/sweep/quadrant trio. Detector permissive")
        print("           IS the design; double-filtering hurts net.")
    else:
        print("  -> MIXED (1/3 positive) — regime-dependent. Options:")
        print("       (a) regime-aware variant (active only in chop/bear regimes)")
        print("       (b) ship in shadow mode + monitor live counterfactual")
        print("       (c) kill defensively")


def main():
    print("CROSS-PERIOD — c3 close confirmation filter")
    print(f"Periods: 2023 + 2024 + 2025")
    print(f"Variants per year: baseline, c3_strict")
    print(f"Total backtests: 6")
    print()
    results = []
    for year, start, end in PERIODS:
        for variant, overrides in VARIANTS:
            results.append(run_one(year, variant, overrides, start, end))
    summarize(results)


if __name__ == "__main__":
    main()
