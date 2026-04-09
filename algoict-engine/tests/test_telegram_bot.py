"""
tests/test_telegram_bot.py
==========================
Tests for alerts/telegram_bot.py

Mocks the actual Telegram bot since we're offline.
"""

import pytest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alerts.telegram_bot import TelegramBot


class MockTelegramBot:
    def __init__(self, token):
        self.token = token
        self.messages = []

    def send_message(self, chat_id, text):
        self.messages.append({"chat_id": chat_id, "text": text})


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestTelegramBotConstructor:
    def test_raises_without_token(self):
        with pytest.raises((ValueError, ImportError)):
            TelegramBot(token="", chat_id="123")

    def test_raises_without_chat_id(self):
        with pytest.raises((ValueError, ImportError)):
            TelegramBot(token="abc", chat_id="")

    def test_raises_if_telegram_not_available(self):
        with patch("alerts.telegram_bot.TELEGRAM_AVAILABLE", False):
            with pytest.raises(ImportError, match="not installed"):
                TelegramBot(token="abc", chat_id="123")


# ---------------------------------------------------------------------------
# Trade Alerts
# ---------------------------------------------------------------------------

class TestSendTradeAlert:
    def test_send_entry_alert(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_trade_alert(
            symbol="MNQ",
            side="BUY",
            contracts=1,
            entry_price=19500.0,
        )

        assert result is True
        assert len(mock_bot.messages) == 1
        assert "ENTRY" in mock_bot.messages[0]["text"]
        assert "MNQ" in mock_bot.messages[0]["text"]

    def test_send_exit_alert_win(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_trade_alert(
            symbol="MNQ",
            side="SELL",
            contracts=2,
            entry_price=19500.0,
            exit_price=19510.0,
            pnl=100.0,
            confluence_score=15,
        )

        assert result is True
        assert "EXIT" in mock_bot.messages[0]["text"]
        assert "WIN" in mock_bot.messages[0]["text"]

    def test_send_exit_alert_loss(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_trade_alert(
            symbol="MNQ",
            side="BUY",
            contracts=1,
            entry_price=19500.0,
            exit_price=19490.0,
            pnl=-100.0,
        )

        assert result is True
        assert "LOSS" in mock_bot.messages[0]["text"]

    def test_send_trade_alert_error_handling(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MagicMock()
        mock_bot.send_message.side_effect = Exception("Connection error")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_trade_alert(
            symbol="MNQ",
            side="BUY",
            contracts=1,
            entry_price=19500.0,
        )

        assert result is False


# ---------------------------------------------------------------------------
# Kill Switch Alerts
# ---------------------------------------------------------------------------

class TestSendKillSwitchAlert:
    def test_send_kill_switch_alert(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_kill_switch_alert("3 consecutive losses")

        assert result is True
        assert "KILL SWITCH" in mock_bot.messages[0]["text"]
        assert "3 consecutive losses" in mock_bot.messages[0]["text"]

    def test_kill_switch_error_handling(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MagicMock()
        mock_bot.send_message.side_effect = Exception("Bot error")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_kill_switch_alert("Test reason")

        assert result is False


# ---------------------------------------------------------------------------
# Heartbeat Alerts
# ---------------------------------------------------------------------------

class TestSendHeartbeatAlert:
    def test_send_heartbeat_ok(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_heartbeat_alert("OK")

        assert result is True
        assert "OK" in mock_bot.messages[0]["text"]

    def test_send_heartbeat_offline(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_heartbeat_alert("OFFLINE", age_seconds=25.3)

        assert result is True
        assert "OFFLINE" in mock_bot.messages[0]["text"]

    def test_send_heartbeat_red_alert(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_heartbeat_alert("RED_ALERT", age_seconds=35.0)

        assert result is True
        assert "RED_ALERT" in mock_bot.messages[0]["text"]


# ---------------------------------------------------------------------------
# Daily Summaries
# ---------------------------------------------------------------------------

class TestSendDailySummary:
    def test_send_daily_summary_profit(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_daily_summary(
            date_str="2024-01-02",
            trades_count=5,
            wins=3,
            losses=2,
            total_pnl=1200.0,
            max_dd=0.05,
            sharpe=1.5,
            best_trade=500.0,
            worst_trade=-100.0,
        )

        assert result is True
        assert "2024-01-02" in mock_bot.messages[0]["text"]

    def test_send_daily_summary_loss(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_daily_summary(
            date_str="2024-01-02",
            trades_count=4,
            wins=1,
            losses=3,
            total_pnl=-1200.0,
            max_dd=0.10,
            sharpe=0.5,
        )

        assert result is True
        assert "NEGATIVE DAY" in mock_bot.messages[0]["text"]

    def test_send_daily_summary_error_handling(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MagicMock()
        mock_bot.send_message.side_effect = Exception("Send failed")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_daily_summary(
            date_str="2024-01-02",
            trades_count=5,
            wins=3,
            losses=2,
            total_pnl=750.0,
        )

        assert result is False


# ---------------------------------------------------------------------------
# VPIN Alerts
# ---------------------------------------------------------------------------

class TestSendVpinAlert:
    def test_send_vpin_calm(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_vpin_alert(vpin=0.20, toxicity_level="calm")

        assert result is True
        assert "CALM" in mock_bot.messages[0]["text"]

    def test_send_vpin_extreme(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_vpin_alert(vpin=0.80, toxicity_level="extreme")

        assert result is True
        assert "EXTREME" in mock_bot.messages[0]["text"]
        assert "flattened" in mock_bot.messages[0]["text"].lower()

    def test_send_vpin_high(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_vpin_alert(vpin=0.65, toxicity_level="high")

        assert result is True
        assert "HIGH" in mock_bot.messages[0]["text"]


# ---------------------------------------------------------------------------
# Emergency Alerts
# ---------------------------------------------------------------------------

class TestSendEmergencyAlert:
    def test_send_emergency_alert(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MockTelegramBot("token")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_emergency_alert("Connection to broker lost")

        assert result is True
        assert "EMERGENCY" in mock_bot.messages[0]["text"]
        assert "Connection to broker lost" in mock_bot.messages[0]["text"]

    def test_emergency_alert_error_handling(self):
        tb = TelegramBot.__new__(TelegramBot)
        mock_bot = MagicMock()
        mock_bot.send_message.side_effect = Exception("Send error")
        tb._bot = mock_bot
        tb._chat_id = "123"

        result = tb.send_emergency_alert("Test emergency")

        assert result is False
