"""
risk/risk_manager.py
====================
Intraday risk state machine — enforces all Sensei Rules in real time.

Hard rules (HARDCODED, cannot be overridden):
  - Kill switch: 3 consecutive losses → done for the day
  - Kill switch amount: daily_pnl < -$750 → done for the day
  - Profit cap: daily_pnl >= $1,500 → stop trading
  - Hard close: 3:00 PM CT → flatten everything
  - Max MNQ trades: 3 per day

Soft overrides (applied by SWC / VPIN modules):
  - SWC: can raise min_confluence requirement and reduce position size
  - VPIN extreme: halt all trading (vpin_halted = True)
  - VPIN high: reduce position size, raise min_confluence

Override priority:
  VPIN halt > Kill switch > Profit cap > Hard close > Max trades > OK
"""

import logging
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Tracks intraday P&L and enforces all risk rules.

    Usage
    -----
    rm = RiskManager()
    rm.record_trade(-250)   # lost $250
    allowed, reason = rm.can_trade()
    rm.reset_daily()        # call at start of each session
    """

    def __init__(self):
        # Daily P&L state
        self.daily_pnl: float = 0.0
        self.consecutive_losses: int = 0
        self.trades_today: int = 0

        # Hard stop flags
        self.kill_switch_active: bool = False
        self.profit_cap_active: bool = False

        # Soft override state (set by SWC / VPIN modules)
        self._min_confluence_adj: int = 0    # +N added to min confluence
        self._position_multiplier: float = 1.0  # 0.75 = 25% reduction
        self._vpin_halted: bool = False

    # ------------------------------------------------------------------ #
    # Public API — state updates                                           #
    # ------------------------------------------------------------------ #

    def record_trade(self, pnl: float) -> None:
        """
        Record a completed trade P&L and update all risk counters.

        Parameters
        ----------
        pnl : float — profit (+) or loss (-) in dollars
        """
        self.daily_pnl += pnl
        self.trades_today += 1

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # ── Kill switch: 3 consecutive losses ──────────────────────────
        if self.consecutive_losses >= config.KILL_SWITCH_LOSSES:
            self.kill_switch_active = True
            logger.warning(
                "KILL SWITCH: %d consecutive losses (daily_pnl=%.2f)",
                self.consecutive_losses, self.daily_pnl,
            )

        # ── Kill switch: daily loss exceeds $750 ────────────────────────
        if self.daily_pnl <= -config.KILL_SWITCH_AMOUNT:
            self.kill_switch_active = True
            logger.warning(
                "KILL SWITCH: daily loss limit hit (daily_pnl=%.2f)",
                self.daily_pnl,
            )

        # ── Profit cap: $1,500/day ──────────────────────────────────────
        if self.daily_pnl >= config.DAILY_PROFIT_CAP:
            self.profit_cap_active = True
            logger.info(
                "PROFIT CAP: daily target hit (daily_pnl=%.2f)", self.daily_pnl,
            )

        logger.debug(
            "Trade recorded: pnl=%.2f | daily=%.2f | losses=%d | trades=%d",
            pnl, self.daily_pnl, self.consecutive_losses, self.trades_today,
        )

    def can_trade(self) -> tuple[bool, str]:
        """
        Check whether a new trade is allowed under all current risk rules.

        Returns
        -------
        (True, 'ok') if trading is allowed
        (False, reason) if blocked — reason is a short string key
        """
        if self._vpin_halted:
            return False, "vpin_halted"
        if self.kill_switch_active:
            return False, "kill_switch"
        if self.profit_cap_active:
            return False, "profit_cap"
        if self.trades_today >= config.MAX_MNQ_TRADES_PER_DAY:
            return False, "max_trades"
        return True, "ok"

    def check_hard_close(self, current_time: datetime) -> bool:
        """
        Return True if it is at or past the hard-close time (3:00 PM CT).

        Parameters
        ----------
        current_time : datetime — tz-aware or naive (treated as CT)

        Returns
        -------
        bool — True means flatten all positions immediately
        """
        close_h = config.HARD_CLOSE_HOUR
        close_m = config.HARD_CLOSE_MINUTE
        t = current_time.time() if hasattr(current_time, "time") else current_time
        return (t.hour, t.minute) >= (close_h, close_m)

    # ------------------------------------------------------------------ #
    # Public API — soft overrides from edge modules                        #
    # ------------------------------------------------------------------ #

    def set_swc_overrides(
        self,
        min_conf_adj: int,
        pos_mult: float,
    ) -> None:
        """
        Apply SWC (sentiment) adjustments.

        Parameters
        ----------
        min_conf_adj : int   — additional points added to min confluence
                               (e.g. +1 when high volatility event today)
        pos_mult     : float — position size multiplier (1.0 = normal)
        """
        self._min_confluence_adj = min_conf_adj
        self._position_multiplier = min(self._position_multiplier, pos_mult)
        logger.info(
            "SWC overrides: conf_adj=+%d, pos_mult=%.2f",
            min_conf_adj, pos_mult,
        )

    def set_vpin_overrides(
        self,
        halted: bool,
        tighten_pct: float,
        pos_mult: float,
    ) -> None:
        """
        Apply VPIN toxicity adjustments.

        Parameters
        ----------
        halted     : bool  — if True, trading is fully halted
        tighten_pct: float — stop tightening percentage (informational)
        pos_mult   : float — position size multiplier (e.g. 0.75 = -25%)
        """
        self._vpin_halted = halted
        if halted:
            logger.warning("VPIN HALT: trading suspended due to extreme toxicity")
        self._position_multiplier = min(self._position_multiplier, pos_mult)
        logger.debug(
            "VPIN overrides: halted=%s, tighten=%.0f%%, pos_mult=%.2f",
            halted, tighten_pct * 100, pos_mult,
        )

    def emergency_flatten(self) -> None:
        """
        Trigger emergency flatten — activates kill switch immediately.

        Called by: heartbeat failure, VPIN extreme event.
        """
        self.kill_switch_active = True
        logger.critical("EMERGENCY FLATTEN triggered — kill switch activated")

    def reset_daily(self) -> None:
        """Reset all daily counters — call at session start (pre-market)."""
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.trades_today = 0
        self.kill_switch_active = False
        self.profit_cap_active = False
        self._min_confluence_adj = 0
        self._position_multiplier = 1.0
        self._vpin_halted = False
        logger.info("RiskManager: daily state reset")

    # ------------------------------------------------------------------ #
    # Public properties (read-only views for strategies)                   #
    # ------------------------------------------------------------------ #

    @property
    def effective_min_confluence(self) -> int:
        """config.MIN_CONFLUENCE + any active adjustments."""
        return config.MIN_CONFLUENCE + self._min_confluence_adj

    @property
    def position_multiplier(self) -> float:
        """Current position size multiplier (1.0 = normal, 0.75 = -25%)."""
        return self._position_multiplier

    @property
    def vpin_halted(self) -> bool:
        """True if VPIN extreme event has halted all trading."""
        return self._vpin_halted

    def __repr__(self) -> str:
        return (
            f"RiskManager(pnl={self.daily_pnl:.2f}, losses={self.consecutive_losses}, "
            f"trades={self.trades_today}, kill={self.kill_switch_active}, "
            f"cap={self.profit_cap_active}, vpin_halt={self._vpin_halted})"
        )
