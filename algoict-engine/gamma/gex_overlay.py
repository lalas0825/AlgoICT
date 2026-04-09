"""
gamma/gex_overlay.py
=====================
GEX Overlay — converts raw GammaRegime data into actionable trading levels.

Produces a GEXOverlay snapshot that the trading engine uses to:
  1. Check if a signal aligns with a GEX wall (+2 confluence bonus)
  2. Set refined take-profit targets (TP at the next GEX wall)
  3. Apply position sizing based on gamma regime

Usage:
    from gamma.gex_overlay import GEXOverlay, build_overlay
    overlay = build_overlay(gamma_regime, spot_price=19500.0)
    print(overlay.call_wall)          # resistance level
    print(overlay.put_wall)           # support level
    print(overlay.gamma_flip)         # regime boundary
    print(overlay.regime_label)       # 'positive' | 'negative' | 'neutral'
    print(overlay.strategy_hint)      # 'silver_bullet' | 'ny_am_reversal' | etc.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# How close (in points) to a GEX wall to count as "aligned"
_DEFAULT_ALIGNMENT_TOLERANCE = 10.0   # MNQ points


# ---------------------------------------------------------------------------
# GEXOverlay dataclass
# ---------------------------------------------------------------------------

@dataclass
class GEXOverlay:
    """
    Actionable GEX summary for the trading engine.

    Produced daily in pre-market and updated ~every 30 minutes during trading.
    """

    spot: float                          # Spot price at time of calculation
    call_wall: float                     # Max call GEX strike (resistance)
    put_wall: float                      # Max put GEX strike (support)
    gamma_flip: float                    # Net GEX sign change level

    regime: str                          # 'positive' | 'negative' | 'neutral'
    near_flip: bool                      # True if spot is close to the flip
    total_gex: float                     # Total market GEX magnitude

    high_gex_levels: list = field(default_factory=list)   # [float, ...] — sticky zones
    strategy_hint: str = ""              # 'silver_bullet' | 'ny_am_reversal' | 'reduce_size' | 'both'
    regime_strength: str = ""            # 'low' | 'medium' | 'high'
    source: str = "calculated"           # 'calculated' | 'synthetic' | 'unavailable'
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None and self.call_wall > 0

    @property
    def regime_label(self) -> str:
        """Human-readable regime with near-flip flag."""
        if self.near_flip:
            return f"{self.regime} (near flip)"
        return self.regime

    # ------------------------------------------------------------------ #
    # Alignment checks
    # ------------------------------------------------------------------ #

    def is_near_call_wall(
        self,
        price: float,
        tolerance: float = _DEFAULT_ALIGNMENT_TOLERANCE,
    ) -> bool:
        """True if price is within `tolerance` points below the call wall."""
        return 0 <= self.call_wall - price <= tolerance * 2

    def is_near_put_wall(
        self,
        price: float,
        tolerance: float = _DEFAULT_ALIGNMENT_TOLERANCE,
    ) -> bool:
        """True if price is within `tolerance` points above the put wall."""
        return 0 <= price - self.put_wall <= tolerance * 2

    def is_near_gex_level(
        self,
        price: float,
        tolerance: float = _DEFAULT_ALIGNMENT_TOLERANCE,
    ) -> bool:
        """True if price is near any high-GEX sticky zone."""
        for lvl in self.high_gex_levels:
            if abs(price - lvl) <= tolerance:
                return True
        return False

    def nearest_wall_above(self, price: float) -> Optional[float]:
        """Return the nearest GEX wall above the given price, or None."""
        candidates = [
            lvl for lvl in [self.call_wall, self.gamma_flip] + self.high_gex_levels
            if lvl > price
        ]
        return min(candidates) if candidates else None

    def nearest_wall_below(self, price: float) -> Optional[float]:
        """Return the nearest GEX wall below the given price, or None."""
        candidates = [
            lvl for lvl in [self.put_wall, self.gamma_flip] + self.high_gex_levels
            if lvl < price
        ]
        return max(candidates) if candidates else None

    def as_dict(self) -> dict:
        return {
            "spot": self.spot,
            "call_wall": self.call_wall,
            "put_wall": self.put_wall,
            "gamma_flip": self.gamma_flip,
            "regime": self.regime,
            "near_flip": self.near_flip,
            "strategy_hint": self.strategy_hint,
            "regime_strength": self.regime_strength,
            "total_gex": self.total_gex,
        }


# ---------------------------------------------------------------------------
# Builder function
# ---------------------------------------------------------------------------

def build_overlay(
    gamma_regime,
    spot: Optional[float] = None,
    regime_result=None,
    near_flip_points: float = 15.0,
) -> GEXOverlay:
    """
    Build a GEXOverlay from a GammaRegime (from gex_calculator.py) and
    optionally a RegimeResult (from regime_detector.py).

    Parameters
    ----------
    gamma_regime : GammaRegime
        Output from GEXCalculator.calculate_gex().
    spot : float
        Current spot price. Uses gamma_regime.spot if not provided.
    regime_result : RegimeResult | None
        Output from RegimeDetector.detect(). Built on-demand if not provided.
    near_flip_points : float
        Proximity threshold for "near flip" classification.

    Returns
    -------
    GEXOverlay
    """
    try:
        if spot is None:
            spot = getattr(gamma_regime, "spot", 0.0) or 0.0

        call_wall = getattr(gamma_regime, "call_wall", 0.0) or 0.0
        put_wall = getattr(gamma_regime, "put_wall", 0.0) or 0.0
        gamma_flip = getattr(gamma_regime, "gamma_flip", 0.0) or 0.0
        total_gex = getattr(gamma_regime, "total_gex", 0.0) or 0.0
        high_gex = list(getattr(gamma_regime, "high_gex_levels", []) or [])

        # Determine regime from regime_result or inline
        if regime_result is not None:
            regime = getattr(regime_result, "regime", "neutral")
            near_flip = getattr(regime_result, "near_flip", False)
            strength = getattr(regime_result, "strength", "medium")
            strategy_hint = _regime_to_strategy(regime, near_flip)
        else:
            regime, near_flip = _classify_regime_inline(spot, gamma_flip, near_flip_points)
            strength = "medium"
            strategy_hint = _regime_to_strategy(regime, near_flip)

        logger.info(
            "GEX overlay built: regime=%s near_flip=%s call_wall=%.0f put_wall=%.0f flip=%.0f",
            regime, near_flip, call_wall, put_wall, gamma_flip,
        )

        return GEXOverlay(
            spot=spot,
            call_wall=call_wall,
            put_wall=put_wall,
            gamma_flip=gamma_flip,
            regime=regime,
            near_flip=near_flip,
            total_gex=total_gex,
            high_gex_levels=high_gex,
            strategy_hint=strategy_hint,
            regime_strength=str(strength),
            source="calculated",
        )

    except Exception as exc:
        logger.error("build_overlay failed: %s", exc)
        return GEXOverlay(
            spot=spot or 0.0,
            call_wall=0.0,
            put_wall=0.0,
            gamma_flip=0.0,
            regime="neutral",
            near_flip=False,
            total_gex=0.0,
            source="unavailable",
            error=str(exc),
        )


def unavailable_overlay(reason: str = "GEX data not available") -> GEXOverlay:
    """Return a neutral overlay when GEX data is unavailable."""
    return GEXOverlay(
        spot=0.0,
        call_wall=0.0,
        put_wall=0.0,
        gamma_flip=0.0,
        regime="neutral",
        near_flip=False,
        total_gex=0.0,
        source="unavailable",
        error=reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_regime_inline(
    spot: float,
    gamma_flip: float,
    near_flip_points: float,
) -> tuple:
    """Inline regime classification without importing regime_detector."""
    if gamma_flip == 0:
        return "neutral", False

    near_flip = abs(spot - gamma_flip) <= near_flip_points

    if spot > gamma_flip:
        return "positive", near_flip
    elif spot < gamma_flip:
        return "negative", near_flip
    else:
        return "neutral", True


def _regime_to_strategy(regime: str, near_flip: bool) -> str:
    """Map gamma regime to recommended strategy."""
    if near_flip:
        return "reduce_size"
    if regime == "positive":
        return "silver_bullet"
    if regime == "negative":
        return "ny_am_reversal"
    return "both"
