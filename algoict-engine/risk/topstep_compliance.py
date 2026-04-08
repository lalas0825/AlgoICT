"""
risk/topstep_compliance.py
===========================
Topstep $50K Combine compliance checks — Sensei Rules enforced here.

Rules (HARDCODED)
-----------------
MLL  (Max Loss Limit)   : running account balance must not fall more than
                          $2,000 below the highest balance reached.
                          balance < balance_high - $2,000 → VIOLATION

DLL  (Daily Loss Limit) : P&L for the current session must not exceed -$1,000.
                          daily_pnl < -$1,000 → VIOLATION

MAX CONTRACTS           : No more than 50 MNQ contracts at one time.
                          num_contracts > 50 → VIOLATION

HARD CLOSE              : Positions must not be open past 3:10 PM CT.
                          time > 15:10 CT with num_contracts > 0 → VIOLATION
                          (15:10 gives a 10-minute warning before 15:00 hard close)

NOTE: The engine's hard close fires at 3:00 PM CT (config.HARD_CLOSE_HOUR).
      Topstep checks 15:10 because they enforce it on their side with a margin.
      Operating correctly means the engine never reaches 15:10 with open positions.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, time

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

logger = logging.getLogger(__name__)

# Topstep hard deadline — engine should have closed at 15:00 CT
TOPSTEP_DEADLINE_HOUR = 15
TOPSTEP_DEADLINE_MINUTE = 10


@dataclass
class ComplianceResult:
    """Result of a Topstep compliance check."""

    is_compliant: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        status = "COMPLIANT" if self.is_compliant else f"VIOLATION({', '.join(self.violations)})"
        return f"ComplianceResult({status})"


def check_compliance(
    balance: float,
    balance_high: float,
    daily_pnl: float,
    num_contracts: int,
    current_time_ct: datetime,
) -> ComplianceResult:
    """
    Run all Topstep Combine compliance checks.

    Parameters
    ----------
    balance          : float    — current account balance
    balance_high     : float    — highest balance ever reached (trailing MLL reference)
    daily_pnl        : float    — today's realized P&L
    num_contracts    : int      — number of open contracts right now
    current_time_ct  : datetime — current time in US/Central (tz-aware or naive)

    Returns
    -------
    ComplianceResult — is_compliant=True only if ALL checks pass
    """
    violations: list[str] = []
    warnings: list[str] = []

    # ── 1. MLL: balance must not fall more than $2,000 below balance_high ─
    mll_floor = balance_high - config.TOPSTEP_MLL
    if balance < mll_floor:
        msg = (
            f"MLL VIOLATION: balance ${balance:.2f} < floor ${mll_floor:.2f} "
            f"(high=${balance_high:.2f} - ${config.TOPSTEP_MLL})"
        )
        violations.append("MLL")
        logger.critical(msg)
    elif balance < mll_floor + 200:
        # Warning at $200 above the MLL floor
        warnings.append(f"MLL WARNING: within $200 of floor (${mll_floor:.2f})")

    # ── 2. DLL: daily loss must not exceed -$1,000 ─────────────────────────
    if daily_pnl < -config.TOPSTEP_DLL:
        msg = (
            f"DLL VIOLATION: daily_pnl ${daily_pnl:.2f} < "
            f"-${config.TOPSTEP_DLL}"
        )
        violations.append("DLL")
        logger.critical(msg)
    elif daily_pnl < -(config.TOPSTEP_DLL - 100):
        warnings.append(f"DLL WARNING: within $100 of daily limit (${daily_pnl:.2f})")

    # ── 3. Max contracts ────────────────────────────────────────────────────
    if num_contracts > config.MAX_CONTRACTS:
        msg = (
            f"MAX_CONTRACTS VIOLATION: {num_contracts} > {config.MAX_CONTRACTS}"
        )
        violations.append("MAX_CONTRACTS")
        logger.critical(msg)

    # ── 4. Hard time: no open positions past 15:10 CT ──────────────────────
    t = current_time_ct.time() if hasattr(current_time_ct, "time") else current_time_ct
    deadline = time(TOPSTEP_DEADLINE_HOUR, TOPSTEP_DEADLINE_MINUTE)
    if t >= deadline and num_contracts > 0:
        msg = (
            f"TIME VIOLATION: {t.strftime('%H:%M')} CT with {num_contracts} "
            f"open contracts (deadline {deadline.strftime('%H:%M')} CT)"
        )
        violations.append("TIME")
        logger.critical(msg)
    elif t >= time(config.HARD_CLOSE_HOUR, config.HARD_CLOSE_MINUTE) and num_contracts > 0:
        # Engine should have already closed — warn
        warnings.append(
            f"TIME WARNING: past hard close {config.HARD_CLOSE_HOUR}:00 CT "
            f"with {num_contracts} open contracts"
        )

    is_compliant = len(violations) == 0
    result = ComplianceResult(
        is_compliant=is_compliant,
        violations=violations,
        warnings=warnings,
    )
    if not is_compliant:
        logger.critical("TOPSTEP COMPLIANCE FAILED: %s", result)
    else:
        logger.debug("Topstep compliance OK")
    return result


def is_within_profit_target(balance: float) -> bool:
    """Return True if account has reached or exceeded the $3,000 Combine target."""
    return (balance - config.TOPSTEP_ACCOUNT_SIZE) >= config.TOPSTEP_PROFIT_TARGET
