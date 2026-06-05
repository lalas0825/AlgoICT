"""Bug fix (2026-06-05): closed trades were persisted with status='open'.

trades.status is NOT NULL DEFAULT 'open'. The live close path (_on_trade_closed
-> write_trade) was the only writer and omitted status, so every closed trade
INSERTed fresh landed on the 'open' default. The dashboard "Open Positions"
panel (filters status='open') then showed closed trades as phantom positions.

write_trade now derives status from the row lifecycle (exit_time => closed).
"""
from unittest.mock import MagicMock, patch

import db.supabase_client as sc


def _make_client():
    """SupabaseClient with the underlying supabase Client mocked out."""
    with patch.object(sc, "SUPABASE_AVAILABLE", True), \
            patch.object(sc, "create_client") as mk:
        client = MagicMock()
        mk.return_value = client
        c = sc.SupabaseClient(url="http://test", key="test-key")
    # isolate the class-level missing-cols cache between tests
    sc.SupabaseClient._missing_trades_cols = set()
    return c, client


def _upserted_payload(client):
    # self._client.table("trades").upsert(payload, on_conflict="id").execute()
    args, _ = client.table.return_value.upsert.call_args
    return args[0]


def test_closed_trade_gets_status_closed():
    c, client = _make_client()
    ok = c.write_trade({
        "symbol": "MNQ", "entry_time": "2026-06-05T10:00:00Z",
        "exit_time": "2026-06-05T10:05:00Z", "pnl": 93.0, "contracts": 6,
    })
    assert ok is True
    assert _upserted_payload(client)["status"] == "closed"


def test_row_without_exit_gets_status_open():
    c, client = _make_client()
    c.write_trade({
        "symbol": "MNQ", "entry_time": "2026-06-05T10:00:00Z",
        "exit_time": None, "pnl": None, "contracts": 6,
    })
    assert _upserted_payload(client)["status"] == "open"


def test_explicit_status_is_respected():
    c, client = _make_client()
    c.write_trade({
        "symbol": "MNQ", "entry_time": "t0", "exit_time": "t1",
        "pnl": -50, "contracts": 2, "status": "cancelled",
    })
    assert _upserted_payload(client)["status"] == "cancelled"
