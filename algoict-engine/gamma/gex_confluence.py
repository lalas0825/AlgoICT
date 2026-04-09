"""
gamma/gex_confluence.py
========================
GEX confluence bonus scoring for AlgoICT.

Adds +2 when an ICT signal aligns with a GEX wall (call wall, put wall,
or high-GEX level), and +1 for the gamma regime confirming the direction.

These are the two GEX-related points in the Confluence Scorer:
    | GEX wall alignment | +2 | GEX |
    | Gamma regime       | +1 | GEX |

Usage:
    from gamma.gex_confluence import score_gex_alignment, GEXConfluenceResult
    overlay = ...  # GEXOverlay from gex_overlay.py
    result = score_gex_alignment(
        entry_price=19500.0,
        direction="long",
        overlay=overlay,
    )
    print(result.total_pts)     # 0, 1, 2, or 3
    print(result.wall_bonus)    # True/False
    print(result.regime_bonus)  # True/False
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Tolerance (MNQ points) to be "near" a GEX wall
_DEFAULT_TOLERANCE = 10.0

# Point values (from CLAUDE.md confluence table)
_WALL_PTS = 2
_REGIME_PTS = 1
_MAX_GEX_PTS = _WALL_PTS + _REGIME_PTS   # 3


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GEXConfluenceResult:
    """Result of GEX confluence check."""

    wall_bonus: bool            # True if entry near a GEX wall
    regime_bonus: bool          # True if gamma regime confirms direction
    wall_pts: int               # 0 or 2
    regime_pts: int             # 0 or 1
    near_call_wall: bool
    near_put_wall: bool
    near_high_gex: bool
    regime: str                 # 'positive' | 'negative' | 'neutral'
    reason: str = ""            # Human-readable explanation

    @property
    def total_pts(self) -> int:
        return self.wall_pts + self.regime_pts

    def __repr__(self) -> str:
        return (
            f"GEXConfluence(pts={self.total_pts} "
            f"wall={self.wall_bonus} regime={self.regime_bonus} "
            f"[{self.regime}])"
        )


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_gex_alignment(
    entry_price: float,
    direction: str,
    overlay,
    tolerance: float = _DEFAULT_TOLERANCE,
) -> GEXConfluenceResult:
    """
    Score GEX confluence for a potential trade entry.

    Parameters
    ----------
    entry_price : float
        Proposed entry price.
    direction : str
        "long" or "short".
    overlay : GEXOverlay
        From gex_overlay.build_overlay().
    tolerance : float
        How close (in points) to a GEX level counts as "aligned".

    Returns
    -------
    GEXConfluenceResult with total_pts, wall_bonus, regime_bonus.
    """
    if overlay is None or not getattr(overlay, "is_valid", False):
        return _zero_result(reason="GEX overlay unavailable")

    direction_lower = direction.lower()

    # --- Wall alignment check ---
    near_call = overlay.is_near_call_wall(entry_price, tolerance)
    near_put = overlay.is_near_put_wall(entry_price, tolerance)
    near_high = overlay.is_near_gex_level(entry_price, tolerance)

    # For longs: aligning near put wall (support) or below call wall
    # For shorts: aligning near call wall (resistance) or above put wall
    wall_bonus = False
    wall_reason = ""

    if direction_lower == "long":
        if near_put:
            wall_bonus = True
            wall_reason = f"Long entry near put wall ({overlay.put_wall:.0f}) — dealer support"
        elif near_high:
            wall_bonus = True
            wall_reason = f"Long entry at high-GEX sticky zone"
    elif direction_lower == "short":
        if near_call:
            wall_bonus = True
            wall_reason = f"Short entry near call wall ({overlay.call_wall:.0f}) — dealer resistance"
        elif near_high:
            wall_bonus = True
            wall_reason = f"Short entry at high-GEX sticky zone"

    wall_pts = _WALL_PTS if wall_bonus else 0

    # --- Regime confirmation check ---
    regime = getattr(overlay, "regime", "neutral")
    near_flip = getattr(overlay, "near_flip", False)

    regime_bonus = False
    regime_reason = ""

    # Near flip = reduce_size, no regime bonus
    if not near_flip:
        if regime == "positive":
            # Positive gamma = mean reversion → Silver Bullet (both directions)
            # Bonus for going against recent move (ICT reversal)
            regime_bonus = True
            regime_reason = "Positive gamma regime — stabilizing (mean-reversion favored)"
        elif regime == "negative" and direction_lower in ("long", "short"):
            # Negative gamma = momentum → bonus for going WITH the move
            regime_bonus = True
            regime_reason = f"Negative gamma regime — amplifying (momentum {direction_lower})"
    else:
        regime_reason = "Near gamma flip — no regime bonus (high uncertainty)"

    regime_pts = _REGIME_PTS if regime_bonus else 0

    # Build full reason
    parts = []
    if wall_bonus:
        parts.append(wall_reason)
    if regime_bonus:
        parts.append(regime_reason)
    if not wall_bonus and not regime_bonus:
        parts.append(f"No GEX alignment (entry={entry_price:.0f}, call_wall={overlay.call_wall:.0f}, put_wall={overlay.put_wall:.0f})")
    full_reason = " | ".join(parts)

    logger.debug(
        "GEX confluence: direction=%s entry=%.0f pts=%d (%s)",
        direction_lower, entry_price, wall_pts + regime_pts, full_reason,
    )

    return GEXConfluenceResult(
        wall_bonus=wall_bonus,
        regime_bonus=regime_bonus,
        wall_pts=wall_pts,
        regime_pts=regime_pts,
        near_call_wall=near_call,
        near_put_wall=near_put,
        near_high_gex=near_high,
        regime=regime,
        reason=full_reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zero_result(reason: str = "") -> GEXConfluenceResult:
    return GEXConfluenceResult(
        wall_bonus=False,
        regime_bonus=False,
        wall_pts=0,
        regime_pts=0,
        near_call_wall=False,
        near_put_wall=False,
        near_high_gex=False,
        regime="neutral",
        reason=reason,
    )


def gex_points_available(overlay) -> int:
    """
    Return the maximum GEX points possible given the current overlay.
    Returns 0 if overlay is unavailable, 3 if fully available.
    """
    if overlay is None or not getattr(overlay, "is_valid", False):
        return 0
    return _MAX_GEX_PTS
