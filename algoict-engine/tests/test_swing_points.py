"""
tests/test_swing_points.py
===========================
Unit tests for detectors/swing_points.py

Swing High: high[N] is strictly greater than every high in the lookback
            window on both sides.
Swing Low:  low[N] is strictly less than every low in the lookback window
            on both sides.

Run: cd algoict-engine && python -m pytest tests/test_swing_points.py -v
"""

import pandas as pd
import pytest

from detectors.swing_points import SwingPoint, SwingPointDetector


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_df(highs: list, lows: list, tz: str = "US/Central") -> pd.DataFrame:
    """
    Build a minimal OHLCV DataFrame from explicit high/low arrays.
    open = low, close = high (irrelevant for swing detection).
    """
    n = len(highs)
    assert n == len(lows), "highs/lows must have same length"
    idx = pd.date_range("2025-03-03 09:00", periods=n, freq="5min", tz=tz)
    return pd.DataFrame({
        "open":   lows,
        "high":   highs,
        "low":    lows,
        "close":  highs,
        "volume": [100] * n,
    }, index=idx)


# Lookback=2 detector for deterministic tests
def _det(lookback: int = 2) -> SwingPointDetector:
    return SwingPointDetector(lookbacks={"5min": lookback, "15min": lookback})


# ─── Tests: Swing High Detection ─────────────────────────────────────────────

class TestSwingHighDetection:

    def test_obvious_swing_high_detected(self):
        """
        Clear swing high: one peak surrounded by lower highs.
        Highs: [10, 12, 20, 12, 10]  → candle[2] is swing high (lookback=2)
        """
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sh = [s for s in swings if s.type == "high"]
        assert len(sh) == 1
        assert sh[0].price == 20.0
        assert sh[0].type == "high"
        assert sh[0].timeframe == "5min"
        assert sh[0].broken is False

    def test_swing_high_price_matches_candle_high(self):
        """swing_high.price == high of the pivot candle."""
        highs = [100, 110, 150, 110, 100]
        lows  = [ 95, 105, 145, 105,  95]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sh = [s for s in swings if s.type == "high"]
        assert sh[0].price == 150.0

    def test_swing_high_not_detected_if_equal_neighbour(self):
        """
        Swing high requires STRICT greater-than.
        Highs: [10, 12, 12, 12, 10] → candle[2] ties with neighbour → NOT a swing high.
        """
        highs = [10, 12, 12, 12, 10]
        lows  = [ 9, 11, 11, 11,  9]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sh = [s for s in swings if s.type == "high"]
        assert len(sh) == 0

    def test_two_swing_highs_in_series(self):
        """
        Two distinct peaks in a longer series.
        Highs: [10, 15, 20, 15, 10, 15, 25, 15, 10]
        With lookback=2: peak at idx 2 (20) and idx 6 (25).
        """
        highs = [10, 15, 20, 15, 10, 15, 25, 15, 10]
        lows  = [ 9, 14, 19, 14,  9, 14, 24, 14,  9]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sh = [s for s in swings if s.type == "high"]
        assert len(sh) == 2
        prices = sorted(s.price for s in sh)
        assert prices == [20.0, 25.0]

    def test_no_swing_high_in_uptrend(self):
        """
        Pure uptrend: each high is strictly greater than the previous.
        No candle has highs lower on both sides → no swing high.
        """
        highs = [10, 12, 14, 16, 18, 20]
        lows  = [ 9, 11, 13, 15, 17, 19]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sh = [s for s in swings if s.type == "high"]
        assert len(sh) == 0

    def test_swing_high_timestamp_correct(self):
        """swing_high.timestamp matches the index of the pivot candle."""
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sh = [s for s in swings if s.type == "high"][0]
        # Pivot is candle[2] → index[2]
        assert sh.timestamp == df.index[2]


# ─── Tests: Swing Low Detection ──────────────────────────────────────────────

class TestSwingLowDetection:

    def test_obvious_swing_low_detected(self):
        """
        Clear swing low: one trough surrounded by higher lows.
        Lows: [10, 8, 4, 8, 10]  → candle[2] is swing low (lookback=2)
        """
        highs = [15, 13, 9, 13, 15]
        lows  = [10,  8, 4,  8, 10]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sl = [s for s in swings if s.type == "low"]
        assert len(sl) == 1
        assert sl[0].price == 4.0

    def test_swing_low_price_matches_candle_low(self):
        """swing_low.price == low of the pivot candle."""
        highs = [100, 90, 70, 90, 100]
        lows  = [ 95, 85, 60, 85,  95]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sl = [s for s in swings if s.type == "low"][0]
        assert sl.price == 60.0

    def test_swing_low_not_detected_if_equal_neighbour(self):
        """Swing low requires STRICT less-than."""
        highs = [15, 12, 12, 12, 15]
        lows  = [10,  8,  8,  8, 10]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sl = [s for s in swings if s.type == "low"]
        assert len(sl) == 0

    def test_no_swing_low_in_downtrend(self):
        """
        Pure downtrend → each low is lower than previous, no trough.
        """
        highs = [20, 18, 16, 14, 12, 10]
        lows  = [19, 17, 15, 13, 11,  9]
        df = _make_df(highs, lows)
        swings = _det().detect(df, "5min")

        sl = [s for s in swings if s.type == "low"]
        assert len(sl) == 0


# ─── Tests: Mixed Swing Highs and Lows ───────────────────────────────────────

class TestMixedSwings:

    def test_zig_zag_produces_alternating_swings(self):
        """
        Classic zig-zag: SH-SL-SH pattern with lookback=1.
        With lookback=1 we only need high[i] > immediate neighbours.

        Highs: [10, 20, 12, 22, 12, 24, 12]
        Lows:  [ 9,  8, 11,  9, 11,  9, 11]
        Swing highs (lookback=1): idx 1 (20), idx 3 (22), idx 5 (24)
        Swing lows  (lookback=1): idx 2 (11), idx 4 (11)
        """
        # Highs: peaks at idx 1 (20), 3 (22), 5 (24) with lookback=1
        # Lows: troughs ONLY at idx 2 (3) and idx 4 (2) — odd-idx lows are rising so NOT troughs
        highs = [10, 20, 12, 22, 12, 24, 12]
        lows  = [ 5,  8,  3,  7,  2,  9,  6]
        df = _make_df(highs, lows)
        swings = _det(lookback=1).detect(df, "5min")

        sh = [s for s in swings if s.type == "high"]
        sl = [s for s in swings if s.type == "low"]

        assert len(sh) == 3, f"Expected 3 swing highs, got {len(sh)}: {sh}"
        assert len(sl) == 2, f"Expected 2 swing lows, got {len(sl)}: {sl}"
        assert sorted(s.price for s in sh) == [20.0, 22.0, 24.0]
        assert sorted(s.price for s in sl) == [2.0, 3.0]

    def test_not_enough_candles_returns_empty(self):
        """
        Fewer candles than 2*lookback+1 → no swings possible.
        lookback=2 requires 5 candles minimum.
        """
        highs = [10, 20, 15]  # only 3 candles
        lows  = [ 9,  8, 14]
        df = _make_df(highs, lows)
        swings = _det(lookback=2).detect(df, "5min")
        assert swings == []

    def test_empty_dataframe_returns_empty(self):
        """Empty DataFrame returns []."""
        df = _make_df([], [])
        swings = _det().detect(df, "5min")
        assert swings == []


# ─── Tests: update_broken ────────────────────────────────────────────────────

class TestUpdateBroken:

    def test_swing_high_broken_when_price_exceeds(self):
        """Swing high is broken when current_price > swing_high.price."""
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")

        broken = det.update_broken(current_price=21.0)

        assert len(broken) == 1
        assert broken[0].type == "high"
        assert broken[0].broken is True

    def test_swing_high_not_broken_at_equal_price(self):
        """Swing high at 20.0 not broken if current_price == 20.0 (must be strictly greater)."""
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")

        broken = det.update_broken(current_price=20.0)

        assert len(broken) == 0

    def test_swing_low_broken_when_price_falls_below(self):
        """Swing low is broken when current_price < swing_low.price."""
        highs = [15, 13, 9, 13, 15]
        lows  = [10,  8, 4,  8, 10]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")

        broken = det.update_broken(current_price=3.0)

        assert len(broken) == 1
        assert broken[0].type == "low"
        assert broken[0].broken is True

    def test_swing_low_not_broken_at_equal_price(self):
        """Swing low at 4.0 not broken if current_price == 4.0."""
        highs = [15, 13, 9, 13, 15]
        lows  = [10,  8, 4,  8, 10]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")

        broken = det.update_broken(current_price=4.0)
        assert len(broken) == 0

    def test_already_broken_not_counted_twice(self):
        """Once broken, a swing point is not reported again."""
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")

        det.update_broken(21.0)          # first call — marks it broken
        broken_again = det.update_broken(25.0)  # second call

        assert len(broken_again) == 0


# ─── Tests: get_active ───────────────────────────────────────────────────────

class TestGetActive:

    def test_get_active_returns_only_unbroken(self):
        """get_active() excludes broken swing points."""
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")

        det.update_broken(21.0)  # break the swing high
        active = det.get_active()
        assert all(not sp.broken for sp in active)

    def test_get_active_filter_high(self):
        """get_active('high') returns only unbroken swing highs."""
        highs = [10, 12, 20, 12, 10]
        lows  = [10,  8,  4,  8, 10]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")

        active_highs = det.get_active("high")
        assert all(sp.type == "high" for sp in active_highs)

    def test_get_active_filter_low(self):
        """get_active('low') returns only unbroken swing lows."""
        highs = [10, 12, 20, 12, 10]
        lows  = [10,  8,  4,  8, 10]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")

        active_lows = det.get_active("low")
        assert all(sp.type == "low" for sp in active_lows)


# ─── Tests: get_latest_swing_high / get_latest_swing_low ─────────────────────

class TestGetLatest:

    def test_get_latest_swing_high_returns_most_recent(self):
        """get_latest_swing_high returns the chronologically last unbroken SH."""
        highs = [10, 20, 12, 25, 12]
        lows  = [ 9,  8, 11,  8, 11]
        df = _make_df(highs, lows)
        det = _det(lookback=1)
        det.detect(df, "5min")

        latest = det.get_latest_swing_high()
        assert latest is not None
        assert latest.price == 25.0

    def test_get_latest_swing_low_returns_most_recent(self):
        """get_latest_swing_low returns the chronologically last unbroken SL."""
        highs = [15, 10, 15, 8, 15]
        lows  = [14,  5, 14, 2, 14]
        df = _make_df(highs, lows)
        det = _det(lookback=1)
        det.detect(df, "5min")

        latest = det.get_latest_swing_low()
        assert latest is not None
        assert latest.price == 2.0

    def test_get_latest_returns_none_when_all_broken(self):
        """Returns None when all swing highs are broken."""
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")
        det.update_broken(21.0)

        assert det.get_latest_swing_high() is None

    def test_get_latest_returns_none_when_no_swings(self):
        """Returns None when no swing points detected yet."""
        det = _det()
        assert det.get_latest_swing_high() is None
        assert det.get_latest_swing_low() is None


# ─── Tests: State and Reset ───────────────────────────────────────────────────

class TestStateManagement:

    def test_swing_points_accumulate_across_calls(self):
        """Second detect() call adds to existing swing_points list."""
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        det = _det()

        det.detect(df, "5min")
        count_first = len(det.swing_points)

        det.detect(df, "5min")  # same data, second call
        count_second = len(det.swing_points)

        assert count_second >= count_first

    def test_clear_resets_all_swing_points(self):
        """clear() empties self.swing_points."""
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        det = _det()
        det.detect(df, "5min")
        assert len(det.swing_points) > 0

        det.clear()
        assert len(det.swing_points) == 0

    def test_swing_point_timeframe_label(self):
        """SwingPoint.timeframe matches the detect() timeframe argument."""
        highs = [10, 12, 20, 12, 10]
        lows  = [ 9, 11, 18, 11,  9]
        df = _make_df(highs, lows)
        det = _det()
        swings = det.detect(df, "15min")

        assert all(sp.timeframe == "15min" for sp in swings)

    def test_default_lookback_from_config(self):
        """Detector initialized without lookbacks uses config.SWING_LOOKBACK."""
        import config
        det = SwingPointDetector()
        assert det.lookbacks == config.SWING_LOOKBACK


# ─── Tests: Lookback Sensitivity ─────────────────────────────────────────────

class TestLookbackSensitivity:

    def test_larger_lookback_detects_fewer_swings(self):
        """
        With lookback=1 a local peak is easily detected.
        With lookback=3 the same data may not qualify.
        """
        # Create data where only local peaks (lookback=1) exist, not strong swings (lookback=3)
        highs = [10, 15, 12, 14, 11]
        lows  = [ 9, 14, 11, 13, 10]
        df = _make_df(highs, lows)

        det_tight = SwingPointDetector(lookbacks={"5min": 1})
        det_wide  = SwingPointDetector(lookbacks={"5min": 3})

        swings_tight = det_tight.detect(df, "5min")
        swings_wide  = det_wide.detect(df, "5min")

        assert len(swings_tight) >= len(swings_wide)
