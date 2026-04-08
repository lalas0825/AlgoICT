"""
tests/test_liquidity.py
========================
Unit tests for detectors/liquidity.py

Run: cd algoict-engine && python -m pytest tests/test_liquidity.py -v
"""

import math
import pandas as pd
import pytest

from detectors.swing_points import SwingPoint, SwingPointDetector
from detectors.liquidity import LiquidityLevel, LiquidityDetector


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_daily_df(highs: list, lows: list, closes: list) -> pd.DataFrame:
    n = len(highs)
    idx = pd.date_range("2025-03-03", periods=n, freq="D", tz="US/Central")
    return pd.DataFrame({
        "open": closes, "high": highs, "low": lows, "close": closes, "volume": [1e6] * n,
    }, index=idx)


def _make_weekly_df(highs: list, lows: list, closes: list) -> pd.DataFrame:
    n = len(highs)
    idx = pd.date_range("2025-03-03", periods=n, freq="W", tz="US/Central")
    return pd.DataFrame({
        "open": closes, "high": highs, "low": lows, "close": closes, "volume": [5e6] * n,
    }, index=idx)


def _make_candle(high: float, low: float, close: float) -> pd.Series:
    return pd.Series({"open": close, "high": high, "low": low, "close": close, "volume": 1000})


def _inject_swing_high(sp: SwingPointDetector, price: float, ts: pd.Timestamp, tf: str) -> SwingPoint:
    swing = SwingPoint(price=price, timestamp=ts, type="high", timeframe=tf)
    sp.swing_points.append(swing)
    return swing


def _inject_swing_low(sp: SwingPointDetector, price: float, ts: pd.Timestamp, tf: str) -> SwingPoint:
    swing = SwingPoint(price=price, timestamp=ts, type="low", timeframe=tf)
    sp.swing_points.append(swing)
    return swing


BASE_TS = pd.Timestamp("2025-03-03 09:00", tz="US/Central")


# ─── Tests: Equal Levels ─────────────────────────────────────────────────────

class TestEqualLevels:

    def test_two_nearby_highs_make_equal_highs(self):
        """Two swing highs within 0.1% → one equal_highs BSL level."""
        sp = SwingPointDetector()
        _inject_swing_high(sp, 100.00, BASE_TS, "5min")
        _inject_swing_high(sp, 100.05, BASE_TS + pd.Timedelta(hours=1), "5min")

        det = LiquidityDetector()
        levels = det.detect_equal_levels(sp, "5min", threshold_pct=0.001)

        eq_highs = [l for l in levels if l.type == "equal_highs"]
        assert len(eq_highs) == 1
        assert eq_highs[0].price == pytest.approx(100.025, rel=1e-4)

    def test_two_nearby_lows_make_equal_lows(self):
        """Two swing lows within 0.1% → one equal_lows SSL level."""
        sp = SwingPointDetector()
        _inject_swing_low(sp, 50.00, BASE_TS, "5min")
        _inject_swing_low(sp, 50.03, BASE_TS + pd.Timedelta(hours=1), "5min")

        det = LiquidityDetector()
        levels = det.detect_equal_levels(sp, "5min", threshold_pct=0.001)

        eq_lows = [l for l in levels if l.type == "equal_lows"]
        assert len(eq_lows) == 1
        assert eq_lows[0].price == pytest.approx(50.015, rel=1e-4)

    def test_distant_highs_no_equal_level(self):
        """Two highs far apart → no equal_highs."""
        sp = SwingPointDetector()
        _inject_swing_high(sp, 100.00, BASE_TS, "5min")
        _inject_swing_high(sp, 105.00, BASE_TS + pd.Timedelta(hours=1), "5min")

        det = LiquidityDetector()
        levels = det.detect_equal_levels(sp, "5min", threshold_pct=0.001)
        eq_highs = [l for l in levels if l.type == "equal_highs"]
        assert len(eq_highs) == 0

    def test_three_nearby_highs_single_cluster(self):
        """Three swing highs all within 0.1% → one cluster (not three separate)."""
        sp = SwingPointDetector()
        _inject_swing_high(sp, 100.00, BASE_TS, "5min")
        _inject_swing_high(sp, 100.05, BASE_TS + pd.Timedelta(hours=1), "5min")
        _inject_swing_high(sp, 100.08, BASE_TS + pd.Timedelta(hours=2), "5min")

        det = LiquidityDetector()
        levels = det.detect_equal_levels(sp, "5min", threshold_pct=0.001)
        eq_highs = [l for l in levels if l.type == "equal_highs"]
        assert len(eq_highs) == 1

    def test_two_distant_clusters(self):
        """Two distinct clusters of highs → two equal_highs levels."""
        sp = SwingPointDetector()
        # Cluster A: ~100
        _inject_swing_high(sp, 100.00, BASE_TS, "5min")
        _inject_swing_high(sp, 100.04, BASE_TS + pd.Timedelta(hours=1), "5min")
        # Cluster B: ~200
        _inject_swing_high(sp, 200.00, BASE_TS + pd.Timedelta(hours=2), "5min")
        _inject_swing_high(sp, 200.10, BASE_TS + pd.Timedelta(hours=3), "5min")

        det = LiquidityDetector()
        levels = det.detect_equal_levels(sp, "5min", threshold_pct=0.001)
        eq_highs = [l for l in levels if l.type == "equal_highs"]
        assert len(eq_highs) == 2

    def test_single_swing_high_no_equal_level(self):
        """Only one swing high — can't form a cluster (min_count=2)."""
        sp = SwingPointDetector()
        _inject_swing_high(sp, 100.00, BASE_TS, "5min")

        det = LiquidityDetector()
        levels = det.detect_equal_levels(sp, "5min")
        assert len(levels) == 0

    def test_broken_swings_excluded(self):
        """Broken swing highs must not contribute to equal levels."""
        sp = SwingPointDetector()
        h1 = _inject_swing_high(sp, 100.00, BASE_TS, "5min")
        h2 = _inject_swing_high(sp, 100.04, BASE_TS + pd.Timedelta(hours=1), "5min")
        h1.broken = True  # mark as broken

        det = LiquidityDetector()
        levels = det.detect_equal_levels(sp, "5min", threshold_pct=0.001)
        eq_highs = [l for l in levels if l.type == "equal_highs"]
        assert len(eq_highs) == 0  # only 1 unbroken swing remains

    def test_timeframe_isolation(self):
        """Equal levels only formed from swings of the requested timeframe."""
        sp = SwingPointDetector()
        _inject_swing_high(sp, 100.00, BASE_TS, "5min")
        _inject_swing_high(sp, 100.04, BASE_TS + pd.Timedelta(hours=1), "5min")
        _inject_swing_high(sp, 100.02, BASE_TS + pd.Timedelta(hours=2), "15min")

        det = LiquidityDetector()
        levels_5 = det.detect_equal_levels(sp, "5min")
        levels_15 = det.detect_equal_levels(sp, "15min")
        assert len([l for l in levels_5 if l.type == "equal_highs"]) == 1
        assert len([l for l in levels_15 if l.type == "equal_highs"]) == 0  # only 1 swing on 15min

    def test_equal_level_timestamp_is_latest_in_cluster(self):
        """Timestamp of an equal level should be the most recent swing in the cluster."""
        ts1 = BASE_TS
        ts2 = BASE_TS + pd.Timedelta(hours=2)
        sp = SwingPointDetector()
        _inject_swing_high(sp, 100.00, ts1, "5min")
        _inject_swing_high(sp, 100.04, ts2, "5min")

        det = LiquidityDetector()
        levels = det.detect_equal_levels(sp, "5min")
        eq = [l for l in levels if l.type == "equal_highs"]
        assert eq[0].timestamp == ts2

    def test_empty_swing_points_no_levels(self):
        sp = SwingPointDetector()
        det = LiquidityDetector()
        assert det.detect_equal_levels(sp, "5min") == []


# ─── Tests: PDH / PDL ─────────────────────────────────────────────────────────

class TestPDHPDL:

    def test_pdh_pdl_from_single_day(self):
        df = _make_daily_df(highs=[110], lows=[90], closes=[100])
        det = LiquidityDetector()
        pdh, pdl = det.get_pdh_pdl(df)
        assert pdh == pytest.approx(110.0)
        assert pdl == pytest.approx(90.0)

    def test_pdh_pdl_last_row_used(self):
        """PDH/PDL uses the LAST row (most recent completed day)."""
        df = _make_daily_df(
            highs=[120, 115, 110],
            lows=[95, 90, 85],
            closes=[110, 105, 100],
        )
        det = LiquidityDetector()
        pdh, pdl = det.get_pdh_pdl(df)
        assert pdh == pytest.approx(110.0)
        assert pdl == pytest.approx(85.0)

    def test_pdh_pdl_empty_returns_nan(self):
        df = _make_daily_df([], [], [])
        det = LiquidityDetector()
        pdh, pdl = det.get_pdh_pdl(df)
        assert math.isnan(pdh)
        assert math.isnan(pdl)


# ─── Tests: PWH / PWL ─────────────────────────────────────────────────────────

class TestPWHPWL:

    def test_pwh_pwl_from_single_week(self):
        df = _make_weekly_df(highs=[200], lows=[150], closes=[175])
        det = LiquidityDetector()
        pwh, pwl = det.get_pwh_pwl(df)
        assert pwh == pytest.approx(200.0)
        assert pwl == pytest.approx(150.0)

    def test_pwh_pwl_last_row_used(self):
        df = _make_weekly_df(
            highs=[220, 210, 200],
            lows=[160, 155, 150],
            closes=[185, 180, 175],
        )
        det = LiquidityDetector()
        pwh, pwl = det.get_pwh_pwl(df)
        assert pwh == pytest.approx(200.0)
        assert pwl == pytest.approx(150.0)

    def test_pwh_pwl_empty_returns_nan(self):
        df = _make_weekly_df([], [], [])
        det = LiquidityDetector()
        pwh, pwl = det.get_pwh_pwl(df)
        assert math.isnan(pwh)
        assert math.isnan(pwl)


# ─── Tests: build_key_levels ─────────────────────────────────────────────────

class TestBuildKeyLevels:

    def test_builds_pdh_pdl_levels(self):
        df_d = _make_daily_df([110], [90], [100])
        det = LiquidityDetector()
        levels = det.build_key_levels(df_daily=df_d)
        types = {l.type for l in levels}
        assert "PDH" in types
        assert "PDL" in types

    def test_builds_pwh_pwl_levels(self):
        df_w = _make_weekly_df([200], [150], [175])
        det = LiquidityDetector()
        levels = det.build_key_levels(df_weekly=df_w)
        types = {l.type for l in levels}
        assert "PWH" in types
        assert "PWL" in types

    def test_builds_all_four_when_both_provided(self):
        df_d = _make_daily_df([110], [90], [100])
        df_w = _make_weekly_df([200], [150], [175])
        det = LiquidityDetector()
        levels = det.build_key_levels(df_daily=df_d, df_weekly=df_w)
        types = {l.type for l in levels}
        assert {"PDH", "PDL", "PWH", "PWL"} == types

    def test_correct_prices(self):
        df_d = _make_daily_df([110], [90], [100])
        det = LiquidityDetector()
        levels = det.build_key_levels(df_daily=df_d)
        pdh = next(l for l in levels if l.type == "PDH")
        pdl = next(l for l in levels if l.type == "PDL")
        assert pdh.price == pytest.approx(110.0)
        assert pdl.price == pytest.approx(90.0)

    def test_empty_dataframes_no_levels(self):
        det = LiquidityDetector()
        levels = det.build_key_levels(
            df_daily=_make_daily_df([], [], []),
            df_weekly=_make_weekly_df([], [], []),
        )
        assert levels == []

    def test_levels_not_swept_initially(self):
        df_d = _make_daily_df([110], [90], [100])
        det = LiquidityDetector()
        levels = det.build_key_levels(df_daily=df_d)
        assert all(not l.swept for l in levels)


# ─── Tests: check_sweep ───────────────────────────────────────────────────────

class TestCheckSweep:

    def test_bsl_sweep_detected(self):
        """Wick above BSL level, closes back below → sweep."""
        level = LiquidityLevel(price=100.0, type="PDH")
        det = LiquidityDetector()
        # high=101 > 100, close=99 < 100
        candle = _make_candle(high=101.0, low=98.0, close=99.0)
        swept = det.check_sweep(candle, [level])
        assert len(swept) == 1
        assert level.swept

    def test_bsl_no_sweep_when_close_above(self):
        """Wick above BSL but closes ABOVE level → not a sweep (continuation)."""
        level = LiquidityLevel(price=100.0, type="PDH")
        det = LiquidityDetector()
        candle = _make_candle(high=102.0, low=99.0, close=101.0)  # close > 100
        swept = det.check_sweep(candle, [level])
        assert len(swept) == 0
        assert not level.swept

    def test_bsl_no_sweep_when_high_doesnt_reach(self):
        """High doesn't touch BSL → no sweep."""
        level = LiquidityLevel(price=100.0, type="PDH")
        det = LiquidityDetector()
        candle = _make_candle(high=99.5, low=97.0, close=98.0)
        det.check_sweep(candle, [level])
        assert not level.swept

    def test_ssl_sweep_detected(self):
        """Wick below SSL level, closes back above → sweep."""
        level = LiquidityLevel(price=50.0, type="PDL")
        det = LiquidityDetector()
        # low=49 < 50, close=51 > 50
        candle = _make_candle(high=52.0, low=49.0, close=51.0)
        swept = det.check_sweep(candle, [level])
        assert len(swept) == 1
        assert level.swept

    def test_ssl_no_sweep_when_close_below(self):
        """Wick below SSL but closes BELOW level → not a sweep (breakdown)."""
        level = LiquidityLevel(price=50.0, type="PDL")
        det = LiquidityDetector()
        candle = _make_candle(high=51.0, low=48.0, close=49.0)  # close < 50
        swept = det.check_sweep(candle, [level])
        assert len(swept) == 0

    def test_ssl_no_sweep_when_low_above(self):
        """Low stays above SSL → no sweep."""
        level = LiquidityLevel(price=50.0, type="PDL")
        det = LiquidityDetector()
        candle = _make_candle(high=53.0, low=51.0, close=52.0)
        det.check_sweep(candle, [level])
        assert not level.swept

    def test_equal_highs_type_is_bsl(self):
        """equal_highs behaves like BSL in sweep detection."""
        level = LiquidityLevel(price=100.0, type="equal_highs")
        det = LiquidityDetector()
        candle = _make_candle(high=101.0, low=98.0, close=99.0)
        swept = det.check_sweep(candle, [level])
        assert len(swept) == 1

    def test_equal_lows_type_is_ssl(self):
        """equal_lows behaves like SSL in sweep detection."""
        level = LiquidityLevel(price=50.0, type="equal_lows")
        det = LiquidityDetector()
        candle = _make_candle(high=52.0, low=49.0, close=51.0)
        swept = det.check_sweep(candle, [level])
        assert len(swept) == 1

    def test_pwh_is_bsl(self):
        level = LiquidityLevel(price=200.0, type="PWH")
        det = LiquidityDetector()
        candle = _make_candle(high=201.0, low=198.0, close=199.0)
        swept = det.check_sweep(candle, [level])
        assert len(swept) == 1

    def test_pwl_is_ssl(self):
        level = LiquidityLevel(price=150.0, type="PWL")
        det = LiquidityDetector()
        candle = _make_candle(high=152.0, low=149.0, close=151.0)
        swept = det.check_sweep(candle, [level])
        assert len(swept) == 1

    def test_already_swept_level_not_re_swept(self):
        """Once swept, the level must not be returned again."""
        level = LiquidityLevel(price=100.0, type="PDH", swept=True)
        det = LiquidityDetector()
        candle = _make_candle(high=101.0, low=98.0, close=99.0)
        swept = det.check_sweep(candle, [level])
        assert swept == []

    def test_multiple_levels_partial_sweep(self):
        """Only the levels whose conditions are met are swept."""
        bsl = LiquidityLevel(price=100.0, type="PDH")
        ssl = LiquidityLevel(price=90.0, type="PDL")
        det = LiquidityDetector()
        # Candle: high=101, low=91, close=99 — sweeps BSL (high>100 & close<100),
        # but NOT SSL (low>90 so wick doesn't reach)
        candle = _make_candle(high=101.0, low=91.0, close=99.0)
        swept = det.check_sweep(candle, [bsl, ssl])
        assert len(swept) == 1
        assert swept[0].type == "PDH"
        assert not ssl.swept

    def test_returns_empty_when_no_levels(self):
        det = LiquidityDetector()
        candle = _make_candle(high=101.0, low=99.0, close=100.0)
        assert det.check_sweep(candle, []) == []
