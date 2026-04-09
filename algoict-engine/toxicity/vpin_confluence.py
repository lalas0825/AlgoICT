"""
toxicity/vpin_confluence.py
============================
VPIN-based confluence bonuses for the ICT scoring system.

Two bonus points from VPIN (per CLAUDE.md):
    | VPIN validated sweep | +1 | VPIN |
    | VPIN quality session | +1 | VPIN |

Sweep validation (+1):
    ICT detects a liquidity grab/sweep. If VPIN was elevated (>0.45)
    before or during the sweep, smart money was behind it → valid sweep.

Session quality (+1):
    If current VPIN is elevated during the Kill Zone, institutions are
    active and setups are more likely to follow through.

Usage:
    from toxicity.vpin_confluence import VPINConfluenceScorer, VPINConfluenceResult
    scorer = VPINConfluenceScorer()
    result = scorer.score(
        vpin=0.52,
        in_kill_zone=True,
        sweep_detected=True,
        vpin_at_sweep=0.48,
    )
    print(result.total_pts)       # 0, 1, or 2
    print(result.sweep_bonus)     # True/False
    print(result.session_bonus)   # True/False
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Thresholds from CLAUDE.md / VPIN skill
_SWEEP_VALIDATION_THRESHOLD = 0.45    # VPIN must be >= this at time of sweep
_SESSION_QUALITY_THRESHOLD = 0.45     # VPIN must be >= this during Kill Zone

# Point values
_SWEEP_PTS = 1
_SESSION_PTS = 1
_MAX_VPIN_PTS = _SWEEP_PTS + _SESSION_PTS   # 2


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class VPINConfluenceResult:
    """Result of VPIN confluence scoring."""

    sweep_bonus: bool           # +1 if VPIN validated the sweep
    session_bonus: bool         # +1 if VPIN shows active Kill Zone
    sweep_pts: int              # 0 or 1
    session_pts: int            # 0 or 1
    vpin: float                 # current VPIN
    vpin_at_sweep: Optional[float]   # VPIN reading at time of sweep
    reason: str = ""

    @property
    def total_pts(self) -> int:
        return self.sweep_pts + self.session_pts

    def __repr__(self) -> str:
        return (
            f"VPINConfluence(pts={self.total_pts} "
            f"sweep={self.sweep_bonus} session={self.session_bonus} "
            f"vpin={self.vpin:.3f})"
        )


# ---------------------------------------------------------------------------
# VPINConfluenceScorer
# ---------------------------------------------------------------------------

class VPINConfluenceScorer:
    """
    Awards VPIN-based confluence bonus points for ICT signal scoring.

    Parameters
    ----------
    sweep_threshold : float
        Minimum VPIN at sweep time to validate the sweep. Default 0.45.
    session_threshold : float
        Minimum current VPIN to award session quality bonus. Default 0.45.
    """

    def __init__(
        self,
        sweep_threshold: float = _SWEEP_VALIDATION_THRESHOLD,
        session_threshold: float = _SESSION_QUALITY_THRESHOLD,
    ):
        self._sweep_threshold = sweep_threshold
        self._session_threshold = session_threshold

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def score(
        self,
        vpin: float,
        in_kill_zone: bool = False,
        sweep_detected: bool = False,
        vpin_at_sweep: Optional[float] = None,
    ) -> VPINConfluenceResult:
        """
        Score VPIN confluence for a potential trade signal.

        Parameters
        ----------
        vpin : float
            Current VPIN reading.
        in_kill_zone : bool
            True if timestamp is within NY AM or Silver Bullet Kill Zone.
        sweep_detected : bool
            True if ICT detector found a liquidity sweep.
        vpin_at_sweep : float | None
            VPIN reading at the time of the sweep (can equal vpin if same bar).

        Returns
        -------
        VPINConfluenceResult
        """
        # Sweep validation bonus
        sweep_vpin = vpin_at_sweep if vpin_at_sweep is not None else vpin
        sweep_bonus = sweep_detected and sweep_vpin >= self._sweep_threshold
        sweep_pts = _SWEEP_PTS if sweep_bonus else 0

        # Session quality bonus
        session_bonus = in_kill_zone and vpin >= self._session_threshold
        session_pts = _SESSION_PTS if session_bonus else 0

        # Build reason
        parts = []
        if sweep_bonus:
            parts.append(
                f"VPIN {sweep_vpin:.3f} validates sweep (>{self._sweep_threshold})"
            )
        if session_bonus:
            parts.append(
                f"VPIN {vpin:.3f} confirms active Kill Zone (>{self._session_threshold})"
            )
        if not sweep_bonus and not session_bonus:
            parts.append(
                f"No VPIN bonus (vpin={vpin:.3f}, in_kz={in_kill_zone}, sweep={sweep_detected})"
            )

        reason = " | ".join(parts)

        logger.debug(
            "VPIN confluence: pts=%d sweep=%s session=%s vpin=%.3f",
            sweep_pts + session_pts, sweep_bonus, session_bonus, vpin,
        )

        return VPINConfluenceResult(
            sweep_bonus=sweep_bonus,
            session_bonus=session_bonus,
            sweep_pts=sweep_pts,
            session_pts=session_pts,
            vpin=vpin,
            vpin_at_sweep=vpin_at_sweep,
            reason=reason,
        )

    def validate_sweep(
        self,
        sweep_detected: bool,
        vpin_at_sweep: float,
    ) -> bool:
        """
        Check if a detected sweep is validated by VPIN.

        Returns True if sweep was driven by informed flow.
        """
        return sweep_detected and vpin_at_sweep >= self._sweep_threshold

    def assess_session_quality(
        self,
        in_kill_zone: bool,
        current_vpin: float,
    ) -> dict:
        """
        Assess Kill Zone session quality.

        Returns a dict with quality, bonus, and note keys.
        """
        if not in_kill_zone:
            return {"quality": "not_in_kz", "bonus": 0, "note": "Outside Kill Zone"}

        if current_vpin >= self._session_threshold:
            return {
                "quality": "high",
                "bonus": 1,
                "note": f"Active KZ — institutions present (VPIN={current_vpin:.3f})",
            }
        elif current_vpin < 0.35:
            return {
                "quality": "low",
                "bonus": 0,
                "note": f"Dead KZ — consider skipping (VPIN={current_vpin:.3f})",
            }
        else:
            return {
                "quality": "normal",
                "bonus": 0,
                "note": f"Standard KZ activity (VPIN={current_vpin:.3f})",
            }


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_scorer = VPINConfluenceScorer()


def score(
    vpin: float,
    in_kill_zone: bool = False,
    sweep_detected: bool = False,
    vpin_at_sweep: Optional[float] = None,
) -> VPINConfluenceResult:
    """Module-level convenience for scoring VPIN confluence."""
    return _default_scorer.score(
        vpin=vpin,
        in_kill_zone=in_kill_zone,
        sweep_detected=sweep_detected,
        vpin_at_sweep=vpin_at_sweep,
    )


def vpin_points_available() -> int:
    """Return max VPIN confluence points available."""
    return _MAX_VPIN_PTS
