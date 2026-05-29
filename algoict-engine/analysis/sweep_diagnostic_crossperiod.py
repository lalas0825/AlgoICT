"""Sweep-gap diagnostic — cross-period 2023/2024/2025 (Step 0, NOT a gate).

Motivation (2026-05-29 forensic): SB fired a LONG after a BSL (high) sweep,
validated by a stale PDL swept 5 days / 650pts away. Direction comes from the
FVG; the sweep gate only checks that *some* opposite-side level was swept and
not reclaimed — no recency, no proximity, and it ignores the most-recent sweep
direction.

This script does NOT add a gate. It runs the canonical baseline backtest and
buckets realized P&L by the per-fire `sweep_diag` telemetry (recency,
proximity, most-recent-sweep direction alignment) to answer ONE question:

    Are "stale / far / direction-contrary sweep" trades net-NEGATIVE across
    all three regimes (→ a recency/proximity/direction gate is worth building)
    or net-POSITIVE (→ another throw-out-winner, like the FVG-quality trio,
    c3, MSS-after-counter — leave it alone)?

Requires the sweep_diag instrumentation in silver_bullet.py + backtester.py +
run_backtest.py --export-json (2026-05-29).
"""
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ENGINE_ROOT = Path(__file__).resolve().parent.parent
RUNNER = ENGINE_ROOT / "scripts" / "run_backtest.py"
DATA = ENGINE_ROOT.parent / "data" / "mnq_1min.csv"
OUT_DIR = Path(__file__).parent / "sweep_diagnostic_crossperiod"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PERIODS = [
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
]


def base_args(start, end, out_json):
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
        "--export-json", str(out_json),
    ]


def run_year(year, start, end):
    out_json = OUT_DIR / f"{year}.json"
    cmd = base_args(start, end, out_json)
    print(f"\n{'='*70}\n=> {year}  ({start} -> {end})\n{'='*70}")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(f"FAIL rc={proc.returncode}")
        print(proc.stderr[-1500:])
        return []
    print("\n".join(proc.stdout.splitlines()[-6:]))
    if not out_json.exists():
        return []
    with open(out_json, "r", encoding="utf-8") as f:
        payload = json.load(f)
    trades = payload.get("trades", [])
    for t in trades:
        t["_year"] = year
    return trades


# ── Bucket key functions ────────────────────────────────────────────────

def k_align(t):
    v = (t.get("sweep_diag") or {}).get("recent_sweep_aligned")
    return {True: "aligned", False: "CONTRARY"}.get(v, "unknown")


def k_recency(t):
    r = (t.get("sweep_diag") or {}).get("recency_min")
    if r is None:
        return "unknown"
    if r <= 30:
        return "a <=30m"
    if r <= 120:
        return "b 30-120m"
    if r <= 480:
        return "c 2-8h"
    return "d >8h STALE"


def k_prox(t):
    p = (t.get("sweep_diag") or {}).get("proximity_pts")
    if p is None:
        return "unknown"
    if p <= 50:
        return "a <=50pt"
    if p <= 150:
        return "b 50-150pt"
    if p <= 300:
        return "c 150-300pt"
    return "d >300pt FAR"


def k_badsetup(t):
    """Combined 'looks wrong per ICT' flag: contrary direction OR stale OR far."""
    d = t.get("sweep_diag") or {}
    contrary = d.get("recent_sweep_aligned") is False
    r = d.get("recency_min")
    stale = (r is not None and r > 480)
    p = d.get("proximity_pts")
    far = (p is not None and p > 300)
    return "BAD (contrary/stale/far)" if (contrary or stale or far) else "clean"


def agg(trades):
    n = len(trades)
    pnl = sum(float(t["pnl"]) for t in trades)
    wins = sum(1 for t in trades if float(t["pnl"]) > 0)
    wr = (wins / n * 100) if n else 0.0
    avg = (pnl / n) if n else 0.0
    return n, wr, pnl, avg


def print_dim(title, trades, keyfn):
    print(f"\n{title}")
    print(f"  {'bucket':<24} {'n':>6} {'WR':>7} {'totalP&L':>13} {'avg/trade':>11}")
    print("  " + "-" * 64)
    buckets = defaultdict(list)
    for t in trades:
        buckets[keyfn(t)].append(t)
    for key in sorted(buckets.keys()):
        n, wr, pnl, avg = agg(buckets[key])
        flag = "  <== net NEG" if pnl < 0 else ""
        print(f"  {key:<24} {n:>6} {wr:>6.1f}% ${pnl:>+11,.0f} ${avg:>+9.0f}{flag}")


def main():
    print("SWEEP-GAP DIAGNOSTIC — cross-period 2023/2024/2025 (Step 0)")
    print("Baseline canonical SB; bucketing realized P&L by sweep_diag.")

    all_trades = []
    per_year = {}
    for year, start, end in PERIODS:
        ts = run_year(year, start, end)
        per_year[year] = ts
        all_trades.extend(ts)

    sb = [t for t in all_trades if t.get("strategy") == "silver_bullet"]
    with_diag = [t for t in sb if (t.get("sweep_diag") or {})]
    print(f"\n{'='*70}")
    print(f" Loaded {len(all_trades)} trades; {len(sb)} silver_bullet; "
          f"{len(with_diag)} with sweep_diag populated")
    print(f"{'='*70}")
    if not with_diag:
        print("\n!! sweep_diag is EMPTY on all trades — instrumentation not "
              "flowing through. Check Signal->pending_entry->Trade->export.")
        return

    # ── 3-year aggregate, per dimension ──
    print("\n" + "#" * 70)
    print("# 3-YEAR AGGREGATE")
    print("#" * 70)
    print_dim("[direction alignment of MOST-RECENT sweep vs trade]", sb, k_align)
    print_dim("[recency of validating sweep]", sb, k_recency)
    print_dim("[proximity of validating sweep to entry]", sb, k_prox)
    print_dim("[combined ICT 'bad setup' flag]", sb, k_badsetup)

    # ── Per-year for the headline (alignment) — regime check ──
    print("\n" + "#" * 70)
    print("# PER-YEAR — direction alignment (regime consistency check)")
    print("#" * 70)
    contrary_neg_years = 0
    for year in sorted(per_year.keys()):
        ys = [t for t in per_year[year] if t.get("strategy") == "silver_bullet"]
        print(f"\n--- {year} ---")
        print_dim(f"[{year}] alignment", ys, k_align)
        contrary = [t for t in ys if k_align(t) == "CONTRARY"]
        _, _, cpnl, _ = agg(contrary)
        if cpnl < 0:
            contrary_neg_years += 1

    # ── Verdict ──
    print("\n" + "=" * 70)
    print(" VERDICT")
    print("=" * 70)
    contrary_all = [t for t in sb if k_align(t) == "CONTRARY"]
    bad_all = [t for t in sb if k_badsetup(t) == "BAD (contrary/stale/far)"]
    _, cwr, cpnl, cavg = agg(contrary_all)
    _, bwr, bpnl, bavg = agg(bad_all)
    print(f"  CONTRARY-direction trades (3yr): n={len(contrary_all)} "
          f"WR={cwr:.1f}% P&L=${cpnl:+,.0f} avg=${cavg:+.0f}")
    print(f"     negative in {contrary_neg_years}/3 years")
    print(f"  'BAD setup' trades (3yr):        n={len(bad_all)} "
          f"WR={bwr:.1f}% P&L=${bpnl:+,.0f} avg=${bavg:+.0f}")
    print()
    if contrary_neg_years == 3 and cpnl < 0:
        print("  -> BUILD: contrary-sweep trades lose in all 3 regimes. A")
        print("     direction/recency gate (Option 1 or 3) is justified — "
              "implement behind a flag + run A/B cross-period.")
    elif cpnl > 0:
        print("  -> LEAVE: contrary-sweep trades are net-POSITIVE across 3yr.")
        print("     Another throw-out-winner — the sweep-direction 'gap' is "
              "not costing money. Do NOT gate.")
    else:
        print("  -> MIXED/regime-dependent. Inspect per-year + per-bucket "
              "before committing. Consider proximity-only or recency-only.")


if __name__ == "__main__":
    main()
