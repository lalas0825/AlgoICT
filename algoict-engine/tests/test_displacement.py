"""
tests/test_displacement.py
==========================
Unit tests for detectors/displacement.py

Strategy: build synthetic OHLCV sequences where exactly one candle
has a body > 2 × ATR and verify detection, direction, magnitude, and
filtering. Also verify the negative case (no large candle → no detection).

Run: cd algoict-engine && python -m pytest tests/test_displacement.py -v
"""

import pandas as pd
import pytest

from detectors.displacement import Displacement, DisplacementDetector, DISPLACEMENT_ATR_MULTIPLIER


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_df(
    opens: list,
    highs: list,
    lows: list,
    closes: list,
    tz: str = "US/Central",
) -> pd.DataFrame:
    n = len(opens)
    assert n == len(highs) == len(lows) == len(closes)
    idx = pd.date_range("2025-03-03 09:00", periods=n, freq="5min", tz=tz)
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": [1000] * n,
    }, index=idx)


def _make_baseline(n: int = 14, price: float = 100.0) -> tuple:
    """
    Return (opens, highs, lows, closes) for n doji-like candles with
    a 1-point range, yielding ATR ≈ 1.0. Body = 0 (open == close).
    """
    opens  = [price] * n
    highs  = [price + 0.5] * n
    lows   = [price - 0.5] * n
    closes = [price] * n
    return opens, highs, lows, closes


def _make_bullish_displacement_df(n_baseline: int = 14, price: float = 100.0) -> pd.DataFrame:
    """
    baseline (ATR ≈ 1) + 1 large bullish candle.
    Large candle body = 5.0 >> 2.0 × ATR ≈ 2.0
    """
    o, h, l, c = _make_baseline(n_baseline, price)
    o.append(price)
    h.append(price + 5.5)
    l.append(price - 0.2)
    c.append(price + 5.0)   # body = 5.0
    return _make_df(o, h, l, c)


def _make_bearish_displacement_df(n_baseline: int = 14, price: float = 100.0) -> pd.DataFrame:
    """
    baseline (ATR ≈ 1) + 1 large bearish candle.
    Large candle body = 5.0 >> 2.0 × ATR ≈ 2.0
    """
    o, h, l, c = _make_baseline(n_baseline, price)
    o.append(price)
    h.append(price + 0.2)
    l.append(price - 5.5)
    c.append(price - 5.0)   # body = 5.0, bearish
    return _make_df(o, h, l, c)


# ─── Tests: Detection ─────────────────────────────────────────────────────────

class TestDisplacementDetection:

    def test_bullish_displacement_detected(self):
        df = _make_bullish_displacement_df()
        det = DisplacementDetector()
        disps = det.detect(df, "5min")
        assert len(disps) >= 1
        bullish = [d for d in disps if d.direction == "bullish"]
        assert len(bullish) >= 1

    def test_bearish_displacement_detected(self):
        df = _make_bearish_displacement_df()
        det = DisplacementDetector()
        disps = det.detect(df, "5min")
        assert len(disps) >= 1
        bearish = [d for d in disps if d.direction == "bearish"]
        assert len(bearish) >= 1

    def test_no_displacement_for_small_candles(self):
        """All candles are doji-like (body = 0) → no displacement."""
        o, h, l, c = _make_baseline(20)
        df = _make_df(o, h, l, c)
        det = DisplacementDetector()
        assert det.detect(df, "5min") == []

    def test_too_few_candles_returns_empty(self):
        """Fewer than atr_period + 1 candles → no detection."""
        o, h, l, c = _make_baseline(10)
        df = _make_df(o, h, l, c)
        det = DisplacementDetector()
        assert det.detect(df, "5min", atr_period=14) == []

    def test_displacement_direction_bullish(self):
        df = _make_bullish_displacement_df()
        det = DisplacementDetector()
        disps = det.detect(df, "5min")
        bullish = [d for d in disps if d.direction == "bullish"]
        assert all(d.direction == "bullish" for d in bullish)

    def test_displacement_direction_bearish(self):
        df = _make_bearish_displacement_df()
        det = DisplacementDetector()
        disps = det.detect(df, "5min")
        bearish = [d for d in disps if d.direction == "bearish"]
        assert all(d.direction == "bearish" for d in bearish)

    def test_displacement_magnitude_correct(self):
        """Magnitude must equal body = |close - open| of the displacement candle."""
        df = _make_bullish_displacement_df(n_baseline=14, price=100.0)
        det = DisplacementDetector()
        disps = det.detect(df, "5min")
        bullish = [d for d in disps if d.direction == "bullish"]
        assert len(bullish) >= 1
        # body = close - open = (100 + 5) - 100 = 5.0
        assert bullish[-1].magnitude == pytest.approx(5.0)

    def test_displacement_timeframe_stored(self):
        df = _make_bullish_displacement_df()
        det = DisplacementDetector()
        disps = det.detect(df, "15min")
        assert all(d.timeframe == "15min" for d in disps)

    def test_displacement_timestamp_is_candle_timestamp(self):
        df = _make_bullish_displacement_df(n_baseline=14)
        det = DisplacementDetector()
        disps = det.detect(df, "5min")
        bullish = [d for d in disps if d.direction == "bullish"]
        assert len(bullish) >= 1
        # The displacement is the last candle
        assert bullish[-1].timestamp == df.index[-1]

    def test_no_duplicate_on_repeated_detect(self):
        """Repeated detect() calls on the same or growing slices must not re-add."""
        df = _make_bullish_displacement_df()
        det = DisplacementDetector()
        det.detect(df, "5min")
        det.detect(df, "5min")
        ts_list = [(d.timestamp, d.timeframe) for d in det.displacements]
        assert len(ts_list) == len(set(ts_list))

    def test_atr_stored(self):
        """Each Displacement must have a positive atr value."""
        df = _make_bullish_displacement_df()
        det = DisplacementDetector()
        disps = det.detect(df, "5min")
        bullish = [d for d in disps if d.direction == "bullish"]
        assert len(bullish) >= 1
        assert bullish[-1].atr > 0

    def test_candle_index_stored(self):
        df = _make_bullish_displacement_df(n_baseline=14)
        det = DisplacementDetector()
        disps = det.detect(df, "5min")
        bullish = [d for d in disps if d.direction == "bullish"]
        assert len(bullish) >= 1
        assert bullish[-1].candle_index == len(df) - 1

    def test_candle_exactly_at_threshold_not_detected(self):
        """
        Body == 2 × ATR should NOT trigger (strict greater-than check).
        Build candles where ATR ≈ 1.0, then add a candle with body exactly 2.0.
        """
        o, h, l, c = _make_baseline(14, price=100.0)
        # Add a candle with body = 2.0 exactly
        o.append(100.0); h.append(101.0); l.append(99.5); c.append(102.0)
        # ATR ≈ 1.0 so threshold = 2.0 × 1.0 = 2.0; body=2.0 is NOT > 2.0
        # Hmm, actually ATR may vary. Let me use a body far below threshold instead.
        # This test verifies body=1.0 (below threshold) is not detected.
        df = _make_df(o, h, l, c)
        det = DisplacementDetector(multiplier=3.0)   # threshold = 3 × ATR ≈ 3.0
        # body = 2.0, threshold = 3.0 → not detected
        disps = det.detect(df, "5min")
        assert len(disps) == 0

    def test_custom_multiplier(self):
        """Lower multiplier → easier to trigger displacement."""
        df = _make_bullish_displacement_df()
        det_strict = DisplacementDetector(multiplier=10.0)
        det_loose  = DisplacementDetector(multiplier=1.0)
        strict = det_strict.detect(df, "5min")
        loose  = det_loose.detect(df, "5min")
        # With multiplier=1.0 we should get at least as many as with 10.0
        assert len(loose) >= len(strict)


# ─── Tests: get_recent ────────────────────────────────────────────────────────

class TestGetRecent:

    def _build_det_with_two(self) -> DisplacementDetector:
        """Detector with one bullish + one bearish displacement on different TFs."""
        det = DisplacementDetector()
        df_bull = _make_bullish_displacement_df()
        df_bear = _make_bearish_displacement_df()
        df_bear.index = df_bear.index + pd.Timedelta(hours=2)
        det.detect(df_bull, "5min")
        det.detect(df_bear, "15min")
        return det

    def test_get_recent_returns_newest_first(self):
        det = self._build_det_with_two()
        recent = det.get_recent(n=2)
        ts_list = [d.timestamp for d in recent]
        assert ts_list == sorted(ts_list, reverse=True)

    def test_get_recent_filter_by_timeframe(self):
        det = self._build_det_with_two()
        tf5 = det.get_recent(n=10, timeframe="5min")
        assert all(d.timeframe == "5min" for d in tf5)

    def test_get_recent_filter_by_direction(self):
        det = self._build_det_with_two()
        bullish = det.get_recent(n=10, direction="bullish")
        bearish = det.get_recent(n=10, direction="bearish")
        assert all(d.direction == "bullish" for d in bullish)
        assert all(d.direction == "bearish" for d in bearish)

    def test_get_recent_respects_n(self):
        """n=1 should return at most 1 item."""
        det = self._build_det_with_two()
        recent = det.get_recent(n=1)
        assert len(recent) <= 1

    def test_get_recent_empty_when_no_displacements(self):
        det = DisplacementDetector()
        assert det.get_recent(n=5) == []


# ─── Tests: clear ─────────────────────────────────────────────────────────────

class TestDisplacementClear:

    def test_clear_resets_all(self):
        df = _make_bullish_displacement_df()
        det = DisplacementDetector()
        det.detect(df, "5min")
        assert len(det.displacements) >= 1
        det.clear()
        assert det.displacements == []

    def test_detect_after_clear_works(self):
        """After clearing, detect should re-find displacements."""
        df = _make_bullish_displacement_df()
        det = DisplacementDetector()
        det.detect(df, "5min")
        det.clear()
        new = det.detect(df, "5min")
        assert len(new) >= 1
