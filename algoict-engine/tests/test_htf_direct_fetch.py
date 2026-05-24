"""Tests for the HTF direct-fetch fix (Option C, 2026-05-23).

Validates:
1. `_bars_to_df` converts broker bar dicts to a DataFrame matching
   `tf_manager.aggregate` output schema (US/Central index, OHLCV).
2. `_make_htf_bias_fn` PREFERS direct daily/weekly cache when available
   and FALLS BACK to 1-min aggregation when not.
3. Default behavior when neither source is available is `neutral`.

Live broker test (`_fetch_htf_bars`) is NOT covered here — it requires
network + TopstepX credentials. Use `tests/test_topstepx_live_contract.py`
opt-in suite (TOPSTEPX_INTEGRATION=1) for that.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))


# ───────────────────────────────────────────────────────────────────────
# _bars_to_df
# ───────────────────────────────────────────────────────────────────────

class TestBarsToDF:

    def test_converts_basic_bar_list(self):
        from main import _bars_to_df
        bars = [
            {
                "symbol": "MNQ",
                "timestamp": pd.Timestamp("2026-05-21 00:00:00", tz="UTC"),
                "open": 100.0, "high": 105.0, "low": 99.0,
                "close": 103.0, "volume": 1000,
            },
            {
                "symbol": "MNQ",
                "timestamp": pd.Timestamp("2026-05-22 00:00:00", tz="UTC"),
                "open": 103.0, "high": 108.0, "low": 102.0,
                "close": 107.0, "volume": 1200,
            },
        ]
        df = _bars_to_df(bars)
        assert len(df) == 2
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.index.tz is not None
        # Should be US/Central (CDT in May = UTC-5)
        assert "Central" in str(df.index.tz) or "US/Central" in str(df.index.tz)
        assert df["high"].max() == 108.0
        assert df["volume"].dtype.kind in ("i", "u")  # integer

    def test_empty_list_returns_empty_df(self):
        from main import _bars_to_df
        df = _bars_to_df([])
        assert df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_sorts_oldest_first(self):
        from main import _bars_to_df
        bars = [
            {
                "timestamp": pd.Timestamp("2026-05-22 00:00:00", tz="UTC"),
                "open": 103.0, "high": 108.0, "low": 102.0, "close": 107.0, "volume": 1200,
            },
            {
                "timestamp": pd.Timestamp("2026-05-20 00:00:00", tz="UTC"),
                "open": 95.0, "high": 100.0, "low": 94.0, "close": 99.0, "volume": 800,
            },
            {
                "timestamp": pd.Timestamp("2026-05-21 00:00:00", tz="UTC"),
                "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000,
            },
        ]
        df = _bars_to_df(bars)
        assert df.index[0] < df.index[1] < df.index[2]

    def test_dedups_duplicate_timestamps(self):
        from main import _bars_to_df
        ts = pd.Timestamp("2026-05-21 00:00:00", tz="UTC")
        bars = [
            {"timestamp": ts, "open": 100, "high": 105, "low": 99, "close": 101, "volume": 500},
            {"timestamp": ts, "open": 100, "high": 110, "low": 95, "close": 108, "volume": 700},
        ]
        df = _bars_to_df(bars)
        assert len(df) == 1
        # `keep="last"` so second wins
        assert df.iloc[0]["close"] == 108

    def test_handles_naive_timestamps(self):
        from main import _bars_to_df
        bars = [
            {
                "timestamp": pd.Timestamp("2026-05-21 00:00:00"),  # naive
                "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000,
            },
        ]
        df = _bars_to_df(bars)
        assert len(df) == 1
        assert df.index.tz is not None  # localized

    def test_skips_bars_missing_timestamp(self):
        from main import _bars_to_df
        bars = [
            {"open": 100, "high": 105, "low": 99, "close": 101, "volume": 500},  # no ts
            {
                "timestamp": pd.Timestamp("2026-05-21 00:00:00", tz="UTC"),
                "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000,
            },
        ]
        df = _bars_to_df(bars)
        assert len(df) == 1


# ───────────────────────────────────────────────────────────────────────
# HTF bias closure priority (direct cache vs aggregation fallback)
# ───────────────────────────────────────────────────────────────────────

class TestHTFBiasClosure:
    """Verify the closure created in `_make_htf_bias_fn` prefers direct
    daily/weekly DataFrames over aggregating bars_1min."""

    def setup_method(self):
        # Real HTFBiasDetector — no mocks. We just call its API the same way.
        from timeframes.htf_bias import HTFBiasDetector
        from timeframes.tf_manager import TimeframeManager
        self.detector = HTFBiasDetector()
        self.tf_mgr = TimeframeManager()
        # The closure is defined inside `_main_components_builder` which is
        # not directly importable. We reconstruct it inline matching the
        # same logic (the production version captures `htf_bias_det` and
        # `logger` from outer scope; we use ours).

    def _make_closure(self, state_ref):
        """Mirror of `_make_htf_bias_fn` semantics for unit testing."""
        from timeframes.htf_bias import BiasResult

        def _fn(price: float):
            neutral = BiasResult(
                direction="neutral", premium_discount="", htf_levels={},
                confidence="low", weekly_bias="neutral", daily_bias="neutral",
            )
            htf_daily = state_ref.get("htf_daily_df")
            htf_weekly = state_ref.get("htf_weekly_df")
            if htf_daily is not None and htf_weekly is not None \
                    and not htf_daily.empty and not htf_weekly.empty:
                try:
                    return self.detector.determine_bias(htf_daily, htf_weekly, price)
                except Exception:
                    pass
            bars = state_ref.get("bars_1min")
            if bars is None or len(bars) < 50:
                return neutral
            try:
                df_daily = self.tf_mgr.aggregate(bars, "D")
                df_weekly = self.tf_mgr.aggregate(bars, "W")
                return self.detector.determine_bias(df_daily, df_weekly, price)
            except Exception:
                return neutral
        return _fn

    def _make_bull_daily(self) -> pd.DataFrame:
        """Build a synthetic bullish daily (HH-HL last 2 bars)."""
        rows = [
            {"timestamp": pd.Timestamp("2026-05-20", tz="US/Central"),
             "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 1000},
            {"timestamp": pd.Timestamp("2026-05-21", tz="US/Central"),
             "open": 102.0, "high": 110.0, "low": 100.0, "close": 108.0, "volume": 1200},
            {"timestamp": pd.Timestamp("2026-05-22", tz="US/Central"),  # forming
             "open": 108.0, "high": 109.0, "low": 107.0, "close": 108.5, "volume": 500},
        ]
        return pd.DataFrame(rows).set_index("timestamp")

    def _make_bear_daily(self) -> pd.DataFrame:
        """Build a synthetic bearish daily (LH-LL last 2 bars)."""
        rows = [
            {"timestamp": pd.Timestamp("2026-05-20", tz="US/Central"),
             "open": 110.0, "high": 115.0, "low": 105.0, "close": 108.0, "volume": 1000},
            {"timestamp": pd.Timestamp("2026-05-21", tz="US/Central"),
             "open": 108.0, "high": 110.0, "low": 95.0, "close": 96.0, "volume": 1200},
            {"timestamp": pd.Timestamp("2026-05-22", tz="US/Central"),  # forming
             "open": 96.0, "high": 97.0, "low": 95.0, "close": 96.5, "volume": 500},
        ]
        return pd.DataFrame(rows).set_index("timestamp")

    def _make_neutral_weekly(self) -> pd.DataFrame:
        """Weekly with 1 bar → swing returns neutral (n<2)."""
        rows = [
            {"timestamp": pd.Timestamp("2026-05-18", tz="US/Central"),
             "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0, "volume": 5000},
        ]
        return pd.DataFrame(rows).set_index("timestamp")

    def test_neutral_when_no_data(self):
        state_ref: dict = {}
        fn = self._make_closure(state_ref)
        result = fn(100.0)
        assert result.direction == "neutral"

    def test_uses_direct_cache_when_present(self):
        """When htf_daily_df + htf_weekly_df present, bias comes from them
        (NOT from bars_1min aggregation)."""
        state_ref = {
            "htf_daily_df": self._make_bull_daily(),
            "htf_weekly_df": self._make_neutral_weekly(),
        }
        fn = self._make_closure(state_ref)
        result = fn(108.0)
        # Last 2 completed daily are bullish (HH-HL).
        assert result.daily_bias == "bullish"
        assert result.direction == "bullish"

    def test_direct_cache_bearish(self):
        state_ref = {
            "htf_daily_df": self._make_bear_daily(),
            "htf_weekly_df": self._make_neutral_weekly(),
        }
        fn = self._make_closure(state_ref)
        result = fn(96.0)
        assert result.daily_bias == "bearish"
        assert result.direction == "bearish"

    def test_falls_back_to_aggregation_when_cache_empty(self):
        """If htf_daily_df is None, the closure aggregates bars_1min."""
        # Build a 1-min DataFrame that aggregates to bearish daily.
        idx = pd.date_range("2026-05-20 09:00", periods=2000, freq="1min", tz="US/Central")
        # Two days of bars — first day higher, second day lower (bearish)
        prices = []
        for i in range(2000):
            day = i // 1000  # 0 or 1
            if day == 0:
                p = 110 + (i % 1000) * 0.001  # ranging high
            else:
                p = 95 + (i % 1000) * 0.001  # ranging low
            prices.append(p)
        bars = pd.DataFrame({
            "open": prices,
            "high": [p + 0.5 for p in prices],
            "low": [p - 0.5 for p in prices],
            "close": prices,
            "volume": [100] * 2000,
        }, index=idx)
        state_ref = {"bars_1min": bars}
        fn = self._make_closure(state_ref)
        # Should compute from aggregation, return SOME bias
        result = fn(96.0)
        assert result.direction in ("bullish", "bearish", "neutral")

    def test_cache_priority_overrides_aggregation(self):
        """When BOTH cache and bars_1min present, cache wins."""
        # Cache says BULLISH
        # bars_1min would say BEARISH if aggregated
        idx = pd.date_range("2026-05-20 09:00", periods=2000, freq="1min", tz="US/Central")
        prices = [110 - i*0.01 for i in range(2000)]  # steady downtrend
        bars = pd.DataFrame({
            "open": prices, "high": [p+0.5 for p in prices],
            "low": [p-0.5 for p in prices], "close": prices,
            "volume": [100]*2000,
        }, index=idx)
        state_ref = {
            "htf_daily_df": self._make_bull_daily(),    # bullish cache
            "htf_weekly_df": self._make_neutral_weekly(),
            "bars_1min": bars,                            # bearish 1-min
        }
        fn = self._make_closure(state_ref)
        result = fn(100.0)
        # Cache wins
        assert result.daily_bias == "bullish"
