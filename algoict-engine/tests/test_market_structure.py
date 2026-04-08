"""
tests/test_market_structure.py
===============================
Unit tests for detectors/market_structure.py

Strategy: build small synthetic OHLCV sequences with clear swing points,
detect swings via SwingPointDetector(lookback=1), then iterate the
MarketStructureDetector bar-by-bar to verify event sequencing and
state-machine evolution.

Run: cd algoict-engine && python -m pytest tests/test_market_structure.py -v
"""

import pandas as pd

from detectors.swing_points import SwingPointDetector
from detectors.market_structure import MarketStructureDetector, StructureEvent


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_df(
    highs: list,
    lows: list,
    closes: list,
    tz: str = "US/Central",
) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from explicit arrays."""
    n = len(highs)
    assert n == len(lows) == len(closes), "highs/lows/closes must align"
    idx = pd.date_range("2025-03-03 09:00", periods=n, freq="5min", tz=tz)
    return pd.DataFrame({
        "open":   closes,    # placeholder
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": [100] * n,
    }, index=idx)


def _run_bar_by_bar(
    df: pd.DataFrame,
    sp: SwingPointDetector,
    ms: MarketStructureDetector,
    timeframe: str,
) -> list[StructureEvent]:
    """
    Walk through *df* one candle at a time, calling ms.update() with the
    history slice up to and including each bar. Returns the full ordered
    list of structure events emitted along the way.
    """
    all_events: list[StructureEvent] = []
    for i in range(len(df)):
        slice_ = df.iloc[: i + 1]
        events = ms.update(slice_, sp, timeframe)
        all_events.extend(events)
    return all_events


# ─── Tests: Initial / Empty State ─────────────────────────────────────────────

class TestInitialState:

    def test_initial_state_is_neutral(self):
        ms = MarketStructureDetector()
        assert ms.get_state("5min") == "neutral"
        assert ms.get_state("15min") == "neutral"

    def test_empty_dataframe_returns_no_events(self):
        ms = MarketStructureDetector()
        sp = SwingPointDetector()
        df = _make_df([], [], [])
        assert ms.update(df, sp, "5min") == []

    def test_no_swings_no_events(self):
        """If no swing points exist before the current bar, nothing happens."""
        ms = MarketStructureDetector()
        sp = SwingPointDetector(lookbacks={"5min": 1})
        df = _make_df([10, 11, 12], [9, 10, 11], [10, 11, 12])  # pure uptrend, no swings
        sp.detect(df, "5min")
        events = _run_bar_by_bar(df, sp, ms, "5min")
        assert events == []
        assert ms.get_state("5min") == "neutral"


# ─── Tests: BOS Bullish from Neutral ─────────────────────────────────────────

class TestBosBullish:

    def test_bullish_bos_from_neutral(self):
        """
        Sequence (lookback=1):
          idx | high | low | close
           0  |  10  |  8  |   9
           1  |  15  | 10  |  14    ← swing high (15) — confirmed by idx 2
           2  |  12  |  9  |  10    ← swing low (9)  — confirmed by idx 3
           3  |  17  | 13  |  16    ← BOS bullish: close 16 > swing high 15
        """
        highs  = [10, 15, 12, 17]
        lows   = [ 8, 10,  9, 13]
        closes = [ 9, 14, 10, 16]
        df = _make_df(highs, lows, closes)

        sp = SwingPointDetector(lookbacks={"5min": 1})
        sp.detect(df, "5min")

        ms = MarketStructureDetector()
        events = _run_bar_by_bar(df, sp, ms, "5min")

        bos = [e for e in events if e.type == "BOS"]
        assert len(bos) == 1
        assert bos[0].direction == "bullish"
        assert bos[0].level == 15.0
        assert bos[0].timestamp == df.index[3]
        assert ms.get_state("5min") == "bullish"


# ─── Tests: BOS Bearish from Neutral ─────────────────────────────────────────

class TestBosBearish:

    def test_bearish_bos_from_neutral(self):
        """
        Mirror of bullish case:
          idx | high | low | close
           0  |  20  | 18  |  19
           1  |  18  | 13  |  14    ← swing low (13) — confirmed by idx 2
           2  |  19  | 15  |  17    ← swing high (19) — confirmed by idx 3
           3  |  16  | 11  |  12    ← BOS bearish: close 12 < swing low 13
        """
        highs  = [20, 18, 19, 16]
        lows   = [18, 13, 15, 11]
        closes = [19, 14, 17, 12]
        df = _make_df(highs, lows, closes)

        sp = SwingPointDetector(lookbacks={"5min": 1})
        sp.detect(df, "5min")

        ms = MarketStructureDetector()
        events = _run_bar_by_bar(df, sp, ms, "5min")

        bos = [e for e in events if e.type == "BOS"]
        assert len(bos) == 1
        assert bos[0].direction == "bearish"
        assert bos[0].level == 13.0
        assert ms.get_state("5min") == "bearish"


# ─── Tests: Higher Highs/Higher Lows → BOS → CHoCH → MSS ─────────────────────

class TestFullSequence:
    """
    The canonical test:
      Phase A: build a swing high & swing low → BOS bullish (state goes bullish)
      Phase B: form another higher swing low after BOS
      Phase C: close below that swing low → CHoCH bearish (state still bullish)
      Phase D: next bar continues lower → MSS bearish (state flips bearish)
    """

    def setup_method(self):
        """
        9-bar sequence:
          idx | high | low | close   notes
           0  |  10  |  8  |   9
           1  |  15  | 10  |  14    SH(15)
           2  |  12  |  9  |  10    SL(9)
           3  |  17  | 13  |  16    BOS bullish (close 16 > 15)
           4  |  20  | 16  |  19    higher
           5  |  17  | 13  |  14    SL(13) forming
           6  |  19  | 15  |  18    SL(13) confirmed; SH(19) forming
           7  |  16  | 11  |  12    CHoCH bearish (close 12 < SL 13)
           8  |  14  |  9  |  10    MSS bearish (close 10 < CHoCH close 12)
        """
        self.highs  = [10, 15, 12, 17, 20, 17, 19, 16, 14]
        self.lows   = [ 8, 10,  9, 13, 16, 13, 15, 11,  9]
        self.closes = [ 9, 14, 10, 16, 19, 14, 18, 12, 10]
        self.df = _make_df(self.highs, self.lows, self.closes)
        self.sp = SwingPointDetector(lookbacks={"5min": 1})
        self.sp.detect(self.df, "5min")
        self.ms = MarketStructureDetector()
        self.events = _run_bar_by_bar(self.df, self.sp, self.ms, "5min")

    def test_emits_bos_bullish(self):
        bos = [e for e in self.events if e.type == "BOS" and e.direction == "bullish"]
        assert len(bos) >= 1
        # The first BOS bullish should break the original swing high (15)
        first_bos = bos[0]
        assert first_bos.level == 15.0
        assert first_bos.timestamp == self.df.index[3]

    def test_emits_choch_bearish(self):
        choch = [e for e in self.events if e.type == "CHoCH" and e.direction == "bearish"]
        assert len(choch) == 1
        assert choch[0].level == 13.0
        assert choch[0].timestamp == self.df.index[7]

    def test_emits_mss_bearish(self):
        mss = [e for e in self.events if e.type == "MSS" and e.direction == "bearish"]
        assert len(mss) == 1
        assert mss[0].timestamp == self.df.index[8]

    def test_event_order(self):
        """BOS bullish must come before CHoCH bearish, which must come before MSS bearish."""
        ordered = [(e.type, e.direction) for e in self.events]
        bos_idx   = next(i for i, e in enumerate(ordered) if e == ("BOS", "bullish"))
        choch_idx = next(i for i, e in enumerate(ordered) if e == ("CHoCH", "bearish"))
        mss_idx   = next(i for i, e in enumerate(ordered) if e == ("MSS", "bearish"))
        assert bos_idx < choch_idx < mss_idx

    def test_state_after_bos_is_bullish(self):
        """After bar 3 (BOS bullish) and before bar 7 (CHoCH), state must be bullish."""
        ms_check = MarketStructureDetector()
        # Replay up to bar 6 only — CHoCH should not have happened yet
        for i in range(7):
            ms_check.update(self.df.iloc[: i + 1], self.sp, "5min")
        assert ms_check.get_state("5min") == "bullish"

    def test_state_after_choch_still_bullish(self):
        """CHoCH alone does not flip the state — only MSS does."""
        ms_check = MarketStructureDetector()
        for i in range(8):  # up to and including bar 7 (CHoCH)
            ms_check.update(self.df.iloc[: i + 1], self.sp, "5min")
        assert ms_check.get_state("5min") == "bullish"

    def test_state_after_mss_is_bearish(self):
        """After MSS confirmation, state must be bearish."""
        assert self.ms.get_state("5min") == "bearish"


# ─── Tests: BOS Continuation ─────────────────────────────────────────────────

class TestBosContinuation:

    def test_multiple_bullish_bos_keeps_state_bullish(self):
        """
        Two consecutive BOS bullish events — both continuation, state stays bullish.
        Sequence:
          0:10/8/9
          1:15/10/14   SH=15
          2:12/9/10    SL=9
          3:18/13/17   BOS bullish (close 17 > 15)
          4:25/16/24   form new SH at idx 4 (need bar 5)
          5:21/18/20   SH(25) confirmed; close 20 < 25; no event yet
          6:30/22/29   BOS bullish (close 29 > 25)
        """
        highs  = [10, 15, 12, 18, 25, 21, 30]
        lows   = [ 8, 10,  9, 13, 16, 18, 22]
        closes = [ 9, 14, 10, 17, 24, 20, 29]
        df = _make_df(highs, lows, closes)

        sp = SwingPointDetector(lookbacks={"5min": 1})
        sp.detect(df, "5min")

        ms = MarketStructureDetector()
        events = _run_bar_by_bar(df, sp, ms, "5min")

        bos_bullish = [e for e in events if e.type == "BOS" and e.direction == "bullish"]
        assert len(bos_bullish) == 2
        assert bos_bullish[0].level == 15.0
        assert bos_bullish[1].level == 25.0
        assert ms.get_state("5min") == "bullish"
        # No CHoCH or MSS in this sequence
        assert all(e.type == "BOS" for e in events)


# ─── Tests: Independent Per-Timeframe State ──────────────────────────────────

class TestPerTimeframeIndependence:

    def test_two_timeframes_independent(self):
        """5min state should not affect 15min state — they're tracked separately."""
        # Build a bullish-BOS sequence on 5min
        highs  = [10, 15, 12, 17]
        lows   = [ 8, 10,  9, 13]
        closes = [ 9, 14, 10, 16]
        df = _make_df(highs, lows, closes)

        sp = SwingPointDetector(lookbacks={"5min": 1, "15min": 1})
        sp.detect(df, "5min")        # only 5min swings populated

        ms = MarketStructureDetector()
        _run_bar_by_bar(df, sp, ms, "5min")

        assert ms.get_state("5min") == "bullish"
        assert ms.get_state("15min") == "neutral"  # untouched

    def test_get_events_filter_by_timeframe(self):
        highs  = [10, 15, 12, 17]
        lows   = [ 8, 10,  9, 13]
        closes = [ 9, 14, 10, 16]
        df = _make_df(highs, lows, closes)

        sp = SwingPointDetector(lookbacks={"5min": 1})
        sp.detect(df, "5min")

        ms = MarketStructureDetector()
        _run_bar_by_bar(df, sp, ms, "5min")

        events_5min = ms.get_events(timeframe="5min")
        events_15min = ms.get_events(timeframe="15min")
        assert len(events_5min) >= 1
        assert len(events_15min) == 0


# ─── Tests: get_events filtering ─────────────────────────────────────────────

class TestGetEventsFilter:

    def setup_method(self):
        # Reuse the full BOS→CHoCH→MSS sequence
        highs  = [10, 15, 12, 17, 20, 17, 19, 16, 14]
        lows   = [ 8, 10,  9, 13, 16, 13, 15, 11,  9]
        closes = [ 9, 14, 10, 16, 19, 14, 18, 12, 10]
        df = _make_df(highs, lows, closes)
        sp = SwingPointDetector(lookbacks={"5min": 1})
        sp.detect(df, "5min")
        self.ms = MarketStructureDetector()
        _run_bar_by_bar(df, sp, self.ms, "5min")

    def test_filter_by_type_bos(self):
        bos = self.ms.get_events(type_filter="BOS")
        assert all(e.type == "BOS" for e in bos)
        assert len(bos) >= 1

    def test_filter_by_type_choch(self):
        choch = self.ms.get_events(type_filter="CHoCH")
        assert all(e.type == "CHoCH" for e in choch)
        assert len(choch) == 1

    def test_filter_by_type_mss(self):
        mss = self.ms.get_events(type_filter="MSS")
        assert all(e.type == "MSS" for e in mss)
        assert len(mss) == 1


# ─── Tests: reset() ──────────────────────────────────────────────────────────

class TestReset:

    def test_reset_clears_state(self):
        highs  = [10, 15, 12, 17]
        lows   = [ 8, 10,  9, 13]
        closes = [ 9, 14, 10, 16]
        df = _make_df(highs, lows, closes)
        sp = SwingPointDetector(lookbacks={"5min": 1})
        sp.detect(df, "5min")

        ms = MarketStructureDetector()
        _run_bar_by_bar(df, sp, ms, "5min")
        assert ms.get_state("5min") == "bullish"
        assert len(ms.events) > 0

        ms.reset()
        assert ms.get_state("5min") == "neutral"
        assert ms.events == []
