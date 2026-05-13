"""
strategies/opportunity_replace.py
=================================
Pure decision functions for the "opportunity replacement" feature.

When the bot has a pending limit order that hasn't filled yet, and a NEW
signal fires, these functions decide whether to:
  - REPLACE the pending limit with the new signal (Tier 1, 2, 2.5)
  - AUTO-CANCEL the pending limit (Tier 1.5)
  - SUPPRESS the new signal (existing single-position rule)

All functions are pure: take dicts/values, return decisions. No I/O,
no state mutation. Easy to unit-test.

Tier definitions (from 2026-05-13 Day 8 audit):
  Tier 1   — Opposite direction → always replace (bias flip)
  Tier 2   — Same direction, materially closer (≥X% closer AND ≥Ypt) → replace
  Tier 2.5 — Stale aging: pending >N bars → priority decays, easier to replace
  Tier 1.5 — Bias-flip auto-cancel: opposite CHoCH/MSS post-signal → cancel
"""

from __future__ import annotations

from typing import Any, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


def should_replace_pending(
    new_signal: Any,
    pending: dict,
    current_price: float,
    bars_pending: int = 0,
) -> tuple[bool, str]:
    """
    Decide whether `new_signal` should REPLACE the existing `pending` limit.

    Returns
    -------
    (replace: bool, reason: str)
        replace=True → cancel pending, take new_signal
        reason → human-readable rationale (for logging/telemetry)
    """
    if not bool(config.cfg("OPPORTUNITY_REPLACE_ENABLED", True)):
        return False, "feature_disabled"

    # Pull pending direction. Backtester uses dict["direction"]; live main.py
    # nests it under pending["signal"].direction.
    pending_direction = (
        pending.get("direction")
        or getattr(pending.get("signal"), "direction", None)
    )
    pending_entry_price = (
        pending.get("limit_price")
        or pending.get("entry_price")
        or getattr(pending.get("signal"), "entry_price", None)
    )
    if pending_direction is None or pending_entry_price is None:
        return False, "pending_missing_fields"

    pending_entry_price = float(pending_entry_price)
    new_direction = new_signal.direction
    new_entry_price = float(new_signal.entry_price)

    # ── TIER 1: Opposite direction → always replace ──────────────
    if new_direction != pending_direction:
        return True, (
            f"tier1_opposite_direction "
            f"(pending={pending_direction} → new={new_direction})"
        )

    # Same direction from here on
    pending_dist = abs(current_price - pending_entry_price)
    new_dist = abs(current_price - new_entry_price)

    # ── TIER 2.5: Stale aging → most signals beat stale pending ──
    stale_threshold = int(config.cfg("STALE_LIMIT_BARS", 10))
    if bars_pending >= stale_threshold:
        # Stale: replace if new is ANY closer (or equal distance with newer FVG)
        if new_dist <= pending_dist:
            return True, (
                f"tier2.5_stale_aging "
                f"(bars_pending={bars_pending}≥{stale_threshold}, "
                f"new_dist={new_dist:.1f}pt ≤ pending_dist={pending_dist:.1f}pt)"
            )

    # ── TIER 2: Materially closer fill probability ───────────────
    proximity_pct = float(config.cfg("REPLACE_MIN_PROXIMITY_PCT", 0.70))
    proximity_pts = float(config.cfg("REPLACE_MIN_PROXIMITY_PTS", 5.0))
    if (
        pending_dist > 0
        and new_dist < pending_dist * proximity_pct
        and (pending_dist - new_dist) >= proximity_pts
    ):
        return True, (
            f"tier2_closer_fill "
            f"(new_dist={new_dist:.1f}pt < {proximity_pct:.0%}×{pending_dist:.1f}={pending_dist*proximity_pct:.1f}pt "
            f"and ≥{proximity_pts:.0f}pt closer)"
        )

    return False, "no_replacement_criteria_met"


def should_autocancel_pending(
    pending: dict,
    structure_events: list,
    pending_signal_ts: Any,
) -> tuple[bool, str]:
    """
    Decide whether `pending` should be PROACTIVELY CANCELLED (no new signal needed).

    Currently implements:
      - TIER 1.5: opposite-direction 5min CHoCH/MSS event registered AFTER
        the pending was placed → structural thesis dead, cancel.

    Returns
    -------
    (cancel: bool, reason: str)
    """
    if not bool(config.cfg("OPPORTUNITY_REPLACE_ENABLED", True)):
        return False, "feature_disabled"
    if not bool(config.cfg("AUTOCANCEL_ON_BIAS_FLIP", True)):
        return False, "autocancel_disabled"

    pending_direction = (
        pending.get("direction")
        or getattr(pending.get("signal"), "direction", None)
    )
    if pending_direction is None:
        return False, "pending_missing_direction"

    # Map trade direction ↔ structure-event direction
    # Trade direction: "long" / "short"  (or "bullish" / "bearish" if signal)
    # Struct event direction: "bullish" / "bearish"
    if pending_direction in ("long", "bullish"):
        pending_dir_struct = "bullish"
        opposite_dir = "bearish"
    else:
        pending_dir_struct = "bearish"
        opposite_dir = "bullish"

    # Find any opposite-direction CHoCH/MSS that fired AFTER pending was placed.
    for ev in structure_events:
        if getattr(ev, "timeframe", None) != "5min":
            continue
        if getattr(ev, "type", None) not in ("CHoCH", "MSS"):
            continue
        if getattr(ev, "direction", None) != opposite_dir:
            continue
        ev_ts = getattr(ev, "timestamp", None)
        if ev_ts is None or pending_signal_ts is None:
            continue
        if ev_ts > pending_signal_ts:
            return True, (
                f"tier1.5_bias_flip "
                f"(opposite {ev.type} {opposite_dir} @ {ev_ts} "
                f"after pending @ {pending_signal_ts})"
            )

    return False, "no_autocancel_trigger"
