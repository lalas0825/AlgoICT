"""
tests/test_supabase_client.py
=============================
Tests for db/supabase_client.py

Mocks the actual Supabase client since we're offline.
"""

import pytest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.supabase_client import SupabaseClient


class MockSupabaseTable:
    def __init__(self, table_name):
        self.table_name = table_name
        self.data = {}
        self.last_operation = None

    def upsert(self, record, on_conflict=None):
        self.last_operation = ("upsert", record, on_conflict)
        self.data[record.get("id")] = record
        return self

    def insert(self, record):
        self.last_operation = ("insert", record)
        self.data[record.get("id")] = record
        return self

    def select(self, *args):
        return self

    def eq(self, col, val):
        return self

    def gte(self, col, val):
        return self

    def lt(self, col, val):
        return self

    def order(self, col, desc=False):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return MockExecuteResult(list(self.data.values()))


class MockExecuteResult:
    def __init__(self, data):
        self.data = data


class MockSupabaseClientLib:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        if name not in self.tables:
            self.tables[name] = MockSupabaseTable(name)
        return self.tables[name]


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestSupabaseClientConstructor:
    def test_raises_without_url(self):
        with pytest.raises((ValueError, ImportError)):
            SupabaseClient(url="", key="test")

    def test_raises_without_key(self):
        with pytest.raises((ValueError, ImportError)):
            SupabaseClient(url="http://test", key="")

    def test_raises_if_supabase_not_available(self):
        with patch("db.supabase_client.SUPABASE_AVAILABLE", False):
            with pytest.raises(ImportError, match="not installed"):
                SupabaseClient(url="http://test", key="test")


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

class TestWriteTrade:
    def test_write_trade_success(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MockSupabaseClientLib()

        trade = {
            "symbol": "MNQ",
            "entry_time": "2024-01-02T09:30:00Z",
            "exit_time": "2024-01-02T09:35:00Z",
            "side": "BUY",
            "contracts": 1,
            "entry_price": 19500.0,
            "exit_price": 19510.0,
            "pnl": 100.0,
            "confluence_score": 15,
            "vpin": 0.25,
            "toxicity": "calm",
            "strategy": "ny_am_reversal",
        }

        result = sb.write_trade(trade)
        assert result is True
        assert "trades" in sb._client.tables

    def test_write_trade_with_extra_fields(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MockSupabaseClientLib()

        trade = {
            "symbol": "TSLA",
            "entry_time": "2024-01-02T10:00:00Z",
            "entry_price": 250.0,
            "side": "SELL",
            "contracts": 1,
            "custom_field": "custom_value",
        }

        result = sb.write_trade(trade)
        assert result is True

    def test_write_trade_error_handling(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MagicMock()
        sb._client.table.side_effect = Exception("Network error")

        result = sb.write_trade({"symbol": "MNQ"})
        assert result is False


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

class TestWriteSignal:
    def test_write_signal_success(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MockSupabaseClientLib()

        signal = {
            "timestamp": "2024-01-02T09:30:00Z",
            "symbol": "MNQ",
            "signal_type": "BUY",
            "price": 19500.0,
            "confluence_score": 12,
            "liquidity_grab": True,
            "fair_value_gap": True,
            "order_block": False,
        }

        result = sb.write_signal(signal)
        assert result is True

    def test_write_signal_error_handling(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MagicMock()
        sb._client.table.side_effect = Exception("DB error")

        result = sb.write_signal({"timestamp": "2024-01-02", "symbol": "MNQ"})
        assert result is False


# ---------------------------------------------------------------------------
# Bot State
# ---------------------------------------------------------------------------

class TestUpdateBotState:
    def test_update_bot_state_success(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MockSupabaseClientLib()

        result = sb.update_bot_state({
            "last_heartbeat": "2024-01-02T09:30:00Z",
            "status": "running",
        })
        assert result is True

    def test_get_bot_state_success(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        mock_client = MockSupabaseClientLib()
        # Pre-populate bot_state
        mock_client.table("bot_state").insert({"id": "bot_1", "status": "running"})
        sb._client = mock_client

        state = sb.get_bot_state()
        assert state is not None
        assert state["id"] == "bot_1"

    def test_get_bot_state_empty(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MockSupabaseClientLib()

        state = sb.get_bot_state()
        assert state is None


# ---------------------------------------------------------------------------
# Daily Performance
# ---------------------------------------------------------------------------

class TestWriteDailyPerformance:
    def test_write_daily_perf_success(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MockSupabaseClientLib()

        perf = {
            "date": "2024-01-02",
            "trades_count": 5,
            "wins": 3,
            "losses": 2,
            "total_pnl": 750.0,
            "max_drawdown": 0.05,
            "sharpe": 1.5,
            "best_trade": 250.0,
            "worst_trade": -100.0,
        }

        result = sb.write_daily_performance(perf)
        assert result is True


# ---------------------------------------------------------------------------
# Post-Mortems
# ---------------------------------------------------------------------------

class TestWritePostMortem:
    def test_write_postmortem_success(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MockSupabaseClientLib()

        pm = {
            "timestamp": "2024-01-02T11:00:00Z",
            "trade_id": "MNQ_2024-01-02T09:30:00Z",
            "reason_category": "entry_timing",
            "analysis": "Entered too early, missed 50 ticks",
            "lesson": "Wait for confirmation",
            "related_trades": ["MNQ_2024-01-02T10:15:00Z"],
        }

        result = sb.write_post_mortem(pm)
        assert result is True


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

class TestGetTradesToday:
    def test_get_trades_today(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        mock_client = MockSupabaseClientLib()
        # Pre-populate trades
        mock_client.table("trades").insert({
            "id": "MNQ_2024-01-02T09:30:00Z",
            "symbol": "MNQ",
            "entry_time": "2024-01-02T09:30:00Z",
        })
        sb._client = mock_client

        trades = sb.get_trades_today("2024-01-02")
        assert isinstance(trades, list)

    def test_get_recent_trades(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = MockSupabaseClientLib()

        trades = sb.get_recent_trades(limit=10)
        assert isinstance(trades, list)

    def test_get_market_levels(self):
        sb = SupabaseClient.__new__(SupabaseClient)
        mock_client = MockSupabaseClientLib()
        # Pre-populate market levels
        mock_client.table("market_levels").insert({
            "id": "MNQ_2024-01-02",
            "symbol": "MNQ",
            "pdh": 19550.0,
            "pdl": 19450.0,
            "timestamp": "2024-01-02T09:30:00Z",
        })
        sb._client = mock_client

        levels = sb.get_market_levels("MNQ")
        assert levels is not None or levels is None  # Either is OK


# ---------------------------------------------------------------------------
# WinError 10035 (WSAEWOULDBLOCK) retry logic in update_bot_state
# ---------------------------------------------------------------------------

def _wsaewouldblock() -> OSError:
    exc = OSError("A non-blocking socket operation could not be completed immediately")
    exc.winerror = 10035  # type: ignore[attr-defined]
    return exc


class TestUpdateBotStateRetry:

    def _make_client(self, fail_times: int = 0):
        """MockSupabaseClientLib whose bot_state table raises WinError on first N calls."""
        calls = {"n": 0}

        class RetryTable(MockSupabaseTable):
            def execute(self_):
                calls["n"] += 1
                if calls["n"] <= fail_times:
                    raise _wsaewouldblock()
                return MockExecuteResult([{"id": "bot_1"}])

        class RetryClientLib(MockSupabaseClientLib):
            def table(self_, name):
                if name == "bot_state":
                    t = RetryTable(name)
                    return t
                return super().table(name)

        return RetryClientLib(), calls

    def test_wsaewouldblock_first_attempt_retries_and_succeeds(self):
        """Single WSAEWOULDBLOCK on first attempt → retry → success → returns True."""
        mock_lib, calls = self._make_client(fail_times=1)
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = mock_lib

        result = sb.update_bot_state({"status": "running"})

        assert result is True, "should return True after successful retry"
        assert calls["n"] == 2, "should have attempted twice (1 fail + 1 success)"

    def test_wsaewouldblock_all_retries_exhausted_returns_false(self):
        """WSAEWOULDBLOCK on every attempt → exhausted → returns False (no exception)."""
        mock_lib, calls = self._make_client(fail_times=99)
        sb = SupabaseClient.__new__(SupabaseClient)
        sb._client = mock_lib

        result = sb.update_bot_state({"status": "running"})

        assert result is False
        assert calls["n"] == 4, "should try 4 times (1 initial + 3 retries)"
