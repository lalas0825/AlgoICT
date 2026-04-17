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
    weekly_alignment_multiplier: float = 1.0  # 1.0 when aligned, 0.5 when opposing

    def __repr__(self) -> str:
        return (
            f"BiasResult(direction={self.direction}, premium_discount={self.premium_discount}, "
            f"confidence={self.confidence}, weekly={self.weekly_bias}, daily={self.daily_bias}, "
            f"weekly_mult={self.weekly_alignment_multiplier:.0%})"
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
        Determine HTF bias using two signals, in order:

        1. PRIMARY: Swing-structure pattern (HH-HL = bullish, LH-LL = bearish).
           This is the institutional-order-flow definition used in ICT.
        2. SECONDARY: Premium / discount zone of the last COMPLETED candle.
           Only used to tie-break or confirm; a mean-reversion read.

        Key differences vs the old logic:
        - Uses the last COMPLETED daily/weekly candle (not the partial one
          that's still forming) — the forming candle's range expands as
          price moves and the bias flips around.
        - Wider neutral band (35-65 % of range instead of ±2 %) so noisy
          mid-range chop doesn't flip the bias bar-by-bar.

        Parameters
        ----------
        df_daily   : pd.DataFrame — daily OHLCV bars
        df_weekly  : pd.DataFrame — weekly OHLCV bars
        current_price : float — typically the last 1-min close

        Returns
        -------
        BiasResult
        """
        if df_daily.empty or df_weekly.empty:
            logger.warning("Empty daily or weekly DataFrame")
            return self._neutral_result()

        # ── 1. Pick the last COMPLETED candle for each TF ──────────────
        # If only 1 bar exists (very early warm-up), fall back to it even
        # though it's still forming.
        daily_candle = df_daily.iloc[-2] if len(df_daily) >= 2 else df_daily.iloc[-1]
        weekly_candle = df_weekly.iloc[-2] if len(df_weekly) >= 2 else df_weekly.iloc[-1]

        # ── 2. Swing-structure bias (PRIMARY) ──────────────────────────
        daily_swing = self._swing_bias(df_daily, "daily")
        weekly_swing = self._swing_bias(df_weekly, "weekly")

        # ── 3. Premium / discount of last completed candle (SECONDARY) ─
        daily_zone_bias, daily_zone = self._zone_bias(
            daily_candle["high"], daily_candle["low"], current_price,
        )
        weekly_zone_bias, weekly_zone = self._zone_bias(
            weekly_candle["high"], weekly_candle["low"], current_price,
        )

        # ── 4. Fuse per-TF: swing wins, zone confirms or tie-breaks ────
        daily_bias = self._fuse(daily_swing, daily_zone_bias)
        weekly_bias = self._fuse(weekly_swing, weekly_zone_bias)

        # ── 5. Daily > Weekly for intraday bias (ICT: "banks use the daily
        # chart for daily bias"). Weekly provides context, not direction.
        direction = self._determine_direction(daily_bias, weekly_bias)
        confidence = self._confidence_level(daily_bias, weekly_bias, direction)
        weekly_mult = self._weekly_alignment_multiplier(daily_bias, weekly_bias)

        htf_levels = {
            "weekly_high": float(weekly_candle["high"]),
            "weekly_low": float(weekly_candle["low"]),
            "weekly_mid": (float(weekly_candle["high"]) + float(weekly_candle["low"])) / 2,
            "daily_high": float(daily_candle["high"]),
            "daily_low": float(daily_candle["low"]),
            "daily_mid": (float(daily_candle["high"]) + float(daily_candle["low"])) / 2,
            "current_price": current_price,
        }

        premium_discount = weekly_zone if weekly_zone != "equilibrium" else daily_zone

        return BiasResult(
            direction=direction,
            premium_discount=premium_discount,
            htf_levels=htf_levels,
            confidence=confidence,
            weekly_bias=weekly_bias,
            daily_bias=daily_bias,
            weekly_alignment_multiplier=weekly_mult,
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _zone_bias(high: float, low: float, price: float) -> tuple[str, str]:
        """
        Premium / discount zone classifier with a WIDE equilibrium band.

        - price below 35 % of the range → discount → bullish tilt
        - price above 65 % of the range → premium → bearish tilt
        - 35–65 % → equilibrium (neutral) — mid-range chop

        The old 2 % band flipped bias almost every bar; 30 % is closer to
        the real ICT equilibrium zone and lets structural swing bias lead.

        Returns: (bias_direction, zone_name)
        """
        range_val = high - low
        if range_val == 0:
            return ("neutral", "equilibrium")

        discount_cap = low + 0.35 * range_val  # below → discount
        premium_floor = low + 0.65 * range_val  # above → premium

        if price < discount_cap:
            return ("bullish", "discount")
        if price > premium_floor:
            return ("bearish", "premium")
        return ("neutral", "equilibrium")

    @staticmethod
    def _swing_bias(df: pd.DataFrame, tf_name: str) -> str:
        """
        HH-HL vs LH-LL structure check on completed candles.

        This is the PRIMARY bias signal: matches how ICT defines weekly /
        daily bias (swing structure, not where price sits within a single
        candle).

        Logic:
          - Skip the forming candle (iloc[-1]).
          - Compare last 2 completed candles → HH-HL = bullish, LH-LL =
            bearish, mixed = check 2-vs-2 aggregate.
          - Not enough data or still mixed → neutral.
        """
        if df is None or df.empty:
            return "neutral"

        # Drop the forming candle if we have ≥ 2 bars.
        completed = df.iloc[:-1] if len(df) >= 2 else df
        n = len(completed)
        if n < 2:
            return "neutral"

        last = completed.iloc[-1]
        prev = completed.iloc[-2]

        higher_high = last["high"] > prev["high"]
        higher_low = last["low"] > prev["low"]
        lower_high = last["high"] < prev["high"]
        lower_low = last["low"] < prev["low"]

        if higher_high and higher_low:
            return "bullish"
        if lower_high and lower_low:
            return "bearish"

        # Inside / outside bar: broaden the window to 2-vs-2 aggregate.
        if n >= 4:
            recent_high = float(completed.iloc[-2:]["high"].max())
            older_high = float(completed.iloc[-4:-2]["high"].max())
            recent_low = float(completed.iloc[-2:]["low"].min())
            older_low = float(completed.iloc[-4:-2]["low"].min())
            if recent_high > older_high and recent_low > older_low:
                return "bullish"
            if recent_high < older_high and recent_low < older_low:
                return "bearish"

        logger.debug("swing_bias %s: neutral (n=%d)", tf_name, n)
        return "neutral"

    @staticmethod
    def _fuse(swing: str, zone: str) -> str:
        """
        Fuse swing-structure bias (primary) with premium/discount (secondary).

        Rules:
          - Swing direction wins when non-neutral.
          - If swing is neutral but zone is non-neutral, use zone as a
            weaker signal (mean-reversion bias).
          - Both neutral → neutral.
        """
        if swing != "neutral":
            return swing
        return zone

    @staticmethod
    def _determine_direction(daily_bias: str, weekly_bias: str) -> str:
        """
        Fuse daily and weekly bias.

        Priority: Daily > Weekly for intraday trading.
        ICT: "Banks and institutional traders mostly utilize the daily chart."
        Weekly provides context (size multiplier) but daily defines direction.
        """
        if daily_bias != "neutral":
            return daily_bias
        return weekly_bias

    @staticmethod
    def _weekly_alignment_multiplier(daily_bias: str, weekly_bias: str) -> float:
        """
        Position-size multiplier based on daily/weekly agreement.

        - daily aligned with weekly (or weekly neutral) → 1.0 (full size)
        - daily opposed to weekly → 0.5 (trade with caution, half size)
        """
        if weekly_bias == "neutral" or daily_bias == "neutral":
            return 1.0
        if daily_bias == weekly_bias:
            return 1.0
        return 0.5

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
