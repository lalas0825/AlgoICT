"""
tests/test_flatten_and_reconcile.py
====================================
Regression coverage for the meta-meta-audit fixes (2026-04-18):

  1. _flatten_all() synthesizes _on_trade_closed() for each open position
     so VPIN-extreme / hard-close / signalr-exhausted paths no longer leak
     realised P&L. Before the fix, broker.flatten_all() cleared the
     bracket-less but _on_broker_fill couldn't match the resulting
     market-order fills against the tracked stop_order.id / target_order.id,
     and P&L / MLL / Supabase / Telegram-exit all silently skipped the
     flattened positions.

  2. _reconcile_positions normalises TopstepX's "CON.F.US.MNQ.M26"
     contract-id form to the root symbol ("MNQ") on BOTH sides of the
     ghost/orphan set diff. Without normalisation every 5-min reconcile
     spammed WARNING alerts because the two sides never compared equal.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ENGINE_DIR))


# ─── Helpers ───────────────────────────────────────────────────────────────

def _make_signal(
    strategy: str = "ny_am_reversal",
    direction: str = "long",
    entry: float = 20000.00,
    stop: float = 19997.00,
    target: float = 20009.00,
    contracts: int = 2,
    kill_zone: str = "ny_am",
):
    """Build a Signal-like object with just the attributes _flatten_all reads."""
    import pandas as pd
    return SimpleNamespace(
        strategy=strategy,
        direction=direction,
        symbol="MNQ",
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        contracts=contracts,
        confluence_score=9,
        confluence_breakdown={"fair_value_gap": 2, "order_block": 2},
        kill_zone=kill_zone,
        timestamp=pd.Timestamp("2024-01-02 09:30", tz="US/Central"),
    )


def _make_components_and_state(open_positions_count: int = 1):
    """Minimal Components + EngineState wired enough for _flatten_all to run."""
    import pandas as pd
    import main as engine_main

    # Broker: flatten_all + cancel_order are awaitables, never raise.
    broker = SimpleNamespace(
        flatten_all=AsyncMock(return_value=None),
        cancel_order=AsyncMock(return_value=None),
    )

    # RiskManager stub — record_trade + emergency_flatten observed.
    risk = MagicMock()
    risk.record_trade = MagicMock()
    risk.emergency_flatten = MagicMock()

    # Supabase + Telegram are optional in _on_trade_closed — pass None so
    # we don't have to mock their full surface.
    supabase = None
    telegram = None
    post_mortem = None

    components = SimpleNamespace(
        broker=broker,
        risk=risk,
        supabase=supabase,
        telegram=telegram,
        post_mortem=post_mortem,
        ny_am_strategy=None,
        silver_bullet_strategy=None,
    )

    # State with `open_positions_count` fake open positions, each with a
    # (unique) stop_order and target_order so the pre-flatten cancel
    # loop has something to cancel.
    bars = pd.DataFrame(
        {
            "open":   [20005.00],
            "high":   [20010.00],
            "low":    [19995.00],
            "close":  [20008.00],     # exit-price proxy
            "volume": [100],
        },
        index=pd.date_range("2024-01-02 09:35", periods=1, freq="1min", tz="US/Central"),
    )
    state = engine_main.EngineState(mode="paper")
    state.bars_1min = bars

    for i in range(open_positions_count):
        signal = _make_signal(
            entry=20000.00 + i * 10,
            stop=19997.00 + i * 10,
            contracts=2,
            kill_zone="ny_am" if i % 2 == 0 else "london",
        )
        state.open_positions[f"pos_{i}"] = {
            "signal": signal,
            "stop_order": SimpleNamespace(order_id=f"stop_{i}"),
            "target_order": SimpleNamespace(order_id=f"target_{i}"),
            "current_stop_price": float(signal.stop_price),
            "opened_at": signal.timestamp,
        }

    return components, state


# ─── _flatten_all P&L synthesis ────────────────────────────────────────────

class TestFlattenPnLSynthesis:
    """Meta-audit Finding A: _flatten_all must emit _on_trade_closed for
    every open position so risk / Supabase / Telegram accounting doesn't
    silently skip VPIN-extreme and hard-close flattens."""

    @pytest.mark.asyncio
    async def test_flatten_records_pnl_for_every_position(self, monkeypatch):
        import main as engine_main
        components, state = _make_components_and_state(open_positions_count=3)

        # Capture every _on_trade_closed call.
        recorded: list[dict] = []
        async def _capture(comp, st, trade):
            recorded.append(trade)
        monkeypatch.setattr(engine_main, "_on_trade_closed", _capture)

        await engine_main._flatten_all(components, state, reason="vpin_extreme")

        # All three positions closed, state cleared.
        assert state.open_positions == {}
        assert len(recorded) == 3
        reasons = {r["reason"] for r in recorded}
        assert reasons == {"flatten:vpin_extreme"}

    @pytest.mark.asyncio
    async def test_flatten_cancels_brackets_before_broker_flatten(self, monkeypatch):
        """Pre-flatten cancellation prevents stop/target ghost fills that
        would otherwise trigger a mismatched _on_broker_fill later."""
        import main as engine_main
        components, state = _make_components_and_state(open_positions_count=2)
        monkeypatch.setattr(engine_main, "_on_trade_closed",
                            AsyncMock(return_value=None))

        await engine_main._flatten_all(components, state, reason="hard_close")

        # 2 positions × 2 bracket orders = 4 cancel calls.
        assert components.broker.cancel_order.await_count == 4
        # Then the single flatten.
        assert components.broker.flatten_all.await_count == 1

    @pytest.mark.asyncio
    async def test_flatten_long_pnl_uses_last_close_as_exit_proxy(self, monkeypatch):
        """Exit-price proxy = last 1-min close. Long PnL = (close - entry) *
        contracts * MNQ_POINT_VALUE."""
        import main as engine_main
        import config
        components, state = _make_components_and_state(open_positions_count=1)
        # One long @ entry=20000 with bars.close.iloc[-1]=20008 → +8 pts × 2 × $2 = $32.
        recorded: list[dict] = []
        async def _cap(comp, st, trade):
            recorded.append(trade)
        monkeypatch.setattr(engine_main, "_on_trade_closed", _cap)

        await engine_main._flatten_all(components, state, reason="hard_close")

        assert len(recorded) == 1
        trade = recorded[0]
        assert trade["direction"] == "long"
        assert trade["entry_price"] == 20000.00
        assert trade["exit_price"] == 20008.00
        assert trade["pnl"] == pytest.approx(8.0 * 2 * config.MNQ_POINT_VALUE)
        assert trade["exit_price_is_proxy"] is True
        assert trade["kill_zone"] == "ny_am"

    @pytest.mark.asyncio
    async def test_flatten_short_pnl_sign_correct(self, monkeypatch):
        import main as engine_main
        import config
        components, state = _make_components_and_state(open_positions_count=0)

        # Inject one SHORT position manually.
        sig_short = _make_signal(
            direction="short", entry=20010.00, stop=20013.00, target=20001.00,
            contracts=1, kill_zone="london",
        )
        state.open_positions["short_1"] = {
            "signal": sig_short,
            "stop_order": SimpleNamespace(order_id="s1"),
            "target_order": SimpleNamespace(order_id="t1"),
            "current_stop_price": float(sig_short.stop_price),
            "opened_at": sig_short.timestamp,
        }
        # bars.close = 20008 → short PnL = (20010 - 20008) × 1 × $2 = +$4.

        recorded: list[dict] = []
        async def _cap(comp, st, trade): recorded.append(trade)
        monkeypatch.setattr(engine_main, "_on_trade_closed", _cap)

        await engine_main._flatten_all(components, state, reason="hard_close")

        assert len(recorded) == 1
        assert recorded[0]["direction"] == "short"
        assert recorded[0]["pnl"] == pytest.approx(2.0 * 1 * config.MNQ_POINT_VALUE)

    @pytest.mark.asyncio
    async def test_emergency_flag_activates_kill_switch(self, monkeypatch):
        import main as engine_main
        components, state = _make_components_and_state(open_positions_count=1)
        monkeypatch.setattr(engine_main, "_on_trade_closed",
                            AsyncMock(return_value=None))

        await engine_main._flatten_all(
            components, state, reason="signalr_exhausted", emergency=True,
        )

        components.risk.emergency_flatten.assert_called_once()

    @pytest.mark.asyncio
    async def test_broker_flatten_failure_still_records_pnl(self, monkeypatch):
        """If broker.flatten_all raises, we still synthesize _on_trade_closed
        for the captured positions — better a proxy P&L record than zero."""
        import main as engine_main
        components, state = _make_components_and_state(open_positions_count=2)
        components.broker.flatten_all.side_effect = RuntimeError("broker down")
        recorded: list[dict] = []
        async def _cap(comp, st, trade): recorded.append(trade)
        monkeypatch.setattr(engine_main, "_on_trade_closed", _cap)

        # Must not raise.
        await engine_main._flatten_all(components, state, reason="hard_close")

        assert len(recorded) == 2
        assert state.open_positions == {}

    @pytest.mark.asyncio
    async def test_on_trade_closed_exception_does_not_abort_loop(self, monkeypatch):
        """If _on_trade_closed raises on position 1, positions 2+ must still
        get their trade rows written and state must still be cleared."""
        import main as engine_main
        components, state = _make_components_and_state(open_positions_count=3)

        calls = {"n": 0}
        async def _flaky(comp, st, trade):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("supabase transient")
        monkeypatch.setattr(engine_main, "_on_trade_closed", _flaky)

        await engine_main._flatten_all(components, state, reason="vpin_extreme")

        # All 3 positions attempted, state cleared regardless of the raise.
        assert calls["n"] == 3
        assert state.open_positions == {}


# ─── _reconcile_positions symbol normalization ─────────────────────────────

class TestReconcileSymbolNormalization:
    """Meta-audit Finding B: broker returns 'CON.F.US.MNQ.M26', local state
    tracks 'MNQ'. Both sides must normalize to the root before set-diff,
    otherwise every 5-min reconcile spams false GHOST/ORPHAN alerts."""

    @pytest.mark.asyncio
    async def test_matching_positions_produce_no_alert(self, caplog):
        import logging
        import main as engine_main
        components, state = _make_components_and_state(open_positions_count=1)
        # Broker reports the full TopstepX contract id.
        components.broker.get_positions = AsyncMock(return_value=[
            SimpleNamespace(symbol="CON.F.US.MNQ.M26", contracts=2),
        ])
        with caplog.at_level(logging.WARNING, logger="algoict.main"):
            await engine_main._reconcile_positions(components, state)
        warnings = [r for r in caplog.records if "reconcile" in r.message.lower()]
        assert warnings == [], f"false reconcile alert: {[w.message for w in warnings]}"

    @pytest.mark.asyncio
    async def test_ghost_detected_when_broker_has_extra_symbol(self, caplog):
        import logging
        import main as engine_main
        components, state = _make_components_and_state(open_positions_count=0)
        # Local: nothing. Broker: two full-format contracts.
        components.broker.get_positions = AsyncMock(return_value=[
            SimpleNamespace(symbol="CON.F.US.ES.M26", contracts=1),
        ])
        with caplog.at_level(logging.WARNING, logger="algoict.main"):
            await engine_main._reconcile_positions(components, state)
        ghosts = [r for r in caplog.records if "GHOST" in r.message]
        assert len(ghosts) == 1
        assert "ES" in ghosts[0].message  # ROOT symbol in the alert, not full id

    @pytest.mark.asyncio
    async def test_orphan_detected_when_local_has_extra_symbol(self, caplog):
        import logging
        import main as engine_main
        components, state = _make_components_and_state(open_positions_count=1)
        # Local: MNQ. Broker: empty (position already closed, we didn't notice).
        components.broker.get_positions = AsyncMock(return_value=[])
        with caplog.at_level(logging.WARNING, logger="algoict.main"):
            await engine_main._reconcile_positions(components, state)
        orphans = [r for r in caplog.records if "ORPHAN" in r.message]
        assert len(orphans) == 1
        assert "MNQ" in orphans[0].message

    @pytest.mark.asyncio
    async def test_both_forms_on_broker_still_normalise_to_root(self, caplog):
        """Some API replies mix 'MNQ' and 'CON.F.US.MNQ.M26' for the same
        underlying — both must collapse to the same root when normalised."""
        import logging
        import main as engine_main
        components, state = _make_components_and_state(open_positions_count=1)
        components.broker.get_positions = AsyncMock(return_value=[
            SimpleNamespace(symbol="MNQ", contracts=1),
            SimpleNamespace(symbol="CON.F.US.MNQ.M26", contracts=1),
        ])
        with caplog.at_level(logging.WARNING, logger="algoict.main"):
            await engine_main._reconcile_positions(components, state)
        alerts = [r for r in caplog.records if "reconcile" in r.message.lower()]
        assert alerts == [], "mixed-format broker reply caused false alerts"
