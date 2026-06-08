"""results-only Telegram verbosity (2026-06-08): suppress per-trade execution
noise (entries/exits/fires/trails/KZ/sweeps), keep daily summary + risk/
emergency alerts. The antidote for screen-watching."""
import asyncio
from unittest.mock import AsyncMock

import alerts.telegram_bot as tb


def _bot(verbosity):
    bot = object.__new__(tb.TelegramBot)  # bypass __init__ (no real connection)
    bot._verbosity = verbosity
    bot._last_alert_ts = {}
    bot._send_message = AsyncMock(return_value=True)
    return bot


def test_results_mode_suppresses_per_trade_noise():
    bot = _bot("results")
    assert asyncio.run(bot.send_trade_opened("MNQ", "long", 2, 29000.0)) is False
    assert asyncio.run(bot.send_trade_closed("MNQ", 100.0, "target", 29050.0)) is False
    assert asyncio.run(bot.send_trade_alert("MNQ", "buy", 2, 29000.0)) is False
    assert asyncio.run(bot.send_trailing_stop_update("MNQ", "long", 28990.0, 29010.0)) is False
    bot._send_message.assert_not_called()  # nothing went out


def test_results_mode_keeps_risk_alerts():
    bot = _bot("results")
    assert asyncio.run(bot.send_kill_switch_alert("daily loss")) is True
    assert asyncio.run(bot.send_heartbeat_alert("OFFLINE", 99.0)) is True
    assert bot._send_message.call_count == 2  # both fired despite results mode


def test_normal_mode_unchanged():
    bot = _bot("normal")
    assert asyncio.run(bot.send_trade_opened("MNQ", "long", 2, 29000.0)) is True
    bot._send_message.assert_called_once()


def test_should_send_results_level():
    bot = _bot("results")
    # normal-gated noise (kz_enter, sweeps) is suppressed in results
    assert bot._should_send("kz_enter", ("london",), min_verbosity="normal") is False
    # a results-level alert passes
    assert bot._should_send("anything", (), min_verbosity="results") is True
