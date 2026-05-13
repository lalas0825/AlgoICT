"""
tests/test_opportunity_replace.py
==================================
Unit tests for the opportunity-replacement decision functions.
"""
from __future__ import annotations
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies.opportunity_replace import (
    should_replace_pending,
    should_autocancel_pending,
)


# ─── Helpers ───────────────────────────────────────────────────────────────

def _sig(direction="short", entry=29306.75):
    return SimpleNamespace(direction=direction, entry_price=entry)


def _pending_bt(direction="short", entry=29306.75):
    """Backtester-style pending dict."""
    return {"direction": direction, "limit_price": entry}


def _pending_live(direction="short", entry=29306.75):
    """Live main.py-style pending dict (signal nested)."""
    return {"signal": SimpleNamespace(direction=direction, entry_price=entry)}


def _struct_event(type_="CHoCH", direction="bullish", ts="2026-05-13 09:00"):
    import pandas as pd
    return SimpleNamespace(
        type=type_,
        direction=direction,
        timeframe="5min",
        timestamp=pd.Timestamp(ts),
    )


# ─── Tier 1: Opposite direction ────────────────────────────────────────────

class TestTier1OppositeDirection:
    def test_long_replaces_pending_short(self):
        new = _sig(direction="long", entry=29200)
        pending = _pending_bt(direction="short", entry=29306.75)
        ok, reason = should_replace_pending(new, pending, current_price=29250)
        assert ok
        assert "tier1_opposite" in reason

    def test_short_replaces_pending_long(self):
        new = _sig(direction="short", entry=29400)
        pending = _pending_bt(direction="long", entry=29300)
        ok, reason = should_replace_pending(new, pending, current_price=29350)
        assert ok
        assert "tier1_opposite" in reason

    def test_works_with_live_pending_shape(self):
        new = _sig(direction="long", entry=29200)
        pending = _pending_live(direction="short", entry=29306.75)
        ok, _ = should_replace_pending(new, pending, current_price=29250)
        assert ok


# ─── Tier 2: Same direction, materially closer ─────────────────────────────

class TestTier2CloserFill:
    def test_replace_when_significantly_closer(self):
        # Pending: short @ 29306.75 (52pt above current 29254)
        # New: short @ 29275 (21pt above current) → 40% of pending dist
        new = _sig(direction="short", entry=29275)
        pending = _pending_bt(direction="short", entry=29306.75)
        ok, reason = should_replace_pending(new, pending, current_price=29254)
        assert ok
        assert "tier2_closer" in reason

    def test_dont_replace_when_only_slightly_closer(self):
        # Pending: short @ 29306.75 (52pt above current 29254)
        # New: short @ 29300 (46pt above current) → 88% of pending dist
        new = _sig(direction="short", entry=29300)
        pending = _pending_bt(direction="short", entry=29306.75)
        ok, _ = should_replace_pending(new, pending, current_price=29254)
        assert not ok

    def test_dont_replace_when_farther(self):
        new = _sig(direction="short", entry=29350)
        pending = _pending_bt(direction="short", entry=29306.75)
        ok, _ = should_replace_pending(new, pending, current_price=29254)
        assert not ok

    def test_proximity_pts_threshold(self):
        # 70% rule satisfied (new=30pt, pending=50pt → 60%)
        # BUT only 20pt difference (>= 5pt threshold)
        new = _sig(direction="short", entry=29280)
        pending = _pending_bt(direction="short", entry=29300)
        ok, reason = should_replace_pending(new, pending, current_price=29250)
        assert ok
        assert "tier2_closer" in reason


# ─── Tier 2.5: Stale aging ─────────────────────────────────────────────────

class TestTier2_5StaleAging:
    def test_stale_pending_replaced_by_equal_distance(self):
        # Same distance — would normally NOT replace.
        # But pending has been waiting 12 bars (≥10 threshold) → stale → replace.
        new = _sig(direction="short", entry=29306)
        pending = _pending_bt(direction="short", entry=29307)
        ok, reason = should_replace_pending(
            new, pending, current_price=29254, bars_pending=12,
        )
        assert ok
        assert "tier2.5_stale" in reason

    def test_fresh_pending_not_replaced_by_equal_distance(self):
        # Same setup but pending only 3 bars old → still fresh, no replace.
        new = _sig(direction="short", entry=29306)
        pending = _pending_bt(direction="short", entry=29307)
        ok, _ = should_replace_pending(
            new, pending, current_price=29254, bars_pending=3,
        )
        assert not ok


# ─── Tier 1.5: Bias-flip auto-cancel ───────────────────────────────────────

class TestTier1_5BiasFlipAutoCancel:
    def test_short_cancelled_by_bullish_choch_after(self):
        import pandas as pd
        pending = _pending_bt(direction="short", entry=29306.75)
        signal_ts = pd.Timestamp("2026-05-13 08:30")
        # Bullish CHoCH AFTER signal — opposite direction → cancel
        events = [_struct_event("CHoCH", "bullish", "2026-05-13 09:00")]
        cancel, reason = should_autocancel_pending(pending, events, signal_ts)
        assert cancel
        assert "tier1.5_bias_flip" in reason

    def test_short_cancelled_by_bullish_mss_after(self):
        import pandas as pd
        pending = _pending_bt(direction="short", entry=29306.75)
        signal_ts = pd.Timestamp("2026-05-13 08:30")
        events = [_struct_event("MSS", "bullish", "2026-05-13 09:00")]
        cancel, _ = should_autocancel_pending(pending, events, signal_ts)
        assert cancel

    def test_short_NOT_cancelled_by_bullish_BOS_after(self):
        # BOS is continuation, not a trend-change event.
        import pandas as pd
        pending = _pending_bt(direction="short", entry=29306.75)
        signal_ts = pd.Timestamp("2026-05-13 08:30")
        events = [_struct_event("BOS", "bullish", "2026-05-13 09:00")]
        cancel, _ = should_autocancel_pending(pending, events, signal_ts)
        assert not cancel

    def test_short_NOT_cancelled_by_event_BEFORE_signal(self):
        import pandas as pd
        pending = _pending_bt(direction="short", entry=29306.75)
        signal_ts = pd.Timestamp("2026-05-13 08:30")
        # Event BEFORE signal → already accounted for in signal generation
        events = [_struct_event("CHoCH", "bullish", "2026-05-13 08:00")]
        cancel, _ = should_autocancel_pending(pending, events, signal_ts)
        assert not cancel

    def test_short_NOT_cancelled_by_aligned_bearish_event(self):
        import pandas as pd
        pending = _pending_bt(direction="short", entry=29306.75)
        signal_ts = pd.Timestamp("2026-05-13 08:30")
        # Same-direction event = continuation, NOT cancel
        events = [_struct_event("MSS", "bearish", "2026-05-13 09:00")]
        cancel, _ = should_autocancel_pending(pending, events, signal_ts)
        assert not cancel


# ─── Feature-disable tests ─────────────────────────────────────────────────

class TestFeatureDisable:
    def test_disabled_means_no_replace(self, monkeypatch):
        monkeypatch.setattr("config.OPPORTUNITY_REPLACE_ENABLED", False)
        new = _sig(direction="long", entry=29200)
        pending = _pending_bt(direction="short", entry=29306.75)
        ok, reason = should_replace_pending(new, pending, current_price=29250)
        assert not ok
        assert "disabled" in reason

    def test_autocancel_disabled_means_no_cancel(self, monkeypatch):
        import pandas as pd
        monkeypatch.setattr("config.AUTOCANCEL_ON_BIAS_FLIP", False)
        pending = _pending_bt(direction="short", entry=29306.75)
        signal_ts = pd.Timestamp("2026-05-13 08:30")
        events = [_struct_event("MSS", "bullish", "2026-05-13 09:00")]
        cancel, _ = should_autocancel_pending(pending, events, signal_ts)
        assert not cancel
