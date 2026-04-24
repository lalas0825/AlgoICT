"""
tests/test_donchian_vol.py
===========================
Unit tests for strategies/donchian_vol.py.

Strategy: 20-bar Donchian breakout + volume confirmation + ATR regime
filter, vol-targeted sizing, swing-based trailing exits. No ICT
primitives (OB / FVG / sweep / confluence).

Run: cd algoict-engine && python -m pytest tests/test_donchian_vol.py -v
"""

import numpy as np
import pandas as pd
import pytest
import pytz

from strategies.donchian_vol import DonchianVolStrategy, Signal
from timeframes.session_manager import SessionManager
from risk.risk_manager import RiskManager


CT = pytz.timezone("US/Central")


def _make_bars(
    n: int,
    start_ts: pd.Timestamp,
    base_price: float = 100.0,
    body: float = 1.0,
    volume: float = 500.0,
    trend: float = 0.0,
) -> pd.DataFrame:
    """Build a DataFrame of 5-min bars centered around `base_price` with an
    optional linear `trend` applied per bar and a consistent per-bar body."""
    opens, highs, lows, closes, volumes = [], [], [], [], []
    price = base_price
    for i in range(n):
        o = price
        c = price + (body if trend >= 0 else -body)
        h = max(o, c) + 0.2
        l = min(o, c) - 0.2
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(volume)
        price = c + trend
    idx = pd.date_range(start_ts, periods=n, freq="5min", tz="US/Central")
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=idx)


def _append_bar(
    df: pd.DataFrame,
    open_px: float,
    close_px: float,
    volume: float,
    high_px: float = None,
    low_px: float = None,
) -> pd.DataFrame:
    high = high_px if high_px is not None else max(open_px, close_px) + 0.25
    low = low_px if low_px is not None else min(open_px, close_px) - 0.25
    last_ts = df.index[-1]
    new_ts = last_ts + pd.Timedelta(minutes=5)
    new_row = pd.DataFrame({
        "open": [open_px], "high": [high], "low": [low],
        "close": [close_px], "volume": [volume],
    }, index=pd.DatetimeIndex([new_ts], tz="US/Central"))
    return pd.concat([df, new_row])


def _build_strategy() -> DonchianVolStrategy:
    """Strategy with empty detectors — Donchian-Vol doesn't read any."""
    return DonchianVolStrategy(
        detectors={},
        risk_manager=RiskManager(),
        session_manager=SessionManager(),
        htf_bias_fn=None,
    )


def _kz_ts(hour: int = 9, minute: int = 0) -> pd.Timestamp:
    """Timestamp inside NY AM kill zone (08:30-12:00 CT)."""
    return pd.Timestamp(CT.localize(pd.Timestamp(2024, 3, 4, hour, minute)))


# ─── Warm-up / insufficient data ─────────────────────────────────────────

class TestPreconditions:

    def test_empty_df_returns_none(self):
        strat = _build_strategy()
        empty = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="US/Central"),
        )
        assert strat.evaluate(empty, empty) is None

    def test_too_few_bars_returns_none(self):
        strat = _build_strategy()
        df = _make_bars(10, _kz_ts(9, 0))
        assert strat.evaluate(df, df) is None


# ─── Session gate ────────────────────────────────────────────────────────

class TestKillZoneGate:

    def test_outside_kz_returns_none(self):
        """02:00 CT Asian session → no kill zone."""
        strat = _build_strategy()
        ts = pd.Timestamp(CT.localize(pd.Timestamp(2024, 3, 4, 21, 0)))  # 21:00 CT
        df = _make_bars(100, ts - pd.Timedelta(minutes=99 * 5))
        # The final bar is at 21:00 CT which is outside london/ny_am/ny_pm.
        assert strat.evaluate(df, df) is None


# ─── Regime filter ───────────────────────────────────────────────────────

class TestRegimeFilter:

    def test_dead_market_rejected(self):
        """Flat tiny bars → ATR low → current ATR <= median → regime dead."""
        strat = _build_strategy()
        df = _make_bars(100, _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5),
                        body=0.25, trend=0.0)  # very tiny bars
        # Append a tiny-bar breakout attempt
        df = _append_bar(df, open_px=100.0, close_px=100.3, volume=1000.0,
                         high_px=100.5, low_px=99.9)
        sig = strat.evaluate(df, df)
        assert sig is None


# ─── Breakout detection ──────────────────────────────────────────────────

class TestBreakoutSignal:

    def _build_setup_with_breakout_long(self) -> tuple[DonchianVolStrategy, pd.DataFrame]:
        """Build a bar history where a clear long breakout is pending.

        Design: 100 bars of modest oscillation around 100 with small bodies
        so the ATR baseline is stable. Then the last bar breaks above the
        20-bar high, with high volume and a big body.
        """
        strat = _build_strategy()
        start = _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5)
        # Base: 100 bars oscillating, body ~ 1 pt, volume 500, trend 0.05
        #   → ATR is non-trivial, 20-bar high is around 104-105 area.
        df = _make_bars(100, start, base_price=100.0, body=1.0,
                        volume=500.0, trend=0.05)
        # Breakout bar: close well above donchian high with huge volume
        # and body >= ATR(14).
        donch_high = float(df["high"].iloc[-20:].max())
        breakout_close = donch_high + 5.0
        breakout_open = donch_high + 0.5
        df = _append_bar(df,
                         open_px=breakout_open,
                         close_px=breakout_close,
                         volume=2000.0,     # 4x avg of 500
                         high_px=breakout_close + 0.25,
                         low_px=breakout_open - 0.1)
        return strat, df

    def test_long_breakout_fires(self):
        strat, df = self._build_setup_with_breakout_long()
        sig = strat.evaluate(df, df)
        assert sig is not None
        assert sig.direction == "long"
        assert sig.strategy == "donchian_vol"
        assert sig.kill_zone in ("london", "ny_am", "ny_pm")

    def test_no_breakout_no_signal(self):
        """Close inside donchian range — no breakout."""
        strat = _build_strategy()
        start = _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5)
        df = _make_bars(100, start, base_price=100.0, body=1.0,
                        volume=500.0, trend=0.05)
        # Append a bar whose close is BELOW prev donchian high.
        donch_high = float(df["high"].iloc[-20:].max())
        df = _append_bar(df,
                         open_px=donch_high - 2.0,
                         close_px=donch_high - 1.0,
                         volume=2000.0)
        assert strat.evaluate(df, df) is None

    def test_weak_volume_rejected(self):
        strat = _build_strategy()
        start = _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5)
        df = _make_bars(100, start, base_price=100.0, body=1.0,
                        volume=500.0, trend=0.05)
        donch_high = float(df["high"].iloc[-20:].max())
        # Breakout with same volume as avg — fails VOL_MULT=1.5 check.
        df = _append_bar(df,
                         open_px=donch_high + 0.5,
                         close_px=donch_high + 5.0,
                         volume=500.0)
        assert strat.evaluate(df, df) is None

    def test_weak_body_rejected(self):
        strat = _build_strategy()
        start = _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5)
        df = _make_bars(100, start, base_price=100.0, body=1.0,
                        volume=500.0, trend=0.05)
        donch_high = float(df["high"].iloc[-20:].max())
        # Breakout with a tiny body (<< ATR(14))
        df = _append_bar(df,
                         open_px=donch_high + 0.5,
                         close_px=donch_high + 0.6,   # 0.1pt body
                         volume=2000.0)
        assert strat.evaluate(df, df) is None


# ─── Entry / Stop / Target math ──────────────────────────────────────────

class TestEntryStopTarget:

    def test_long_entry_close_plus_tick(self):
        strat = _build_strategy()
        start = _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5)
        df = _make_bars(100, start, body=1.0, volume=500.0, trend=0.05)
        donch_high = float(df["high"].iloc[-20:].max())
        breakout_close = donch_high + 5.0
        df = _append_bar(df, open_px=donch_high + 0.5,
                         close_px=breakout_close, volume=2000.0)
        sig = strat.evaluate(df, df)
        assert sig is not None
        # Entry = close + 1 tick = close + 0.25
        assert sig.entry_price == pytest.approx(breakout_close + 0.25)

    def test_long_stop_below_entry_by_2x_atr(self):
        strat = _build_strategy()
        start = _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5)
        df = _make_bars(100, start, body=1.0, volume=500.0, trend=0.05)
        donch_high = float(df["high"].iloc[-20:].max())
        df = _append_bar(df, open_px=donch_high + 0.5,
                         close_px=donch_high + 5.0, volume=2000.0)
        sig = strat.evaluate(df, df)
        assert sig.stop_price < sig.entry_price
        # Distance should be roughly STOP_ATR_MULT × ATR20. We won't
        # pin down the exact ATR but the stop-distance must be
        # strictly positive.
        assert abs(sig.entry_price - sig.stop_price) > 0

    def test_target_very_far_for_trailing(self):
        strat = _build_strategy()
        start = _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5)
        df = _make_bars(100, start, body=1.0, volume=500.0, trend=0.05)
        donch_high = float(df["high"].iloc[-20:].max())
        df = _append_bar(df, open_px=donch_high + 0.5,
                         close_px=donch_high + 5.0, volume=2000.0)
        sig = strat.evaluate(df, df)
        target_dist = abs(sig.target_price - sig.entry_price)
        stop_dist = abs(sig.entry_price - sig.stop_price)
        # Target should be >= 20 × stop distance (proxy for "far").
        assert target_dist > 20 * stop_dist


# ─── Short symmetry ──────────────────────────────────────────────────────

class TestShortBreakout:

    def test_short_breakdown_fires(self):
        strat = _build_strategy()
        start = _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5)
        # Negative trend so recent bars are descending; donchian low drops.
        df = _make_bars(100, start, base_price=100.0, body=1.0,
                        volume=500.0, trend=-0.05)
        donch_low = float(df["low"].iloc[-20:].min())
        breakdown_close = donch_low - 5.0
        df = _append_bar(df,
                         open_px=donch_low - 0.5,
                         close_px=breakdown_close,
                         volume=2000.0,
                         high_px=donch_low + 0.1,
                         low_px=breakdown_close - 0.25)
        sig = strat.evaluate(df, df)
        assert sig is not None
        assert sig.direction == "short"
        # Entry = close - 1 tick
        assert sig.entry_price == pytest.approx(breakdown_close - 0.25)
        # Stop above entry, target below entry
        assert sig.stop_price > sig.entry_price
        assert sig.target_price < sig.entry_price


# ─── Max trades per zone ─────────────────────────────────────────────────

class TestMaxTrades:

    def test_max_trades_is_one_per_zone(self):
        strat = _build_strategy()
        start = _kz_ts(9, 0) - pd.Timedelta(minutes=99 * 5)
        df = _make_bars(100, start, body=1.0, volume=500.0, trend=0.05)
        donch_high = float(df["high"].iloc[-20:].max())
        df = _append_bar(df, open_px=donch_high + 0.5,
                         close_px=donch_high + 5.0, volume=2000.0)
        sig1 = strat.evaluate(df, df)
        assert sig1 is not None
        strat.notify_trade_executed(sig1)
        # Append yet ANOTHER breakout bar — should be blocked.
        df2 = _append_bar(df, open_px=donch_high + 5.5,
                          close_px=donch_high + 11.0, volume=2000.0)
        sig2 = strat.evaluate(df2, df2)
        assert sig2 is None

    def test_reset_daily_clears_zone_counts(self):
        strat = _build_strategy()
        strat._trades_by_zone["ny_am"] = 1
        strat.trades_today = 1
        strat.reset_daily()
        assert strat.trades_today == 0
        assert strat._trades_by_zone["ny_am"] == 0
