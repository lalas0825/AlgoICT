"""
toxicity/vpin_engine.py
========================
VPIN Engine — real-time order flow toxicity orchestrator.

Connects to live volume data (from TopstepX WebSocket bars) and
maintains a rolling VPIN calculation. Checks the shield on every
new bucket and triggers protective actions when VPIN is extreme.

Data flow:
    WebSocket 1-min bar
        → VolumeBucketizer (volume time buckets)
            → BVCClassifier (buy/sell classification)
                → VPINCalculator (rolling VPIN)
                    → ToxicityClassifier (level label)
                        → ShieldManager (protective actions)

Usage:
    from toxicity.vpin_engine import VPINEngine
    engine = VPINEngine(risk_manager=rm, telegram_bot=tb)
    engine.on_new_bar(bar)          # Call on every 1-min bar
    status = engine.get_status()    # Current VPIN + level

    # For main.py integration:
    from toxicity.vpin_engine import VPINEngineAdapter
    adapter = VPINEngineAdapter(risk_manager=rm)
    vpin, level = adapter.process_bar(bar)
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from toxicity.vpin_calculator import VPINCalculator, VPINReading, classify_toxicity
from toxicity.toxicity_classifier import ToxicityClassifier, ToxicityLevel
from toxicity.shield_actions import ShieldManager, ShieldAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VPINStatus dataclass
# ---------------------------------------------------------------------------

@dataclass
class VPINStatus:
    """Current VPIN snapshot returned by VPINEngine.get_status()."""

    vpin: Optional[float]           # None if not yet ready
    label: str                      # 'unknown' | 'calm' | ... | 'extreme'
    is_ready: bool                  # True once enough buckets accumulated
    is_halted: bool                 # True if shield triggered halt
    bucket_count: int               # Total buckets processed

    @property
    def is_dangerous(self) -> bool:
        return self.label in ("high", "extreme")

    def __repr__(self) -> str:
        vpin_str = f"{self.vpin:.3f}" if self.vpin is not None else "N/A"
        return f"VPINStatus(vpin={vpin_str} [{self.label}] halted={self.is_halted})"


# ---------------------------------------------------------------------------
# VPINEngine
# ---------------------------------------------------------------------------

class VPINEngine:
    """
    Real-time VPIN orchestrator for the trading engine.

    Processes 1-minute bars, maintains rolling VPIN, evaluates shield.

    Parameters
    ----------
    risk_manager : optional
        Used by ShieldManager for emergency_flatten calls.
    telegram_bot : optional
        Used for VPIN alert notifications.
    bucket_size : int
        Volume per bucket (passed to VPINCalculator).
    num_buckets : int
        Rolling window size (passed to VPINCalculator).
    """

    def __init__(
        self,
        risk_manager=None,
        telegram_bot=None,
        bucket_size: int = 1000,
        num_buckets: int = 50,
    ):
        self._calculator = VPINCalculator(
            bucket_size=bucket_size,
            num_buckets=num_buckets,
        )
        self._classifier = ToxicityClassifier()
        self._shield = ShieldManager(
            risk_manager=risk_manager,
            telegram_bot=telegram_bot,
        )
        self._bucket_count = 0
        self._last_reading: Optional[VPINReading] = None
        self._last_action: Optional[ShieldAction] = None
        logger.info(
            "VPINEngine initialized (bucket_size=%d, num_buckets=%d)",
            bucket_size, num_buckets,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def on_new_bar(self, bar: pd.Series) -> Optional[ShieldAction]:
        """
        Process a new 1-minute bar and evaluate the shield.

        Parameters
        ----------
        bar : pd.Series
            OHLCV series with at least 'close' and 'volume' fields.

        Returns
        -------
        ShieldAction if VPIN is ready, None otherwise.
        """
        try:
            reading = self._calculator.update(bar)
            self._bucket_count += 1

            if reading is None:
                return None  # Not enough data yet

            self._last_reading = reading
            action = self._shield.evaluate(reading.vpin)
            self._last_action = action

            # Check if halt can be deactivated
            self._shield.check_deactivate(reading.vpin)

            return action

        except Exception as exc:
            logger.error("VPINEngine.on_new_bar failed: %s", exc)
            return None

    async def on_new_bar_async(self, bar: pd.Series) -> Optional[ShieldAction]:
        """
        Async version of on_new_bar. Executes flatten if extreme.

        Call this from the main async trading loop.
        """
        action = self.on_new_bar(bar)

        if action is not None and action.should_flatten:
            await self._shield.execute_flatten(
                reason=f"VPIN extreme: {action.vpin:.3f}"
            )

        return action

    def get_status(self) -> VPINStatus:
        """Return current VPIN status snapshot."""
        if self._last_reading is None:
            return VPINStatus(
                vpin=None,
                label="unknown",
                is_ready=False,
                is_halted=self._shield.is_halted,
                bucket_count=self._bucket_count,
            )

        return VPINStatus(
            vpin=self._last_reading.vpin,
            label=self._last_reading.toxicity,
            is_ready=True,
            is_halted=self._shield.is_halted,
            bucket_count=self._bucket_count,
        )

    def is_safe_to_trade(self) -> bool:
        """
        True if VPIN is not halted and not extreme.

        Use this in the trading loop before evaluating any setup.
        """
        if self._shield.is_halted:
            return False
        if self._last_reading is None:
            return True  # No data yet — don't block trading
        return not classify_toxicity(self._last_reading.vpin) == "extreme"

    def current_size_multiplier(self) -> float:
        """Return current position size multiplier from last VPIN reading."""
        if self._last_action is None:
            return 1.0
        return self._last_action.size_multiplier

    def current_confluence_delta(self) -> int:
        """Return current extra min_confluence requirement from VPIN."""
        if self._last_action is None:
            return 0
        return self._last_action.min_confluence_delta

    def reset(self) -> None:
        """Reset for new trading day."""
        self._calculator.reset()
        self._shield.reset()
        self._bucket_count = 0
        self._last_reading = None
        self._last_action = None
        logger.info("VPINEngine reset for new day")


# ---------------------------------------------------------------------------
# VPINEngineAdapter — simple interface for main.py
# ---------------------------------------------------------------------------

class VPINEngineAdapter:
    """
    Simplified VPIN adapter for use in main.py trading loop.

    Wraps VPINEngine with a simpler process_bar() interface that returns
    (vpin, level) tuples for logging and confluence scoring.
    """

    def __init__(self, risk_manager=None, telegram_bot=None):
        self._engine = VPINEngine(
            risk_manager=risk_manager,
            telegram_bot=telegram_bot,
        )

    def process_bar(self, bar: pd.Series) -> tuple:
        """
        Process a 1-min bar. Returns (vpin_float, level_str).

        Returns (None, 'unknown') if VPIN is not yet ready.
        """
        action = self._engine.on_new_bar(bar)
        status = self._engine.get_status()
        return status.vpin, status.label

    def is_safe(self) -> bool:
        return self._engine.is_safe_to_trade()

    def size_multiplier(self) -> float:
        return self._engine.current_size_multiplier()

    def confluence_delta(self) -> int:
        return self._engine.current_confluence_delta()

    def reset(self) -> None:
        self._engine.reset()
