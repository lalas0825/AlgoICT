"""
backtest/risk_audit.py
=======================
Verifies that every trade in a backtest result obeys AlgoICT risk rules.
Returns ZERO violations or a detailed list of what broke.

Rules checked
-------------
Per-trade:
  1. Max risk <= $250  (stop_distance * contracts * point_value)
  2. Floor sizing     (contracts == floor(250 / (stop_distance * 2.0)), or 1 if
                       the raw quotient is < 1)
  3. Hard close       (non-hard_close trades must exit before 15:00 CT)
  4. Min confluence   (confluence_score >= 7)

Per-day:
  5. Kill switch      (no trade taken AFTER 3 consecutive losses within a day)
  6. Profit cap       (no trade taken when cumulative daily P&L >= $1,500)
"""

import math
import datetime
import logging
from dataclasses import dataclass, field
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

logger = logging.getLogger(__name__)

MNQ_POINT_VALUE = config.MNQ_POINT_VALUE
_HARD_CLOSE_TIME = datetime.time(config.HARD_CLOSE_HOUR, config.HARD_CLOSE_MINUTE)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TradeViolation:
    """Violations found for a single trade."""
    trade_index: int
    entry_time: object          # pd.Timestamp
    reason: str
    detail: str


@dataclass
class AuditResult:
    """Outcome of audit_trades()."""
    is_clean: bool
    violations: list = field(default_factory=list)   # list[str]  (summary)
    trade_violations: list = field(default_factory=list)  # list[TradeViolation]
    violation_count: int = 0

    def __repr__(self) -> str:
        status = "CLEAN" if self.is_clean else f"VIOLATIONS({self.violation_count})"
        return f"AuditResult({status})"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def audit_trades(trades) -> AuditResult:
    """
    Audit a list of Trade objects from a BacktestResult.

    Parameters
    ----------
    trades : list[Trade]

    Returns
    -------
    AuditResult — is_clean=True if no violations found.
    """
    all_violations: list[TradeViolation] = []
    summary: list[str] = []

    # Group trades by calendar date (entry_time.date())
    days: dict[datetime.date, list[tuple[int, object]]] = {}
    for i, t in enumerate(trades):
        try:
            d = t.entry_time.date()
        except AttributeError:
            d = t.entry_time.to_pydatetime().date()
        days.setdefault(d, []).append((i, t))

    for date, day_trades in sorted(days.items()):
        consecutive_losses = 0
        daily_pnl = 0.0

        for i, t in day_trades:
            stop_distance = abs(t.entry_price - t.stop_price)

            # ── Rule 1: Max risk ───────────────────────────────────────────
            actual_risk = stop_distance * t.contracts * MNQ_POINT_VALUE
            if actual_risk > config.RISK_PER_TRADE + 0.01:   # 1-cent tolerance
                v = TradeViolation(
                    trade_index=i,
                    entry_time=t.entry_time,
                    reason="max_risk_exceeded",
                    detail=(
                        f"risk=${actual_risk:.2f} > ${config.RISK_PER_TRADE} "
                        f"(stop_dist={stop_distance:.4f}, contracts={t.contracts})"
                    ),
                )
                all_violations.append(v)
                summary.append(f"[{i}] max_risk_exceeded: {v.detail}")

            # ── Rule 2: Floor sizing ───────────────────────────────────────
            if stop_distance > 0:
                raw_contracts = config.RISK_PER_TRADE / (stop_distance * MNQ_POINT_VALUE)
                expected = max(1, min(int(math.floor(raw_contracts)), config.MAX_CONTRACTS))
                # Allow soft override to reduce (multiplier < 1 is OK); flag if MORE
                if t.contracts > expected:
                    v = TradeViolation(
                        trade_index=i,
                        entry_time=t.entry_time,
                        reason="oversized_position",
                        detail=(
                            f"contracts={t.contracts} > floor({raw_contracts:.2f})={expected}"
                        ),
                    )
                    all_violations.append(v)
                    summary.append(f"[{i}] oversized_position: {v.detail}")

            # ── Rule 3: Hard close ─────────────────────────────────────────
            if t.reason != "hard_close":
                try:
                    exit_time = t.exit_time.time()
                except AttributeError:
                    exit_time = t.exit_time.to_pydatetime().time()
                if exit_time >= _HARD_CLOSE_TIME:
                    v = TradeViolation(
                        trade_index=i,
                        entry_time=t.entry_time,
                        reason="hard_close_violation",
                        detail=(
                            f"non-hard_close trade exited at {exit_time} "
                            f"(must be before {_HARD_CLOSE_TIME})"
                        ),
                    )
                    all_violations.append(v)
                    summary.append(f"[{i}] hard_close_violation: {v.detail}")

            # ── Rule 4: Min confluence ─────────────────────────────────────
            if t.confluence_score < config.MIN_CONFLUENCE:
                v = TradeViolation(
                    trade_index=i,
                    entry_time=t.entry_time,
                    reason="low_confluence",
                    detail=(
                        f"confluence_score={t.confluence_score} < "
                        f"min={config.MIN_CONFLUENCE}"
                    ),
                )
                all_violations.append(v)
                summary.append(f"[{i}] low_confluence: {v.detail}")

            # ── Rule 5: Kill switch ────────────────────────────────────────
            # A trade is a violation if it was taken AFTER the kill switch
            # would have been triggered by previous losses that day.
            if consecutive_losses >= config.KILL_SWITCH_LOSSES:
                v = TradeViolation(
                    trade_index=i,
                    entry_time=t.entry_time,
                    reason="kill_switch_violation",
                    detail=(
                        f"trade taken after {consecutive_losses} consecutive "
                        f"losses on {date}"
                    ),
                )
                all_violations.append(v)
                summary.append(f"[{i}] kill_switch_violation: {v.detail}")

            # ── Rule 6: Profit cap ─────────────────────────────────────────
            if daily_pnl >= config.DAILY_PROFIT_CAP:
                v = TradeViolation(
                    trade_index=i,
                    entry_time=t.entry_time,
                    reason="profit_cap_violation",
                    detail=(
                        f"trade taken when daily_pnl=${daily_pnl:.2f} >= "
                        f"cap=${config.DAILY_PROFIT_CAP}"
                    ),
                )
                all_violations.append(v)
                summary.append(f"[{i}] profit_cap_violation: {v.detail}")

            # ── Update running state ───────────────────────────────────────
            daily_pnl += t.pnl
            if t.pnl < 0:
                consecutive_losses += 1
            else:
                consecutive_losses = 0

    is_clean = len(all_violations) == 0
    result = AuditResult(
        is_clean=is_clean,
        violations=summary,
        trade_violations=all_violations,
        violation_count=len(all_violations),
    )

    if is_clean:
        logger.info("Risk audit PASSED — ZERO violations (%d trades)", len(trades))
    else:
        logger.warning(
            "Risk audit FAILED — %d violation(s) across %d trades",
            len(all_violations), len(trades),
        )
        for msg in summary:
            logger.warning("  %s", msg)

    return result
