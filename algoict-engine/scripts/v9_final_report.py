"""
scripts/v9_final_report.py
===========================
Master comparison V8 vs V9 across all 7 years + combine sim.
Writes a detailed markdown report to analysis/V9_FINAL_REPORT_2026_04_23.md.

Assumes:
  - sb_v8_YYYY.json for 2019-2025 (NQ baseline)
  - sb_v9_session_recency_YYYY.json for 2019-2025 (V9 NQ)
  - combine_sim_nq_7yr.log (V8)
  - combine_sim_nq_v9_7yr.log (V9 — this script runs it if missing)
"""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

ROOT = Path("C:/AI Projects/AlgoICT/algoict-engine")
ANALYSIS = ROOT / "analysis"
YEARS = list(range(2019, 2026))


def _load(prefix: str, year: int):
    path = ANALYSIS / f"{prefix}_{year}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _stats(data):
    if not data:
        return None
    trades = data["trades"]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gw = sum(t["pnl"] for t in wins)
    gl = sum(t["pnl"] for t in losses)
    return dict(
        n=len(trades),
        wins=len(wins), losses=len(losses),
        wr=len(wins) / len(trades) if trades else 0,
        pnl=data.get("total_pnl", sum(t["pnl"] for t in trades)),
        pf=abs(gw / gl) if gl else float("inf"),
        avg_w=gw / len(wins) if wins else 0,
        avg_l=gl / len(losses) if losses else 0,
        max_dd=data.get("max_drawdown_dollars", 0),
        resets=data.get("combine_resets", 0),
    )


def _run_combine_sim():
    """Run NQ V9 combine sim if not already done."""
    target = ANALYSIS / "combine_sim_nq_v9_7yr.log"
    if target.exists() and target.stat().st_size > 500:
        return
    args = ["C:/Python314/python.exe", "-u", "scripts/combine_simulator.py", "--multi"]
    for y in YEARS:
        args.append(f"{y}:analysis/sb_v9_session_recency_{y}.json")
    args += ["--attempts", "30"]
    with open(target, "wb") as out:
        subprocess.run(args, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)


def _parse_combine_sim(path: Path):
    if not path.exists():
        return {}
    lines = path.read_text(errors="ignore").splitlines()
    years = {}
    current_year = None
    for line in lines:
        line = line.strip()
        if "=== Year" in line:
            try:
                current_year = int(line.split("Year")[1].strip().split()[0])
                years[current_year] = {}
            except Exception:
                current_year = None
        elif current_year and "PASS:" in line:
            try:
                years[current_year]["pass"] = int(line.split("PASS:")[1].split()[0])
            except Exception:
                pass
        elif current_year and "FAIL_MLL" in line:
            try:
                years[current_year]["fail_mll"] = int(line.split(":")[1].split()[0])
            except Exception:
                pass
        elif current_year and "FAIL_DLL" in line:
            try:
                years[current_year]["fail_dll"] = int(line.split(":")[1].split()[0])
            except Exception:
                pass
        elif "AGGREGATE" in line:
            current_year = "AGG"
            years["AGG"] = {}
        elif current_year == "AGG" and "Total PASSES:" in line:
            try:
                parts = line.split("Total PASSES:")[1].strip().split()
                years["AGG"]["pass"] = int(parts[0])
                years["AGG"]["total"] = int(parts[2])
            except Exception:
                pass
    return years


def main():
    # Run combine sim if missing
    _run_combine_sim()

    v8 = {y: _stats(_load("sb_v8", y)) for y in YEARS}
    v9 = {y: _stats(_load("sb_v9_session_recency", y)) for y in YEARS}

    cs_v8 = _parse_combine_sim(ANALYSIS / "combine_sim_nq_7yr.log")
    cs_v9 = _parse_combine_sim(ANALYSIS / "combine_sim_nq_v9_7yr.log")

    out = []
    out.append(f"# V9 (Session Recency Fix) Final Report — NQ 7-Year Walk-Forward")
    out.append(f"\n> Generated 2026-04-23 autonomous run")
    out.append(f"> Bug A fix: structure detector rejects stale (pre-today) events")
    out.append(f"> Bug B fix: phantom cleanup respects LIMIT_ORDER_TTL_BARS + KZ-awareness")
    out.append(f"> Bug C fix: KZ-aware TTL extends through KZ window")
    out.append(f"\n---\n\n## Executive summary\n")

    # Aggregate numbers
    v8_pnl = sum(s["pnl"] for s in v8.values() if s)
    v9_pnl = sum(s["pnl"] for s in v9.values() if s)
    v8_trades = sum(s["n"] for s in v8.values() if s)
    v9_trades = sum(s["n"] for s in v9.values() if s)
    v8_wins = sum(s["wins"] for s in v8.values() if s)
    v9_wins = sum(s["wins"] for s in v9.values() if s)
    v8_losses = sum(s["losses"] for s in v8.values() if s)
    v9_losses = sum(s["losses"] for s in v9.values() if s)
    v8_wr = v8_wins / v8_trades if v8_trades else 0
    v9_wr = v9_wins / v9_trades if v9_trades else 0
    v8_resets = sum(s["resets"] for s in v8.values() if s)
    v9_resets = sum(s["resets"] for s in v9.values() if s)
    negative_v8 = sum(1 for s in v8.values() if s and s["pnl"] < 0)
    negative_v9 = sum(1 for s in v9.values() if s and s["pnl"] < 0)

    out.append(f"| Metric | V8 baseline | V9 recency | Delta |")
    out.append(f"|--------|-------------|------------|-------|")
    out.append(f"| Total trades 7y | {v8_trades:,} | {v9_trades:,} | {v9_trades-v8_trades:+,} ({(v9_trades/v8_trades-1)*100:+.1f}%) |")
    out.append(f"| Total P&L 7y | ${v8_pnl:,.0f} | ${v9_pnl:,.0f} | ${v9_pnl-v8_pnl:+,.0f} ({(v9_pnl/v8_pnl-1)*100:+.1f}%) |")
    out.append(f"| Aggregate WR | {v8_wr:.1%} | {v9_wr:.1%} | {(v9_wr-v8_wr)*100:+.1f}pp |")
    out.append(f"| Combine resets total | {v8_resets} | {v9_resets} | {v9_resets-v8_resets:+d} |")
    out.append(f"| Negative years | {negative_v8}/7 | {negative_v9}/7 | — |")
    out.append(f"| Combine sim pass rate | {cs_v8.get('AGG', {}).get('pass', '?')}/{cs_v8.get('AGG', {}).get('total', '?')} | {cs_v9.get('AGG', {}).get('pass', '?')}/{cs_v9.get('AGG', {}).get('total', '?')} | — |")
    out.append(f"\n## Per-year detail\n")
    out.append(f"| Year | Version | Trades | WR | P&L | PF | MaxDD | Resets |")
    out.append(f"|------|---------|--------|-----|------|------|-------|--------|")
    for y in YEARS:
        v8s = v8.get(y)
        v9s = v9.get(y)
        if v8s:
            out.append(f"| {y} | V8 | {v8s['n']:,} | {v8s['wr']:.1%} | ${v8s['pnl']:,.0f} | {v8s['pf']:.2f} | ${v8s['max_dd']:,.0f} | {v8s['resets']} |")
        if v9s:
            delta = ""
            if v8s:
                d_pnl = v9s['pnl'] - v8s['pnl']
                delta = f" ({'+' if d_pnl>=0 else ''}${d_pnl:,.0f})"
            out.append(f"| {y} | V9 | {v9s['n']:,} | {v9s['wr']:.1%} | ${v9s['pnl']:,.0f}{delta} | {v9s['pf']:.2f} | ${v9s['max_dd']:,.0f} | {v9s['resets']} |")

    out.append(f"\n## Combine simulator — 210 attempts per version\n")
    out.append(f"| Year | V8 pass | V9 pass | Delta |")
    out.append(f"|------|---------|---------|-------|")
    for y in YEARS:
        v8p = cs_v8.get(y, {}).get("pass", "—")
        v9p = cs_v9.get(y, {}).get("pass", "—")
        try:
            delta = f"{v9p - v8p:+d}"
        except Exception:
            delta = "—"
        out.append(f"| {y} | {v8p} | {v9p} | {delta} |")
    out.append(f"| **AGG** | **{cs_v8.get('AGG',{}).get('pass','?')}/{cs_v8.get('AGG',{}).get('total','?')}** | **{cs_v9.get('AGG',{}).get('pass','?')}/{cs_v9.get('AGG',{}).get('total','?')}** | — |")

    report_path = ANALYSIS / "V9_FINAL_REPORT_2026_04_23.md"
    report_path.write_text("\n".join(out))
    print(f"Report written: {report_path}")

    # Also print to stdout
    print("\n".join(out))


if __name__ == "__main__":
    main()
