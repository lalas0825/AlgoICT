"""
v14 walk-forward aggregator + combine summary.

Loads `analysis/sb_v14_<year>.json` for all 7 years (2019-2025) and:
  1. Aggregates yearly metrics (trades, WR, P&L, PF, Max DD, resets)
  2. Runs simulate_combine() on each year's trades for pass-rate
  3. Compares against the v8 baseline in CLAUDE.md
  4. Prints markdown-friendly summary

Usage:  python scripts/v14_aggregate_report.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from backtest.combine_simulator import simulate_combine


# v8 baseline from CLAUDE.md (2026-04-24 snapshot)
V8_BASELINE = {
    2019: {"trades": 2110, "wr": 0.431, "pnl": 70028, "pf": 1.68, "dd": 3030, "resets": 10},
    2020: {"trades": 2049, "wr": 0.437, "pnl": 92203, "pf": 1.84, "dd": 5813, "resets": 10},
    2021: {"trades": 1916, "wr": 0.407, "pnl": 110598, "pf": 2.06, "dd": 5790, "resets": 12},
    2022: {"trades": 2101, "wr": 0.448, "pnl": 103804, "pf": 2.01, "dd": 3810, "resets": 8},
    2023: {"trades": 1991, "wr": 0.453, "pnl": 91062, "pf": 1.88, "dd": 4261, "resets": 8},
    2024: {"trades": 2067, "wr": 0.441, "pnl": 115547, "pf": 2.05, "dd": 3864, "resets": 7},
    2025: {"trades": 1952, "wr": 0.449, "pnl": 89759, "pf": 1.86, "dd": 3032, "resets": 9},
}


def load_year(year: int) -> dict | None:
    path = ENGINE_ROOT / "analysis" / f"sb_v14_{year}_full.json" if year == 2025 else ENGINE_ROOT / "analysis" / f"sb_v14_{year}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def metrics(d: dict) -> dict:
    trades = d.get("trades", [])
    gross_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    return {
        "trades": len(trades),
        "wr": d.get("win_rate", 0),
        "pnl": d.get("total_pnl", 0),
        "pf": pf,
        "dd": d.get("max_drawdown_dollars", 0),
        "resets": d.get("combine_resets", 0),
        "raw_trades": trades,
    }


def fmt_year_row(year: int, v14: dict, v8: dict | None) -> str:
    if v8:
        delta_pnl = v14["pnl"] - v8["pnl"]
        delta_wr = (v14["wr"] - v8["wr"]) * 100
        return (
            f"| {year} | {v14['trades']:>5,} ({v14['trades']-v8['trades']:+d}) | "
            f"{v14['wr']*100:5.1f}% ({delta_wr:+.1f}pp) | "
            f"${v14['pnl']:>+10,.0f} ({delta_pnl:+,.0f}) | "
            f"{v14['pf']:.2f} ({v14['pf']-v8['pf']:+.2f}) | "
            f"${v14['dd']:>5,.0f} | {v14['resets']:>2} ({v14['resets']-v8['resets']:+d}) |"
        )
    return f"| {year} | {v14['trades']:>5,} | {v14['wr']*100:5.1f}% | ${v14['pnl']:>+10,.0f} | {v14['pf']:.2f} | ${v14['dd']:>5,.0f} | {v14['resets']:>2} |"


def run_combine_for_trades(trades: list[dict]) -> dict:
    """Run simulate_combine on a year's worth of trades."""
    # Convert raw dicts to a Trade-like protocol expected by simulate_combine.
    # The simulator iterates entry_time and uses pnl, so a SimpleNamespace wrapper works.
    from types import SimpleNamespace
    wrapped = []
    for t in trades:
        ns = SimpleNamespace(
            entry_time=t.get("entry_time", ""),
            exit_time=t.get("exit_time", ""),
            pnl=float(t.get("pnl", 0)),
            symbol=t.get("symbol", ""),
            kill_zone=t.get("kill_zone", ""),
            strategy=t.get("strategy", ""),
            direction=t.get("direction", ""),
        )
        wrapped.append(ns)
    try:
        result = simulate_combine(wrapped)
        return {
            "passed": getattr(result, "passed", False),
            "balance_final": getattr(result, "balance_final", 0),
            "max_balance": getattr(result, "max_balance", 0),
            "min_balance": getattr(result, "min_balance", 0),
            "breach_reason": getattr(result, "breach_reason", ""),
            "trading_days": getattr(result, "trading_days", 0),
        }
    except Exception as exc:
        return {"passed": False, "error": str(exc)}


def main() -> int:
    print("# v14 Walk-Forward Aggregate Report")
    print()

    years = sorted(V8_BASELINE.keys())
    yearly_v14 = {}
    for year in years:
        d = load_year(year)
        if d is None:
            print(f"  [WARN]  {year}: v14 JSON not found yet")
            continue
        yearly_v14[year] = metrics(d)

    if not yearly_v14:
        print("No v14 results available yet. Run run_v14_walkforward.ps1 first.")
        return 1

    # Header
    print()
    print("## Yearly comparison (v14 vs v8 baseline)")
    print()
    print("| Year | Trades (vs) | WR (vs) | P&L (vs) | PF (vs) | MaxDD | Resets (vs) |")
    print("|------|-----------|--------|---------|--------|-------|-----------|")
    for year in years:
        v14 = yearly_v14.get(year)
        if v14:
            print(fmt_year_row(year, v14, V8_BASELINE.get(year)))

    # Aggregates
    total_trades = sum(v["trades"] for v in yearly_v14.values())
    total_pnl = sum(v["pnl"] for v in yearly_v14.values())
    total_resets = sum(v["resets"] for v in yearly_v14.values())
    avg_wr = sum(v["wr"] for v in yearly_v14.values()) / len(yearly_v14)
    avg_pf = sum(v["pf"] for v in yearly_v14.values()) / len(yearly_v14)
    v8_total_pnl = sum(V8_BASELINE[y]["pnl"] for y in yearly_v14.keys())

    print()
    print("## Aggregate (all years available)")
    print()
    print(f"- Years covered:       {sorted(yearly_v14.keys())}")
    print(f"- Total trades:        {total_trades:,}")
    print(f"- Total P&L (v14):     ${total_pnl:+,.0f}")
    print(f"- Total P&L (v8 ref):  ${v8_total_pnl:+,.0f}")
    print(f"- vs vs v8:             ${total_pnl - v8_total_pnl:+,.0f}")
    print(f"- Mean WR:             {avg_wr*100:.2f}%")
    print(f"- Mean PF:             {avg_pf:.2f}")
    print(f"- Total combine resets: {total_resets}")

    # Combine simulator per-year
    print()
    print("## Combine simulator per year")
    print()
    print("| Year | Combine passed | Final balance | Max balance | Trading days | Breach |")
    print("|------|----------------|---------------|-------------|--------------|--------|")
    for year, v14 in yearly_v14.items():
        c = run_combine_for_trades(v14["raw_trades"])
        if "error" in c:
            print(f"| {year} | [WARN] ERROR | — | — | — | {c['error'][:50]} |")
            continue
        passed = "[PASS]" if c["passed"] else "[FAIL]"
        breach = c.get("breach_reason", "") or "—"
        print(
            f"| {year} | {passed} | ${c.get('balance_final', 0):,.0f} | "
            f"${c.get('max_balance', 0):,.0f} | {c.get('trading_days', 0)} | {breach} |"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
