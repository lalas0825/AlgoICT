"""
sentiment/confluence_adjuster.py
==================================
Maps economic event risk levels to confluence / position-size adjustments.

These adjustments are applied by RiskManager on event days:
  - min_confluence raised  -> fewer, higher-quality signals required
  - position_multiplier    -> scales contracts (via RiskManager.position_multiplier)

Risk -> Adjustment mapping:
  extreme : min_confluence=10, position_multiplier=0.5   (FOMC etc.)
  high    : min_confluence=9,  position_multiplier=0.75  (CPI, NFP)
  medium  : min_confluence=8,  position_multiplier=0.90  (GDP, PCE, Retail)
  low     : min_confluence=7,  position_multiplier=1.0   (standard ICT rules)
  none    : min_confluence=7,  position_multiplier=1.0

Usage:
    from sentiment.confluence_adjuster import get_adjustments
    adj = get_adjustments('high')
    # {'min_confluence': 9, 'position_multiplier': 0.75, 'risk_level': 'high'}
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Adjustment dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Adjustments:
    risk_level: str
    min_confluence: int
    position_multiplier: float
    description: str = ""

    def as_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "min_confluence": self.min_confluence,
            "position_multiplier": self.position_multiplier,
            "description": self.description,
        }

    def __repr__(self) -> str:
        return (
            f"Adjustments(risk={self.risk_level} "
            f"min_conf={self.min_confluence} "
            f"pos_mult={self.position_multiplier})"
        )


# ---------------------------------------------------------------------------
# Adjustment table
# ---------------------------------------------------------------------------

_ADJUSTMENTS: dict[str, Adjustments] = {
    "extreme": Adjustments(
        risk_level="extreme",
        min_confluence=10,
        position_multiplier=0.5,
        description="FOMC: half size, A-grade setups only",
    ),
    "high": Adjustments(
        risk_level="high",
        min_confluence=9,
        position_multiplier=0.75,
        description="CPI/NFP: reduced size, elevated quality bar",
    ),
    "medium": Adjustments(
        risk_level="medium",
        min_confluence=8,
        position_multiplier=0.90,
        description="GDP/PCE/Retail: slight reduction, tighter confluence",
    ),
    "low": Adjustments(
        risk_level="low",
        min_confluence=7,
        position_multiplier=1.0,
        description="Low-impact event: standard ICT rules apply",
    ),
    "none": Adjustments(
        risk_level="none",
        min_confluence=7,
        position_multiplier=1.0,
        description="No event: standard ICT rules apply",
    ),
}

# Valid risk levels (ordered low to high)
RISK_LEVELS = ("none", "low", "medium", "high", "extreme")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_adjustments(event_risk: str) -> dict:
    """
    Return adjustment dict for the given event risk level.

    Parameters
    ----------
    event_risk : str — one of 'none' | 'low' | 'medium' | 'high' | 'extreme'

    Returns
    -------
    dict with keys: risk_level, min_confluence, position_multiplier, description

    Raises
    ------
    ValueError if event_risk is not a valid risk level.
    """
    key = event_risk.lower().strip()
    if key not in _ADJUSTMENTS:
        raise ValueError(
            f"Unknown risk level: {event_risk!r}. "
            f"Valid: {RISK_LEVELS}"
        )

    adj = _ADJUSTMENTS[key]
    logger.debug("Adjustments for risk=%s: %s", key, adj)
    return adj.as_dict()


def get_adjustments_obj(event_risk: str) -> Adjustments:
    """
    Same as get_adjustments() but returns the typed Adjustments dataclass.
    """
    key = event_risk.lower().strip()
    if key not in _ADJUSTMENTS:
        raise ValueError(
            f"Unknown risk level: {event_risk!r}. "
            f"Valid: {RISK_LEVELS}"
        )
    return _ADJUSTMENTS[key]


def describe_risk(event_risk: str) -> str:
    """Return a human-readable description of what the risk level means for trading."""
    adj = get_adjustments_obj(event_risk)
    return adj.description


def is_trading_restricted(event_risk: str) -> bool:
    """
    True if event risk warrants extra caution (min_confluence > base 7).
    """
    adj = get_adjustments_obj(event_risk)
    return adj.min_confluence > 7
