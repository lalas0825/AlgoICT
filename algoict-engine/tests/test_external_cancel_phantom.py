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
from unittest.mock import MagicMock, AsyncMock, patch

import main
import brokers.topstepx as tx


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


# --- race fix (2026-06-08): cancel_order must tag self BEFORE the API await,
#     else the status=3 user-hub event (handled during the await) reads the
#     cancel as external and fires a false "phantom cleared externally" alert.

def _broker():
    c = tx.TopstepXClient(username="u", api_key="k", account_id="123")
    c._account_id = "123"  # normally set during connect()/account selection
    return c


def test_cancel_order_pre_registers_self_tag_before_api():
    client = _broker()
    seen = {}
    def _post_side(path, body):  # sync side_effect runs at await-time
        seen["tagged_during_call"] = str(body["orderId"]) in client._self_cancelled_ids
        return {"success": True}
    with patch.object(client, "_post", new=AsyncMock(side_effect=_post_side)):
        ok = asyncio.run(client.cancel_order("3089072228"))
    assert ok is True
    # the id was already tagged self when the cancel API was hit (race-safe)
    assert seen["tagged_during_call"] is True


def test_cancel_order_drops_tag_on_rejection():
    client = _broker()
    with patch.object(client, "_post", new=AsyncMock(
            return_value={"success": False, "errorCode": 1, "errorMessage": "not found"})):
        ok = asyncio.run(client.cancel_order("999"))
    assert ok is False
    assert "999" not in client._self_cancelled_ids  # optimistic tag dropped
