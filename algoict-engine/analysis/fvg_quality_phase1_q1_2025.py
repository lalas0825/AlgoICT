"""Phase 1 EDA: FVG quality filters on Q1 2025 (single-quarter sanity).

Runs 6 backtests via the canonical run_backtest.py runner with
--config-override to flip each filter. Captures: trade count, WR, P&L,
PF, KZ split. If all variants stay within ±5% of baseline P&L → kill
experiment. If at least one shows >+10% promise → Phase 2 cross-period.

LESSON (CLAUDE.md SB_MIN_LIVE_CONFLUENCE postmortem): NEVER ship a gate
from a single-quarter result. This is EDA only — not a shipping decision.
"""
import subprocess
import json
import sys
from pathlib import Path

# Windows cp1252 -> utf-8 for unicode safety
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ENGINE_ROOT = Path(__file__).resolve().parent.parent
RUNNER = ENGINE_ROOT / "scripts" / "run_backtest.py"
DATA = ENGINE_ROOT.parent / "data" / "mnq_1min.csv"
OUT_DIR = Path(__file__).parent / "fvg_quality_phase1"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Common args shared by all runs — match live config:
#   - Silver Bullet strategy
#   - dynamic-bias (computed HTF, not static)
#   - wide-kz (v19a-WIDE, matches live RTH Mode)
#   - trailing exit (matches live + config default)
#   - no Supabase write (local-only EDA)
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

# Variants — each is a tuple (label, list of --config-override flags).
# Note: SB_FVG_QUALITY_SHADOW_MODE=False is REQUIRED for the gate to
# actually act on signals (otherwise it just logs).
VARIANTS = [
    ("B0_baseline", []),
    ("B1_displacement_2", [
        "--config-override", "SB_FVG_REQUIRE_DISPLACEMENT=True",
        "--config-override", "SB_FVG_MIN_DISPLACEMENT=2.0",
        "--config-override", "SB_FVG_QUALITY_SHADOW_MODE=False",
    ]),
    ("B2_linked_sweep", [
        "--config-override", "SB_FVG_REQUIRE_LINKED_SWEEP=True",
        "--config-override", "SB_FVG_SWEEP_LOOKBACK_BARS=10",
        "--config-override", "SB_FVG_QUALITY_SHADOW_MODE=False",
    ]),
    ("B3_quadrant", [
        "--config-override", "SB_FVG_REQUIRE_QUADRANT=True",
        "--config-override", "SB_FVG_QUALITY_SHADOW_MODE=False",
    ]),
    ("B4_all_three", [
        "--config-override", "SB_FVG_REQUIRE_DISPLACEMENT=True",
        "--config-override", "SB_FVG_MIN_DISPLACEMENT=2.0",
        "--config-override", "SB_FVG_REQUIRE_LINKED_SWEEP=True",
        "--config-override", "SB_FVG_SWEEP_LOOKBACK_BARS=10",
        "--config-override", "SB_FVG_REQUIRE_QUADRANT=True",
        "--config-override", "SB_FVG_QUALITY_SHADOW_MODE=False",
    ]),
    ("B5_displacement_3", [
        "--config-override", "SB_FVG_REQUIRE_DISPLACEMENT=True",
        "--config-override", "SB_FVG_MIN_DISPLACEMENT=3.0",
        "--config-override", "SB_FVG_QUALITY_SHADOW_MODE=False",
    ]),
]


def run_one(label: str, overrides: list[str]) -> dict:
    """Run one backtest variant, return parsed JSON stats."""
    out_json = OUT_DIR / f"{label}.json"
    cmd = (
        BASE_ARGS
        + overrides
        + ["--export-json", str(out_json)]
    )
    print(f"\n{'='*70}")
    print(f"=> {label}")
    print(f"   overrides: {overrides if overrides else '(none -- baseline)'}")
    print(f"{'='*70}")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(f"FAIL rc={proc.returncode}")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return {"label": label, "error": True}
    # tail of stdout for sanity
    tail = "\n".join(proc.stdout.splitlines()[-25:])
    print(tail)
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
        "peak": payload.get("peak_equity", 0.0),
    }


def summarize(results: list[dict]) -> None:
    """Print comparison table relative to baseline."""
    print()
    print("=" * 90)
    print(" PHASE 1 EDA — Q1 2025 FVG QUALITY GATE RESULTS")
    print("=" * 90)
    print()
    print(f"{'Variant':<22} {'Trades':>7} {'WR':>7} {'P&L':>12} "
          f"{'PF':>6} {'MaxDD':>10} {'ΔP&L vs B0':>14}")
    print("-" * 90)

    base = next((r for r in results if r["label"] == "B0_baseline"), None)
    base_pnl = base.get("pnl", 0) if base else 0
    base_trades = base.get("trades", 0) if base else 0

    for r in results:
        if r.get("error"):
            print(f"{r['label']:<22}  FAILED")
            continue
        pnl = r["pnl"]
        delta = pnl - base_pnl
        delta_pct = (delta / base_pnl * 100) if base_pnl else 0
        delta_str = f"${delta:>+9.0f} ({delta_pct:>+5.1f}%)"
        print(
            f"{r['label']:<22} {r['trades']:>7} "
            f"{r['wr']*100:>6.1f}% "
            f"${pnl:>+10,.0f} "
            f"{'-':>6} "
            f"${r['max_dd']:>8,.0f} "
            f"{delta_str:>14}"
        )

    print("-" * 90)
    print()
    print("DECISION CRITERIA for Phase 2 (cross-period 2023-2024-2025):")
    print("  -> IF best variant deltaP&L >= +10% AND trades_delta < -40% loss:")
    print("    PROMOTE that variant to Phase 2")
    print("  -> IF all variants within +/-5% of baseline: KILL experiment")
    print("  -> IF best variant deltaP&L > 0 but minor: log + revisit after more live data")
    print()
    print(f"Detailed JSON in: {OUT_DIR}")


def main():
    print("PHASE 1 EDA — FVG quality gate on Q1 2025")
    print(f"Data: {DATA}")
    print(f"Variants: {len(VARIANTS)}")
    print()
    results = []
    for label, overrides in VARIANTS:
        results.append(run_one(label, overrides))
    summarize(results)


if __name__ == "__main__":
    main()
