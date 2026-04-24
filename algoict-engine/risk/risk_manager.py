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

    Topstep Combine awareness (M14)
    --------------------------------
    When ``topstep_mode=True``, the manager tracks multi-day equity and
    enforces MLL (Maximum Loss Limit) protection:

      * ``peak_balance_eod``  — highest end-of-day balance ever reached
      * ``current_drawdown``  — peak_balance_eod - current_balance (intraday)

    Drawdown zones (defaults locked 2026-04-17, Combine pass 19/20 = 95%):
      * <  40% of MLL ($800)   — NORMAL: full size
      * >= 40% of MLL ($800)   — WARNING: -25% size, min confluence +1
      * >= 60% of MLL ($1,200) — CAUTION: -50% size, min confluence +2
      * >= 85% of MLL ($1,700) — STOP: no new trades until next session
      * target reached ($53k)  — PROTECTIVE: max 1 trade/day, size halved
        (only applies with ``protective_after_target=True``, off by default
        for combine sims — the combine ends when target is reached)

    These compound with existing intraday rules (kill switch, profit cap,
    VPIN halt). The tightest restriction always wins.

    Usage
    -----
    rm = RiskManager()
    rm.enable_topstep_mode(starting_balance=50000)
    rm.record_trade(-250)
    allowed, reason = rm.can_trade()
    rm.end_of_day()       # call at session close to update EOD peak
    rm.reset_daily()      # call at start of each session
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
        # Clearable VPIN extreme halt — resets when VPIN drops below 0.55.
        # Distinct from kill_switch_active (which is permanent for the day).
        self._vpin_halt_active: bool = False

        # ── Topstep Combine MLL tracking (M14) ──────────────────────────
        self._topstep_mode: bool = False
        self._current_balance: float = 0.0
        self._peak_balance_eod: float = 0.0
        self._starting_balance: float = 0.0
        self._mll_limit: float = config.TOPSTEP_MLL            # $2,000
        # Locked 2026-04-17 via M17b validation (Combine rolling pass rate
        # 19/20 = 95% on NY AM 2024 vs 1/10 without MLL). Changing these
        # requires re-running the Combine simulator at the new thresholds.
        self._mll_warning_pct: float = 0.40                    # 40% = $800  → -25% size
        self._mll_caution_pct: float = 0.60                    # 60% = $1,200 → -50% size
        self._mll_stop_pct: float = 0.85                       # 85% = $1,700 → no trades
        self._profit_target: float = config.TOPSTEP_PROFIT_TARGET  # $3,000
        self._target_reached: bool = False
        self._protective_after_target: bool = False  # for funded account, not combine
        self._mll_zone: str = "normal"  # normal | warning | caution | stop

        # ── Cruise mode (post-target, accumulate trading days) ──────────
        self._cruise_mode: bool = False
        self._cruise_enabled: bool = False          # user opt-in
        self._cruise_min_confluence: int = 9        # high-confidence tier (ICT-only max ~11)
        self._cruise_max_risk: float = 100.0        # $100 max loss/trade
        self._cruise_max_contracts: int = 1         # 1 MNQ
        self._trading_days_set: set = set()         # dates with >=1 trade
        self._min_trading_days: int = 5             # Topstep minimum

        # ── Risk Ladder + Per-KZ Loss Caps (2026-04-22) ─────────────────
        # Ladder = step-down risk sizing after each loss so we get 5 shots
        # instead of 3 inside the same $750-$1,000 DLL budget. DIFFERENT
        # from consecutive_losses (which resets on win + can be reset per
        # KZ) — losses_today only increments, never resets intraday.
        self._ladder_enabled: bool = bool(getattr(config, "RISK_LADDER_ENABLED", False))
        self._ladder_schedule: tuple = tuple(getattr(config, "RISK_LADDER", (250, 200, 150, 100, 50)))
        self._losses_today: int = 0     # count of LOSING trades today; only increments
        # Per-kill-zone losing-trade caps. Zones not listed have no cap.
        # Mutated via set_kz_loss_caps(). Stats in _kz_losing_trades mirror
        # the dict keys (plus any zone we see losses on). Both reset at EOD.
        self._kz_loss_caps: dict = dict(getattr(config, "KZ_LOSS_CAPS", {}) or {})
        self._kz_losing_trades: dict = {}

    # ------------------------------------------------------------------ #
    # Public API — Topstep Combine mode                                    #
    # ------------------------------------------------------------------ #

    def enable_topstep_mode(
        self,
        starting_balance: float = config.TOPSTEP_ACCOUNT_SIZE,
        mll: float = config.TOPSTEP_MLL,
        profit_target: float = config.TOPSTEP_PROFIT_TARGET,
        warning_pct: float = 0.40,
        caution_pct: float = 0.60,
        stop_pct: float = 0.85,
        protective_after_target: bool = False,
        cruise_mode: bool = False,
        reset_on_mll_breach: bool = False,
    ) -> None:
        """
        Enable Topstep Combine MLL-aware risk protection.

        Parameters
        ----------
        protective_after_target : bool
            If True, switch to 1-trade/day + halved size after target is
            reached. For live funded-account protection, NOT for combine
            simulations. Default False.
        reset_on_mll_breach : bool
            "Combine Mode with auto-reset" — when drawdown reaches MLL,
            simulate a paid reset (counts as an event, resets balance/peak
            to starting state) instead of permanently blocking trades.
            Used for backtests that want to study the full-year edge while
            still applying MLL position-size reductions at the warning and
            caution zones. Default False (classic stop-on-breach behavior).
        """
        self._topstep_mode = True
        self._starting_balance = starting_balance
        self._current_balance = starting_balance
        self._peak_balance_eod = starting_balance
        self._mll_limit = mll
        self._mll_warning_pct = warning_pct
        self._mll_caution_pct = caution_pct
        self._mll_stop_pct = stop_pct
        self._profit_target = profit_target
        self._target_reached = False
        self._protective_after_target = protective_after_target
        self._mll_zone = "normal"
        self._cruise_enabled = cruise_mode
        self._cruise_mode = False
        self._trading_days_set = set()
        self._reset_on_mll_breach = reset_on_mll_breach
        self._combine_resets: int = 0
        self._combine_reset_events: list = []   # list of (date, dd_at_reset)
        logger.info(
            "Topstep mode ON: balance=$%.2f, MLL=$%.2f, target=$%.2f, "
            "protective=%s, cruise=%s, reset_on_breach=%s",
            starting_balance, mll, profit_target, protective_after_target,
            cruise_mode, reset_on_mll_breach,
        )

    def _simulate_combine_reset(self) -> None:
        """Simulate paying for a Combine reset: balance and peak are
        restored to the starting value, all daily flags are cleared, and
        the MLL zone drops back to normal. The reset event is logged and
        counted so the backtest can compute reset-fee cost later.
        """
        self._combine_resets += 1
        dd_at_reset = self.current_drawdown
        self._combine_reset_events.append({
            "reset_n": self._combine_resets,
            "dd_at_reset": dd_at_reset,
            "balance_before": self._current_balance,
            "peak_before": self._peak_balance_eod,
        })
        logger.warning(
            "Topstep Combine RESET #%d simulated (dd=$%.2f, bal=$%.2f -> $%.2f)",
            self._combine_resets, dd_at_reset, self._current_balance,
            self._starting_balance,
        )
        self._current_balance = self._starting_balance
        self._peak_balance_eod = self._starting_balance
        self._mll_zone = "normal"
        # Clear daily flags so trading can resume immediately.
        self.consecutive_losses = 0
        self.kill_switch_active = False
        self.profit_cap_active = False
        self.daily_pnl = 0.0

    @property
    def combine_resets(self) -> int:
        """Number of MLL-breach resets simulated so far."""
        return getattr(self, "_combine_resets", 0)

    @property
    def combine_reset_events(self) -> list:
        return getattr(self, "_combine_reset_events", [])

    def end_of_day(self) -> None:
        """
        Called at session close to update end-of-day peak balance.

        The MLL is a TRAILING limit from the highest EOD balance, so we
        only update the watermark at session end (not intraday). This
        matches Topstep's documented rules.
        """
        if not self._topstep_mode:
            return
        if self._current_balance > self._peak_balance_eod:
            self._peak_balance_eod = self._current_balance
            logger.info(
                "Topstep: new EOD peak $%.2f", self._peak_balance_eod,
            )
        # Check if target reached
        if (
            not self._target_reached
            and self._current_balance >= self._starting_balance + self._profit_target
        ):
            self._target_reached = True
            logger.info(
                "Topstep: PROFIT TARGET REACHED at $%.2f",
                self._current_balance,
            )

    # ------------------------------------------------------------------ #
    # Public API — state updates                                           #
    # ------------------------------------------------------------------ #

    def record_trade(self, pnl: float, kill_zone: str = None) -> None:
        """
        Record a completed trade P&L and update all risk counters.

        Parameters
        ----------
        pnl : float — profit (+) or loss (-) in dollars
        kill_zone : str, optional — KZ the trade was taken in. Required
            for per-KZ loss cap tracking; ignored when no caps set.
        """
        self.daily_pnl += pnl
        self.trades_today += 1

        if pnl < 0:
            self.consecutive_losses += 1
            # Ladder: monotonically increment on loss (never resets on win).
            self._losses_today += 1
            # Per-KZ loss counter (tracked even if no cap set — cheap).
            if kill_zone:
                self._kz_losing_trades[kill_zone] = (
                    self._kz_losing_trades.get(kill_zone, 0) + 1
                )
        else:
            self.consecutive_losses = 0

        # ── Kill switch: 3 consecutive losses ──────────────────────────
        # When the risk ladder is enabled, the 3-consecutive-loss kill
        # switch is SUPPRESSED — the ladder (5 shots at step-down risk)
        # IS the replacement loss-control mechanism. Triggering the old
        # 3-loss halt would block shots 4 + 5 ($100 + $50) which the
        # ladder explicitly budgets for inside the DLL. Daily-loss and
        # ladder-exhaustion checks below still trip the kill switch.
        if (
            not self._ladder_enabled
            and self.consecutive_losses >= config.KILL_SWITCH_LOSSES
        ):
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

        # ── Ladder exhausted: all shots used, halt for the day ──────────
        if (
            self._ladder_enabled
            and self._losses_today >= len(self._ladder_schedule)
        ):
            self.kill_switch_active = True
            logger.warning(
                "KILL SWITCH: risk ladder exhausted (%d losses, schedule=%s, daily_pnl=%.2f)",
                self._losses_today, self._ladder_schedule, self.daily_pnl,
            )

        # ── Profit cap: $1,500/day ──────────────────────────────────────
        if self.daily_pnl >= config.DAILY_PROFIT_CAP:
            self.profit_cap_active = True
            logger.info(
                "PROFIT CAP: daily target hit (daily_pnl=%.2f)", self.daily_pnl,
            )

        # ── Topstep Combine: update running balance + MLL zone ──────────
        if self._topstep_mode:
            self._current_balance += pnl
            self._update_mll_zone()

            # Check if target just reached
            if (
                not self._target_reached
                and self._current_balance
                >= self._starting_balance + self._profit_target
            ):
                self._target_reached = True
                logger.info(
                    "Topstep: TARGET REACHED at $%.2f", self._current_balance,
                )
                # Activate cruise if enabled and not enough trading days
                if (
                    self._cruise_enabled
                    and len(self._trading_days_set) < self._min_trading_days
                ):
                    self._cruise_mode = True
                    logger.info(
                        "Topstep: CRUISE MODE ON — %d/%d trading days, "
                        "accumulating remaining days",
                        len(self._trading_days_set),
                        self._min_trading_days,
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
        if self._vpin_halt_active:
            return False, "vpin_halted"

        # ── Cruise mode: max 1 trade/day, target already reached ────────
        if self._cruise_mode:
            if self.trades_today >= 1:
                return False, "cruise_max_1"
            # Cruise mode is gentle — skip kill switch / profit cap checks
            # because we're just accumulating trading days
            return True, "cruise"

        if self.kill_switch_active:
            return False, "kill_switch"
        if self.profit_cap_active:
            return False, "profit_cap"
        if self.trades_today >= config.MAX_MNQ_TRADES_PER_DAY:
            return False, "max_trades"

        # ── Topstep MLL protection ──────────────────────────────────────
        if self._topstep_mode:
            if self._mll_zone == "stop":
                return False, "mll_stop"
            # Protective mode: max 1 trade/day after target (funded account only)
            if (
                self._protective_after_target
                and self._target_reached
                and self.trades_today >= 1
            ):
                return False, "target_protective"

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
            self.activate_vpin_halt()  # also set the clearable flag
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

    def reset_kill_switch_only(self, reason: str = "kz_boundary") -> None:
        """
        Reset ONLY the consecutive-loss kill switch — leaves daily P&L,
        profit cap, MLL zones, VPIN state intact. Used when the strategy
        crosses a kill-zone boundary (e.g., London ended, NY AM starts):
        each session should get its own 3-loss budget instead of letting
        a bad London morning lock NY out for the rest of the day.

        Daily losses still accumulate toward DLL. If DLL is hit the full
        kill_switch would re-activate on next trade anyway.
        """
        if self.consecutive_losses > 0 or self.kill_switch_active:
            logger.info(
                "Kill switch RESET (%s): losses %d -> 0, kill_active %s -> False",
                reason, self.consecutive_losses, self.kill_switch_active,
            )
        self.consecutive_losses = 0
        self.kill_switch_active = False
        # CRITICAL: If the risk ladder is exhausted (5 losses already
        # spent across any combination of KZs), KZ-boundary reset must NOT
        # re-open trading. The ladder is day-global and kill_switch must
        # stay active to honor the Combine DLL. losses_today persists.
        if (
            self._ladder_enabled
            and self._losses_today >= len(self._ladder_schedule)
        ):
            self.kill_switch_active = True
            logger.info(
                "Kill switch re-activated post-reset: ladder exhausted "
                "(%d losses)", self._losses_today,
            )

    # ------------------------------------------------------------------ #
    # Risk Ladder + Per-KZ Loss Caps (2026-04-22)                          #
    # ------------------------------------------------------------------ #

    def enable_ladder(
        self,
        schedule: tuple = None,
    ) -> None:
        """
        Turn on the post-loss risk ladder (5 shots inside 1 DLL budget).

        Parameters
        ----------
        schedule : tuple[float], optional
            Per-loss risk amounts in dollars. Default reads
            config.RISK_LADDER. Sum should be <= $1,000 (Topstep DLL).
            Example: (250, 200, 150, 100, 50) → sum $750 with $250 buffer.

        Wins do NOT reset the ladder (C3 variant — _losses_today increments
        monotonically, resets only at EOD). This eliminates the martingale-
        like "reset after one win" pattern that lets us re-take full size
        after breaking the DLL buffer.
        """
        self._ladder_enabled = True
        if schedule is not None:
            self._ladder_schedule = tuple(schedule)
        logger.info(
            "Risk ladder ENABLED: schedule=%s (max day loss if all shots miss: $%.0f)",
            self._ladder_schedule, float(sum(self._ladder_schedule)),
        )

    def set_kz_loss_caps(self, caps: dict) -> None:
        """
        Set per-kill-zone losing-trade caps. Zones not in ``caps`` get no
        cap from this mechanism (they only hit kill switch / DLL / ladder
        halts). Example: ``{"london": 2}`` blocks new London entries after
        2 losses in London — NY AM + NY PM still get their full budget.

        Replaces any existing caps dict. Call with ``{}`` to clear.
        """
        self._kz_loss_caps = dict(caps or {})
        logger.info("KZ loss caps set: %s", self._kz_loss_caps or "(none)")

    def get_current_risk(self) -> float:
        """
        Return the dollar risk allowed for the NEXT trade.

        When the ladder is disabled (default), returns config.RISK_PER_TRADE
        ($250). When enabled, returns ladder_schedule[losses_today] — i.e.
        the Nth loss has already happened when this is called, so we're
        sizing trade N+1 (which will itself risk ladder[N]).

        If _losses_today >= len(ladder), returns $0 and trade should be
        blocked upstream by can_trade().
        """
        if not self._ladder_enabled:
            return float(config.RISK_PER_TRADE)
        if self._losses_today >= len(self._ladder_schedule):
            return 0.0
        return float(self._ladder_schedule[self._losses_today])

    def can_trade_in_kz(self, kill_zone: str) -> tuple[bool, str]:
        """
        Check BOTH the global can_trade() gate AND the per-KZ loss cap.

        Called by strategies before sizing a new entry. Returns the same
        (allowed, reason) shape as can_trade() so callers treat both
        identically.
        """
        # Per-KZ losing-trade cap (independent from kill switch)
        cap = self._kz_loss_caps.get(kill_zone)
        if cap is not None:
            used = self._kz_losing_trades.get(kill_zone, 0)
            if used >= cap:
                return False, f"kz_loss_cap:{kill_zone}"
        # Ladder exhausted
        if self._ladder_enabled and self._losses_today >= len(self._ladder_schedule):
            return False, "ladder_exhausted"
        return self.can_trade()

    def record_trading_day(self, date) -> None:
        """
        Record that a trade occurred on this date. Call from the
        backtester whenever a trade closes.

        Parameters
        ----------
        date : datetime.date — the calendar date of the trade
        """
        if self._topstep_mode:
            self._trading_days_set.add(date)
            # Check if cruise mode can deactivate
            if (
                self._cruise_mode
                and len(self._trading_days_set) >= self._min_trading_days
            ):
                self._cruise_mode = False
                logger.info(
                    "Topstep: CRUISE MODE OFF — %d trading days reached",
                    len(self._trading_days_set),
                )

    def reset_daily(self) -> None:
        """Reset all daily counters — call at session start (pre-market)."""
        # EOD peak update happens at session close (end_of_day), but if
        # reset_daily is called first (which the backtester does), we
        # update the peak here too as a safety net.
        if self._topstep_mode and self._current_balance > self._peak_balance_eod:
            self._peak_balance_eod = self._current_balance

        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.trades_today = 0
        self.kill_switch_active = False
        self.profit_cap_active = False
        self._min_confluence_adj = 0
        self._position_multiplier = 1.0
        self._vpin_halted = False
        self._vpin_halt_active = False
        # Ladder + KZ caps reset daily — losses_today tallies from 0
        # each morning. The ladder schedule + caps themselves persist.
        self._losses_today = 0
        self._kz_losing_trades = {}

        # MLL zone recalc at day start (the "stop" zone resets because
        # a new day gives the trader a fresh chance, but the drawdown
        # from peak doesn't reset — only daily flags do).
        if self._topstep_mode:
            self._update_mll_zone()

        logger.info("RiskManager: daily state reset")

    # ------------------------------------------------------------------ #
    # Public properties (read-only views for strategies)                   #
    # ------------------------------------------------------------------ #

    @property
    def effective_min_confluence(self) -> int:
        """config.MIN_CONFLUENCE + any active adjustments (incl. MLL caution)."""
        if self._cruise_mode:
            return self._cruise_min_confluence  # 12 — A+ trades only
        adj = self._min_confluence_adj
        if self._topstep_mode:
            if self._mll_zone == "caution":
                adj += 2  # MLL caution: +2 confluence required
            elif self._mll_zone == "warning":
                adj += 1  # MLL warning: +1 confluence required
        return config.MIN_CONFLUENCE + adj

    @property
    def position_multiplier(self) -> float:
        """
        Current position size multiplier (1.0 = normal, 0.5 = halved).

        Compounds: the lowest of SWC, VPIN, and MLL multipliers wins.
        """
        mult = self._position_multiplier
        if self._topstep_mode:
            if self._mll_zone == "caution" or self._target_reached:
                mult = min(mult, 0.5)  # halve in caution or protective mode
            elif self._mll_zone == "warning":
                mult = min(mult, 0.75)  # -25% early size reduction
        return mult

    # ── Cruise mode properties ────────────────────────────────────────

    @property
    def cruise_mode(self) -> bool:
        """True if target reached and still accumulating trading days."""
        return self._cruise_mode

    @property
    def cruise_max_risk(self) -> float:
        """Max dollar risk per trade in cruise mode ($100)."""
        return self._cruise_max_risk

    @property
    def cruise_max_contracts(self) -> int:
        """Max contracts in cruise mode (1 MNQ)."""
        return self._cruise_max_contracts

    @property
    def trading_days_count(self) -> int:
        """Number of unique calendar days with at least 1 trade."""
        return len(self._trading_days_set)

    @property
    def vpin_halted(self) -> bool:
        """True if VPIN extreme event has halted all trading."""
        return self._vpin_halted

    @property
    def vpin_halt_active(self) -> bool:
        """True if the clearable VPIN extreme halt is active."""
        return self._vpin_halt_active

    def activate_vpin_halt(self) -> None:
        """
        Activate VPIN extreme halt.

        Unlike ``emergency_flatten()`` this does NOT set ``kill_switch_active``.
        Trading resumes automatically via ``deactivate_vpin_halt()`` when VPIN
        drops back below the deactivation threshold (0.55).
        """
        self._vpin_halt_active = True
        logger.warning("VPIN HALT: trading suspended due to extreme toxicity")

    def deactivate_vpin_halt(self, vpin: float) -> None:
        """
        Deactivate VPIN halt — called by ShieldManager when VPIN normalizes.

        Logs the resume message required by alert consumers.
        """
        self._vpin_halt_active = False
        logger.info("VPIN normalized: %.2f — trading resumed", vpin)

    # ── Topstep-specific properties ────────────────────────────────────

    @property
    def topstep_mode(self) -> bool:
        return self._topstep_mode

    @property
    def current_balance(self) -> float:
        return self._current_balance

    @property
    def peak_balance_eod(self) -> float:
        return self._peak_balance_eod

    @property
    def current_drawdown(self) -> float:
        """Dollar drawdown from EOD peak. Always >= 0."""
        if not self._topstep_mode:
            return 0.0
        return max(0.0, self._peak_balance_eod - self._current_balance)

    @property
    def mll_zone(self) -> str:
        """Current MLL zone: 'normal' | 'caution' | 'stop'."""
        return self._mll_zone

    @property
    def target_reached(self) -> bool:
        return self._target_reached

    # ------------------------------------------------------------------ #
    # Private — MLL zone computation                                       #
    # ------------------------------------------------------------------ #

    def _update_mll_zone(self) -> None:
        """
        Recompute the MLL zone based on current drawdown vs peak.

        Zones:
          normal  — drawdown < 80% of MLL      ($0–$1,599)
          caution — drawdown 80%–95% of MLL     ($1,600–$1,899)
          stop    — drawdown >= 95% of MLL      ($1,900+)

        The 'stop' zone prevents new trades until the next session reset.
        In 'caution' zone, position size is halved and min confluence +2.
        """
        dd = self.current_drawdown
        warning_threshold = self._mll_limit * self._mll_warning_pct
        caution_threshold = self._mll_limit * self._mll_caution_pct
        stop_threshold = self._mll_limit * self._mll_stop_pct

        old_zone = self._mll_zone

        if dd >= stop_threshold:
            self._mll_zone = "stop"
        elif dd >= caution_threshold:
            self._mll_zone = "caution"
        elif dd >= warning_threshold:
            self._mll_zone = "warning"
        else:
            self._mll_zone = "normal"

        if self._mll_zone != old_zone:
            logger.warning(
                "Topstep MLL zone: %s -> %s (dd=$%.2f, peak=$%.2f, bal=$%.2f)",
                old_zone, self._mll_zone, dd,
                self._peak_balance_eod, self._current_balance,
            )

        # Combine-reset mode: when we hit the stop zone (DD >= stop_threshold
        # = 85% of MLL by default), simulate a paid reset instead of
        # permanently blocking trades. This lets backtests study full-year
        # edge behavior with MLL position-size reductions still in effect.
        if (
            self._mll_zone == "stop"
            and getattr(self, "_reset_on_mll_breach", False)
        ):
            self._simulate_combine_reset()

    def __repr__(self) -> str:
        base = (
            f"RiskManager(pnl={self.daily_pnl:.2f}, losses={self.consecutive_losses}, "
            f"trades={self.trades_today}, kill={self.kill_switch_active}, "
            f"cap={self.profit_cap_active}, vpin_halt={self._vpin_halt_active}"
        )
        if self._topstep_mode:
            base += (
                f", topstep=ON, bal={self._current_balance:.2f}, "
                f"peak={self._peak_balance_eod:.2f}, "
                f"dd={self.current_drawdown:.2f}, zone={self._mll_zone}"
            )
        return base + ")"
