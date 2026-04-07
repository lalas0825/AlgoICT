"""
timeframes/htf_bias.py
======================
Higher Timeframe (Weekly/Daily) bias detection for ICT strategies.

Bias Logic (ICT principle):
    - Price in discount zone (below 50% of range) = bullish bias
    - Price in premium zone (above 50% of range) = bearish bias
    - Bias confidence increases when Weekly and Daily align

All DataFrames must have US/Central DatetimeIndex and OHLCV columns.
"""

import logging
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BiasResult:
    """Result of HTF bias determination."""

    direction: str  # "bullish" | "bearish" | "neutral"
    premium_discount: str  # "premium" | "discount" | "equilibrium"
    htf_levels: dict  # {"weekly_high": ..., "weekly_low": ..., "daily_high": ..., "daily_low": ...}
    confidence: str  # "high" | "medium" | "low"
    weekly_bias: str  # bullish | bearish | neutral
    daily_bias: str  # bullish | bearish | neutral

    def __repr__(self) -> str:
        return (
            f"BiasResult(direction={self.direction}, premium_discount={self.premium_discount}, "
            f"confidence={self.confidence}, weekly={self.weekly_bias}, daily={self.daily_bias})"
        )


class HTFBiasDetector:
    """
    Detects Weekly and Daily bias for confluence scoring.

    Bias = direction of institutional order flow based on price position
    within the week and day candles.
    """

    def __init__(self):
        pass

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def determine_bias(
        self,
        df_daily: pd.DataFrame,
        df_weekly: pd.DataFrame,
        current_price: float,
    ) -> BiasResult:
        """
        Determine HTF bias based on price position in daily and weekly ranges.

        Parameters
        ----------
        df_daily   : pd.DataFrame — daily OHLCV bars (must include latest close)
        df_weekly  : pd.DataFrame — weekly OHLCV bars (must include latest close)
        current_price : float — the price to evaluate (typically last close)

        Returns
        -------
        BiasResult — direction, premium/discount zone, HTF levels, confidence
        """
        if df_daily.empty or df_weekly.empty:
            logger.warning("Empty daily or weekly DataFrame")
            return self._neutral_result()

        # Get the most recent (current) daily and weekly candles
        daily_candle = df_daily.iloc[-1]
        weekly_candle = df_weekly.iloc[-1]

        # ── Calculate bias for each timeframe ──────────────────────────
        daily_bias, daily_zone = self._calc_bias(
            daily_candle["high"],
            daily_candle["low"],
            current_price,
            "daily",
        )
        weekly_bias, weekly_zone = self._calc_bias(
            weekly_candle["high"],
            weekly_candle["low"],
            current_price,
            "weekly",
        )

        # ── Determine overall direction and confidence ─────────────────
        direction = self._determine_direction(daily_bias, weekly_bias)
        confidence = self._confidence_level(daily_bias, weekly_bias, direction)

        # ── Collect HTF levels ────────────────────────────────────────
        htf_levels = {
            "weekly_high": float(weekly_candle["high"]),
            "weekly_low": float(weekly_candle["low"]),
            "weekly_mid": (float(weekly_candle["high"]) + float(weekly_candle["low"])) / 2,
            "daily_high": float(daily_candle["high"]),
            "daily_low": float(daily_candle["low"]),
            "daily_mid": (float(daily_candle["high"]) + float(daily_candle["low"])) / 2,
            "current_price": current_price,
        }

        # ── Premium/discount at the _primary_ zone (weekly takes priority) ─
        premium_discount = weekly_zone if weekly_bias != "neutral" else daily_zone

        return BiasResult(
            direction=direction,
            premium_discount=premium_discount,
            htf_levels=htf_levels,
            confidence=confidence,
            weekly_bias=weekly_bias,
            daily_bias=daily_bias,
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _calc_bias(high: float, low: float, price: float, tf: str) -> tuple[str, str]:
        """
        Calculate bias for a single candle.

        If price < 50% of range: discount = bullish bias
        If price > 50% of range: premium = bearish bias
        If price ≈ 50%: neutral

        Returns: (bias_direction, zone_name)
        """
        range_val = high - low
        if range_val == 0:
            return ("neutral", "equilibrium")

        mid = (high + low) / 2
        threshold = 0.02 * range_val  # 2% tolerance for "equilibrium"

        if price < mid - threshold:
            return ("bullish", "discount")
        elif price > mid + threshold:
            return ("bearish", "premium")
        else:
            return ("neutral", "equilibrium")

    @staticmethod
    def _determine_direction(daily_bias: str, weekly_bias: str) -> str:
        """
        Fuse daily and weekly bias.

        Priority: Weekly > Daily (institutional structure defines primary direction)
        """
        if weekly_bias != "neutral":
            return weekly_bias
        return daily_bias

    @staticmethod
    def _confidence_level(daily_bias: str, weekly_bias: str, direction: str) -> str:
        """
        Confidence based on agreement.

        - high: both weekly and daily agree with overall direction
        - medium: one agrees, other is neutral
        - low: they disagree or both neutral
        """
        if weekly_bias == "neutral" and daily_bias == "neutral":
            return "low"

        # Check agreement with final direction
        weekly_agrees = weekly_bias == direction or weekly_bias == "neutral"
        daily_agrees = daily_bias == direction or daily_bias == "neutral"

        if weekly_agrees and daily_agrees and daily_bias != "neutral" and weekly_bias != "neutral":
            return "high"
        elif weekly_agrees or daily_agrees:
            return "medium"
        else:
            return "low"

    @staticmethod
    def _neutral_result() -> BiasResult:
        return BiasResult(
            direction="neutral",
            premium_discount="equilibrium",
            htf_levels={},
            confidence="low",
            weekly_bias="neutral",
            daily_bias="neutral",
        )
