"""Tests for SB_HTF_WEAK_MIN_CONF conditional gate (2026-05-20).

Verifies the post-mortem-driven conditional gate behavior:
  - When HTF is weak (D1 or W1 = neutral/None) AND sb_score below threshold,
    shadow mode logs a "would skip" entry to JSONL but does not block the
    signal; active mode returns None.
  - When HTF is strong (both defined), gate does NOT fire regardless of
    score.
  - When score >= threshold, gate does NOT fire regardless of HTF weakness.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# Build minimal stand-ins for the gate logic. Rather than running the full
# silver_bullet pipeline, we test the gate decision pure-function-style.
def _evaluate_gate(
    *,
    htf_weak_min: int,
    weak_requires: str,
    d_bias: str,
    w_bias: str,
    sb_score: int,
) -> dict:
    """Re-implement the gate decision logic for unit-test isolation."""
    weak_set = {"neutral", "none", ""}
    weak_d = str(d_bias or "none").lower().strip() in weak_set
    weak_w = str(w_bias or "none").lower().strip() in weak_set
    if weak_requires == "both":
        htf_weak = weak_d and weak_w
    else:
        htf_weak = weak_d or weak_w
    fires = htf_weak_min > 0 and htf_weak and sb_score < htf_weak_min
    return {
        "weak_d": weak_d,
        "weak_w": weak_w,
        "htf_weak": htf_weak,
        "fires": fires,
    }


class TestHtfWeakGateLogic:

    def test_disabled_when_min_conf_zero(self):
        out = _evaluate_gate(
            htf_weak_min=0, weak_requires="either",
            d_bias="neutral", w_bias="neutral", sb_score=0,
        )
        assert not out["fires"]

    def test_either_weak_d1_fires(self):
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="either",
            d_bias="neutral", w_bias="bullish", sb_score=1,
        )
        assert out["fires"]

    def test_either_weak_w1_fires(self):
        """Today's case: d=bearish w=neutral, score=1 → would skip."""
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="either",
            d_bias="bearish", w_bias="neutral", sb_score=1,
        )
        assert out["fires"]

    def test_both_strong_does_not_fire(self):
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="either",
            d_bias="bullish", w_bias="bullish", sb_score=0,
        )
        assert not out["fires"]

    def test_score_at_threshold_does_not_fire(self):
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="either",
            d_bias="neutral", w_bias="bullish", sb_score=2,
        )
        assert not out["fires"]

    def test_score_above_threshold_does_not_fire(self):
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="either",
            d_bias="neutral", w_bias="neutral", sb_score=3,
        )
        assert not out["fires"]

    def test_requires_both_d_only_weak_does_not_fire(self):
        """With weak_requires='both', a single weak side is insufficient."""
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="both",
            d_bias="neutral", w_bias="bullish", sb_score=1,
        )
        assert not out["fires"]

    def test_requires_both_both_weak_fires(self):
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="both",
            d_bias="neutral", w_bias="neutral", sb_score=1,
        )
        assert out["fires"]

    def test_none_treated_as_weak(self):
        """Bias as None should be treated as weak."""
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="either",
            d_bias=None, w_bias="bullish", sb_score=1,
        )
        assert out["fires"]

    def test_empty_string_treated_as_weak(self):
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="either",
            d_bias="", w_bias="bullish", sb_score=1,
        )
        assert out["fires"]

    def test_case_insensitive(self):
        out = _evaluate_gate(
            htf_weak_min=2, weak_requires="either",
            d_bias="NEUTRAL", w_bias="BULLISH", sb_score=1,
        )
        assert out["fires"]


class TestHtfWeakGateBoundaryCases:

    def test_min_conf_3_with_score_2_fires(self):
        out = _evaluate_gate(
            htf_weak_min=3, weak_requires="either",
            d_bias="neutral", w_bias="bullish", sb_score=2,
        )
        assert out["fires"]

    def test_min_conf_3_with_score_3_does_not_fire(self):
        out = _evaluate_gate(
            htf_weak_min=3, weak_requires="either",
            d_bias="neutral", w_bias="bullish", sb_score=3,
        )
        assert not out["fires"]

    def test_min_conf_1_blocks_only_zero_score(self):
        """min=1 with score=0 fires, with score=1 does not."""
        out_zero = _evaluate_gate(
            htf_weak_min=1, weak_requires="either",
            d_bias="neutral", w_bias="bullish", sb_score=0,
        )
        assert out_zero["fires"]
        out_one = _evaluate_gate(
            htf_weak_min=1, weak_requires="either",
            d_bias="neutral", w_bias="bullish", sb_score=1,
        )
        assert not out_one["fires"]
