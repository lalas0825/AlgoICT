"""
strategies/donchian_vol.py
===========================
Donchian-Vol — trend-following baseline strategy.

Thesis: enter on N-bar Donchian breakout confirmed by volume and an ATR-
normalized body; size by volatility; exit via swing-based trailing stop.
No ICT concepts, no HTF bias, no confluence scoring. Designed to be the
simple statistically-validated benchmark against which the ICT-based
Silver Bullet / NY AM Reversal get compared.

Rationale for existence (2026-04-21): after a full session of iterations
on ICT strategies (v1-v3b on NY AM Reversal all negative, v4 Silver Bullet
+$11K on 2024 only), we needed a second strategy whose edge is documented
in academic literature (Moskowitz-Ooi-Pedersen 2012, Hurst-Ooi-Pedersen
2017) to triangulate whether the infrastructure is sound and to give the
Combine attempt a diversified pair of bets.

Signal (long; short is mirror)
------------------------------
1. bar.close > max(prev N=20 highs)           -- Donchian breakout
2. bar.volume > VOL_MULT × mean(prev 20 vol)  -- volume confirmation
3. bar.body >= BODY_ATR_MULT × ATR(14)        -- strong body
4. ATR(20) > median(ATR over last 60 bars)    -- regime is active (vol floor)
5. kill-zone active (london / ny_am / ny_pm)
6. no economic-event blackout in effect (passed through risk check)

Entry / Stop / Target
---------------------
entry  = bar.close + 1 tick            (long, pessimistic market-ish fill)
stop   = entry - STOP_ATR_MULT × ATR(20)   (default 2.0×)
target = entry + 50 × ATR               (far away — trailing does the exit)

Short is mirror.

Trade management
----------------
Uses the Backtester's "trailing" mode, which advances the stop to the most
recent swing low (long) / high (short) detected by `swing_entry`. This
approximates a structure-following trail that tightens as price runs away.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from risk.position_sizer import calculate_position

logger = logging.getLogger(__name__)


def _ts_hm(ts) -> str:
    try:
        return ts.strftime("%H:%M")
    except AttributeError:
        return str(ts)


@dataclass
class Signal:
    strategy: str
    symbol: str
    direction: str
    entry_price: float
    stop_price: float
    target_price: float
    contracts: int
    confluence_score: int = 0
    confluence_breakdown: dict = field(default_factory=dict)
    confluence_reasons: list = field(default_factory=list)
    timestamp: pd.Timestamp = None
    kill_zone: str = ""

    def __repr__(self) -> str:
        return (
            f"Signal({self.strategy} {self.direction} {self.symbol} "
            f"entry={self.entry_price:.2f} stop={self.stop_price:.2f} "
            f"target={self.target_price:.2f} x{self.contracts} "
            f"kz={self.kill_zone})"
        )


class DonchianVolStrategy:
    """N-bar Donchian breakout with volume + ATR confirmation, vol-targeted."""

    # Kill zones for breakout: all RTH sessions. Asian skipped (low vol).
    KILL_ZONES = ("london", "ny_am", "ny_pm")
    MAX_TRADES_PER_ZONE = 1
    MAX_TRADES = MAX_TRADES_PER_ZONE * 3
    ENTRY_TF = "5min"
    # We don't actually consume the context TF — kept for Backtester
    # compatibility (it passes both; we ignore the second arg).
    CONTEXT_TF = "15min"
    SYMBOL = "MNQ"

    # --- Parameters (walk-forward tuneable later) ----------------------
    DONCHIAN_LOOKBACK = 20          # bars
    ATR_PERIOD = 14
    ATR_REGIME_PERIOD = 20
    ATR_REGIME_LOOKBACK = 60        # bars used for median comparison
    VOL_MULT = 1.5                  # volume >= VOL_MULT × 20-bar avg
    BODY_ATR_MULT = 1.0             # body >= BODY_ATR_MULT × ATR(14)
    STOP_ATR_MULT = 2.0             # stop = entry - 2 × ATR(20)
    TARGET_ATR_MULT = 50.0          # target = entry + 50 × ATR (trailing exits)

    def __init__(
        self,
        detectors: dict,
        risk_manager,
        session_manager,
        htf_bias_fn=None,            # accepted for API compat; ignored
    ):
        self.detectors = detectors
        self.risk = risk_manager
        self.session = session_manager
        self.htf_bias_fn = htf_bias_fn  # unused
        self.trades_today: int = 0
        self._trades_by_zone: dict[str, int] = {z: 0 for z in self.KILL_ZONES}
        self._last_evaluated_bar_ts = None
        # Track the last bar where we SAW a breakout that was rejected by
        # regime/session filters — used only for debug logging (not state).
        self._last_signal_ts = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def evaluate(
        self,
        candles_entry: pd.DataFrame,
        candles_context: pd.DataFrame,
    ) -> Optional[Signal]:
        """Evaluate the latest 5-min bar for a Donchian breakout."""

        # Need enough bars for lookback + ATR + regime median.
        min_bars = max(
            self.DONCHIAN_LOOKBACK + 1,
            self.ATR_PERIOD + 1,
            self.ATR_REGIME_LOOKBACK + self.ATR_REGIME_PERIOD + 1,
        )
        if candles_entry.empty or len(candles_entry) < min_bars:
            return None

        last = candles_entry.iloc[-1]
        ts = candles_entry.index[-1]
        close = float(last["close"])
        open_ = float(last["open"])
        volume = float(last["volume"])
        body = abs(close - open_)

        # Dedup on successful fires.
        if ts == self._last_evaluated_bar_ts:
            return None

        # ── 1. Session gate ────────────────────────────────────────────
        active_zone = next(
            (kz for kz in self.KILL_ZONES if self.session.is_kill_zone(ts, kz)),
            None,
        )
        if active_zone is None:
            logger.info(
                "EVAL donchian_vol [%s]: signal=reject, reason=outside_kz",
                _ts_hm(ts),
            )
            return None

        if self.risk.check_hard_close(ts):
            logger.info(
                "EVAL donchian_vol [%s]: signal=reject, reason=past_hard_close",
                _ts_hm(ts),
            )
            return None

        allowed, reason = self.risk.can_trade()
        if not allowed:
            logger.info(
                "EVAL donchian_vol [%s]: signal=reject, reason=risk_blocked (%s)",
                _ts_hm(ts), reason,
            )
            return None

        if self._trades_by_zone.get(active_zone, 0) >= self.MAX_TRADES_PER_ZONE:
            logger.info(
                "EVAL donchian_vol [%s]: signal=reject, reason=max_trades (zone=%s)",
                _ts_hm(ts), active_zone,
            )
            return None

        # ── 2. Compute ATR(14) and ATR(20) ─────────────────────────────
        atr_14 = self._atr(candles_entry, self.ATR_PERIOD)
        if atr_14 is None or atr_14 <= 0:
            return None
        atr_20 = self._atr(candles_entry, self.ATR_REGIME_PERIOD)
        if atr_20 is None or atr_20 <= 0:
            return None

        # ── 3. Regime filter: current ATR > rolling median ─────────────
        # Past ATR_REGIME_LOOKBACK bars' ATRs to form median.
        atr_window = self._atr_series(
            candles_entry, self.ATR_REGIME_PERIOD, self.ATR_REGIME_LOOKBACK,
        )
        if atr_window is None or len(atr_window) == 0:
            return None
        atr_median = float(np.median(atr_window))
        if atr_20 <= atr_median:
            logger.info(
                "EVAL donchian_vol [%s]: signal=reject, reason=regime_dead "
                "(atr_20=%.3f <= median=%.3f)",
                _ts_hm(ts), atr_20, atr_median,
            )
            return None

        # ── 4. Donchian breakout check ─────────────────────────────────
        # Highs/lows EXCLUDING the current bar.
        prev_highs = candles_entry["high"].iloc[-self.DONCHIAN_LOOKBACK - 1: -1]
        prev_lows = candles_entry["low"].iloc[-self.DONCHIAN_LOOKBACK - 1: -1]
        donch_high = float(prev_highs.max())
        donch_low = float(prev_lows.min())

        if close > donch_high:
            direction = "long"
        elif close < donch_low:
            direction = "short"
        else:
            # No breakout — common case, no log spam.
            return None

        # ── 5. Volume confirmation ─────────────────────────────────────
        prev_vol = candles_entry["volume"].iloc[-self.DONCHIAN_LOOKBACK - 1: -1]
        avg_vol = float(prev_vol.mean())
        if avg_vol > 0 and volume < self.VOL_MULT * avg_vol:
            logger.info(
                "EVAL donchian_vol [%s]: signal=reject, reason=weak_volume "
                "(%.0f < %.1fx avg %.0f)",
                _ts_hm(ts), volume, self.VOL_MULT, avg_vol,
            )
            return None

        # ── 6. Body strength ───────────────────────────────────────────
        if body < self.BODY_ATR_MULT * atr_14:
            logger.info(
                "EVAL donchian_vol [%s]: signal=reject, reason=weak_body "
                "(%.2fpts < %.1fx ATR %.2fpts)",
                _ts_hm(ts), body, self.BODY_ATR_MULT, atr_14,
            )
            return None

        # ── 7. Entry / Stop / Target ───────────────────────────────────
        tick = config.MNQ_TICK_SIZE
        if direction == "long":
            entry_price = close + tick
            stop_price = entry_price - self.STOP_ATR_MULT * atr_20
            target_price = entry_price + self.TARGET_ATR_MULT * atr_20
        else:
            entry_price = close - tick
            stop_price = entry_price + self.STOP_ATR_MULT * atr_20
            target_price = entry_price - self.TARGET_ATR_MULT * atr_20

        stop_points = abs(entry_price - stop_price)
        if stop_points <= 0:
            return None

        # Snap stop / target to tick grid.
        def _snap(px: float) -> float:
            return round(px / tick) * tick
        stop_price = _snap(stop_price)
        target_price = _snap(target_price)

        # ── 8. Position sizing ─────────────────────────────────────────
        pos = calculate_position(
            stop_points=stop_points,
            risk=config.RISK_PER_TRADE,
            point_value=config.MNQ_POINT_VALUE,
            max_contracts=config.MAX_CONTRACTS,
        )
        contracts = max(1, int(pos.contracts * self.risk.position_multiplier))

        # ── 9. Build signal ────────────────────────────────────────────
        signal = Signal(
            strategy="donchian_vol",
            symbol=self.SYMBOL,
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            contracts=contracts,
            timestamp=ts,
            kill_zone=active_zone,
        )
        self._last_evaluated_bar_ts = ts

        logger.info(
            "EVAL donchian_vol [%s]: signal=fire %s donch=[%.2f-%.2f] "
            "close=%.2f vol=%.0f (%.1fx avg) body=%.2f (%.1fx ATR14) "
            "atr20=%.2f (regime>median=%.2f) | %s",
            _ts_hm(ts), direction, donch_low, donch_high, close, volume,
            volume / max(avg_vol, 1), body, body / atr_14,
            atr_20, atr_median, signal,
        )
        return signal

    # ------------------------------------------------------------------ #
    # Backtester / engine lifecycle                                        #
    # ------------------------------------------------------------------ #

    def rollback_last_evaluated_bar(self, ts) -> None:
        if self._last_evaluated_bar_ts == ts:
            self._last_evaluated_bar_ts = None

    def notify_trade_executed(self, signal) -> None:
        zone = getattr(signal, "kill_zone", "") or ""
        if zone in self._trades_by_zone:
            self._trades_by_zone[zone] = self._trades_by_zone[zone] + 1
        self.trades_today += 1

    def reset_daily(self) -> None:
        self.trades_today = 0
        self._trades_by_zone = {z: 0 for z in self.KILL_ZONES}
        self._last_evaluated_bar_ts = None

    # ------------------------------------------------------------------ #
    # Private helpers — ATR                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _true_range(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
        n = len(highs)
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            prev_close = closes[i - 1]
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        return tr

    @classmethod
    def _atr(cls, candles: pd.DataFrame, period: int) -> Optional[float]:
        """Simple Wilder-ish ATR: mean of true range over last `period` bars."""
        if len(candles) < period + 1:
            return None
        highs = candles["high"].values
        lows = candles["low"].values
        closes = candles["close"].values
        tr = cls._true_range(highs, lows, closes)
        return float(tr[-period:].mean())

    @classmethod
    def _atr_series(
        cls,
        candles: pd.DataFrame,
        period: int,
        lookback: int,
    ) -> Optional[np.ndarray]:
        """Return last `lookback` ATR values (computed over rolling `period`)."""
        n = len(candles)
        if n < period + lookback:
            return None
        highs = candles["high"].values
        lows = candles["low"].values
        closes = candles["close"].values
        tr = cls._true_range(highs, lows, closes)
        # Rolling mean of TR over `period` at each point.
        out = np.zeros(lookback)
        for i in range(lookback):
            # Index of the "current" bar for this historical ATR value:
            #   last bar index (n-1) - (lookback - 1) + i
            end_idx = n - 1 - (lookback - 1) + i
            start_idx = end_idx - period + 1
            if start_idx < 0:
                out[i] = np.nan
            else:
                out[i] = tr[start_idx: end_idx + 1].mean()
        mask = ~np.isnan(out)
        return out[mask]
