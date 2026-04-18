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
# Mood-driven adjustments
# ---------------------------------------------------------------------------
#
# Added 2026-04-17 after audit showed `mood` labels (choppy, risk_off,
# event_driven, etc.) were informational only and never reached the risk
# manager. A "choppy" mood on an event-free day used to get zero penalty,
# contrary to the documented design.
#
# Mood adjustments COMPOSE with event_risk adjustments by taking the
# stricter of the two: max(min_confluence), min(position_multiplier).
# This way a choppy day WITH a high-impact event still applies the full
# event tightening, and a choppy day WITHOUT an event still gets a
# meaningful conservatism bump.

_MOOD_ADJUSTMENTS: dict[str, Adjustments] = {
    "choppy": Adjustments(
        risk_level="choppy",
        min_confluence=9,
        position_multiplier=0.75,
        description="Choppy mood: whipsaw risk, tighter quality bar + -25% size",
    ),
    "event_driven": Adjustments(
        risk_level="event_driven",
        min_confluence=9,
        position_multiplier=0.75,
        description="Event-driven: uncertainty, tighter quality + -25% size",
    ),
    "risk_off": Adjustments(
        risk_level="risk_off",
        min_confluence=8,
        position_multiplier=0.90,
        description="Risk-off mood: slight tightening, -10% size",
    ),
    "risk_on": Adjustments(
        risk_level="risk_on",
        min_confluence=7,
        position_multiplier=1.0,
        description="Risk-on mood: standard ICT rules apply",
    ),
    "normal": Adjustments(
        risk_level="normal",
        min_confluence=7,
        position_multiplier=1.0,
        description="Normal mood: standard ICT rules apply",
    ),
}


def get_mood_adjustments(mood: str) -> Adjustments:
    """Return Adjustments for a mood label.

    Fail-closed: unknown / empty / corrupted labels default to ``choppy``
    (min_conf=9, pos_mult=0.75) — NOT ``normal``. A typo or unexpected
    label from an upstream source must not silently disable the mood
    gate; meta-audit 2026-04-17 flagged the prior fail-open default as
    permissive. Choppy is the conservative assumption when we don't
    know what market regime we're in.
    """
    key = (mood or "").lower().strip().replace("-", "_").replace(" ", "_")
    adj = _MOOD_ADJUSTMENTS.get(key)
    if adj is not None:
        return adj
    logger.warning(
        "Unknown mood label %r — falling back to 'choppy' (conservative)",
        mood,
    )
    return _MOOD_ADJUSTMENTS["choppy"]


def combine_adjustments(
    event_risk: str,
    mood: str,
) -> Adjustments:
    """Return the strictest of event-risk and mood adjustments.

    Stricter = higher min_confluence (quality bar) + lower
    position_multiplier (size). risk_level is labeled with the
    dominant source so logs stay readable.
    """
    event_adj = get_adjustments_obj(event_risk)
    mood_adj = get_mood_adjustments(mood)
    # Stricter: max min_conf, min pos_mult
    combined_min_conf = max(event_adj.min_confluence, mood_adj.min_confluence)
    combined_pos_mult = min(event_adj.position_multiplier, mood_adj.position_multiplier)
    # Label with whichever side drove the decision; event wins on ties
    if combined_min_conf == event_adj.min_confluence and combined_pos_mult == event_adj.position_multiplier:
        label = f"event:{event_adj.risk_level}"
        desc = event_adj.description
    elif combined_min_conf == mood_adj.min_confluence and combined_pos_mult == mood_adj.position_multiplier:
        label = f"mood:{mood_adj.risk_level}"
        desc = mood_adj.description
    else:
        label = f"event:{event_adj.risk_level}+mood:{mood_adj.risk_level}"
        desc = f"{event_adj.description} | {mood_adj.description}"
    return Adjustments(
        risk_level=label,
        min_confluence=combined_min_conf,
        position_multiplier=combined_pos_mult,
        description=desc,
    )


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
