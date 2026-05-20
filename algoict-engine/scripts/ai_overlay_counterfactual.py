"""
scripts/ai_overlay_counterfactual.py
=====================================
Counterfactual P&L analysis for Camino C2 AI Overlay (SHADOW mode).

After 3+ weeks of shadow data accumulated in `ai_overlay_decisions`
Supabase table, run this script to compute:

  - Agreement rate (Claude vote vs what the bot did)
  - Asymmetry analysis (when Claude said skip, did the KZ lose?)
  - Counterfactual P&L (if bot had obeyed Claude's decisions)
  - Ship/kill recommendation based on counterfactual edge

Usage
-----
    python scripts/ai_overlay_counterfactual.py
    python scripts/ai_overlay_counterfactual.py --since 2026-05-20

Decision criteria (recap from CLAUDE.md):
  - SHIP to active mode if: counterfactual P&L > actual P&L by margin
    (e.g., +10%) over 3-week period
  - KILL feature if: Claude's calls would have hurt or been neutral
  - Mixed: refine prompt, extend shadow period

Sample size considerations:
  - 3 weeks = ~45-60 KZ entries. Tight statistical power.
  - 6 weeks = ~90-120 entries. Better confidence.
  - Earlier kill possible if pattern is overwhelmingly negative.

NOTE: This is a STUB. Fill in the actual Supabase + trades query
logic when shadow data starts arriving. The bot's `ai_overlay_decisions`
table is the source of truth.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--since",
        default=(datetime.now(timezone.utc) - timedelta(days=21)).strftime("%Y-%m-%d"),
        help="ISO date — analyze decisions since this date (default: 21 days ago)",
    )
    p.add_argument(
        "--export-csv",
        default=None,
        help="Optional: write per-decision table to this CSV path",
    )
    return p.parse_args()


def load_decisions(since_iso: str) -> list:
    """Load ai_overlay_decisions from Supabase since the given date."""
    # TODO: implement once shadow data is flowing.
    # Pseudo:
    #   from db.supabase_client import SupabaseClient
    #   client = SupabaseClient()
    #   rows = (client.client.table("ai_overlay_decisions")
    #           .select("*").gte("ts", since_iso).execute().data)
    #   return rows
    return []


def load_trades_for_kz(kz: str, day_iso: str) -> list:
    """Load actual trades for a given KZ on a given date."""
    # TODO: query `trades` table where kill_zone = kz and trade date = day_iso
    return []


def compute_counterfactual(decision: dict, trades: list) -> dict:
    """Given Claude's decision and actual KZ trades, compute hypothetical P&L."""
    actual_pnl = sum(float(t.get("pnl", 0)) for t in trades)
    actual_trades = len(trades)
    mult = float(decision.get("size_multiplier", 1.0))
    # Counterfactual: if Claude said skip → 0 trades, 0 P&L
    # If half → half the P&L (approximating proportional size scaling)
    # If fire → same as actual
    counterfactual_pnl = actual_pnl * mult
    return {
        "actual_kz_pnl": actual_pnl,
        "actual_kz_trades": actual_trades,
        "counterfactual_pnl": counterfactual_pnl,
        "delta": counterfactual_pnl - actual_pnl,
    }


def main():
    args = parse_args()
    print("=" * 78)
    print(f" AI OVERLAY COUNTERFACTUAL — since {args.since}")
    print("=" * 78)

    decisions = load_decisions(args.since)
    if not decisions:
        print("\nNo decisions found. Either:")
        print("  1. KZ_VALIDATOR_ENABLED is still False (shadow mode not yet on)")
        print("  2. The bot hasn't run since shadow was enabled")
        print("  3. Supabase table `ai_overlay_decisions` doesn't exist yet")
        print("     (run migration 0004_ai_overlay_decisions.sql)")
        print("\nThis script is a STUB. Will be completed once shadow data flows.")
        return 0

    # Per-decision analysis
    by_decision = {"fire": [], "skip": [], "half": []}
    for d in decisions:
        kz = d.get("kz", "")
        day = d.get("ts", "")[:10]  # 'YYYY-MM-DD'
        trades = load_trades_for_kz(kz, day)
        cf = compute_counterfactual(d, trades)
        d.update(cf)
        by_decision[d.get("decision", "fire")].append(d)

    # Summary
    total_actual = sum(d.get("actual_kz_pnl", 0) for d in decisions)
    total_counter = sum(d.get("counterfactual_pnl", 0) for d in decisions)
    delta = total_counter - total_actual
    pct = (delta / total_actual * 100) if total_actual else 0

    print(f"\nDecisions: {len(decisions)} total")
    print(f"  fire: {len(by_decision['fire'])}")
    print(f"  half: {len(by_decision['half'])}")
    print(f"  skip: {len(by_decision['skip'])}")
    print(f"\nActual KZ P&L:         ${total_actual:>+12,.2f}")
    print(f"Counterfactual P&L:    ${total_counter:>+12,.2f}")
    print(f"Delta (if obeyed):     ${delta:>+12,.2f} ({pct:+.1f}%)")

    # Per-decision-type breakdown
    print("\nBy decision type:")
    for dec_type, items in by_decision.items():
        if not items:
            continue
        n = len(items)
        act = sum(i.get("actual_kz_pnl", 0) for i in items)
        cf = sum(i.get("counterfactual_pnl", 0) for i in items)
        print(f"  {dec_type:<6} n={n:>3} actual=${act:>+10,.2f} "
              f"counterfactual=${cf:>+10,.2f} delta=${cf-act:>+8,.2f}")

    # Recommendation
    print("\nRecommendation:")
    if total_actual == 0:
        print("  Insufficient data (no realized P&L in sample).")
    elif pct >= 10:
        print(f"  SHIP to active mode — counterfactual {pct:+.1f}% > +10% threshold")
    elif pct >= -5:
        print(f"  HOLD — counterfactual {pct:+.1f}% within neutral band")
        print("  Extend shadow period for stronger signal.")
    else:
        print(f"  KILL feature — counterfactual {pct:+.1f}% < -5%")
        print("  Claude's decisions would have hurt P&L.")

    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
