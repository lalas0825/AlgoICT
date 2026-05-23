"""Phase 1 EDA: c3 close confirmation filter on Q1 2025.

Forensic-driven (Thu 5/21 audit, 3 live trades all had c3.close inside c2
range). Tests whether this filter — ICT-canonical body-close confirmation
— mejora P&L sin tankear trade count.

Baseline (B0) vs c3-strict (B1) on Q1 2025 first. If promising, run
cross-period 2023-2024-2025.
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
OUT_DIR = Path(__file__).parent / "fvg_c3_phase1"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_ARGS = [
    sys.executable, str(RUNNER),
    "--strategy", "silver_bullet",
    "--csv", str(DATA),
    "--start", "2025-01-01",
    "--end", "2025-03-31",
    "--dynamic-bias",
    "--wide-kz",
    "--trade-management", "trailing",
    "--no-supabase",
]

VARIANTS = [
    ("B0_baseline", []),
    ("B1_c3_strict", [
        "--config-override", "SB_FVG_REQUIRE_C3_CONFIRMATION=True",
        "--config-override", "SB_FVG_QUALITY_SHADOW_MODE=False",
    ]),
]


def run_one(label, overrides):
    out_json = OUT_DIR / f"{label}.json"
    cmd = BASE_ARGS + overrides + ["--export-json", str(out_json)]
    print(f"\n{'='*70}\n=> {label}\n{'='*70}")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(f"FAIL rc={proc.returncode}")
        print(proc.stdout[-1500:])
        print(proc.stderr[-1500:])
        return {"label": label, "error": True}
    print("\n".join(proc.stdout.splitlines()[-15:]))
    if not out_json.exists():
        return {"label": label, "error": True, "msg": "no JSON exported"}
    with open(out_json, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return {
        "label": label,
        "trades": payload.get("total_trades", 0),
        "wins": payload.get("wins", 0),
        "losses": payload.get("losses", 0),
        "wr": payload.get("win_rate", 0.0),
        "pnl": payload.get("total_pnl", 0.0),
        "max_dd": payload.get("max_drawdown_dollars", 0.0),
    }


def summarize(results):
    print()
    print("=" * 90)
    print(" PHASE 1 EDA — C3 CLOSE CONFIRMATION (Q1 2025)")
    print("=" * 90)
    print()
    print(f"{'Variant':<18} {'Trades':>7} {'WR':>7} {'P&L':>13} "
          f"{'MaxDD':>10} {'deltaP&L':>14}")
    print("-" * 90)

    base = next((r for r in results if r["label"] == "B0_baseline"), None)
    base_pnl = base.get("pnl", 0) if base else 0
    base_trades = base.get("trades", 0) if base else 0

    for r in results:
        if r.get("error"):
            print(f"{r['label']:<18}  FAILED")
            continue
        pnl = r["pnl"]
        delta = pnl - base_pnl
        delta_pct = (delta / base_pnl * 100) if base_pnl else 0
        print(
            f"{r['label']:<18} {r['trades']:>7} "
            f"{r['wr']*100:>6.1f}% "
            f"${pnl:>+11,.0f} "
            f"${r['max_dd']:>8,.0f} "
            f"${delta:>+9.0f} ({delta_pct:>+5.1f}%)"
        )

    print("-" * 90)
    print()
    if base and not results[-1].get("error"):
        treatment = results[-1]
        trade_cut_pct = (1 - treatment["trades"]/base_trades) * 100 if base_trades else 0
        wr_delta_pp = (treatment["wr"] - base["wr"]) * 100
        pnl_delta_pct = (treatment["pnl"] - base_pnl) / base_pnl * 100 if base_pnl else 0
        print(f"Trade cut:   {trade_cut_pct:>+5.1f}%  ({base_trades} -> {treatment['trades']})")
        print(f"WR delta:    {wr_delta_pp:>+5.1f}pp ({base['wr']*100:.1f}% -> {treatment['wr']*100:.1f}%)")
        print(f"P&L delta:   {pnl_delta_pct:>+5.1f}%")
        print()
        print("DECISION CRITERIA:")
        print("  PROMOTE to cross-period IF deltaP&L >= +5% AND trade_cut < 60%")
        print("  KILL                  IF deltaP&L < -5% OR trade_cut > 70%")
        print("  REVISIT (caution)     otherwise")


def main():
    print("PHASE 1 — c3 close confirmation filter")
    print(f"Period: 2025-01-01 to 2025-03-31 (Q1 2025)")
    print()
    results = []
    for label, overrides in VARIANTS:
        results.append(run_one(label, overrides))
    summarize(results)


if __name__ == "__main__":
    main()
