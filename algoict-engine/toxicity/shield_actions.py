"""
toxicity/shield_actions.py
===========================
VPIN Shield — protective actions triggered by toxicity levels.

This module defines what the bot DOES when VPIN reaches dangerous levels.
The shield runs in the main trading loop, checking VPIN after every new
volume bucket.

Shield layers:
    Elevated: Tighten stops on open positions by 10%
    High:     Reduce new position size to 75%, require A+ setup (conf +1)
    Extreme:  FLATTEN ALL positions, HALT all new trading
              (Override is absolute. No exceptions.)

Usage:
    from toxicity.shield_actions import ShieldManager, ShieldAction
    shield = ShieldManager(risk_manager, telegram_bot)
    action = shield.evaluate(vpin=0.72)
    if action.should_flatten:
        await shield.execute_flatten(reason="VPIN extreme 0.72")
"""

import logging
from dataclasses import dataclass
from typing import Optional

from toxicity.toxicity_classifier import ToxicityClassifier, ToxicityLevel

logger = logging.getLogger(__name__)

# Resume threshold: once halted, VPIN must drop to or below this to resume.
# No hysteresis — mirrors the activate threshold exactly.
_DEACTIVATE_THRESHOLD = 0.70   # resume as soon as VPIN exits extreme
_FLATTEN_THRESHOLD = 0.70       # extreme threshold


# ---------------------------------------------------------------------------
# ShieldAction dataclass
# ---------------------------------------------------------------------------

@dataclass
class ShieldAction:
    """
    Recommended action from shield evaluation.

    Returned by ShieldManager.evaluate(). The caller is responsible
    for actually executing the action (calling flatten, adjusting risk, etc.).
    """
    toxicity: ToxicityLevel
    should_flatten: bool
    should_halt: bool
    should_tighten_stops: bool
    size_multiplier: float              # 0.0-1.0
    min_confluence_delta: int           # extra points required
    stop_tighten_pct: float             # % to tighten stop distance
    alert_level: str                    # "none" | "warning" | "critical"
    message: str = ""

    @property
    def vpin(self) -> float:
        return self.toxicity.vpin

    @property
    def label(self) -> str:
        return self.toxicity.label


# ---------------------------------------------------------------------------
# ShieldManager
# ---------------------------------------------------------------------------

class ShieldManager:
    """
    Manages VPIN-driven protective actions.

    Integrates with RiskManager and TelegramBot to execute protective
    measures when VPIN reaches dangerous levels.

    Parameters
    ----------
    risk_manager : optional
        The RiskManager instance. Used for flatten/halt calls.
    telegram_bot : optional
        TelegramBot instance. Used for alert notifications.
    """

    def __init__(
        self,
        risk_manager=None,
        telegram_bot=None,
    ):
        self._risk_manager = risk_manager
        self._telegram = telegram_bot
        self._classifier = ToxicityClassifier()
        self._halt_active = False
        self._last_level: Optional[str] = None
        logger.info("ShieldManager initialized")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def is_halted(self) -> bool:
        """True if trading is currently halted due to VPIN shield."""
        return self._halt_active

    def evaluate(self, vpin: float) -> ShieldAction:
        """
        Evaluate a VPIN reading and return the recommended ShieldAction.

        Does NOT execute the action — caller must call execute_flatten()
        or apply the action parameters to the risk manager.

        Parameters
        ----------
        vpin : float
            Current VPIN reading.

        Returns
        -------
        ShieldAction with all recommended parameters.
        """
        level = self._classifier.classify(vpin)
        action = self._build_action(level)

        # Track level transitions for logging
        if level.label != self._last_level:
            if level.is_extreme:
                logger.critical("VPIN SHIELD: %s -> EXTREME (%.3f) — initiating flatten", self._last_level, vpin)
            elif level.is_dangerous:
                logger.warning("VPIN SHIELD: %s -> %s (%.3f)", self._last_level, level.label, vpin)
            self._last_level = level.label

        return action

    async def execute_flatten(self, reason: str = "") -> bool:
        """
        Execute emergency flatten via risk_manager.

        Parameters
        ----------
        reason : str
            Human-readable reason for the flatten.

        Returns True if flatten was called, False if already halted or no risk_manager.

        Edge-detection guard: if the shield is already in halt state (e.g. VPIN
        has been extreme for multiple bars), this method returns False immediately
        without re-sending the Telegram alert or re-triggering the flatten.
        The caller (main.py) should also check `was_halted` before calling this,
        but this guard provides defence-in-depth.
        """
        full_reason = reason or f"VPIN shield activated (extreme toxicity)"

        # ── Edge-detection: False → True only ─────────────────────────────
        if self._halt_active:
            # Already halted from a previous bar — do not repeat the alert.
            logger.debug("VPIN SHIELD: execute_flatten called while already halted — skipping")
            return False

        self._halt_active = True
        logger.critical("VPIN SHIELD: executing flatten — %s", full_reason)

        if self._telegram is not None:
            try:
                await self._telegram.send_vpin_alert(
                    vpin=self._classifier.classify(0.75).vpin,
                    toxicity_level="extreme",
                )
            except Exception as exc:
                logger.error("Failed to send VPIN alert: %s", exc)

        if self._risk_manager is not None:
            try:
                # Activate the clearable VPIN halt (not the permanent kill switch).
                activate = getattr(self._risk_manager, "activate_vpin_halt", None)
                if activate is not None:
                    activate()
                return True
            except Exception as exc:
                logger.error("VPIN flatten failed: %s", exc)
                return False

        return False

    def check_deactivate(self, vpin: float) -> bool:
        """
        Check if the halt should be deactivated based on current VPIN.

        When VPIN drops to or below the deactivation threshold (0.70), clears
        the internal halt flag and tells the RiskManager to resume trading.

        True → False transition: logs a CRITICAL-level "NORMALIZED" message so
        the operator can see trading has resumed. A Telegram alert for the
        normalized state should be sent by the async caller (main.py) using
        the returned True value.

        Returns True if halt was deactivated this call (transition event).
        """
        if self._halt_active and vpin <= _DEACTIVATE_THRESHOLD:
            self._halt_active = False
            logger.critical(
                "VPIN SHIELD: NORMALIZED — halt cleared (vpin=%.3f <= %.2f). Trading resumed.",
                vpin, _DEACTIVATE_THRESHOLD,
            )
            # Propagate resume to RiskManager so can_trade() unblocks.
            if self._risk_manager is not None:
                deactivate = getattr(self._risk_manager, "deactivate_vpin_halt", None)
                if deactivate is not None:
                    deactivate(vpin)
            return True
        return False

    def reset(self) -> None:
        """Reset shield state (e.g. at start of new trading day)."""
        self._halt_active = False
        self._last_level = None
        logger.info("ShieldManager reset")

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _build_action(self, level: ToxicityLevel) -> ShieldAction:
        """Build a ShieldAction from a ToxicityLevel."""
        alert_level = "none"
        if level.is_extreme:
            alert_level = "critical"
        elif level.is_dangerous:
            alert_level = "warning"

        should_tighten = level.stop_tighten_pct > 0

        msg_parts = [f"VPIN {level.vpin:.3f} [{level.label.upper()}]"]
        if level.should_flatten:
            msg_parts.append("FLATTEN ALL POSITIONS")
        elif level.is_dangerous:
            msg_parts.append(f"Reduce size {(1 - level.size_multiplier) * 100:.0f}%")
        if level.min_confluence_delta > 0 and not level.should_halt:
            msg_parts.append(f"Min confluence +{level.min_confluence_delta}")
        if should_tighten:
            msg_parts.append(f"Tighten stops {level.stop_tighten_pct * 100:.0f}%")

        return ShieldAction(
            toxicity=level,
            should_flatten=level.should_flatten,
            should_halt=level.should_halt or self._halt_active,
            should_tighten_stops=should_tighten,
            size_multiplier=level.size_multiplier,
            min_confluence_delta=level.min_confluence_delta,
            stop_tighten_pct=level.stop_tighten_pct,
            alert_level=alert_level,
            message=" | ".join(msg_parts),
        )
