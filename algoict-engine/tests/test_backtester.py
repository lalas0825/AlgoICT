"""
tests/test_backtester.py
=========================
Unit tests for backtest/backtester.py

Strategy: use a deterministic MockStrategy that fires signals on specific
evaluation calls, then patch synthetic 1-min bars to force stop/target hits
at known timestamps. This isolates the backtester's state machine from the
real strategies (which have their own 421 tests).

The test suite also runs a full synthetic week through the backtester with
both a silent mock and a firing mock to verify the hot loop works end-to-end.
"""

import datetime
from dataclasses import dataclass, field

import pandas as pd
import pytest
import pytz

from backtest.backtester import (
    Backtester, BacktestResult, Trade, SignalLog, MNQ_POINT_VALUE,
)
from strategies.ny_am_reversal import Signal  # same shape as SB.Signal
from risk.risk_manager import RiskManager
from timeframes.tf_manager import TimeframeManager
from timeframes.session_manager import SessionManager


CT = pytz.timezone("US/Central")


# ─── Synthetic data helpers ──────────────────────────────────────────────────

def _build_day(
    date: datetime.date,
    price: float = 100.0,
    n_bars: int = 480,   # 08:00 → 15:59 CT (covers hard close at 15:00)
) -> pd.DataFrame:
    """Build 1-min bars for a single day starting at 08:00 CT."""
    start = pd.Timestamp(
        year=date.year, month=date.month, day=date.day,
        hour=8, minute=0, tz="US/Central",
    )
    idx = pd.date_range(start, periods=n_bars, freq="1min")
    df = pd.DataFrame(
        {
            "open":   [price] * n_bars,
            "high":   [price + 0.1] * n_bars,
            "low":    [price - 0.1] * n_bars,
            "close":  [price] * n_bars,
            "volume": [1000] * n_bars,
        },
        index=idx,
    )
    return df


def _build_week(
    start_date: datetime.date = datetime.date(2025, 3, 3),  # Monday
    price: float = 100.0,
    n_bars_per_day: int = 420,
) -> pd.DataFrame:
    """Build 1-min bars for 5 consecutive weekdays (Mon–Fri)."""
    parts = []
    for offset in range(5):
        d = start_date + datetime.timedelta(days=offset)
        parts.append(_build_day(d, price=price, n_bars=n_bars_per_day))
    return pd.concat(parts)


def _patch_bar(df: pd.DataFrame, ts: pd.Timestamp, **cols) -> None:
    """Overwrite OHLC columns on a specific bar in-place."""
    for col, val in cols.items():
        df.loc[ts, col] = val


# ─── Mock strategy ───────────────────────────────────────────────────────────

class MockStrategy:
    """
    Deterministic stand-in for real strategies.

    - Fires a pre-defined Signal on each evaluation listed in `fire_on_calls`.
    - Entry / stop / target / direction / contracts are configurable.
    - Tracks eval_count, last_eval_ts, reset_count for assertions.
    """

    ENTRY_TF = "5min"
    CONTEXT_TF = "15min"

    def __init__(
        self,
        fire_on_calls=None,       # set[int] of 1-indexed evaluate() calls
        direction: str = "long",
        entry_price: float = 100.0,
        stop_price: float = 99.0,
        target_price: float = 101.5,
        contracts: int = 5,
        confluence: int = 10,
    ):
        self.fire_on_calls = set(fire_on_calls or [])
        self.direction = direction
        self.entry_price = entry_price
        self.stop_price = stop_price
        self.target_price = target_price
        self.contracts = contracts
        self.confluence = confluence

        self.eval_count = 0
        self.last_eval_ts = None
        self.reset_count = 0
        self.trades_today = 0

    def evaluate(self, df_entry, df_context):
        self.eval_count += 1
        if df_entry.empty:
            return None
        self.last_eval_ts = df_entry.index[-1]
        if self.eval_count in self.fire_on_calls:
            self.trades_today += 1
            return Signal(
                strategy="mock",
                symbol="MNQ",
                direction=self.direction,
                entry_price=self.entry_price,
                stop_price=self.stop_price,
                target_price=self.target_price,
                contracts=self.contracts,
                confluence_score=self.confluence,
                timestamp=self.last_eval_ts,
                kill_zone="test",
            )
        return None

    def reset_daily(self) -> None:
        self.reset_count += 1
        self.trades_today = 0


class OneMinMockStrategy(MockStrategy):
    """Mock using 1-min entry TF (like Silver Bullet)."""
    ENTRY_TF = "1min"
    CONTEXT_TF = "5min"


# ─── Builder ─────────────────────────────────────────────────────────────────

def _make_backtester(strategy=None, detectors=None):
    strategy = strategy or MockStrategy()
    detectors = detectors if detectors is not None else {}
    risk = RiskManager()
    tf = TimeframeManager()
    session = SessionManager()
    return Backtester(
        strategy=strategy,
        detectors=detectors,
        risk_manager=risk,
        tf_manager=tf,
        session_manager=session,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tests — empty / no-signal baseline
# ═══════════════════════════════════════════════════════════════════════════

class TestEmptyAndBaseline:

    def test_empty_dataframe_returns_empty_result(self):
        bt = _make_backtester()
        empty_df = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="US/Central"),
        )
        result = bt.run(empty_df)
        assert isinstance(result, BacktestResult)
        assert result.total_trades == 0
        assert result.total_signals == 0
        assert result.total_pnl == 0.0

    def test_no_signals_produces_no_trades(self):
        """Mock with empty fire_on_calls never returns a signal."""
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        df = _build_day(datetime.date(2025, 3, 3))
        result = bt.run(df)
        assert result.total_trades == 0
        assert result.total_signals == 0
        # Strategy was evaluated many times (one per new 5min bar)
        assert mock.eval_count > 10

    def test_strategy_reset_daily_called_at_start(self):
        """reset_daily fires at least once (at the very first bar)."""
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        df = _build_day(datetime.date(2025, 3, 3))
        bt.run(df)
        assert mock.reset_count >= 1


# ═══════════════════════════════════════════════════════════════════════════
# Tests — signal / exit logic
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalAndExit:

    def test_signal_target_hit_produces_win(self):
        """Long signal + later bar with high >= target → win."""
        df = _build_day(datetime.date(2025, 3, 3))
        # Signal fires on 2nd evaluation (so after a few 5min bars close).
        # Patch a later bar to spike high above target.
        mock = MockStrategy(
            fire_on_calls=[2],
            direction="long",
            entry_price=100.0, stop_price=99.0, target_price=101.0,
            contracts=5,
        )
        # Patch bar at 09:30 (well after any 2nd eval) with high=102
        spike_ts = pd.Timestamp("2025-03-03 09:30", tz="US/Central")
        _patch_bar(df, spike_ts, high=102.0)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)

        assert result.total_trades == 1
        assert result.wins == 1
        assert result.losses == 0
        trade = result.trades[0]
        assert trade.reason == "target"
        assert trade.exit_price == pytest.approx(101.0)
        # PnL = (101 - 100) * 5 * 2.0 = 10.0
        assert trade.pnl == pytest.approx(10.0)

    def test_signal_stop_hit_produces_loss(self):
        """Long signal + later bar with low <= stop → loss."""
        df = _build_day(datetime.date(2025, 3, 3))
        mock = MockStrategy(
            fire_on_calls=[2],
            direction="long",
            entry_price=100.0, stop_price=99.0, target_price=101.0,
            contracts=5,
        )
        crash_ts = pd.Timestamp("2025-03-03 09:30", tz="US/Central")
        _patch_bar(df, crash_ts, low=98.5)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)

        assert result.total_trades == 1
        assert result.wins == 0
        assert result.losses == 1
        trade = result.trades[0]
        assert trade.reason == "stop"
        assert trade.exit_price == pytest.approx(99.0)
        # PnL = (99 - 100) * 5 * 2.0 = -10.0
        assert trade.pnl == pytest.approx(-10.0)

    def test_short_target_hit(self):
        """Short signal → target hit when low reaches target."""
        df = _build_day(datetime.date(2025, 3, 3))
        mock = MockStrategy(
            fire_on_calls=[2],
            direction="short",
            entry_price=100.0, stop_price=101.0, target_price=99.0,
            contracts=5,
        )
        dump_ts = pd.Timestamp("2025-03-03 09:30", tz="US/Central")
        _patch_bar(df, dump_ts, low=98.5)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)

        assert result.total_trades == 1
        assert result.wins == 1
        trade = result.trades[0]
        assert trade.reason == "target"
        assert trade.exit_price == pytest.approx(99.0)
        # PnL short: (entry - exit) * contracts * pv = (100-99)*5*2 = 10
        assert trade.pnl == pytest.approx(10.0)

    def test_short_stop_hit(self):
        """Short signal → stop when high >= stop."""
        df = _build_day(datetime.date(2025, 3, 3))
        mock = MockStrategy(
            fire_on_calls=[2],
            direction="short",
            entry_price=100.0, stop_price=101.0, target_price=99.0,
            contracts=5,
        )
        spike_ts = pd.Timestamp("2025-03-03 09:30", tz="US/Central")
        _patch_bar(df, spike_ts, high=101.5)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)

        assert result.total_trades == 1
        assert result.losses == 1
        trade = result.trades[0]
        assert trade.reason == "stop"
        # PnL short loss: (100 - 101) * 5 * 2 = -10
        assert trade.pnl == pytest.approx(-10.0)

    def test_both_stop_and_target_in_bar_stop_wins(self):
        """If stop AND target fall in same bar, stop is taken (conservative)."""
        df = _build_day(datetime.date(2025, 3, 3))
        mock = MockStrategy(
            fire_on_calls=[2],
            direction="long",
            entry_price=100.0, stop_price=99.0, target_price=101.0,
            contracts=5,
        )
        both_ts = pd.Timestamp("2025-03-03 09:30", tz="US/Central")
        _patch_bar(df, both_ts, high=102.0, low=98.5)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)

        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade.reason == "stop"
        assert trade.pnl < 0

    def test_pnl_uses_mnq_point_value(self):
        """Confirm MNQ_POINT_VALUE = 2.0 is applied to P&L."""
        df = _build_day(datetime.date(2025, 3, 3))
        mock = MockStrategy(
            fire_on_calls=[2],
            entry_price=100.0, stop_price=99.0, target_price=100.5,
            contracts=10,
        )
        _patch_bar(df, pd.Timestamp("2025-03-03 09:30", tz="US/Central"), high=101.0)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)
        trade = result.trades[0]
        # PnL = (100.5 - 100.0) * 10 * 2.0 = 10.0
        assert trade.pnl == pytest.approx(10.0)
        assert MNQ_POINT_VALUE == 2.0

    def test_duration_bars_counted(self):
        """duration_bars = exit bar idx - entry bar idx."""
        df = _build_day(datetime.date(2025, 3, 3))
        mock = MockStrategy(fire_on_calls=[2],
                            entry_price=100.0, stop_price=99.0, target_price=100.5)
        _patch_bar(df, pd.Timestamp("2025-03-03 09:30", tz="US/Central"), high=101.0)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)
        assert result.trades[0].duration_bars > 0


# ═══════════════════════════════════════════════════════════════════════════
# Tests — hard close
# ═══════════════════════════════════════════════════════════════════════════

class TestHardClose:

    def test_hard_close_flattens_open_position(self):
        """Position open at 15:00 CT → flatten at bar close (hard close)."""
        df = _build_day(datetime.date(2025, 3, 3))
        mock = MockStrategy(
            fire_on_calls=[2],
            direction="long",
            entry_price=100.0, stop_price=95.0, target_price=110.0,  # never hit
            contracts=5,
        )
        bt = _make_backtester(strategy=mock)
        result = bt.run(df)

        # Since neither stop nor target fires on flat data, hard close must trigger
        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade.reason == "hard_close"
        # Exit at 15:00 CT or later
        assert trade.exit_time.hour >= 15

    def test_hard_close_flattens_at_bar_close(self):
        """Exit price is the bar close price when hard-closed."""
        df = _build_day(datetime.date(2025, 3, 3))
        mock = MockStrategy(
            fire_on_calls=[2],
            direction="long",
            entry_price=100.0, stop_price=95.0, target_price=110.0,
            contracts=5,
        )
        bt = _make_backtester(strategy=mock)
        result = bt.run(df)
        trade = result.trades[0]
        # Flat synthetic close at 100.0, entry also 100.0 → pnl = 0
        assert trade.exit_price == pytest.approx(100.0)
        assert trade.pnl == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Tests — daily reset / multi-day
# ═══════════════════════════════════════════════════════════════════════════

class TestDailyReset:

    def test_new_day_triggers_reset(self):
        """Strategy.reset_daily fires on every new calendar date."""
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        df = _build_week()  # 5 weekdays
        bt.run(df)
        # Exactly 5 day boundaries
        assert mock.reset_count == 5

    def test_daily_pnl_tracked_per_date(self):
        """result.daily_pnl dict has one entry per date seen."""
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        df = _build_week()
        result = bt.run(df)
        assert len(result.daily_pnl) == 5
        # All zero — no trades
        for d, pnl in result.daily_pnl.items():
            assert pnl == 0.0

    def test_risk_manager_resets_on_new_day(self):
        """After a losing trade on day 1, day 2 starts with daily_pnl=0."""
        df = _build_week()
        mock = MockStrategy(
            fire_on_calls=[2],  # Only fires once, on day 1
            direction="long",
            entry_price=100.0, stop_price=99.0, target_price=101.0,
            contracts=5,
        )
        # Force stop hit on day 1 at 09:30
        _patch_bar(df, pd.Timestamp("2025-03-03 09:30", tz="US/Central"), low=98.5)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)

        assert result.total_trades == 1
        # The risk_manager state has been reset on subsequent day boundaries
        assert bt.risk.daily_pnl == 0.0  # reset on day 2, 3, 4, 5
        # But day 1 had a loss
        day1 = datetime.date(2025, 3, 3)
        assert result.daily_pnl[day1] == pytest.approx(-10.0)


# ═══════════════════════════════════════════════════════════════════════════
# Tests — aggregation / metrics
# ═══════════════════════════════════════════════════════════════════════════

class TestAggregation:

    def test_total_pnl_sums_trade_pnls(self):
        """result.total_pnl = sum(trade.pnl)."""
        df = _build_week()
        # Fire a signal on day 1; target hit
        mock = MockStrategy(
            fire_on_calls=[2],
            entry_price=100.0, stop_price=99.0, target_price=101.0,
            contracts=5,
        )
        _patch_bar(df, pd.Timestamp("2025-03-03 09:30", tz="US/Central"), high=102.0)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)
        assert result.total_pnl == pytest.approx(sum(t.pnl for t in result.trades))
        assert result.total_pnl == pytest.approx(10.0)

    def test_win_rate_calculation(self):
        """2 wins / (2 wins + 0 losses) = 100%."""
        df = _build_week()
        # Force one win on day 1 and one win on day 2
        mock = MockStrategy(
            fire_on_calls=[2],  # Fires once per day (resets on new day → eval_count restarts)
            entry_price=100.0, stop_price=99.0, target_price=101.0,
            contracts=5,
        )
        # Actually eval_count doesn't reset on new day in mock — so only day 1 fires.
        # Patch 2 days with spikes, but mock only fires once total:
        _patch_bar(df, pd.Timestamp("2025-03-03 09:30", tz="US/Central"), high=102.0)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)
        assert result.total_trades == 1
        assert result.win_rate == 1.0  # 1/1

    def test_win_rate_zero_trades_is_zero(self):
        """Zero trades → win_rate = 0.0 (not NaN)."""
        bt = _make_backtester(strategy=MockStrategy(fire_on_calls=[]))
        df = _build_day(datetime.date(2025, 3, 3))
        result = bt.run(df)
        assert result.win_rate == 0.0
        assert result.total_trades == 0

    def test_signal_logged_in_result(self):
        """Each signal that fires is recorded in result.signals."""
        df = _build_day(datetime.date(2025, 3, 3))
        mock = MockStrategy(
            fire_on_calls=[2],
            entry_price=100.0, stop_price=99.0, target_price=101.0,
        )
        _patch_bar(df, pd.Timestamp("2025-03-03 09:30", tz="US/Central"), high=102.0)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)
        assert result.total_signals == 1
        sig = result.signals[0]
        assert isinstance(sig, SignalLog)
        assert sig.direction == "long"
        assert sig.entry_price == pytest.approx(100.0)
        assert sig.strategy == "mock"


# ═══════════════════════════════════════════════════════════════════════════
# Tests — position open blocks new signals
# ═══════════════════════════════════════════════════════════════════════════

class TestPositionBlocking:

    def test_open_position_blocks_new_signal_evaluation(self):
        """While a position is open, evaluate() is NOT called."""
        # Use a short day that stops BEFORE hard close so the position
        # never closes and we can assert evaluate was frozen.
        df = _build_day(datetime.date(2025, 3, 3), n_bars=420)  # 08:00–14:59
        mock = MockStrategy(
            fire_on_calls=[2],
            direction="long",
            entry_price=100.0, stop_price=95.0, target_price=110.0,  # never hit
            contracts=5,
        )
        bt = _make_backtester(strategy=mock)
        result = bt.run(df)

        # Exactly 1 signal fired (call #2); evaluate() never ran again.
        assert result.total_signals == 1
        # Position never closed (no hard close, no stop/target hit)
        assert result.total_trades == 0
        assert mock.eval_count == 2  # frozen after position opened


# ═══════════════════════════════════════════════════════════════════════════
# Tests — date filter
# ═══════════════════════════════════════════════════════════════════════════

class TestDateFilter:

    def test_start_date_filter(self):
        """start_date filters out earlier bars."""
        df = _build_week()
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        result = bt.run(df, start_date="2025-03-05")  # Only Wed-Fri
        # Expect 3 days of reset calls
        assert mock.reset_count == 3

    def test_end_date_filter(self):
        """end_date filters out later bars."""
        df = _build_week()
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        result = bt.run(df, end_date="2025-03-04")  # Only Mon-Tue
        assert mock.reset_count == 2

    def test_start_end_filter_combined(self):
        df = _build_week()
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        result = bt.run(df, start_date="2025-03-04", end_date="2025-03-05")
        assert mock.reset_count == 2  # Tue + Wed


# ═══════════════════════════════════════════════════════════════════════════
# Tests — strategy TF introspection
# ═══════════════════════════════════════════════════════════════════════════

class TestStrategyTimeframes:

    def test_reads_5min_entry_from_mock(self):
        """Default MockStrategy.ENTRY_TF = 5min — backtester uses it."""
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        df = _build_day(datetime.date(2025, 3, 3))
        bt.run(df)
        # 480 1-min bars → 96 5min bars. Minus the first few (not yet closed)
        # plus warmup skip. We expect eval_count to be close to 96 minus warmup.
        assert 80 < mock.eval_count < 100

    def test_reads_1min_entry_from_mock(self):
        """OneMinMockStrategy has ENTRY_TF=1min — eval fires ~per minute."""
        mock = OneMinMockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        df = _build_day(datetime.date(2025, 3, 3))
        bt.run(df)
        # 420 1-min bars, each one triggers an evaluation (minus warmup)
        assert mock.eval_count > 400


# ═══════════════════════════════════════════════════════════════════════════
# Tests — integration on 1 week of data
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegrationOneWeek:

    def test_one_week_runs_clean(self):
        """Full 5-day run completes without error and returns valid result."""
        df = _build_week()
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        result = bt.run(df)

        assert isinstance(result, BacktestResult)
        assert result.total_trades == 0
        assert result.total_signals == 0
        assert result.start_date == df.index[0]
        assert result.end_date == df.index[-1]
        assert len(result.daily_pnl) == 5

    def test_one_week_with_trade_hits_target(self):
        """Full 1-week run with 1 winning trade."""
        df = _build_week()
        mock = MockStrategy(
            fire_on_calls=[2],
            direction="long",
            entry_price=100.0, stop_price=99.0, target_price=101.0,
            contracts=5,
        )
        _patch_bar(df, pd.Timestamp("2025-03-03 09:30", tz="US/Central"), high=102.0)

        bt = _make_backtester(strategy=mock)
        result = bt.run(df)
        assert result.total_trades == 1
        assert result.wins == 1
        assert result.total_pnl == pytest.approx(10.0)
        assert result.win_rate == 1.0

    def test_result_repr_is_readable(self):
        """BacktestResult has a sensible __repr__."""
        mock = MockStrategy(fire_on_calls=[])
        bt = _make_backtester(strategy=mock)
        df = _build_day(datetime.date(2025, 3, 3))
        result = bt.run(df)
        text = repr(result)
        assert "BacktestResult" in text
        assert "MockStrategy" in text


# ═══════════════════════════════════════════════════════════════════════════
# Tests — internal helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestHelpers:

    def test_tf_delta_known_values(self):
        assert Backtester._tf_delta("1min") == pd.Timedelta(minutes=1)
        assert Backtester._tf_delta("5min") == pd.Timedelta(minutes=5)
        assert Backtester._tf_delta("15min") == pd.Timedelta(minutes=15)
        assert Backtester._tf_delta("1H") == pd.Timedelta(hours=1)

    def test_latest_closed_idx_returns_minus_one_before_first_close(self):
        """Before any 5min bar has fully closed, idx should be -1."""
        idx = pd.date_range(
            "2025-03-03 08:00", periods=10, freq="5min", tz="US/Central",
        )
        # Query at 08:00 with delta=5min → cutoff = 07:55 → nothing before → -1
        result = Backtester._latest_closed_idx(
            idx, pd.Timestamp("2025-03-03 08:00", tz="US/Central"),
            pd.Timedelta(minutes=5),
        )
        assert result == -1

    def test_latest_closed_idx_returns_first_bar_at_close_time(self):
        """At the exact close time of bar 0, that bar becomes available."""
        idx = pd.date_range(
            "2025-03-03 08:00", periods=10, freq="5min", tz="US/Central",
        )
        # At 08:05, bar labeled 08:00 has closed
        result = Backtester._latest_closed_idx(
            idx, pd.Timestamp("2025-03-03 08:05", tz="US/Central"),
            pd.Timedelta(minutes=5),
        )
        assert result == 0

    def test_latest_closed_idx_midway_through_bar(self):
        """Mid-bar: return the PREVIOUS closed bar (not current one)."""
        idx = pd.date_range(
            "2025-03-03 08:00", periods=10, freq="5min", tz="US/Central",
        )
        # At 08:07, bar labeled 08:00 has closed; 08:05 hasn't yet
        result = Backtester._latest_closed_idx(
            idx, pd.Timestamp("2025-03-03 08:07", tz="US/Central"),
            pd.Timedelta(minutes=5),
        )
        assert result == 0
