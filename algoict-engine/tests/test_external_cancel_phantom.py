"""Bug fix (2026-06-05): a manually-cancelled pending limit left a phantom.

The user-hub order handler (`_on_order_update`) only processed fills (status=2),
so cancelling a resting entry by hand (status=3) never cleared it from
`state.open_positions`. The phantom occupied the single-position slot and
blocked new entries until a restart.

`_on_broker_cancel` now drops the matching UNFILLED entry (and only that),
distinguishing bot-initiated cancels (no alert) from external ones (alert).
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import main


def _pos(order_id, filled=False, direction="short", symbol="MNQ", entry=29922.5):
    return {
        "entry_order": SimpleNamespace(order_id=order_id),
        "stop_order": SimpleNamespace(order_id=order_id + 1),
        "target_order": None,
        "signal": SimpleNamespace(direction=direction, symbol=symbol, entry_price=entry),
        "entry_fill_confirmed": filled,
    }


def _state(positions):
    return SimpleNamespace(open_positions=dict(positions))


def test_external_cancel_clears_unfilled_phantom():
    state = _state({"386": _pos(386, filled=False)})
    comp = SimpleNamespace(telegram=None)
    asyncio.run(main._on_broker_cancel({"orderId": 386, "_self_initiated": False}, comp, state))
    assert state.open_positions == {}


def test_cancel_does_not_drop_filled_position():
    state = _state({"386": _pos(386, filled=True)})
    comp = SimpleNamespace(telegram=None)
    asyncio.run(main._on_broker_cancel({"orderId": 386, "_self_initiated": False}, comp, state))
    assert "386" in state.open_positions  # live position preserved


def test_cancel_of_unknown_order_is_noop():
    state = _state({"386": _pos(386, filled=False)})
    comp = SimpleNamespace(telegram=None)
    # 999 is e.g. a bracket stop leg or an already-removed key
    asyncio.run(main._on_broker_cancel({"orderId": 999}, comp, state))
    assert "386" in state.open_positions


def test_external_cancel_alerts_user():
    sent = []
    tg = MagicMock()
    async def _send(msg):  # noqa: E306
        sent.append(msg)
    tg.send_emergency_alert = _send
    state = _state({"386": _pos(386, filled=False)})
    comp = SimpleNamespace(telegram=tg)
    asyncio.run(main._on_broker_cancel({"orderId": 386, "_self_initiated": False}, comp, state))
    assert state.open_positions == {}
    assert len(sent) == 1 and "phantom cleared" in sent[0]


def test_self_initiated_cancel_clears_but_no_alert():
    sent = []
    tg = MagicMock()
    async def _send(msg):  # noqa: E306
        sent.append(msg)
    tg.send_emergency_alert = _send
    state = _state({"386": _pos(386, filled=False)})
    comp = SimpleNamespace(telegram=tg)
    asyncio.run(main._on_broker_cancel({"orderId": 386, "_self_initiated": True}, comp, state))
    assert state.open_positions == {}  # still cleared (race safety)
    assert sent == []                  # but no user-facing alert
