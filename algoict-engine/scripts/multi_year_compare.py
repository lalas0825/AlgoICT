"""
scripts/multi_year_compare.py
==============================
Cross-year comparison of V8 walk-forward JSONs.

Reads yearly backtest JSONs matching a prefix pattern and prints a single
comparison table: year-by-year summary + rolling totals + per-KZ aggregate.

Usage:
    # Default: NQ (sb_v8_YYYY.json)
    python scripts/multi_year_compare.py

    # ES
    python scripts/multi_year_compare.py --pattern sb_v8_es_

    # YM
    python scripts/multi_year_compare.py --pattern sb_v8_ym_
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

ANALYSIS = Path("C:/AI Projects/AlgoICT/algoict-engine/analysis")


def extract_year_stats(path: Path) -> dict:
    data = json.loads(path.read_text())
    trades = data.get("trades", [])
    if not trades:
        return {"year": path.stem.split("_")[-1], "trades": 0}

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    bes = [t for t in trades if t["pnl"] == 0]
    gw = sum(t["pnl"] for t in wins)
    gl = sum(t["pnl"] for t in losses)
    pf = abs(gw / gl) if gl else float("inf")

    # Per day
    by_day = defaultdict(list)
    for t in trades:
        by_day[t["entry_time"][:10]].append(t)
    day_pnls = {d: sum(t["pnl"] for t in ts) for d, ts in by_day.items()}
    winning_days = sum(1 for p in day_pnls.values() if p > 0)
    losing_days = sum(1 for p in day_pnls.values() if p < 0)
    dll_breaches = sum(1 for p in day_pnls.values() if p <= -1000)

    # Per month
    by_month = defaultdict(list)
    for t in trades:
        by_month[t["entry_time"][:7]].append(t)
    monthly_pnls = {m: sum(t["pnl"] for t in ts) for m, ts in by_month.items()}
    positive_months = sum(1 for p in monthly_pnls.values() if p > 0)
    negative_months = sum(1 for p in monthly_pnls.values() if p < 0)

    # Per KZ
    by_kz = defaultdict(list)
    for t in trades:
        by_kz[t.get("kill_zone", "unknown")].append(t)
    kz_pnl = {k: sum(t["pnl"] for t in ts) for k, ts in by_kz.items()}
    kz_trades = {k: len(ts) for k, ts in by_kz.items()}
    kz_wr = {}
    for k, ts in by_kz.items():
        w = sum(1 for t in ts if t["pnl"] > 0)
        kz_wr[k] = w / len(ts) if ts else 0

    return {
        "year": path.stem.split("_")[-1],
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "bes": len(bes),
        "wr": len(wins) / len(trades),
        "pnl": sum(t["pnl"] for t in trades),
        "pf": pf,
        "avg_win": gw / len(wins) if wins else 0,
        "avg_loss": gl / len(losses) if losses else 0,
        "expectancy": sum(t["pnl"] for t in trades) / len(trades),
        "best_trade": max(t["pnl"] for t in trades),
        "worst_trade": min(t["pnl"] for t in trades),
        "max_dd": data.get("max_drawdown_dollars", 0),
        "peak_equity": data.get("peak_equity", 0),
        "combine_resets": data.get("combine_resets", 0),
        "trading_days": len(by_day),
        "winning_days": winning_days,
        "losing_days": losing_days,
        "dll_breaches": dll_breaches,
        "worst_day": min(day_pnls.values()) if day_pnls else 0,
        "best_day": max(day_pnls.values()) if day_pnls else 0,
        "positive_months": positive_months,
        "negative_months": negative_months,
        "kz_pnl": kz_pnl,
        "kz_trades": kz_trades,
        "kz_wr": kz_wr,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pattern", default="sb_v8_",
        help="Prefix for JSON files (default 'sb_v8_' = NQ; use 'sb_v8_es_' for ES)",
    )
    ap.add_argument("--label", default=None,
                    help="Label override for the header (e.g. 'NQ', 'ES')")
    args = ap.parse_args()

    # Build glob: prefix + 4-digit-year + .json
    # NQ:   sb_v8_YYYY.json  -> stem parts: [sb, v8, YYYY]
    # ES:   sb_v8_es_YYYY.json -> stem parts: [sb, v8, es, YYYY]
    paths = sorted(ANALYSIS.glob(f"{args.pattern}*.json"))
    # Filter: stem ends with 4-digit year AND exact prefix match (so "sb_v8_"
    # doesn't accidentally include "sb_v8_es_").
    def _is_yearly(p: Path) -> bool:
        last = p.stem.split("_")[-1]
        if not (last.isdigit() and len(last) == 4):
            return False
        # Ensure the file's stem starts with pattern exactly
        expected = args.pattern.rstrip("_") + "_" + last
        return p.stem == expected
    paths = [p for p in paths if _is_yearly(p)]

    if not paths:
        print(f"No yearly JSONs found matching pattern '{args.pattern}*YYYY.json'")
        return

    # Infer label if not set
    label = args.label
    if not label:
        if args.pattern == "sb_v8_":
            label = "NQ"
        elif "es" in args.pattern.lower():
            label = "ES"
        elif "ym" in args.pattern.lower():
            label = "YM"
        else:
            label = args.pattern.strip("_")

    stats = [extract_year_stats(p) for p in paths]

    # ═══ Summary table ══════════════════════════════════════════════════
    print("=" * 112)
    print(f"  V8 SILVER BULLET {label} — CROSS-YEAR COMPARISON ({len(paths)} years walk-forward)")
    print("=" * 112)
    print(f"  {'Year':5} {'Trades':>6} {'WR':>6} {'P&L':>12} {'PF':>6} "
          f"{'AvgW':>7} {'AvgL':>7} {'Expec':>7} {'MaxDD':>8} {'Resets':>7} "
          f"{'+Days':>6} {'-Days':>6} {'DLL':>4}")
    print("  " + "-" * 108)
    totals = defaultdict(float)
    for s in stats:
        if s["trades"] == 0:
            print(f"  {s['year']:5}  (no trades)")
            continue
        print(f"  {s['year']:5} {s['trades']:>6} {s['wr']:>5.1%} "
              f"${s['pnl']:>10,.0f} {s['pf']:>6.2f} "
              f"${s['avg_win']:>5,.0f} ${s['avg_loss']:>5,.0f} "
              f"${s['expectancy']:>5,.0f} ${s['max_dd']:>6,.0f} "
              f"{s['combine_resets']:>7} {s['winning_days']:>6} "
              f"{s['losing_days']:>6} {s['dll_breaches']:>4}")
        totals["trades"] += s["trades"]
        totals["wins"] += s["wins"]
        totals["losses"] += s["losses"]
        totals["pnl"] += s["pnl"]
        totals["combine_resets"] += s["combine_resets"]
        totals["trading_days"] += s["trading_days"]
        totals["winning_days"] += s["winning_days"]
        totals["losing_days"] += s["losing_days"]
        totals["dll_breaches"] += s["dll_breaches"]
        totals["positive_months"] += s["positive_months"]
        totals["negative_months"] += s["negative_months"]
    print("  " + "-" * 108)
    avg_wr = totals["wins"] / totals["trades"] if totals["trades"] else 0
    # Aggregate PF across years
    agg_gw = sum(s.get("avg_win", 0) * s.get("wins", 0) for s in stats)
    agg_gl = sum(s.get("avg_loss", 0) * s.get("losses", 0) for s in stats)
    agg_pf = abs(agg_gw / agg_gl) if agg_gl else 0
    print(f"  {'AGG':5} {int(totals['trades']):>6} {avg_wr:>5.1%} "
          f"${totals['pnl']:>10,.0f} {agg_pf:>6.2f} "
          f"{'':>7} {'':>7} "
          f"${totals['pnl']/totals['trades']:>5,.0f} {'':>8} "
          f"{int(totals['combine_resets']):>7} "
          f"{int(totals['winning_days']):>6} "
          f"{int(totals['losing_days']):>6} "
          f"{int(totals['dll_breaches']):>4}")
    print()

    # ═══ Monthly consistency ════════════════════════════════════════════
    total_months = totals["positive_months"] + totals["negative_months"]
    month_hit = totals["positive_months"] / total_months if total_months else 0
    day_hit = totals["winning_days"] / totals["trading_days"] if totals["trading_days"] else 0
    print(f"  Monthly  positive : {int(totals['positive_months'])}/"
          f"{int(total_months)} = {month_hit:.1%}")
    print(f"  Daily    positive : {int(totals['winning_days'])}/"
          f"{int(totals['trading_days'])} = {day_hit:.1%}")
    print(f"  DLL breach days   : {int(totals['dll_breaches'])}/"
          f"{int(totals['trading_days'])} = "
          f"{totals['dll_breaches']/totals['trading_days']:.2%}")
    print()

    # ═══ Per-KZ across all years ════════════════════════════════════════
    print("=" * 112)
    print("  KILL ZONE AGGREGATE (all years combined)")
    print("=" * 112)
    kz_agg = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for s in stats:
        for kz in ("london", "ny_am", "ny_pm"):
            if kz not in s["kz_trades"]:
                continue
            kz_agg[kz]["trades"] += s["kz_trades"][kz]
            kz_agg[kz]["pnl"] += s["kz_pnl"][kz]
            kz_agg[kz]["wins"] += int(s["kz_wr"][kz] * s["kz_trades"][kz])

    total_pnl = totals["pnl"]
    print(f"  {'KZ':10} {'Trades':>7} {'Wins':>5} {'WR':>6} "
          f"{'P&L':>14} {'% of total':>11}")
    print("  " + "-" * 80)
    for kz in ("london", "ny_am", "ny_pm"):
        if kz not in kz_agg:
            continue
        agg = kz_agg[kz]
        wr = agg["wins"] / agg["trades"] if agg["trades"] else 0
        pct = agg["pnl"] / total_pnl * 100 if total_pnl else 0
        print(f"  {kz:10} {agg['trades']:>7} {agg['wins']:>5} {wr:>6.1%} "
              f"${agg['pnl']:>12,.0f} {pct:>10.1f}%")
    print()

    # ═══ Per-KZ per-year ═══════════════════════════════════════════════
    print("=" * 112)
    print("  KILL ZONE P&L PER YEAR")
    print("=" * 112)
    print(f"  {'Year':5} {'London':>14} {'NY AM':>14} {'NY PM':>14}  [Best KZ]")
    print("  " + "-" * 80)
    for s in stats:
        if s["trades"] == 0:
            continue
        l = s["kz_pnl"].get("london", 0)
        a = s["kz_pnl"].get("ny_am", 0)
        p = s["kz_pnl"].get("ny_pm", 0)
        pairs = [("london", l), ("ny_am", a), ("ny_pm", p)]
        best = max(pairs, key=lambda x: x[1])
        print(f"  {s['year']:5} ${l:>12,.0f} ${a:>12,.0f} ${p:>12,.0f}  [{best[0]}]")
    print()

    # ═══ Variance / consistency ═════════════════════════════════════════
    annual_pnls = [s["pnl"] for s in stats if s["trades"] > 0]
    if len(annual_pnls) > 1:
        print("=" * 112)
        print("  CONSISTENCY METRICS")
        print("=" * 112)
        print(f"  Mean annual P&L   : ${mean(annual_pnls):,.0f}")
        print(f"  Median annual P&L : ${sorted(annual_pnls)[len(annual_pnls)//2]:,.0f}")
        print(f"  Std dev annual    : ${stdev(annual_pnls):,.0f}")
        print(f"  Best year         : ${max(annual_pnls):,.0f}")
        print(f"  Worst year        : ${min(annual_pnls):,.0f}")
        neg_years = sum(1 for p in annual_pnls if p < 0)
        print(f"  Negative years    : {neg_years}/{len(annual_pnls)}")
        print()


if __name__ == "__main__":
    main()
