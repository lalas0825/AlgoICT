"""
tests/test_order_block.py
=========================
Unit tests for detectors/order_block.py

Strategy: build synthetic OHLCV sequences with clear displacement candles
(large bodies ≥ 1.5 × ATR), verify OB detection, validation, mitigation,
and filtering.

Run: cd algoict-engine && python -m pytest tests/test_order_block.py -v
"""

import pandas as pd
import pytest

from detectors.swing_points import SwingPointDetector
from detectors.fair_value_gap import FairValueGapDetector
from detectors.order_block import OrderBlock, OrderBlockDetector, OB_ATR_MULTIPLIER


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
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": [1000] * n,
    }, index=idx)


def _make_bullish_displacement_df(n_padding: int = 14):
    """
    Returns a DataFrame where:
      - bars 0..n_padding-1: small consolidation (build ATR baseline)
      - bar n_padding:       last bearish candle → becomes Bullish OB
      - bar n_padding+1:     large bullish displacement candle
    """
    opens  = []
    highs  = []
    lows   = []
    closes = []

    # Build ATR baseline with small 1-point candles around price=100
    for i in range(n_padding):
        opens.append(100.0)
        highs.append(101.0)
        lows.append(99.0)
        closes.append(100.0)

    # OB candle: bearish (close < open)
    opens.append(101.0)
    highs.append(102.0)
    lows.append(99.0)
    closes.append(99.5)   # bearish

    # Displacement candle: large bullish (body >> ATR)
    opens.append(99.5)
    highs.append(115.0)
    lows.append(99.0)
    closes.append(114.0)  # body = 14.5 >> ATR ≈ 2

    return _make_df(opens, highs, lows, closes)


def _make_bearish_displacement_df(n_padding: int = 14):
    """
    Returns a DataFrame where:
      - bars 0..n_padding-1: small consolidation
      - bar n_padding:       last bullish candle → becomes Bearish OB
      - bar n_padding+1:     large bearish displacement candle
    """
    opens  = []
    highs  = []
    lows   = []
    closes = []

    for i in range(n_padding):
        opens.append(100.0)
        highs.append(101.0)
        lows.append(99.0)
        closes.append(100.0)

    # OB candle: bullish (close > open)
    opens.append(99.0)
    highs.append(102.0)
    lows.append(98.5)
    closes.append(101.5)   # bullish

    # Displacement candle: large bearish
    opens.append(101.5)
    highs.append(102.0)
    lows.append(87.0)
    closes.append(87.5)    # body = 14 >> ATR ≈ 2

    return _make_df(opens, highs, lows, closes)


# ─── Tests: Basic Detection ───────────────────────────────────────────────────

class TestOrderBlockDetection:

    def test_bullish_ob_detected(self):
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        obs = det.detect(df, "5min")

        bullish_obs = [ob for ob in obs if ob.direction == "bullish"]
        assert len(bullish_obs) >= 1

    def test_bullish_ob_is_last_bearish_candle(self):
        df = _make_bullish_displacement_df(n_padding=14)
        det = OrderBlockDetector()
        obs = det.detect(df, "5min")

        bullish_obs = [ob for ob in obs if ob.direction == "bullish"]
        assert len(bullish_obs) >= 1
        ob = bullish_obs[-1]
        # The OB should be the bearish candle at index n_padding (open=101, close=99.5)
        assert ob.high == pytest.approx(102.0)
        assert ob.low == pytest.approx(99.0)

    def test_bearish_ob_detected(self):
        df = _make_bearish_displacement_df()
        det = OrderBlockDetector()
        obs = det.detect(df, "5min")

        bearish_obs = [ob for ob in obs if ob.direction == "bearish"]
        assert len(bearish_obs) >= 1

    def test_bearish_ob_is_last_bullish_candle(self):
        df = _make_bearish_displacement_df(n_padding=14)
        det = OrderBlockDetector()
        obs = det.detect(df, "5min")

        bearish_obs = [ob for ob in obs if ob.direction == "bearish"]
        assert len(bearish_obs) >= 1
        ob = bearish_obs[-1]
        # The OB should be the bullish candle (open=99, close=101.5)
        assert ob.high == pytest.approx(102.0)
        assert ob.low == pytest.approx(98.5)

    def test_no_ob_without_displacement(self):
        """Small candles — no displacement → no OB."""
        opens  = [100] * 20
        highs  = [101] * 20
        lows   = [ 99] * 20
        closes = [100] * 20
        df = _make_df(opens, highs, lows, closes)
        det = OrderBlockDetector()
        obs = det.detect(df, "5min")
        assert obs == []

    def test_too_few_candles_returns_empty(self):
        opens  = [100, 99]
        highs  = [101, 100]
        lows   = [ 99,  98]
        closes = [100, 99]
        df = _make_df(opens, highs, lows, closes)
        det = OrderBlockDetector()
        assert det.detect(df, "5min") == []

    def test_ob_timeframe_stored(self):
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        obs = det.detect(df, "15min")
        bullish = [ob for ob in obs if ob.direction == "bullish"]
        assert all(ob.timeframe == "15min" for ob in bullish)

    def test_no_duplicate_on_repeated_detect(self):
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        det.detect(df, "5min")  # repeat
        ts_list = [ob.timestamp for ob in det.order_blocks]
        assert len(ts_list) == len(set(ts_list))


# ─── Tests: Proximal / Distal ─────────────────────────────────────────────────

class TestOrderBlockEdges:

    def test_bullish_ob_proximal_is_high(self):
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        obs = det.detect(df, "5min")
        bullish = [ob for ob in obs if ob.direction == "bullish"]
        assert len(bullish) >= 1
        ob = bullish[-1]
        assert ob.proximal == ob.high

    def test_bullish_ob_distal_is_low(self):
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        obs = det.detect(df, "5min")
        bullish = [ob for ob in obs if ob.direction == "bullish"]
        ob = bullish[-1]
        assert ob.distal == ob.low

    def test_bearish_ob_proximal_is_low(self):
        df = _make_bearish_displacement_df()
        det = OrderBlockDetector()
        obs = det.detect(df, "5min")
        bearish = [ob for ob in obs if ob.direction == "bearish"]
        assert len(bearish) >= 1
        ob = bearish[-1]
        assert ob.proximal == ob.low

    def test_bearish_ob_distal_is_high(self):
        df = _make_bearish_displacement_df()
        det = OrderBlockDetector()
        obs = det.detect(df, "5min")
        bearish = [ob for ob in obs if ob.direction == "bearish"]
        ob = bearish[-1]
        assert ob.distal == ob.high


# ─── Tests: Validation ────────────────────────────────────────────────────────

class TestOrderBlockValidation:

    def test_ob_unvalidated_without_swing_or_fvg(self):
        """Without swing_points or fvg_detector, validated must be False."""
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        obs = det.detect(df, "5min", swing_points=None, fvg_detector=None)
        bullish = [ob for ob in obs if ob.direction == "bullish"]
        assert len(bullish) >= 1
        assert all(not ob.validated for ob in bullish)

    def test_ob_validated_with_sweep_and_fvg(self):
        """
        Build a scenario where:
        - A swing low exists just before the OB candle
        - An FVG exists just after the OB candle (same direction)
        Then validated should be True.
        """
        df = _make_bullish_displacement_df(n_padding=14)
        n = len(df)
        ob_idx = n - 2   # OB candle index

        # Create a swing point detector with a swing low near the OB
        sp = SwingPointDetector(lookbacks={"5min": 1})
        # Manually inject a swing low at ob_idx - 2
        from detectors.swing_points import SwingPoint
        sl_ts = df.index[ob_idx - 2]
        sp.swing_points.append(SwingPoint(
            price=99.0,
            timestamp=sl_ts,
            type="low",
            timeframe="5min",
        ))

        # Create an FVG detector with an FVG just after the OB candle
        fvg_det = FairValueGapDetector()
        from detectors.fair_value_gap import FVG
        fvg_ts = df.index[ob_idx]  # same or +1
        fvg_det.fvgs.append(FVG(
            top=105.0,
            bottom=100.0,
            direction="bullish",
            timeframe="5min",
            candle_index=ob_idx,
            timestamp=fvg_ts,
        ))

        det = OrderBlockDetector()
        obs = det.detect(df, "5min", swing_points=sp, fvg_detector=fvg_det)

        bullish = [ob for ob in obs if ob.direction == "bullish"]
        assert len(bullish) >= 1
        # At least one should be validated
        assert any(ob.validated for ob in bullish)

    def test_ob_unvalidated_with_sweep_but_no_fvg(self):
        """Sweep present but no FVG → still unvalidated (needs both)."""
        df = _make_bullish_displacement_df(n_padding=14)
        n = len(df)
        ob_idx = n - 2

        sp = SwingPointDetector(lookbacks={"5min": 1})
        from detectors.swing_points import SwingPoint
        sl_ts = df.index[ob_idx - 2]
        sp.swing_points.append(SwingPoint(
            price=99.0,
            timestamp=sl_ts,
            type="low",
            timeframe="5min",
        ))

        det = OrderBlockDetector()
        obs = det.detect(df, "5min", swing_points=sp, fvg_detector=None)

        bullish = [ob for ob in obs if ob.direction == "bullish"]
        assert len(bullish) >= 1
        assert all(not ob.validated for ob in bullish)


# ─── Tests: Mitigation ────────────────────────────────────────────────────────

class TestOrderBlockMitigation:

    def _build_bullish_ob(self) -> tuple[OrderBlockDetector, OrderBlock]:
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        bullish = [ob for ob in det.order_blocks if ob.direction == "bullish"]
        assert len(bullish) >= 1
        return det, bullish[-1]

    def _build_bearish_ob(self) -> tuple[OrderBlockDetector, OrderBlock]:
        df = _make_bearish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        bearish = [ob for ob in det.order_blocks if ob.direction == "bearish"]
        assert len(bearish) >= 1
        return det, bearish[-1]

    def test_bullish_ob_mitigated_when_close_below_low(self):
        det, ob = self._build_bullish_ob()
        # Build a 1-bar df with a close below ob.low
        close_below = ob.low - 1.0
        df_mit = _make_df([close_below], [close_below + 0.5], [close_below - 0.5], [close_below])
        mitigated = det.update_mitigation(df_mit)
        assert ob.mitigated
        assert ob in mitigated

    def test_bullish_ob_not_mitigated_when_close_above_low(self):
        det, ob = self._build_bullish_ob()
        close_above = ob.low + 0.5
        df_safe = _make_df([close_above], [close_above + 0.5], [close_above - 0.5], [close_above])
        det.update_mitigation(df_safe)
        assert not ob.mitigated

    def test_bearish_ob_mitigated_when_close_above_high(self):
        det, ob = self._build_bearish_ob()
        close_above = ob.high + 1.0
        df_mit = _make_df([close_above], [close_above + 0.5], [close_above - 0.5], [close_above])
        mitigated = det.update_mitigation(df_mit)
        assert ob.mitigated
        assert ob in mitigated

    def test_bearish_ob_not_mitigated_when_close_below_high(self):
        det, ob = self._build_bearish_ob()
        close_below = ob.high - 0.5
        df_safe = _make_df([close_below], [close_below + 0.5], [close_below - 0.5], [close_below])
        det.update_mitigation(df_safe)
        assert not ob.mitigated

    def test_empty_df_no_mitigation(self):
        det, ob = self._build_bullish_ob()
        result = det.update_mitigation(_make_df([], [], [], []))
        assert result == []
        assert not ob.mitigated

    def test_double_mitigation_no_duplicate(self):
        det, ob = self._build_bullish_ob()
        close_below = ob.low - 1.0
        df_mit = _make_df([close_below], [close_below + 0.5], [close_below - 0.5], [close_below])
        det.update_mitigation(df_mit)
        result2 = det.update_mitigation(df_mit)
        assert result2 == []


# ─── Tests: get_active / filtering ───────────────────────────────────────────

class TestOrderBlockGetActive:

    def setup_method(self):
        df_bull = _make_bullish_displacement_df()
        df_bear = _make_bearish_displacement_df()
        # Shift bearish timestamps to avoid collision
        df_bear.index = df_bear.index + pd.Timedelta(hours=2)

        self.det = OrderBlockDetector()
        self.det.detect(df_bull, "5min")
        self.det.detect(df_bear, "5min")

    def test_get_active_returns_unmitigated(self):
        active = self.det.get_active()
        assert all(not ob.mitigated for ob in active)

    def test_filter_by_direction_bullish(self):
        bullish = self.det.get_active(direction="bullish")
        assert all(ob.direction == "bullish" for ob in bullish)
        assert len(bullish) >= 1

    def test_filter_by_direction_bearish(self):
        bearish = self.det.get_active(direction="bearish")
        assert all(ob.direction == "bearish" for ob in bearish)
        assert len(bearish) >= 1

    def test_filter_by_timeframe(self):
        # detect on 15min with shifted timestamps
        df_bull_15 = _make_bullish_displacement_df()
        df_bull_15.index = df_bull_15.index + pd.Timedelta(hours=4)
        self.det.detect(df_bull_15, "15min")

        tf15 = self.det.get_active(timeframe="15min")
        assert all(ob.timeframe == "15min" for ob in tf15)

    def test_validated_only_filter(self):
        # No validated OBs unless we inject sweep+FVG
        non_validated = self.det.get_active(validated_only=True)
        assert all(ob.validated for ob in non_validated)

    def test_active_sorted_ascending(self):
        active = self.det.get_active()
        ts_list = [ob.timestamp for ob in active]
        assert ts_list == sorted(ts_list)

    def test_mitigated_excluded_from_active(self):
        bullish = self.det.get_active(direction="bullish")
        if bullish:
            ob = bullish[0]
            ob.mitigated = True
            new_active = self.det.get_active(direction="bullish")
            assert ob not in new_active


# ─── Tests: get_nearest ──────────────────────────────────────────────────────

class TestOrderBlockGetNearest:

    def test_returns_nearest_ob(self):
        df = _make_bullish_displacement_df(n_padding=14)
        det = OrderBlockDetector()
        det.detect(df, "5min")
        bullish = det.get_active(direction="bullish")
        if bullish:
            ob = bullish[-1]
            nearest = det.get_nearest(ob.proximal + 0.1, direction="bullish")
            assert nearest is not None

    def test_returns_none_when_empty(self):
        det = OrderBlockDetector()
        assert det.get_nearest(100.0) is None


# ─── Tests: clear ────────────────────────────────────────────────────────────

class TestOrderBlockClear:

    def test_clear_resets_all(self):
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        assert len(det.order_blocks) >= 1
        det.clear()
        assert det.order_blocks == []


class TestInvalidateByStructure:

    def test_bullish_bos_invalidates_bearish_obs(self):
        df = _make_bearish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        bearish_obs = [ob for ob in det.order_blocks if ob.direction == "bearish"]
        assert len(bearish_obs) >= 1, "need at least one bearish OB for this test"
        # current_bar_count=200 ensures age (200 - candle_index) > 100 for all OBs
        invalidated = det.invalidate_by_structure("bullish", current_bar_count=200)
        assert len(invalidated) == len(bearish_obs)
        for ob in bearish_obs:
            assert ob.mitigated

    def test_bearish_bos_invalidates_bullish_obs(self):
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        bullish_obs = [ob for ob in det.order_blocks if ob.direction == "bullish"]
        assert len(bullish_obs) >= 1
        invalidated = det.invalidate_by_structure("bearish", current_bar_count=200)
        assert len(invalidated) == len(bullish_obs)
        for ob in bullish_obs:
            assert ob.mitigated

    def test_fresh_ob_not_purged_by_structure(self):
        """OBs younger than 100 bars must survive a BOS (age gate)."""
        df = _make_bearish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        bearish_obs = [ob for ob in det.order_blocks if ob.direction == "bearish"]
        assert len(bearish_obs) >= 1
        # current_bar_count close to candle_index → age ≤ 100 → not purged
        max_candle_idx = max(ob.candle_index for ob in bearish_obs)
        invalidated = det.invalidate_by_structure("bullish", current_bar_count=max_candle_idx + 50)
        assert invalidated == []
        for ob in bearish_obs:
            assert not ob.mitigated

    def test_invalidate_does_not_touch_same_direction(self):
        df = _make_bullish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        # bullish BOS should NOT invalidate bullish OBs regardless of bar count
        before_count = len([ob for ob in det.order_blocks if not ob.mitigated and ob.direction == "bullish"])
        det.invalidate_by_structure("bullish", current_bar_count=200)
        after_count = len([ob for ob in det.order_blocks if not ob.mitigated and ob.direction == "bullish"])
        assert after_count == before_count

    def test_invalidate_skips_already_mitigated(self):
        df = _make_bearish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        for ob in det.order_blocks:
            ob.mitigated = True
        invalidated = det.invalidate_by_structure("bullish", current_bar_count=200)
        assert invalidated == []

    def test_invalidate_returns_list_of_affected_obs(self):
        df = _make_bearish_displacement_df()
        det = OrderBlockDetector()
        det.detect(df, "5min")
        result = det.invalidate_by_structure("bullish", current_bar_count=200)
        assert isinstance(result, list)
        assert all(isinstance(ob, OrderBlock) for ob in result)


class TestExpireOld:

    def _make_ob_at_ts(self, ts: pd.Timestamp, direction: str = "bullish") -> OrderBlock:
        return OrderBlock(
            high=102.0, low=99.0, direction=direction,
            timeframe="5min", candle_index=0, timestamp=ts,
        )

    def test_ob_within_max_age_not_expired(self):
        det = OrderBlockDetector()
        ts_ob = pd.Timestamp("2025-03-03 09:00", tz="US/Central")
        ts_now = ts_ob + pd.Timedelta(minutes=100)   # 20 bars × 5min — well within 1000-bar limit
        det.order_blocks = [self._make_ob_at_ts(ts_ob)]
        expired = det.expire_old(ts_now)
        assert expired == []
        assert not det.order_blocks[0].mitigated

    def test_ob_beyond_max_age_expires(self):
        det = OrderBlockDetector()
        ts_ob = pd.Timestamp("2025-03-03 09:00", tz="US/Central")
        ts_now = ts_ob + pd.Timedelta(minutes=1000 * 5 + 1)   # 1 min beyond 1000-bar window
        det.order_blocks = [self._make_ob_at_ts(ts_ob)]
        expired = det.expire_old(ts_now)
        assert len(expired) == 1
        assert det.order_blocks[0].mitigated

    def test_already_mitigated_ob_not_returned(self):
        det = OrderBlockDetector()
        ts_ob = pd.Timestamp("2025-01-01 09:00", tz="US/Central")
        ts_now = ts_ob + pd.Timedelta(days=30)
        ob = self._make_ob_at_ts(ts_ob)
        ob.mitigated = True
        det.order_blocks = [ob]
        expired = det.expire_old(ts_now)
        assert expired == []

    def test_only_old_obs_expire(self):
        det = OrderBlockDetector()
        ts_old = pd.Timestamp("2025-03-01 09:00", tz="US/Central")
        ts_new = pd.Timestamp("2025-03-10 09:00", tz="US/Central")
        ts_now = ts_new + pd.Timedelta(minutes=5)   # 1 bar after ts_new
        det.order_blocks = [
            self._make_ob_at_ts(ts_old, "bullish"),
            self._make_ob_at_ts(ts_new, "bearish"),
        ]
        expired = det.expire_old(ts_now)
        assert len(expired) == 1
        assert expired[0].timestamp == ts_old
        assert not det.order_blocks[1].mitigated
