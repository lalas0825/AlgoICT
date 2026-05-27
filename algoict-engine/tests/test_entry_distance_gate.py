"""Tests for SB_MAX_ENTRY_DISTANCE_PCT gate (Fix A, 2026-05-27).

Forensic origin: Wed 5/27 NY AM. Bot fired SHORT @ 30,328.75 with current
price at 30,016.75 (312pts = 1.04% away). Limit placed at a 2h-old FVG
formed during earlier bull regime; market had since flipped bearish (3 BOS
bear in 10 min before the fire). Limit had ~5-10% probability of fill.

The closer FVGs at current price had stop_pts < 15pt floor, so the bot
fell back to the stale far FVG. This gate prevents that pattern.
"""
import pandas as pd
import pytest


def _evaluate_distance_gate(
    *,
    max_pct: float,
    entry_price: float,
    current_price: float,
) -> dict:
    """Pure-function mirror of the gate in silver_bullet.py.

    Returns dict with `rejected` (bool), `reason` (str), `dist_pct` (float).
    """
    if max_pct <= 0 or current_price <= 0:
        return {"rejected": False, "reason": "disabled", "dist_pct": None}
    dist_pct = abs(entry_price - current_price) / current_price * 100.0
    if dist_pct > max_pct:
        return {"rejected": True, "reason": "entry_too_far", "dist_pct": dist_pct}
    return {"rejected": False, "reason": "within_band", "dist_pct": dist_pct}


# ───────────────────────────────────────────────────────────────────────
# Gate disabled when max_pct <= 0
# ───────────────────────────────────────────────────────────────────────

class TestGateDisabled:

    def test_zero_pct_disables(self):
        out = _evaluate_distance_gate(
            max_pct=0.0,
            entry_price=30328.75,
            current_price=30016.75,
        )
        assert not out["rejected"]
        assert out["reason"] == "disabled"

    def test_negative_pct_disables(self):
        out = _evaluate_distance_gate(
            max_pct=-1.0,
            entry_price=30328.75,
            current_price=30016.75,
        )
        assert not out["rejected"]

    def test_zero_current_price_disables(self):
        """Defensive: if last_close == 0 we can't compute distance."""
        out = _evaluate_distance_gate(
            max_pct=1.0,
            entry_price=30000.0,
            current_price=0.0,
        )
        assert not out["rejected"]


# ───────────────────────────────────────────────────────────────────────
# Gate enabled — typical thresholds
# ───────────────────────────────────────────────────────────────────────

class TestGateEnabled:

    def test_forensic_wed_5_27_blocked(self):
        """Reproduces the Wed 5/27 NY AM WTF trade.
        Entry 30,328.75 vs current 30,016.75 = 1.04% away. Default 1.0%
        threshold should REJECT this exact case."""
        out = _evaluate_distance_gate(
            max_pct=1.0,
            entry_price=30328.75,
            current_price=30016.75,
        )
        assert out["rejected"]
        assert out["reason"] == "entry_too_far"
        assert out["dist_pct"] == pytest.approx(1.039, abs=0.01)

    def test_within_band_passes(self):
        """Entry within 0.5% of price — passes."""
        out = _evaluate_distance_gate(
            max_pct=1.0,
            entry_price=30050.0,
            current_price=30000.0,
        )
        assert not out["rejected"]
        assert out["reason"] == "within_band"
        assert out["dist_pct"] == pytest.approx(0.167, abs=0.01)

    def test_at_boundary_passes(self):
        """Exactly at threshold passes (strict > test)."""
        # 1.0% of 30000 = 300 pts
        out = _evaluate_distance_gate(
            max_pct=1.0,
            entry_price=30300.0,
            current_price=30000.0,
        )
        assert not out["rejected"]
        assert out["dist_pct"] == pytest.approx(1.0, abs=0.0001)

    def test_slightly_over_boundary_rejected(self):
        """0.001% over threshold = reject."""
        out = _evaluate_distance_gate(
            max_pct=1.0,
            entry_price=30300.30,
            current_price=30000.0,
        )
        assert out["rejected"]

    def test_short_side_symmetric(self):
        """Distance computed via abs(), so SHORT setup (entry above price)
        and LONG setup (entry below price) are treated identically."""
        # SHORT: entry above
        out_short = _evaluate_distance_gate(
            max_pct=1.0,
            entry_price=30350.0,
            current_price=30000.0,
        )
        # LONG: entry below
        out_long = _evaluate_distance_gate(
            max_pct=1.0,
            entry_price=29650.0,
            current_price=30000.0,
        )
        assert out_short["rejected"] and out_long["rejected"]
        # Both ~1.167% away
        assert abs(out_short["dist_pct"] - out_long["dist_pct"]) < 0.01


# ───────────────────────────────────────────────────────────────────────
# Custom thresholds
# ───────────────────────────────────────────────────────────────────────

class TestCustomThresholds:

    def test_tight_threshold_0_5pct(self):
        """0.5% threshold = ~150pts. 312pt distance (Wed forensic) blocked."""
        out = _evaluate_distance_gate(
            max_pct=0.5,
            entry_price=30328.75,
            current_price=30016.75,
        )
        assert out["rejected"]

    def test_loose_threshold_2pct(self):
        """2% threshold = ~600pts. 312pt distance passes."""
        out = _evaluate_distance_gate(
            max_pct=2.0,
            entry_price=30328.75,
            current_price=30016.75,
        )
        assert not out["rejected"]

    def test_typical_close_setup_always_passes(self):
        """Normal SB setup: entry within 15pts of price (typical FVG entry
        distance after a sweep). Passes for 0.5%+ thresholds. At very tight
        thresholds (0.05%, etc.) even normal setups can fail — that's by
        design, ultra-tight users may want to disable the gate."""
        # 15pts on 29,000 = 0.052% — passes 0.1%+ easily
        for max_pct in (0.1, 0.5, 1.0, 2.0):
            out = _evaluate_distance_gate(
                max_pct=max_pct,
                entry_price=29015.0,
                current_price=29000.0,
            )
            assert not out["rejected"], f"Should pass at threshold {max_pct}%"

    def test_30pt_setup_blocked_at_extra_tight(self):
        """30pt entry distance = 0.103% on MNQ@29K. Blocked at 0.1%
        threshold but passes at 0.5% (default). Documents the boundary."""
        out_tight = _evaluate_distance_gate(
            max_pct=0.1,
            entry_price=29030.0,
            current_price=29000.0,
        )
        assert out_tight["rejected"]
        out_default = _evaluate_distance_gate(
            max_pct=1.0,
            entry_price=29030.0,
            current_price=29000.0,
        )
        assert not out_default["rejected"]


# ───────────────────────────────────────────────────────────────────────
# Config integration — verify default is active
# ───────────────────────────────────────────────────────────────────────

class TestConfigDefault:

    def test_default_is_active(self):
        """Ship-active default — 1.0% gate enabled out of the box."""
        import config
        max_pct = float(config.cfg("SB_MAX_ENTRY_DISTANCE_PCT", 0.0))
        assert max_pct == 1.0

    def test_default_blocks_wed_5_27_forensic(self):
        """With default config, the Wed 5/27 trade WOULD be blocked."""
        import config
        max_pct = float(config.cfg("SB_MAX_ENTRY_DISTANCE_PCT", 0.0))
        out = _evaluate_distance_gate(
            max_pct=max_pct,
            entry_price=30328.75,
            current_price=30016.75,
        )
        assert out["rejected"]
