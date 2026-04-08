"""
tests/test_fvg.py
=================
Unit tests for detectors/fair_value_gap.py

Strategy: build minimal 3-candle OHLCV sequences where the gap condition
is clear, then verify detection, mitigation, and filtering.

Run: cd algoict-engine && python -m pytest tests/test_fvg.py -v
"""

import pandas as pd
import pytest

from detectors.fair_value_gap import FVG, FairValueGapDetector


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_df(
    highs: list,
    lows: list,
    closes: list,
    tz: str = "US/Central",
) -> pd.DataFrame:
    n = len(highs)
    assert n == len(lows) == len(closes)
    idx = pd.date_range("2025-03-03 09:00", periods=n, freq="5min", tz=tz)
    return pd.DataFrame({
        "open":   closes,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": [100] * n,
    }, index=idx)


# ─── Tests: Detection ────────────────────────────────────────────────────────

class TestFVGDetection:

    def test_bullish_fvg_detected(self):
        """
        Candles: idx0.high=10, idx1=body, idx2.low=15
        highs[0]=10, lows[2]=15  → gap: [10, 15]
        """
        highs  = [10, 13, 18]
        lows   = [ 8, 11, 15]
        closes = [ 9, 12, 17]
        df = _make_df(highs, lows, closes)

        det = FairValueGapDetector()
        fvgs = det.detect(df, "5min")

        assert len(fvgs) == 1
        fvg = fvgs[0]
        assert fvg.direction == "bullish"
        assert fvg.bottom == 10.0   # highs[i-1]
        assert fvg.top == 15.0      # lows[i+1]
        assert fvg.timeframe == "5min"
        assert not fvg.mitigated

    def test_bearish_fvg_detected(self):
        """
        Candles: idx0.low=20, idx1=body, idx2.high=15
        lows[0]=20, highs[2]=15 → gap: [15, 20]
        """
        highs  = [25, 22, 15]
        lows   = [20, 17, 12]
        closes = [22, 18, 13]
        df = _make_df(highs, lows, closes)

        det = FairValueGapDetector()
        fvgs = det.detect(df, "5min")

        assert len(fvgs) == 1
        fvg = fvgs[0]
        assert fvg.direction == "bearish"
        assert fvg.top == 20.0      # lows[i-1]
        assert fvg.bottom == 15.0   # highs[i+1]
        assert not fvg.mitigated

    def test_no_fvg_when_candles_overlap(self):
        """Candles overlap — no gap."""
        highs  = [12, 14, 16]
        lows   = [ 8, 10, 12]
        closes = [10, 12, 14]
        df = _make_df(highs, lows, closes)

        det = FairValueGapDetector()
        fvgs = det.detect(df, "5min")
        assert fvgs == []

    def test_no_fvg_when_exactly_touching(self):
        """
        highs[0] == lows[2] → gap size = 0, strict < required: no FVG.
        """
        highs  = [10, 13, 18]
        lows   = [ 8, 11, 10]   # lows[2] == highs[0] → touching, not gapped
        closes = [ 9, 12, 14]
        df = _make_df(highs, lows, closes)

        det = FairValueGapDetector()
        fvgs = det.detect(df, "5min")
        assert fvgs == []

    def test_too_few_candles_returns_empty(self):
        highs  = [10, 15]
        lows   = [ 8, 12]
        closes = [ 9, 13]
        df = _make_df(highs, lows, closes)

        det = FairValueGapDetector()
        assert det.detect(df, "5min") == []

    def test_empty_dataframe_returns_empty(self):
        df = _make_df([], [], [])
        det = FairValueGapDetector()
        assert det.detect(df, "5min") == []

    def test_multiple_fvgs_in_sequence(self):
        """
        5-candle sequence should detect exactly 2 bullish FVGs (at idx 1 and idx 3).
        Candle i is the centre of the 3-candle window [i-1, i, i+1].

        To prevent an unintended FVG at i=2, lows[3] must be ≤ highs[1]:
          i=2 check: highs[1]=13 < lows[3]=12 → False → no FVG ✓
        """
        #  idx: 0   1   2   3   4
        highs  = [10, 13, 20, 23, 30]
        lows   = [ 8, 11, 15, 12, 27]
        closes = [ 9, 12, 18, 20, 28]
        # FVG at i=1: highs[0]=10 < lows[2]=15  ✓
        # NO FVG i=2: highs[1]=13 < lows[3]=12  → False ✓
        # FVG at i=3: highs[2]=20 < lows[4]=27  ✓
        df = _make_df(highs, lows, closes)

        det = FairValueGapDetector()
        fvgs = det.detect(df, "5min")

        assert len(fvgs) == 2
        assert all(f.direction == "bullish" for f in fvgs)
        assert fvgs[0].bottom == 10.0
        assert fvgs[0].top == 15.0
        assert fvgs[1].bottom == 20.0
        assert fvgs[1].top == 27.0

    def test_fvg_timestamp_is_middle_candle(self):
        """FVG timestamp must be the middle (index i) candle."""
        highs  = [10, 13, 18]
        lows   = [ 8, 11, 15]
        closes = [ 9, 12, 17]
        df = _make_df(highs, lows, closes)

        det = FairValueGapDetector()
        fvgs = det.detect(df, "5min")

        assert fvgs[0].timestamp == df.index[1]

    def test_no_duplicate_on_repeated_detect(self):
        """
        Calling detect() twice on a growing slice must not re-detect the same FVG.
        """
        highs  = [10, 13, 18, 20, 22]
        lows   = [ 8, 11, 15, 16, 18]
        closes = [ 9, 12, 17, 18, 20]
        df = _make_df(highs, lows, closes)

        det = FairValueGapDetector()
        det.detect(df.iloc[:3], "5min")
        det.detect(df.iloc[:5], "5min")

        # The FVG at idx 1 should only exist once
        assert len(det.fvgs) == len({f.timestamp for f in det.fvgs})

    def test_per_timeframe_stored_separately(self):
        highs  = [10, 13, 18]
        lows   = [ 8, 11, 15]
        closes = [ 9, 12, 17]
        df = _make_df(highs, lows, closes)

        det = FairValueGapDetector()
        det.detect(df, "5min")
        det.detect(df, "15min")

        tfs = {f.timeframe for f in det.fvgs}
        assert "5min" in tfs
        assert "15min" in tfs


# ─── Tests: Mitigation ────────────────────────────────────────────────────────

class TestFVGMitigation:

    def _build_bullish_fvg(self) -> tuple[FairValueGapDetector, FVG]:
        """Build a detector with one bullish FVG: bottom=10, top=15, mid=12.5"""
        highs  = [10, 13, 18]
        lows   = [ 8, 11, 15]
        closes = [ 9, 12, 17]
        df = _make_df(highs, lows, closes)
        det = FairValueGapDetector()
        det.detect(df, "5min")
        return det, det.fvgs[0]

    def _build_bearish_fvg(self) -> tuple[FairValueGapDetector, FVG]:
        """Build a detector with one bearish FVG: bottom=15, top=20, mid=17.5"""
        highs  = [25, 22, 15]
        lows   = [20, 17, 12]
        closes = [22, 18, 13]
        df = _make_df(highs, lows, closes)
        det = FairValueGapDetector()
        det.detect(df, "5min")
        return det, det.fvgs[0]

    def test_bullish_fvg_mitigated_at_midpoint(self):
        """Bullish FVG mitigated when price drops to midpoint."""
        det, fvg = self._build_bullish_fvg()
        assert fvg.midpoint == pytest.approx(12.5)
        mitigated = det.update_mitigation(12.5)
        assert len(mitigated) == 1
        assert fvg.mitigated

    def test_bullish_fvg_mitigated_below_midpoint(self):
        det, fvg = self._build_bullish_fvg()
        det.update_mitigation(11.0)   # below midpoint (12.5)
        assert fvg.mitigated

    def test_bullish_fvg_not_mitigated_above_midpoint(self):
        det, fvg = self._build_bullish_fvg()
        det.update_mitigation(13.0)   # above midpoint
        assert not fvg.mitigated

    def test_bearish_fvg_mitigated_at_midpoint(self):
        """Bearish FVG mitigated when price rises to midpoint."""
        det, fvg = self._build_bearish_fvg()
        assert fvg.midpoint == pytest.approx(17.5)
        det.update_mitigation(17.5)
        assert fvg.mitigated

    def test_bearish_fvg_mitigated_above_midpoint(self):
        det, fvg = self._build_bearish_fvg()
        det.update_mitigation(19.0)
        assert fvg.mitigated

    def test_bearish_fvg_not_mitigated_below_midpoint(self):
        det, fvg = self._build_bearish_fvg()
        det.update_mitigation(16.0)
        assert not fvg.mitigated

    def test_double_mitigation_no_duplicate(self):
        """Once mitigated, calling update again must not append it twice."""
        det, fvg = self._build_bullish_fvg()
        det.update_mitigation(12.0)
        result2 = det.update_mitigation(12.0)
        assert result2 == []

    def test_mitigation_returns_list_of_mitigated(self):
        det, _ = self._build_bullish_fvg()
        result = det.update_mitigation(12.0)
        assert isinstance(result, list)
        assert len(result) == 1


# ─── Tests: get_active / filtering ──────────────────────────────────────────

class TestFVGGetActive:

    def setup_method(self):
        """Build 3 FVGs: bullish on 5min, bearish on 5min, bullish on 15min."""
        self.det = FairValueGapDetector()

        # Bullish FVG on 5min
        h5b = [10, 13, 18]; l5b = [8, 11, 15]; c5b = [9, 12, 17]
        self.det.detect(_make_df(h5b, l5b, c5b), "5min")

        # Bearish FVG on 5min (different timestamps via longer df)
        h5r = [25, 22, 15]; l5r = [20, 17, 12]; c5r = [22, 18, 13]
        df5r = _make_df(h5r, l5r, c5r)
        # Shift timestamps to avoid collision
        df5r.index = df5r.index + pd.Timedelta(hours=1)
        self.det.detect(df5r, "5min")

        # Bullish FVG on 15min
        h15 = [10, 13, 18]; l15 = [8, 11, 15]; c15 = [9, 12, 17]
        df15 = _make_df(h15, l15, c15)
        df15.index = df15.index + pd.Timedelta(hours=2)
        self.det.detect(df15, "15min")

    def test_get_active_returns_all_unmitigated(self):
        assert len(self.det.get_active()) == 3

    def test_filter_by_timeframe(self):
        tf5 = self.det.get_active(timeframe="5min")
        tf15 = self.det.get_active(timeframe="15min")
        assert len(tf5) == 2
        assert len(tf15) == 1

    def test_filter_by_direction(self):
        bullish = self.det.get_active(direction="bullish")
        bearish = self.det.get_active(direction="bearish")
        assert len(bullish) == 2
        assert len(bearish) == 1

    def test_mitigated_fvgs_excluded(self):
        # Mitigate the bullish 5min FVG (bottom=10, top=15, mid=12.5)
        fvg_5min_bull = self.det.get_active(timeframe="5min", direction="bullish")[0]
        fvg_5min_bull.mitigated = True
        assert len(self.det.get_active()) == 2

    def test_get_active_sorted_ascending(self):
        active = self.det.get_active()
        ts_list = [f.timestamp for f in active]
        assert ts_list == sorted(ts_list)


# ─── Tests: get_nearest ──────────────────────────────────────────────────────

class TestFVGGetNearest:

    def test_returns_nearest_fvg(self):
        """Two bullish FVGs at midpoints 12.5 and 50 — nearest to price 48 should be 50."""
        det = FairValueGapDetector()
        # FVG1: bottom=10, top=15, mid=12.5
        h1 = [10, 13, 18]; l1 = [8, 11, 15]; c1 = [9, 12, 17]
        det.detect(_make_df(h1, l1, c1), "5min")

        # FVG2: bottom=45, top=55, mid=50
        h2 = [45, 50, 60]; l2 = [40, 46, 55]; c2 = [44, 48, 58]
        df2 = _make_df(h2, l2, c2)
        df2.index = df2.index + pd.Timedelta(hours=1)
        det.detect(df2, "5min")

        nearest = det.get_nearest(48.0)
        assert nearest is not None
        assert nearest.midpoint == pytest.approx(50.0)

    def test_returns_none_when_no_active(self):
        det = FairValueGapDetector()
        assert det.get_nearest(100.0) is None


# ─── Tests: clear ────────────────────────────────────────────────────────────

class TestFVGClear:

    def test_clear_resets_all(self):
        highs  = [10, 13, 18]
        lows   = [ 8, 11, 15]
        closes = [ 9, 12, 17]
        df = _make_df(highs, lows, closes)
        det = FairValueGapDetector()
        det.detect(df, "5min")
        assert len(det.fvgs) == 1
        det.clear()
        assert det.fvgs == []
