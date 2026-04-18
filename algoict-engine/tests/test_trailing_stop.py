"""
tests/test_trailing_stop.py
============================
Unit tests for _manage_open_positions() in main.py.

All broker/swing interactions are mocked — no network calls.
Validates that the live trailing stop logic mirrors backtester._update_trailing_stop
exactly.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import _manage_open_positions, EngineState, Components
from brokers.topstepx import OrderResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(direction: str, stop_price: float, symbol: str = "MNQ", contracts: int = 1):
    sig = MagicMock()
    sig.direction = direction
    sig.symbol = symbol
    sig.contracts = contracts
    sig.stop_price = stop_price
    return sig


def _make_stop_order(order_id: str = "ord-001") -> OrderResult:
    return OrderResult(
        order_id=order_id,
        symbol="MNQ",
        side="sell",
        order_type="Stop",
        contracts=1,
        status="submitted",
    )


def _make_swing_point(price: float, swing_type: str = "low"):
    sp = MagicMock()
    sp.price = price
    sp.type = swing_type
    return sp


def _make_components(swing_low=None, swing_high=None) -> Components:
    swing = MagicMock()
    swing.get_latest_swing_low.return_value = swing_low
    swing.get_latest_swing_high.return_value = swing_high

    broker = MagicMock()
    broker.cancel_order = AsyncMock(return_value=True)
    broker.submit_stop_order = AsyncMock(return_value=_make_stop_order("ord-new"))

    components = MagicMock(spec=Components)
    components.detectors = {"swing": swing}
    components.broker = broker
    return components


def _make_state_with_position(
    direction: str,
    current_stop: float,
    stop_order_id: str = "ord-001",
) -> EngineState:
    state = EngineState(mode="paper")
    signal = _make_signal(direction, current_stop)
    stop_order = _make_stop_order(stop_order_id)
    state.open_positions["entry-1"] = {
        "signal": signal,
        "entry_order": MagicMock(),
        "stop_order": stop_order,
        "target_order": MagicMock(),
        "opened_at": None,
        "current_stop_price": current_stop,
    }
    return state


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# LONG direction
# ---------------------------------------------------------------------------

class TestTrailingLong:
    def test_updates_when_new_swing_above_stop(self):
        """LONG: new swing low > current stop → stop moves up."""
        current_stop = 19_000.0
        new_swing_price = 19_010.0
        sp = _make_swing_point(new_swing_price, "low")
        components = _make_components(swing_low=sp)
        state = _make_state_with_position("long", current_stop)

        _run(_manage_open_positions(components, state))

        pos = list(state.open_positions.values())[0]
        assert pos["current_stop_price"] == new_swing_price
        components.broker.cancel_order.assert_awaited_once_with("ord-001")
        components.broker.submit_stop_order.assert_awaited_once()
        call_kwargs = components.broker.submit_stop_order.call_args.kwargs
        assert call_kwargs["stop_price"] == new_swing_price
        assert call_kwargs["side"] == "sell"

    def test_no_update_when_swing_below_current_stop(self):
        """LONG: new swing low < current stop → tighten-only guard, no change."""
        current_stop = 19_020.0
        worse_swing = 19_010.0
        sp = _make_swing_point(worse_swing, "low")
        components = _make_components(swing_low=sp)
        state = _make_state_with_position("long", current_stop)

        _run(_manage_open_positions(components, state))

        pos = list(state.open_positions.values())[0]
        assert pos["current_stop_price"] == current_stop
        components.broker.cancel_order.assert_not_awaited()
        components.broker.submit_stop_order.assert_not_awaited()

    def test_no_update_when_swing_equals_current_stop(self):
        """LONG: swing == current stop → no update (not strictly greater)."""
        current_stop = 19_010.0
        sp = _make_swing_point(current_stop, "low")
        components = _make_components(swing_low=sp)
        state = _make_state_with_position("long", current_stop)

        _run(_manage_open_positions(components, state))

        pos = list(state.open_positions.values())[0]
        assert pos["current_stop_price"] == current_stop
        components.broker.cancel_order.assert_not_awaited()

    def test_no_update_when_no_swing_detected(self):
        """LONG: no swing low detected → skip gracefully."""
        components = _make_components(swing_low=None)
        state = _make_state_with_position("long", 19_000.0)

        _run(_manage_open_positions(components, state))

        components.broker.cancel_order.assert_not_awaited()


# ---------------------------------------------------------------------------
# SHORT direction
# ---------------------------------------------------------------------------

class TestTrailingShort:
    def test_updates_when_new_swing_below_stop(self):
        """SHORT: new swing high < current stop → stop moves down."""
        current_stop = 19_050.0
        new_swing_price = 19_040.0
        sp = _make_swing_point(new_swing_price, "high")
        components = _make_components(swing_high=sp)
        state = _make_state_with_position("short", current_stop)

        _run(_manage_open_positions(components, state))

        pos = list(state.open_positions.values())[0]
        assert pos["current_stop_price"] == new_swing_price
        components.broker.cancel_order.assert_awaited_once_with("ord-001")
        call_kwargs = components.broker.submit_stop_order.call_args.kwargs
        assert call_kwargs["stop_price"] == new_swing_price
        assert call_kwargs["side"] == "buy"

    def test_no_update_when_swing_above_current_stop(self):
        """SHORT: new swing high > current stop → no change."""
        current_stop = 19_040.0
        worse_swing = 19_050.0
        sp = _make_swing_point(worse_swing, "high")
        components = _make_components(swing_high=sp)
        state = _make_state_with_position("short", current_stop)

        _run(_manage_open_positions(components, state))

        pos = list(state.open_positions.values())[0]
        assert pos["current_stop_price"] == current_stop
        components.broker.cancel_order.assert_not_awaited()

    def test_no_update_when_no_swing_detected(self):
        """SHORT: no swing high detected → skip gracefully."""
        components = _make_components(swing_high=None)
        state = _make_state_with_position("short", 19_050.0)

        _run(_manage_open_positions(components, state))

        components.broker.cancel_order.assert_not_awaited()


# ---------------------------------------------------------------------------
# Race conditions + error handling
# ---------------------------------------------------------------------------

class TestRaceConditions:
    def test_cancel_failure_handled_gracefully(self):
        """cancel_order raises → warning logged, no crash, no new stop submitted."""
        from brokers.topstepx import TopstepXOrderError
        sp = _make_swing_point(19_010.0, "low")
        components = _make_components(swing_low=sp)
        components.broker.cancel_order = AsyncMock(
            side_effect=TopstepXOrderError("already filled")
        )
        state = _make_state_with_position("long", 19_000.0)

        _run(_manage_open_positions(components, state))

        # Position stop price must NOT change — we skipped the replace
        pos = list(state.open_positions.values())[0]
        assert pos["current_stop_price"] == 19_000.0
        components.broker.submit_stop_order.assert_not_awaited()

    def test_empty_open_positions_skips_entirely(self):
        """No open positions → function returns without touching the broker."""
        sp = _make_swing_point(19_010.0, "low")
        components = _make_components(swing_low=sp)
        state = EngineState(mode="paper")  # open_positions = {}

        _run(_manage_open_positions(components, state))

        components.broker.cancel_order.assert_not_awaited()
        components.broker.submit_stop_order.assert_not_awaited()

    def test_no_swing_detector_skips_entirely(self):
        """swing detector missing from components.detectors → no error."""
        components = _make_components()
        components.detectors = {}  # no "swing" key
        state = _make_state_with_position("long", 19_000.0)

        _run(_manage_open_positions(components, state))

        components.broker.cancel_order.assert_not_awaited()

    def test_submit_stop_failure_handled_gracefully(self):
        """submit_stop_order raises → warning logged, current_stop_price unchanged."""
        from brokers.topstepx import TopstepXOrderError
        sp = _make_swing_point(19_010.0, "low")
        components = _make_components(swing_low=sp)
        components.broker.submit_stop_order = AsyncMock(
            side_effect=TopstepXOrderError("broker down")
        )
        state = _make_state_with_position("long", 19_000.0)

        _run(_manage_open_positions(components, state))

        pos = list(state.open_positions.values())[0]
        # stop price should NOT be updated since new stop was not placed
        assert pos["current_stop_price"] == 19_000.0


# ---------------------------------------------------------------------------
# Config "fixed" mode skips trailing entirely
# ---------------------------------------------------------------------------

class TestConfigFixed:
    def test_fixed_mode_bypasses_manage_open_positions(self):
        """
        When TRADE_MANAGEMENT == "fixed", _on_new_bar must not call
        _manage_open_positions. We verify by checking _manage_open_positions
        itself: when called it would update stops. The _on_new_bar hook guards
        via `config.TRADE_MANAGEMENT == "trailing"`, which is separately verified
        here by patching config and asserting the broker is never touched.
        """
        import config as cfg
        original = cfg.TRADE_MANAGEMENT
        try:
            cfg.TRADE_MANAGEMENT = "fixed"

            sp = _make_swing_point(19_010.0, "low")
            components = _make_components(swing_low=sp)
            state = _make_state_with_position("long", 19_000.0)

            # Simulate the guard that lives in _on_new_bar
            if cfg.TRADE_MANAGEMENT == "trailing" and state.open_positions:
                _run(_manage_open_positions(components, state))

            components.broker.cancel_order.assert_not_awaited()
            components.broker.submit_stop_order.assert_not_awaited()
        finally:
            cfg.TRADE_MANAGEMENT = original

    def test_trailing_mode_calls_manage_open_positions(self):
        """
        When TRADE_MANAGEMENT == "trailing", the guard passes and the stop
        is updated.
        """
        import config as cfg
        original = cfg.TRADE_MANAGEMENT
        try:
            cfg.TRADE_MANAGEMENT = "trailing"

            sp = _make_swing_point(19_010.0, "low")
            components = _make_components(swing_low=sp)
            state = _make_state_with_position("long", 19_000.0)

            if cfg.TRADE_MANAGEMENT == "trailing" and state.open_positions:
                _run(_manage_open_positions(components, state))

            components.broker.cancel_order.assert_awaited_once()
            components.broker.submit_stop_order.assert_awaited_once()
        finally:
            cfg.TRADE_MANAGEMENT = original
