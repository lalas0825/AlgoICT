"""
backtest/combine_simulator.py
==============================
Simulates the Topstep $50K Combine rules against a list of backtest trades.

Rules
-----
- Starting balance    : $50,000
- Profit target       : $3,000  (reach $53,000)
- Max Loss Limit (MLL): $2,000  trailing from the highest EOD balance achieved
                        (account balance must never drop >= $2,000 below the
                         running peak EOD balance)
- Daily Loss Limit    : $1,000  (daily realised P&L must not go below -$1,000)
- Consistency rule    : best single day < 50% of total profit
                        (only applies when target is reached)
- Minimum trading days: 5 calendar days with at least 1 trade each

Simulation details
------------------
- Trades are processed in entry_time order.
- EOD balance high is updated once per calendar day after all trades that day
  are closed.  We update it conservatively: only if the day closed higher than
  the previous EOD high.
- MLL check is intraday: computed after each trade closes.
- DLL check is intraday: computed after each trade closes.
- When any hard limit is breached the simulate stops and records why.
"""

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


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DayRecord:
    date: datetime.date
    pnl: float
    balance_eod: float
    trades: int


@dataclass
class CombineResult:
    """Outcome of simulate_combine()."""

    passed: bool
    failure_reason: Optional[str]   # None if passed
    starting_balance: float
    ending_balance: float
    peak_balance: float             # highest EOD balance reached

    total_pnl: float
    total_trades: int
    trading_days: int               # days with >= 1 trade
    total_days: int                 # calendar days from first to last trade

    profit_target: float
    mll_limit: float
    dll_limit: float

    days: list = field(default_factory=list)  # list[DayRecord]
    best_day_pnl: float = 0.0
    best_day_date: Optional[datetime.date] = None
    consistency_ok: Optional[bool] = None    # None if target not reached

    def __repr__(self) -> str:
        status = "PASSED" if self.passed else f"FAILED({self.failure_reason})"
        return (
            f"CombineResult({status} "
            f"pnl=${self.total_pnl:+.2f} "
            f"balance=${self.ending_balance:.2f} "
            f"days={self.trading_days})"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def simulate_combine(
    trades,
    starting_balance: float = config.TOPSTEP_ACCOUNT_SIZE,
) -> CombineResult:
    """
    Simulate Topstep $50K Combine rules.

    Parameters
    ----------
    trades           : list[Trade]  — from BacktestResult.trades, chronological
    starting_balance : float        — default $50,000

    Returns
    -------
    CombineResult
    """
    if not trades:
        return CombineResult(
            passed=False,
            failure_reason="no_trades",
            starting_balance=starting_balance,
            ending_balance=starting_balance,
            peak_balance=starting_balance,
            total_pnl=0.0,
            total_trades=0,
            trading_days=0,
            total_days=0,
            profit_target=config.TOPSTEP_PROFIT_TARGET,
            mll_limit=config.TOPSTEP_MLL,
            dll_limit=config.TOPSTEP_DLL,
        )

    # Sort trades by entry_time
    sorted_trades = sorted(trades, key=lambda t: t.entry_time)

    # Group by calendar date (using entry_time)
    days_map: dict[datetime.date, list] = {}
    for t in sorted_trades:
        try:
            d = t.entry_time.date()
        except AttributeError:
            d = t.entry_time.to_pydatetime().date()
        days_map.setdefault(d, []).append(t)

    balance = starting_balance
    peak_eod_balance = starting_balance   # MLL tracks from the EOD peak
    day_records: list[DayRecord] = []
    failure_reason: Optional[str] = None

    best_day_pnl = 0.0
    best_day_date: Optional[datetime.date] = None

    for date in sorted(days_map.keys()):
        day_trades = days_map[date]
        daily_pnl = 0.0

        for t in day_trades:
            daily_pnl += t.pnl
            balance += t.pnl
            running_balance = balance

            # MLL check (intraday): balance must not drop >= MLL below peak EOD
            if peak_eod_balance - running_balance >= config.TOPSTEP_MLL:
                failure_reason = (
                    f"mll_breach on {date}: "
                    f"balance=${running_balance:.2f} "
                    f"(peak_eod=${peak_eod_balance:.2f}, "
                    f"drawdown=${peak_eod_balance - running_balance:.2f} "
                    f">= mll=${config.TOPSTEP_MLL})"
                )
                logger.warning("Combine FAILED: %s", failure_reason)
                # Record partial day
                day_records.append(DayRecord(
                    date=date,
                    pnl=daily_pnl,
                    balance_eod=balance,
                    trades=len(day_trades),
                ))
                return _build_result(
                    passed=False,
                    failure_reason=failure_reason,
                    starting_balance=starting_balance,
                    balance=balance,
                    peak_balance=peak_eod_balance,
                    day_records=day_records,
                    sorted_trades=sorted_trades,
                    best_day_pnl=best_day_pnl,
                    best_day_date=best_day_date,
                )

        # DLL check (end of day): daily P&L must not be < -DLL
        if daily_pnl < -config.TOPSTEP_DLL:
            failure_reason = (
                f"dll_breach on {date}: "
                f"daily_pnl=${daily_pnl:.2f} < "
                f"-dll=${config.TOPSTEP_DLL}"
            )
            logger.warning("Combine FAILED: %s", failure_reason)
            day_records.append(DayRecord(
                date=date, pnl=daily_pnl, balance_eod=balance, trades=len(day_trades),
            ))
            return _build_result(
                passed=False,
                failure_reason=failure_reason,
                starting_balance=starting_balance,
                balance=balance,
                peak_balance=peak_eod_balance,
                day_records=day_records,
                sorted_trades=sorted_trades,
                best_day_pnl=best_day_pnl,
                best_day_date=best_day_date,
            )

        # Update EOD peak
        if balance > peak_eod_balance:
            peak_eod_balance = balance

        # Track best day
        if daily_pnl > best_day_pnl:
            best_day_pnl = daily_pnl
            best_day_date = date

        day_records.append(DayRecord(
            date=date, pnl=daily_pnl, balance_eod=balance, trades=len(day_trades),
        ))

    # ── Final checks ──────────────────────────────────────────────────────
    total_pnl = balance - starting_balance

    # Minimum trading days
    trading_days = len(days_map)
    if trading_days < 5:
        failure_reason = (
            f"insufficient_trading_days: {trading_days} < 5 required"
        )
        return _build_result(
            passed=False,
            failure_reason=failure_reason,
            starting_balance=starting_balance,
            balance=balance,
            peak_balance=peak_eod_balance,
            day_records=day_records,
            sorted_trades=sorted_trades,
            best_day_pnl=best_day_pnl,
            best_day_date=best_day_date,
        )

    # Profit target
    if total_pnl < config.TOPSTEP_PROFIT_TARGET:
        failure_reason = (
            f"profit_target_not_reached: "
            f"pnl=${total_pnl:.2f} < target=${config.TOPSTEP_PROFIT_TARGET}"
        )
        return _build_result(
            passed=False,
            failure_reason=failure_reason,
            starting_balance=starting_balance,
            balance=balance,
            peak_balance=peak_eod_balance,
            day_records=day_records,
            sorted_trades=sorted_trades,
            best_day_pnl=best_day_pnl,
            best_day_date=best_day_date,
        )

    # Consistency: best day < 50% of total profit
    consistency_ok = best_day_pnl < 0.5 * total_pnl
    if not consistency_ok:
        failure_reason = (
            f"consistency_rule_violated: "
            f"best_day=${best_day_pnl:.2f} >= 50% of "
            f"total_pnl=${total_pnl:.2f}"
        )
        return _build_result(
            passed=False,
            failure_reason=failure_reason,
            starting_balance=starting_balance,
            balance=balance,
            peak_balance=peak_eod_balance,
            day_records=day_records,
            sorted_trades=sorted_trades,
            best_day_pnl=best_day_pnl,
            best_day_date=best_day_date,
            consistency_ok=consistency_ok,
        )

    logger.info(
        "Combine PASSED: pnl=$%.2f in %d trading days", total_pnl, trading_days
    )
    return _build_result(
        passed=True,
        failure_reason=None,
        starting_balance=starting_balance,
        balance=balance,
        peak_balance=peak_eod_balance,
        day_records=day_records,
        sorted_trades=sorted_trades,
        best_day_pnl=best_day_pnl,
        best_day_date=best_day_date,
        consistency_ok=True,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_result(
    passed, failure_reason,
    starting_balance, balance, peak_balance,
    day_records, sorted_trades,
    best_day_pnl, best_day_date,
    consistency_ok=None,
) -> CombineResult:
    total_days = 0
    if day_records:
        first_d = day_records[0].date
        last_d = day_records[-1].date
        total_days = (last_d - first_d).days + 1

    return CombineResult(
        passed=passed,
        failure_reason=failure_reason,
        starting_balance=starting_balance,
        ending_balance=balance,
        peak_balance=peak_balance,
        total_pnl=balance - starting_balance,
        total_trades=len(sorted_trades),
        trading_days=len(day_records),
        total_days=total_days,
        profit_target=config.TOPSTEP_PROFIT_TARGET,
        mll_limit=config.TOPSTEP_MLL,
        dll_limit=config.TOPSTEP_DLL,
        days=day_records,
        best_day_pnl=best_day_pnl,
        best_day_date=best_day_date,
        consistency_ok=consistency_ok,
    )
