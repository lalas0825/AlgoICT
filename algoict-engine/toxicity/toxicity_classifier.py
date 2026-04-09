"""
toxicity/toxicity_classifier.py
================================
Maps VPIN values to toxicity levels and trading actions.

This module is the single source of truth for VPIN level thresholds
and the action each level requires. It wraps classify_toxicity() from
vpin_calculator.py and adds structured action recommendations.

VPIN Levels (from CLAUDE.md):
    < 0.35  -> calm     : Normal operation
    0.35-0.45 -> normal : Normal operation
    0.45-0.55 -> elevated: Alert, tighten stops 10%
    0.55-0.70 -> high   : Min confluence +1, reduce position 25%
    > 0.70  -> extreme  : FLATTEN ALL. HALT TRADING.

Usage:
    from toxicity.toxicity_classifier import ToxicityClassifier, ToxicityLevel
    tc = ToxicityClassifier()
    level = tc.classify(0.65)
    print(level.label)           # 'high'
    print(level.should_flatten)  # False
    print(level.size_multiplier) # 0.75
    print(level.min_confluence_delta)  # +1
"""

import logging
from dataclasses import dataclass
from typing import Optional

from toxicity.vpin_calculator import classify_toxicity

logger = logging.getLogger(__name__)

# VPIN thresholds (mirrors CLAUDE.md)
_THRESHOLDS = {
    "calm":     (0.00, 0.35),
    "normal":   (0.35, 0.45),
    "elevated": (0.45, 0.55),
    "high":     (0.55, 0.70),
    "extreme":  (0.70, 1.01),
}


# ---------------------------------------------------------------------------
# ToxicityLevel dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToxicityLevel:
    """
    Complete toxicity assessment for a given VPIN reading.

    Attributes
    ----------
    label : str
        Level name: 'calm' | 'normal' | 'elevated' | 'high' | 'extreme'
    vpin : float
        The VPIN value this was derived from.
    should_flatten : bool
        True if extreme — all positions must be closed immediately.
    should_halt : bool
        True if extreme — no new trades allowed.
    size_multiplier : float
        Position size multiplier (0.75 = 25% reduction).
    min_confluence_delta : int
        Extra points required above the base min_confluence.
    stop_tighten_pct : float
        Percentage to tighten stops (0.10 = tighten by 10% of stop distance).
    emoji : str
        Alert emoji for Telegram notifications.

    Examples
    --------
    calm     -> flatten=False halt=False size=1.00 conf_delta=0
    normal   -> flatten=False halt=False size=1.00 conf_delta=0
    elevated -> flatten=False halt=False size=1.00 conf_delta=0 stop_tighten=10%
    high     -> flatten=False halt=False size=0.75 conf_delta=+1
    extreme  -> flatten=True  halt=True  size=0.00 conf_delta=N/A
    """

    label: str
    vpin: float
    should_flatten: bool
    should_halt: bool
    size_multiplier: float
    min_confluence_delta: int
    stop_tighten_pct: float
    emoji: str
    description: str = ""

    @property
    def is_extreme(self) -> bool:
        return self.label == "extreme"

    @property
    def is_dangerous(self) -> bool:
        return self.label in ("high", "extreme")

    @property
    def is_safe(self) -> bool:
        return self.label in ("calm", "normal")

    def __repr__(self) -> str:
        return (
            f"ToxicityLevel({self.label} vpin={self.vpin:.3f} "
            f"flatten={self.should_flatten})"
        )


# ---------------------------------------------------------------------------
# Action table
# ---------------------------------------------------------------------------

_ACTIONS = {
    "calm": dict(
        should_flatten=False,
        should_halt=False,
        size_multiplier=1.00,
        min_confluence_delta=0,
        stop_tighten_pct=0.00,
        emoji="",
        description="Balanced flow. Normal operation.",
    ),
    "normal": dict(
        should_flatten=False,
        should_halt=False,
        size_multiplier=1.00,
        min_confluence_delta=0,
        stop_tighten_pct=0.00,
        emoji="",
        description="Typical activity. Normal operation.",
    ),
    "elevated": dict(
        should_flatten=False,
        should_halt=False,
        size_multiplier=1.00,
        min_confluence_delta=0,
        stop_tighten_pct=0.10,
        emoji="",
        description="Some informed flow. Tighten stops 10%.",
    ),
    "high": dict(
        should_flatten=False,
        should_halt=False,
        size_multiplier=0.75,
        min_confluence_delta=1,
        stop_tighten_pct=0.00,
        emoji="",
        description="Smart money active. Reduce size 25%. Need A+ setups.",
    ),
    "extreme": dict(
        should_flatten=True,
        should_halt=True,
        size_multiplier=0.00,
        min_confluence_delta=99,    # Effectively: no new trades
        stop_tighten_pct=0.00,
        emoji="",
        description="Maximum toxicity. FLATTEN ALL. HALT TRADING.",
    ),
}


# ---------------------------------------------------------------------------
# ToxicityClassifier
# ---------------------------------------------------------------------------

class ToxicityClassifier:
    """
    Classifies VPIN readings into actionable ToxicityLevel objects.
    """

    def classify(self, vpin: float) -> ToxicityLevel:
        """
        Classify a VPIN value into a ToxicityLevel.

        Parameters
        ----------
        vpin : float
            VPIN value in [0.0, 1.0].

        Returns
        -------
        ToxicityLevel with action recommendations.
        """
        label = classify_toxicity(vpin)
        actions = _ACTIONS[label]

        level = ToxicityLevel(
            label=label,
            vpin=round(vpin, 4),
            **actions,
        )

        if level.is_extreme:
            logger.critical(
                "VPIN EXTREME: %.3f — FLATTEN ALL POSITIONS. HALT TRADING.", vpin
            )
        elif level.is_dangerous:
            logger.warning("VPIN HIGH: %.3f — reduced size, elevated confluence required.", vpin)
        else:
            logger.debug("VPIN %s: %.3f", label, vpin)

        return level

    def threshold_for(self, label: str) -> tuple:
        """Return (low, high) VPIN threshold for a given label."""
        return _THRESHOLDS.get(label, (0.0, 0.0))

    def label_for_vpin(self, vpin: float) -> str:
        """Return just the label string for a VPIN value."""
        return classify_toxicity(vpin)

    def all_levels(self) -> list:
        """Return all level labels in order from least to most toxic."""
        return ["calm", "normal", "elevated", "high", "extreme"]


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_classifier = ToxicityClassifier()


def classify(vpin: float) -> ToxicityLevel:
    """Module-level convenience: classify a VPIN value."""
    return _default_classifier.classify(vpin)
