"""Tests for db.supabase_lab_client with mocked Supabase backend."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from db.supabase_lab_client import SupabaseLabClient, get_lab_client


# ─── Mock Supabase client ───────────────────────────────────────────────

class MockTable:
    """Pretends to be a supabase-py table() object."""

    def __init__(self, name: str, store: list):
        self.name = name
        self.store = store
        self._pending: dict = {}
        self._operation: str = ""

    def upsert(self, payload, on_conflict: str = "id"):
        self._operation = "upsert"
        self._pending = {"payload": payload, "on_conflict": on_conflict}
        return self

    def insert(self, payload):
        self._operation = "insert"
        self._pending = {"payload": payload}
        return self

    def update(self, payload):
        self._operation = "update"
        self._pending = {"payload": payload}
        return self

    def select(self, *args, **kwargs):
        self._operation = "select"
        return self

    def eq(self, column: str, value: Any):
        self._pending["filter"] = (column, value)
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, n: int):
        return self

    def single(self):
        return self

    def execute(self):
        if self._operation in ("upsert", "insert"):
            payload = self._pending["payload"]
            if isinstance(payload, list):
                self.store.extend(payload)
            else:
                self.store.append(payload)
            return MagicMock(data=[payload] if not isinstance(payload, list) else payload)
        if self._operation == "update":
            return MagicMock(data=[self._pending["payload"]])
        if self._operation == "select":
            # Simple filter support
            flt = self._pending.get("filter")
            if flt:
                col, val = flt
                matches = [r for r in self.store if r.get(col) == val]
                return MagicMock(data=matches[0] if matches else None)
            return MagicMock(data=self.store)
        return MagicMock(data=None)


class MockClient:
    """Top-level mock implementing only what SupabaseLabClient calls."""

    def __init__(self):
        self.tables: dict[str, list] = {
            "bot_state": [],
            "trades": [],
            "signals": [],
            "daily_performance": [],
            "post_mortems": [],
            "market_levels": [],
            "backtest_results": [],
            "strategy_candidates": [],
        }
        self.call_log: list = []

    def table(self, name: str) -> MockTable:
        self.call_log.append(name)
        return MockTable(name, self.tables[name])


@pytest.fixture
def mock_client():
    return MockClient()


@pytest.fixture
def lab_client(mock_client):
    return SupabaseLabClient(mock_client, url="http://test.supabase")


# ─── Construction + stats ──────────────────────────────────────────────

class TestConstruction:
    def test_stores_url(self, lab_client):
        assert lab_client.url == "http://test.supabase"

    def test_initial_stats_zero(self, lab_client):
        stats = lab_client.stats
        assert stats["writes"] == 0
        assert stats["errors"] == 0
        assert stats["success_rate"] == 1.0


class TestFactoryWithMissingEnv:
    def test_get_lab_client_returns_none_without_env(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        # Block dotenv file loading too
        monkeypatch.setattr(
            "db.supabase_lab_client._load_env_if_needed", lambda: None
        )
        client = get_lab_client()
        assert client is None

    def test_get_lab_client_accepts_overrides(self, monkeypatch):
        # Even without env, passing both should return a real client
        # (assuming supabase-py is installed, which the smoke test verified)
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        client = get_lab_client(url="http://x", key="y")
        # Real supabase-py will happily build against a bogus URL
        # (it doesn't connect on construction)
        assert client is not None


# ─── Low-level writers ────────────────────────────────────────────────

class TestUpsertBotState:
    def test_writes_normalized_payload(self, lab_client, mock_client):
        ok = lab_client.upsert_bot_state({"vpin": 0.5, "is_running": True})
        assert ok is True
        assert len(mock_client.tables["bot_state"]) == 1
        stored = mock_client.tables["bot_state"][0]
        assert stored["id"] == "bot_1"
        assert stored["vpin"] == 0.5
        assert stored["is_running"] is True

    def test_invalid_enum_normalized(self, lab_client, mock_client):
        lab_client.upsert_bot_state({"toxicity_level": "nuclear"})
        assert mock_client.tables["bot_state"][0]["toxicity_level"] == "calm"

    def test_stats_updated_on_success(self, lab_client):
        lab_client.upsert_bot_state({"vpin": 0.1})
        assert lab_client.stats["writes"] == 1

    def test_stats_updated_on_error(self, lab_client, mock_client):
        # Make the mock raise
        def boom(name):
            raise RuntimeError("supabase down")
        mock_client.table = boom
        ok = lab_client.upsert_bot_state({"vpin": 0.1})
        assert ok is False
        assert lab_client.stats["errors"] == 1


class TestInsertTrade:
    def test_single_trade(self, lab_client, mock_client):
        ok = lab_client.insert_trade({
            "direction": "long",
            "entry_price": 18000,
            "stop_price": 17980,
            "target_price": 18060,
            "entry_time": "2025-03-10T14:30:00+00:00",
            "exit_time": "2025-03-10T14:45:00+00:00",
            "exit_price": 18060,
            "contracts": 1,
            "pnl": 120,
            "confluence_score": 12,
            "strategy": "ny_am_reversal",
        })
        assert ok is True
        row = mock_client.tables["trades"][0]
        assert row["direction"] == "long"
        assert row["stop_loss"] == 17980  # Mapped from stop_price

    def test_batch_insert_count(self, lab_client, mock_client):
        trades = [
            {
                "id": f"T{i}",
                "direction": "long" if i % 2 == 0 else "short",
                "entry_price": 18000 + i,
                "stop_price": 17990,
                "target_price": 18060,
                "entry_time": f"2025-03-10T14:{30+i:02d}:00+00:00",
                "contracts": 1,
                "confluence_score": 10,
            }
            for i in range(5)
        ]
        n = lab_client.insert_trades_batch(trades)
        assert n == 5
        assert len(mock_client.tables["trades"]) == 5

    def test_empty_batch_returns_zero(self, lab_client):
        assert lab_client.insert_trades_batch([]) == 0


class TestInsertBacktestResult:
    def test_writes_aggregated_row(self, lab_client, mock_client):
        from dataclasses import dataclass, field

        @dataclass
        class BR:
            strategy: str = "ny_am_reversal"
            trades: list = field(default_factory=list)
            daily_pnl: dict = field(default_factory=dict)
            total_pnl: float = 500.0
            total_trades: int = 5
            wins: int = 3
            losses: int = 2
            win_rate: float = 0.6
            start_date: str = "2025-01-01"
            end_date: str = "2025-03-31"

        ok = lab_client.insert_backtest_result(BR(), run_id="test_bt_001")
        assert ok is True
        row = mock_client.tables["backtest_results"][0]
        assert row["id"] == "test_bt_001"
        assert row["win_rate"] == 0.6
        assert row["total_trades"] == 5


class TestInsertMarketLevel:
    def test_returns_id_on_success(self, lab_client, mock_client):
        level = {
            "symbol": "MNQ",
            "type": "FVG",
            "direction": "bullish",
            "timeframe": "5min",
            "price_low": 17990,
            "price_high": 18010,
            "active": True,
            "id": "test-uuid-1",  # Injected so the mock has something to return
        }
        returned_id = lab_client.insert_market_level(level)
        assert returned_id == "test-uuid-1"

    def test_mark_mitigated(self, lab_client, mock_client):
        ok = lab_client.mark_market_level_mitigated("test-uuid-1")
        assert ok is True


class TestStrategyCandidates:
    def test_single_upsert(self, lab_client, mock_client):
        record = {
            "id": "H-001",
            "hypothesis": {"ict_reasoning": "test reasoning"},
            "strategy_name": "ny_am_reversal",
            "status": "passed",
            "gates_passed": 9,
            "gates_total": 9,
            "score": 85,
            "session_id": "LAB-001",
        }
        ok = lab_client.upsert_strategy_candidate(record)
        assert ok is True
        stored = mock_client.tables["strategy_candidates"][0]
        assert stored["id"] == "H-001"
        assert stored["score"] == 85

    def test_batch_count(self, lab_client, mock_client):
        records = [
            {
                "id": f"H-{i:03d}",
                "hypothesis": {"ict_reasoning": f"test {i}"},
                "strategy_name": "ny_am_reversal",
                "session_id": "LAB-batch",
            }
            for i in range(3)
        ]
        n = lab_client.upsert_strategy_candidates_batch(records)
        assert n == 3


class TestPostMortem:
    def test_writes_pm_row(self, lab_client, mock_client):
        pm = {
            "category": "htf_misread",
            "severity": "high",
            "reason": "Entered against weekly bias",
            "recommendation": "Skip when weekly bias diverges",
            "pnl": -250,
            "timestamp": "2025-03-10T15:00:00+00:00",
        }
        ok = lab_client.insert_post_mortem(pm, trade_id="trade_001")
        assert ok is True
        row = mock_client.tables["post_mortems"][0]
        assert row["trade_id"] == "trade_001"
        assert row["reason_category"] == "htf_misread"


class TestErrorHandling:
    def test_write_failures_are_caught(self, lab_client, mock_client):
        # Swap out table() to always raise
        def boom(name):
            raise ConnectionError("network down")
        mock_client.table = boom

        # None of these should raise
        assert lab_client.upsert_bot_state({"vpin": 0.1}) is False
        assert lab_client.insert_trade({"direction": "long", "entry_price": 1, "stop_price": 0.9, "target_price": 1.2, "entry_time": "2025-01-01", "contracts": 1, "confluence_score": 10}) is False
        assert lab_client.insert_trades_batch([{"direction": "long", "entry_price": 1, "stop_price": 0.9, "target_price": 1.2, "entry_time": "2025-01-01", "contracts": 1, "confluence_score": 10}]) == 0

        # All should be counted as errors
        stats = lab_client.stats
        assert stats["errors"] >= 3
