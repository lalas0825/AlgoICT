"""Tests for SB_REQUIRE_MSS_AFTER_COUNTER gate (Fix #3, 2026-05-23).

Forensic origin: Thu 5/21 trade #2 (-$143 WTF LONG). Bot fired LONG with
struct_last3=[BOS bull 13:10, BOS bull 13:15, BOS bull 13:30] after a
250pt bearish drop. ICT canonical says pure BOS chain after counter-
direction event = continuation of opposite trend (recovery rally), not
a flip. A real flip requires MSS or CHoCH event.

Gate logic mirrored as pure function (same pattern as test_htf_weak_gate
and test_fvg_quality_gate) to test in isolation from the full SB pipeline.
"""
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd


# Minimal stand-in for a structure event (mirrors detectors/market_structure
# StructureEvent shape).
@dataclass
class StubEvent:
    type: str          # "MSS" | "BOS" | "CHoCH"
    direction: str     # "bullish" | "bearish"
    timestamp: pd.Timestamp


def _evaluate_flip_gate(
    *,
    require_flip: bool = False,
    bias_dir: str = "bullish",
    aligned: List[StubEvent] = None,
    most_recent_opp: Optional[StubEvent] = None,
) -> dict:
    """Mirror of the Fix #3 gate in silver_bullet.py.
    Returns dict with `rejected` (bool) and `reason` (str)."""
    aligned = aligned or []
    if not require_flip:
        return {"rejected": False, "reason": ""}
    if most_recent_opp is None:
        # No counter event → BOS chain is fine (trending session)
        return {"rejected": False, "reason": "no_counter_event"}
    has_flip = any(e.type in ("MSS", "CHoCH") for e in aligned)
    if not has_flip:
        return {
            "rejected": True,
            "reason": "no_flip_after_counter",
            "aligned_types": ",".join(e.type for e in aligned),
        }
    return {"rejected": False, "reason": "has_flip"}


def _ts(hour: int, minute: int) -> pd.Timestamp:
    return pd.Timestamp(f"2026-05-21 {hour:02d}:{minute:02d}:00", tz="US/Central")


# ───────────────────────────────────────────────────────────────────────
# Disabled — gate doesn't fire
# ───────────────────────────────────────────────────────────────────────

class TestGateDisabled:

    def test_disabled_does_not_reject(self):
        """Even with worst-case (3 BOS, opp event exists), disabled = pass."""
        opp = StubEvent("BOS", "bearish", _ts(12, 30))
        aligned = [
            StubEvent("BOS", "bullish", _ts(13, 10)),
            StubEvent("BOS", "bullish", _ts(13, 15)),
            StubEvent("BOS", "bullish", _ts(13, 30)),
        ]
        out = _evaluate_flip_gate(
            require_flip=False, bias_dir="bullish",
            aligned=aligned, most_recent_opp=opp,
        )
        assert not out["rejected"]


# ───────────────────────────────────────────────────────────────────────
# Trending session — no counter event ever happened
# ───────────────────────────────────────────────────────────────────────

class TestTrendingSession:

    def test_no_counter_event_bos_chain_passes(self):
        """Pure trending session: BOS chain in single direction = fine."""
        aligned = [
            StubEvent("BOS", "bullish", _ts(9, 30)),
            StubEvent("BOS", "bullish", _ts(10, 0)),
            StubEvent("BOS", "bullish", _ts(10, 30)),
        ]
        out = _evaluate_flip_gate(
            require_flip=True, bias_dir="bullish",
            aligned=aligned, most_recent_opp=None,
        )
        assert not out["rejected"]
        assert out["reason"] == "no_counter_event"


# ───────────────────────────────────────────────────────────────────────
# After counter event — flip required
# ───────────────────────────────────────────────────────────────────────

class TestFlipRequired:

    def setup_method(self):
        # Common counter-direction event in early session
        self.counter = StubEvent("BOS", "bearish", _ts(12, 30))

    def test_pure_bos_chain_after_counter_rejected(self):
        """Trade #2 reproduction: 3 BOS bull after counter bear → REJECT.
        This is the exact scenario from Thu 5/21 trade #2 audit."""
        aligned = [
            StubEvent("BOS", "bullish", _ts(13, 10)),
            StubEvent("BOS", "bullish", _ts(13, 15)),
            StubEvent("BOS", "bullish", _ts(13, 30)),
        ]
        out = _evaluate_flip_gate(
            require_flip=True, bias_dir="bullish",
            aligned=aligned, most_recent_opp=self.counter,
        )
        assert out["rejected"]
        assert out["reason"] == "no_flip_after_counter"
        assert out["aligned_types"] == "BOS,BOS,BOS"

    def test_single_bos_after_counter_rejected(self):
        """Even 1 BOS without flip after counter → reject."""
        aligned = [StubEvent("BOS", "bullish", _ts(13, 10))]
        out = _evaluate_flip_gate(
            require_flip=True, bias_dir="bullish",
            aligned=aligned, most_recent_opp=self.counter,
        )
        assert out["rejected"]

    def test_mss_in_aligned_passes(self):
        """MSS bull in aligned = real flip → fire allowed."""
        aligned = [
            StubEvent("MSS", "bullish", _ts(13, 5)),
            StubEvent("BOS", "bullish", _ts(13, 15)),
        ]
        out = _evaluate_flip_gate(
            require_flip=True, bias_dir="bullish",
            aligned=aligned, most_recent_opp=self.counter,
        )
        assert not out["rejected"]
        assert out["reason"] == "has_flip"

    def test_choch_in_aligned_passes(self):
        """CHoCH bull in aligned = first reversal sign → fire allowed."""
        aligned = [
            StubEvent("CHoCH", "bullish", _ts(13, 5)),
            StubEvent("BOS", "bullish", _ts(13, 15)),
        ]
        out = _evaluate_flip_gate(
            require_flip=True, bias_dir="bullish",
            aligned=aligned, most_recent_opp=self.counter,
        )
        assert not out["rejected"]

    def test_mss_then_many_bos_passes(self):
        """MSS + multiple BOS continuations = valid trend with flip."""
        aligned = [
            StubEvent("MSS", "bullish", _ts(13, 0)),
            StubEvent("BOS", "bullish", _ts(13, 10)),
            StubEvent("BOS", "bullish", _ts(13, 20)),
            StubEvent("BOS", "bullish", _ts(13, 30)),
        ]
        out = _evaluate_flip_gate(
            require_flip=True, bias_dir="bullish",
            aligned=aligned, most_recent_opp=self.counter,
        )
        assert not out["rejected"]

    def test_only_mss_in_aligned_passes(self):
        """Just MSS without BOS continuations = still valid flip."""
        aligned = [StubEvent("MSS", "bullish", _ts(13, 5))]
        out = _evaluate_flip_gate(
            require_flip=True, bias_dir="bullish",
            aligned=aligned, most_recent_opp=self.counter,
        )
        assert not out["rejected"]


# ───────────────────────────────────────────────────────────────────────
# Symmetric short side
# ───────────────────────────────────────────────────────────────────────

class TestShortSideSymmetric:

    def test_short_pure_bos_after_bull_counter_rejected(self):
        """SHORT trade: 3 BOS bear after counter bull → REJECT."""
        opp = StubEvent("BOS", "bullish", _ts(11, 0))
        aligned = [
            StubEvent("BOS", "bearish", _ts(12, 0)),
            StubEvent("BOS", "bearish", _ts(12, 10)),
            StubEvent("BOS", "bearish", _ts(12, 30)),
        ]
        out = _evaluate_flip_gate(
            require_flip=True, bias_dir="bearish",
            aligned=aligned, most_recent_opp=opp,
        )
        assert out["rejected"]

    def test_short_with_mss_passes(self):
        """SHORT with MSS bear in aligned → fire allowed."""
        opp = StubEvent("BOS", "bullish", _ts(11, 0))
        aligned = [StubEvent("MSS", "bearish", _ts(12, 0))]
        out = _evaluate_flip_gate(
            require_flip=True, bias_dir="bearish",
            aligned=aligned, most_recent_opp=opp,
        )
        assert not out["rejected"]


# ───────────────────────────────────────────────────────────────────────
# Config default
# ───────────────────────────────────────────────────────────────────────

class TestConfigDefault:

    def test_default_off(self):
        """Ship-safe: default OFF until cross-period validates."""
        import config
        assert config.cfg("SB_REQUIRE_MSS_AFTER_COUNTER", False) is False
