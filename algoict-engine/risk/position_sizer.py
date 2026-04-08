"""
risk/position_sizer.py
======================
ICT Position sizing — risk-based with floor() and expanded stop.

Sensei Rule: Risk exactly $250/trade. Never use raw stop distance as-is —
floor the contracts then expand the stop to maintain the dollar risk.

Algorithm
---------
  raw_contracts = risk_dollars / (stop_points × point_value)
  contracts     = floor(raw_contracts)   ← always down, never up
  contracts     = clamp(contracts, 1, max_contracts)
  actual_stop   = risk_dollars / (contracts × point_value)
  breathing_room = actual_stop - stop_points   ← extra wiggle room

Example (MNQ, stop = 15 pts, risk = $250, point_value = $2.0):
  raw = 250 / (15 × 2) = 8.33 → contracts = 8
  actual_stop = 250 / (8 × 2) = 15.625
  breathing = 15.625 - 15 = 0.625 pts

MNQ point value: $2.00 per point per contract
NQ  point value: $20.00 per point per contract
"""

import math
import logging
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

logger = logging.getLogger(__name__)


@dataclass
class PositionResult:
    """Output of position size calculation."""

    contracts: int          # Final contract count (floor, clamped)
    actual_stop_points: float  # Expanded stop that preserves dollar risk
    breathing_room: float   # actual_stop - requested_stop (extra wiggle)
    risk_dollars: float     # Dollar risk (== config.RISK_PER_TRADE)

    def __repr__(self) -> str:
        return (
            f"PositionResult(contracts={self.contracts}, "
            f"stop={self.actual_stop_points:.3f}pts, "
            f"breathing={self.breathing_room:.3f}pts, "
            f"risk=${self.risk_dollars:.2f})"
        )


def calculate_position(
    stop_points: float,
    risk: float = config.RISK_PER_TRADE,
    point_value: float = 2.0,       # MNQ: $2/point/contract
    max_contracts: int = config.MAX_CONTRACTS,
) -> PositionResult:
    """
    Calculate position size given a stop distance.

    Parameters
    ----------
    stop_points    : float — distance from entry to stop (in price points)
    risk           : float — dollar risk to target (default $250)
    point_value    : float — dollar value per point per contract (MNQ = $2.00)
    max_contracts  : int   — hard ceiling (default config.MAX_CONTRACTS = 50)

    Returns
    -------
    PositionResult

    Raises
    ------
    ValueError if stop_points <= 0 or point_value <= 0
    """
    if stop_points <= 0:
        raise ValueError(f"stop_points must be > 0, got {stop_points}")
    if point_value <= 0:
        raise ValueError(f"point_value must be > 0, got {point_value}")
    if risk <= 0:
        raise ValueError(f"risk must be > 0, got {risk}")

    raw = risk / (stop_points * point_value)
    contracts = max(1, min(math.floor(raw), max_contracts))

    actual_stop = risk / (contracts * point_value)
    breathing_room = actual_stop - stop_points

    result = PositionResult(
        contracts=contracts,
        actual_stop_points=actual_stop,
        breathing_room=breathing_room,
        risk_dollars=risk,
    )
    logger.debug(
        "Position: stop=%.2f pts → %d contracts, actual_stop=%.3f, breathing=%.3f",
        stop_points, contracts, actual_stop, breathing_room,
    )
    return result
