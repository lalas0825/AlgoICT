"""
gamma/regime_detector.py
=========================
Classifies the current gamma regime based on spot price vs gamma flip.

Regime rules
------------
    spot >  gamma_flip  -> 'positive' (stabilizing — mean reversion favored)
    spot <  gamma_flip  -> 'negative' (amplifying  — momentum favored)
    spot == gamma_flip  -> 'neutral'  (regime transition zone)

Near-flip zone
--------------
If spot is within `near_flip_points` of the flip level, we flag the regime
as "near_flip" — a high-uncertainty transition zone where position sizing
should be reduced regardless of sign.

Strength
--------
Re-computed here from total GEX and net_gex std dev so the detector can
run against any GammaRegime snapshot, not just the one that created it.

Strategy recommendation
-----------------------
The detector returns a recommended strategy class based on regime:
    positive    -> 'silver_bullet' (scalps, mean reversion, tight ranges)
    negative    -> 'ny_am_reversal' (trend, momentum, wide targets)
    near_flip   -> 'reduce_size'   (caution, wait for regime to settle)
    neutral     -> 'both'          (no strong preference)
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# Default proximity (in points) for "near flip" classification.
# MNQ typically moves 50-150 points per day, so 15 points is a tight zone.
DEFAULT_NEAR_FLIP_POINTS = 15.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RegimeResult:
    """
    Classification of the current gamma regime.
    """
    regime: str              # 'positive' | 'negative' | 'neutral'
    near_flip: bool          # True if spot within near_flip_points of flip
    distance_to_flip: float  # absolute distance in points (always >= 0)
    spot: float
    gamma_flip: float
    total_gex: float
    strength: str            # 'weak' | 'moderate' | 'strong'
    recommended_strategy: str   # 'silver_bullet' | 'ny_am_reversal' | 'reduce_size' | 'both'
    description: str = ""

    def __repr__(self) -> str:
        near = " [NEAR FLIP]" if self.near_flip else ""
        return (
            f"RegimeResult(regime={self.regime}{near} "
            f"spot={self.spot:.2f} flip={self.gamma_flip:.2f} "
            f"dist={self.distance_to_flip:.2f} strength={self.strength})"
        )


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class RegimeDetector:
    """
    Classifies gamma regime from a GammaRegime snapshot (from gex_calculator)
    or from raw spot + gamma_flip + total_gex values.
    """

    def __init__(self, near_flip_points: float = DEFAULT_NEAR_FLIP_POINTS):
        self.near_flip_points = float(near_flip_points)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def detect(self, gamma_regime) -> RegimeResult:
        """
        Classify regime from a GammaRegime snapshot.

        Parameters
        ----------
        gamma_regime : GammaRegime (from gamma.gex_calculator)

        Returns
        -------
        RegimeResult
        """
        spot = float(gamma_regime.spot)
        flip = float(gamma_regime.gamma_flip)
        total_gex = float(gamma_regime.total_gex)

        # Prefer the strength that the calculator already computed (it used
        # the net_gex std dev internally). Fall back to recomputation if
        # the caller passes a bare object.
        strength = getattr(gamma_regime, "strength", None) or self._strength_from_array(
            gamma_regime.net_gex_array if hasattr(gamma_regime, "net_gex_array") else None,
            total_gex,
        )

        return self._classify(spot, flip, total_gex, strength)

    def detect_from_values(
        self,
        spot: float,
        gamma_flip: float,
        total_gex: float = 0.0,
        strength: str = "weak",
    ) -> RegimeResult:
        """
        Classify regime from raw values. Useful for tests or when you've
        already computed the flip level externally.
        """
        return self._classify(
            float(spot), float(gamma_flip), float(total_gex), strength,
        )

    # ------------------------------------------------------------------ #
    # Core classification                                                  #
    # ------------------------------------------------------------------ #

    def _classify(
        self,
        spot: float,
        gamma_flip: float,
        total_gex: float,
        strength: str,
    ) -> RegimeResult:
        distance = abs(spot - gamma_flip)
        near_flip = distance <= self.near_flip_points

        if spot > gamma_flip:
            regime = "positive"
        elif spot < gamma_flip:
            regime = "negative"
        else:
            regime = "neutral"

        # Recommendation: near-flip overrides everything else.
        if near_flip:
            recommended = "reduce_size"
            description = (
                f"Near gamma flip (distance={distance:.1f} pts) — "
                "regime transition zone, reduce position size"
            )
        elif regime == "positive":
            recommended = "silver_bullet"
            description = (
                "Positive gamma — dealers hedge against the move. "
                "Expect mean reversion and range-bound behavior. "
                "Favor Silver Bullet scalps."
            )
        elif regime == "negative":
            recommended = "ny_am_reversal"
            description = (
                "Negative gamma — dealers hedge with the move. "
                "Expect momentum and wider ranges. "
                "Favor NY AM Reversal with wide targets."
            )
        else:
            recommended = "both"
            description = "Neutral gamma — no strong directional preference."

        return RegimeResult(
            regime=regime,
            near_flip=near_flip,
            distance_to_flip=distance,
            spot=spot,
            gamma_flip=gamma_flip,
            total_gex=total_gex,
            strength=strength,
            recommended_strategy=recommended,
            description=description,
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strength_from_array(
        net_gex: Optional[np.ndarray],
        total_gex: float,
    ) -> str:
        if net_gex is None or len(net_gex) == 0:
            return "weak"
        std = float(np.std(net_gex))
        if std == 0 or not np.isfinite(std):
            return "weak"
        if abs(total_gex) > 2 * std:
            return "strong"
        if abs(total_gex) > std:
            return "moderate"
        return "weak"


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def classify_regime(gamma_regime) -> RegimeResult:
    """Shortcut using a default-configured detector."""
    return RegimeDetector().detect(gamma_regime)


def is_positive_regime(spot: float, gamma_flip: float) -> bool:
    """True if spot is above the gamma flip."""
    return spot > gamma_flip


def is_negative_regime(spot: float, gamma_flip: float) -> bool:
    """True if spot is below the gamma flip."""
    return spot < gamma_flip


def is_near_flip(
    spot: float,
    gamma_flip: float,
    threshold: float = DEFAULT_NEAR_FLIP_POINTS,
) -> bool:
    """True if spot is within `threshold` points of the flip."""
    return abs(spot - gamma_flip) <= threshold
