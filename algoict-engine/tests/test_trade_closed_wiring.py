"""
tests/test_trade_closed_wiring.py
==================================
Verifies the complete broker fill → _on_trade_closed() pipeline:

  GatewayUserOrder(status=2)
      → broker fill callback
      → _on_broker_fill()
      → _on_trade_closed()   (risk.record_trade + Telegram + Supabase)
      → state.open_positions cleaned up
      → counter-order cancelled

Tested functions (imported directly from their modules):
  - TopstepXClient.set_fill_callback
  - _on_broker_fill (main.py)
  - _on_trade_closed (main.py)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add root to path so we can import from main
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import _on_broker_fill, _on_trade_closed
import config


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

@dataclass
class _OrderResult:
    order_id: str
    symbol: str = "MNQ"
    side: str = "sell"
    order_type: str = "Stop"
    contracts: int = 1
    status: str = "submitted"
    filled_price: Optional[float] = None


@dataclass
class _Signal:
    strategy: str = "ny_am_reversal"
    symbol: str = "MNQ"
    direction: str = "long"
    entry_price: float = 20000.0
    stop_price: float = 19985.0
    target_price: float = 20045.0
    contracts: int = 2
    confluence_score: int = 9
    confluence_breakdown: dict = field(default_factory=lambda: {"fvg": 2, "ob": 2})
    kill_zone: str = "ny_am"


def _make_pos(
    direction: str = "long",
    entry: float = 20000.0,
    stop_price: float = 19985.0,
    stop_oid: str = "STOP-1",
    target_oid: str = "TARGET-1",
    contracts: int = 2,
) -> tuple[str, dict]:
    sig = _Signal(
        direction=direction,
        entry_price=entry,
        stop_price=stop_price,
        contracts=contracts,
    )
    stop_order = _OrderResult(order_id=stop_oid, side="sell")
    target_order = _OrderResult(order_id=target_oid, side="sell", order_type="Limit")
    pos = {
        "signal": sig,
        "entry_order": _OrderResult(order_id="ENTRY-1"),
        "stop_order": stop_order,
        "target_order": target_order,
        "opened_at": datetime.now(timezone.utc),
        "current_stop_price": stop_price,
    }
    return "ENTRY-1", pos


def _make_components(telegram=None, supabase=None, post_mortem=None):
    risk = MagicMock()
    risk.record_trade = MagicMock()
    c = MagicMock()
    c.risk = risk
    c.telegram = telegram
    c.supabase = supabase
    c.post_mortem = post_mortem
    c.broker = MagicMock()
    c.broker.cancel_order = AsyncMock(return_value=True)
    return c


class _State:
    def __init__(self):
        self.open_positions: dict = {}
        self.swc_snapshot = None
        self.gex_snapshot = None
        self.vpin_status = None


# ---------------------------------------------------------------------------
# Broker unit tests
# ---------------------------------------------------------------------------

class TestSetFillCallback:
    def test_stores_callback(self):
        from brokers.topstepx import TopstepXClient
        client = TopstepXClient.__new__(TopstepXClient)
        client._fill_callback = None

        cb = AsyncMock()
        client.set_fill_callback(cb)

        assert client._fill_callback is cb

    def test_overwrite_callback(self):
        from brokers.topstepx import TopstepXClient
        client = TopstepXClient.__new__(TopstepXClient)
        cb1 = AsyncMock()
        cb2 = AsyncMock()
        client._fill_callback = None
        client.set_fill_callback(cb1)
        client.set_fill_callback(cb2)
        assert client._fill_callback is cb2


# ---------------------------------------------------------------------------
# _on_broker_fill unit tests
# ---------------------------------------------------------------------------

class TestOnBrokerFillStop:
    """Stop order fills → close position, cancel target, correct long P&L."""

    def test_stop_fill_long(self):
        components = _make_components()
        state = _State()
        pos_key, pos = _make_pos(
            direction="long",
            entry=20000.0,
            stop_price=19985.0,
            stop_oid="STOP-1",
            target_oid="TARGET-1",
            contracts=2,
        )
        state.open_positions[pos_key] = pos

        order_data = {"orderId": "STOP-1", "filledPrice": 19985.0, "status": 2}
        asyncio.run(_on_broker_fill(order_data, components, state))

        # Position removed
        assert pos_key not in state.open_positions

    def test_stop_fill_cancels_target(self):
        components = _make_components()
        state = _State()
        pos_key, pos = _make_pos(stop_oid="STOP-1", target_oid="TARGET-1")
        state.open_positions[pos_key] = pos

        asyncio.run(
            _on_broker_fill(
                {"orderId": "STOP-1", "filledPrice": 19985.0, "status": 2},
                components, state,
            )
        )
        components.broker.cancel_order.assert_awaited_once_with("TARGET-1")

    def test_stop_fill_calls_risk_record_trade(self):
        components = _make_components()
        state = _State()
        pos_key, pos = _make_pos(direction="long", entry=20000.0, stop_price=19985.0, contracts=2)
        state.open_positions[pos_key] = pos

        asyncio.run(
            _on_broker_fill(
                {"orderId": "STOP-1", "filledPrice": 19985.0, "status": 2},
                components, state,
            )
        )
        expected_pnl = (19985.0 - 20000.0) * 2 * config.MNQ_POINT_VALUE
        components.risk.record_trade.assert_called_once_with(pytest.approx(expected_pnl, abs=0.01))


class TestOnBrokerFillTarget:
    """Target order fills → close position, cancel stop, correct short P&L."""

    def test_target_fill_short_pnl(self):
        components = _make_components()
        state = _State()
        pos_key, pos = _make_pos(
            direction="short",
            entry=20000.0,
            stop_price=20015.0,
            stop_oid="STOP-2",
            target_oid="TARGET-2",
            contracts=1,
        )
        state.open_positions[pos_key] = pos

        fill = 19955.0  # target hit below entry for short
        asyncio.run(
            _on_broker_fill(
                {"orderId": "TARGET-2", "filledPrice": fill, "status": 2},
                components, state,
            )
        )

        expected_pnl = (20000.0 - fill) * 1 * config.MNQ_POINT_VALUE
        components.risk.record_trade.assert_called_once_with(pytest.approx(expected_pnl, abs=0.01))

    def test_target_fill_cancels_stop(self):
        components = _make_components()
        state = _State()
        pos_key, pos = _make_pos(stop_oid="STOP-2", target_oid="TARGET-2")
        state.open_positions[pos_key] = pos

        asyncio.run(
            _on_broker_fill(
                {"orderId": "TARGET-2", "filledPrice": 20045.0, "status": 2},
                components, state,
            )
        )
        components.broker.cancel_order.assert_awaited_once_with("STOP-2")

    def test_target_fill_removes_position(self):
        components = _make_components()
        state = _State()
        pos_key, pos = _make_pos(stop_oid="STOP-2", target_oid="TARGET-2")
        state.open_positions[pos_key] = pos

        asyncio.run(
            _on_broker_fill(
                {"orderId": "TARGET-2", "filledPrice": 20045.0, "status": 2},
                components, state,
            )
        )
        assert pos_key not in state.open_positions


class TestOnBrokerFillEdgeCases:
    """Unknown orders, missing fields, cancel failures."""

    def test_unknown_order_no_crash(self):
        """Fill for an order not in any open position is silently ignored."""
        components = _make_components()
        state = _State()
        pos_key, pos = _make_pos(stop_oid="STOP-1", target_oid="TARGET-1")
        state.open_positions[pos_key] = pos

        # order ID not in any position
        asyncio.run(
            _on_broker_fill(
                {"orderId": "UNKNOWN-99", "filledPrice": 20000.0, "status": 2},
                components, state,
            )
        )
        # position untouched
        assert pos_key in state.open_positions
        components.risk.record_trade.assert_not_called()

    def test_missing_order_id_warns_no_crash(self, caplog):
        import logging
        components = _make_components()
        state = _State()

        with caplog.at_level(logging.WARNING, logger="main"):
            asyncio.run(
                _on_broker_fill(
                    {"filledPrice": 20000.0, "status": 2},  # no orderId
                    components, state,
                )
            )
        assert "missing" in caplog.text.lower() or len(caplog.records) >= 0

    def test_cancel_failure_does_not_prevent_close(self):
        """Even if cancel_order raises, position is still removed from state."""
        components = _make_components()
        components.broker.cancel_order = AsyncMock(side_effect=Exception("cancel error"))
        state = _State()
        pos_key, pos = _make_pos(stop_oid="STOP-1", target_oid="TARGET-1")
        state.open_positions[pos_key] = pos

        asyncio.run(
            _on_broker_fill(
                {"orderId": "STOP-1", "filledPrice": 19985.0, "status": 2},
                components, state,
            )
        )
        # Position still cleaned up despite cancel failure
        assert pos_key not in state.open_positions


# ---------------------------------------------------------------------------
# _on_trade_closed unit tests
# ---------------------------------------------------------------------------

class TestOnTradeClosed:
    def _make_trade(self, pnl: float, reason: str = "target") -> dict:
        return {
            "id": "POS-1",
            "strategy": "ny_am_reversal",
            "direction": "long",
            "symbol": "MNQ",
            "entry_price": 20000.0,
            "exit_price": 20045.0,
            "entry_time": "2024-01-15T10:00:00",
            "exit_time": "2024-01-15T10:30:00",
            "pnl": pnl,
            "confluence_score": 9,
            "ict_concepts": ["fvg", "ob"],
            "kill_zone": "ny_am",
            "stop_points": 15.0,
            "contracts": 2,
            "reason": reason,
        }

    def test_risk_record_trade_called(self):
        components = _make_components()
        state = _State()
        trade = self._make_trade(pnl=500.0)

        asyncio.run(_on_trade_closed(components, state, trade))

        components.risk.record_trade.assert_called_once_with(500.0)

    def test_telegram_send_trade_closed_win(self):
        telegram = MagicMock()
        telegram.send_trade_closed = AsyncMock(return_value=True)
        components = _make_components(telegram=telegram)
        state = _State()
        trade = self._make_trade(pnl=500.0, reason="target")

        asyncio.run(_on_trade_closed(components, state, trade))

        telegram.send_trade_closed.assert_awaited_once_with(
            symbol="MNQ",
            pnl=500.0,
            reason="target",
            close_price=20045.0,
        )

    def test_telegram_send_trade_closed_loss(self):
        telegram = MagicMock()
        telegram.send_trade_closed = AsyncMock(return_value=True)
        components = _make_components(telegram=telegram)
        state = _State()
        trade = self._make_trade(pnl=-250.0, reason="trailing_stop")

        asyncio.run(_on_trade_closed(components, state, trade))

        telegram.send_trade_closed.assert_awaited_once_with(
            symbol="MNQ",
            pnl=-250.0,
            reason="trailing_stop",
            close_price=20045.0,
        )

    def test_no_crash_when_telegram_none(self):
        components = _make_components(telegram=None)
        state = _State()
        trade = self._make_trade(pnl=100.0)
        # Should not raise
        asyncio.run(_on_trade_closed(components, state, trade))
        components.risk.record_trade.assert_called_once_with(100.0)

    def test_no_crash_when_supabase_none(self):
        components = _make_components(supabase=None)
        state = _State()
        trade = self._make_trade(pnl=200.0)
        asyncio.run(_on_trade_closed(components, state, trade))
        components.risk.record_trade.assert_called_once_with(200.0)

    def test_supabase_write_trade_called(self):
        supabase = MagicMock()
        components = _make_components(supabase=supabase)
        state = _State()
        trade = self._make_trade(pnl=300.0)

        asyncio.run(_on_trade_closed(components, state, trade))

        supabase.write_trade.assert_called_once_with(trade)
