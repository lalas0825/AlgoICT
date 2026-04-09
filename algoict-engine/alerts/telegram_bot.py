"""
alerts/telegram_bot.py
======================
Telegram bot for trading alerts.

Sends real-time alerts for:
    - Trade entries/exits (wins/losses)
    - Kill switch activations
    - Heartbeat status
    - Daily summaries

Emojis:
    ✅ = Win / OK
    ❌ = Loss / Error
    🚨 = Critical alert
    📊 = Summary stats
    ⚠️  = Warning / Caution
    🔔 = Notification
    💰 = Money/PnL
    📈 = Up/Profit
    📉 = Down/Loss

Usage:
    from alerts.telegram_bot import TelegramBot

    bot = TelegramBot()
    await bot.send_trade_alert(trade_result)
    await bot.send_kill_switch_alert("3 consecutive losses")
    await bot.send_daily_summary({"trades": 5, "pnl": 1200, ...})
"""

import logging
from typing import Optional

try:
    import telegram
    from telegram import Bot
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Telegram bot for sending trading alerts.

    All send methods are synchronous. For async usage, wrap in executor.
    """

    def __init__(
        self,
        token: str = TELEGRAM_BOT_TOKEN,
        chat_id: str = TELEGRAM_CHAT_ID,
    ):
        if not TELEGRAM_AVAILABLE:
            raise ImportError(
                "python-telegram-bot package not installed. "
                "Run: pip install python-telegram-bot"
            )

        if not token or not chat_id:
            raise ValueError(
                "Telegram credentials missing. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
            )

        self._token = token
        self._chat_id = chat_id
        self._bot = Bot(token=token)
        logger.info("TelegramBot initialized (chat_id: %s)", chat_id)

    # ------------------------------------------------------------------ #
    # Trade Alerts
    # ------------------------------------------------------------------ #

    def send_trade_alert(
        self,
        symbol: str,
        side: str,
        contracts: int,
        entry_price: float,
        exit_price: Optional[float] = None,
        pnl: Optional[float] = None,
        confluence_score: Optional[int] = None,
    ) -> bool:
        """
        Send a trade entry or exit alert.

        If exit_price is None, it's an entry alert. Otherwise, it's an exit.

        Parameters
        ----------
        symbol   : e.g. "MNQ", "TSLA"
        side     : "BUY" or "SELL"
        contracts: number of contracts
        entry_price: entry price
        exit_price: exit price (None for entry)
        pnl: profit/loss (None for entry)
        confluence_score: 0-20 confluence

        Returns True on success.
        """
        try:
            side_upper = side.upper()
            is_entry = exit_price is None

            if is_entry:
                emoji = "🔔"
                status = "ENTRY"
                price_line = f"Entry: ${entry_price:.2f}"
            else:
                is_win = pnl is not None and pnl > 0
                emoji = "✅" if is_win else "❌"
                status = "EXIT (WIN)" if is_win else "EXIT (LOSS)"
                price_line = f"Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f}"

            msg = f"""
{emoji} {status}

Symbol: {symbol}
Side: {side_upper} {contracts}x
{price_line}
"""
            if pnl is not None:
                pnl_emoji = "📈" if pnl > 0 else "📉"
                msg += f"P&L: {pnl_emoji} ${pnl:+,.2f}\n"

            if confluence_score is not None:
                msg += f"Confluence: {confluence_score}/20\n"

            self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Trade alert sent: %s %s %s", symbol, side_upper, status)
            return True

        except Exception as exc:
            logger.error("Failed to send trade alert: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Kill Switch Alerts
    # ------------------------------------------------------------------ #

    def send_kill_switch_alert(self, reason: str) -> bool:
        """
        Send a critical kill switch activation alert.

        Parameters
        ----------
        reason : str
            Why the kill switch was triggered
            (e.g. "3 consecutive losses", "Daily loss limit $1000")

        Returns True on success.
        """
        try:
            msg = f"""
🚨 KILL SWITCH ACTIVATED 🚨

Reason: {reason}

Trading HALTED for remainder of day.
"""
            self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.warning("Kill switch alert sent: %s", reason)
            return True

        except Exception as exc:
            logger.error("Failed to send kill switch alert: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Heartbeat Alerts
    # ------------------------------------------------------------------ #

    def send_heartbeat_alert(
        self,
        status: str,
        age_seconds: Optional[float] = None,
    ) -> bool:
        """
        Send a heartbeat status alert.

        Parameters
        ----------
        status : "OK", "OFFLINE", "RED_ALERT"
        age_seconds : how old the last heartbeat is

        Returns True on success.
        """
        try:
            if status == "OK":
                emoji = "✅"
            elif status == "OFFLINE":
                emoji = "⚠️"
            else:  # RED_ALERT
                emoji = "🚨"

            msg = f"{emoji} Heartbeat: {status}\n"
            if age_seconds is not None:
                msg += f"Age: {age_seconds:.1f}s\n"

            self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Heartbeat alert sent: %s", status)
            return True

        except Exception as exc:
            logger.error("Failed to send heartbeat alert: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Daily Summaries
    # ------------------------------------------------------------------ #

    def send_daily_summary(
        self,
        date_str: str,
        trades_count: int,
        wins: int,
        losses: int,
        total_pnl: float,
        max_dd: float = 0.0,
        sharpe: float = 0.0,
        best_trade: Optional[float] = None,
        worst_trade: Optional[float] = None,
    ) -> bool:
        """
        Send an end-of-day summary.

        Parameters
        ----------
        date_str : "2024-01-02"
        trades_count: total trades
        wins, losses: counts
        total_pnl: net P&L
        max_dd: max drawdown %
        sharpe: Sharpe ratio
        best_trade, worst_trade: best/worst PnL

        Returns True on success.
        """
        try:
            win_rate = (wins / trades_count * 100) if trades_count > 0 else 0.0
            pnl_emoji = "📈" if total_pnl > 0 else "📉"

            msg = f"""
📊 DAILY SUMMARY — {date_str}

Trades: {trades_count}
Wins: {wins} | Losses: {losses}
Win Rate: {win_rate:.1f}%

P&L: {pnl_emoji} ${total_pnl:+,.2f}
Max DD: {max_dd:.1f}%
Sharpe: {sharpe:.2f}
"""
            if best_trade is not None:
                msg += f"Best Trade: ${best_trade:,.2f}\n"
            if worst_trade is not None:
                msg += f"Worst Trade: ${worst_trade:,.2f}\n"

            if total_pnl < -1000:
                msg += "\n⚠️ NEGATIVE DAY — Monitor closely\n"

            self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Daily summary sent: %s | P&L: %.2f", date_str, total_pnl)
            return True

        except Exception as exc:
            logger.error("Failed to send daily summary: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # VPIN / Toxicity Alerts
    # ------------------------------------------------------------------ #

    def send_vpin_alert(
        self,
        vpin: float,
        toxicity_level: str,
    ) -> bool:
        """
        Send a VPIN toxicity alert.

        Parameters
        ----------
        vpin : float (0.0-1.0)
        toxicity_level : "calm", "normal", "elevated", "high", "extreme"

        Returns True on success.
        """
        try:
            if toxicity_level == "extreme":
                emoji = "🚨"
            elif toxicity_level == "high":
                emoji = "⚠️"
            elif toxicity_level == "elevated":
                emoji = "🔔"
            else:
                emoji = "✅"

            msg = f"""
{emoji} VPIN ALERT

Level: {toxicity_level.upper()}
Value: {vpin:.3f}
"""
            if toxicity_level == "extreme":
                msg += "\nAll positions flattened. Trading halted.\n"
            elif toxicity_level == "high":
                msg += "\nPosition size reduced 25%. Tighter stops.\n"

            self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("VPIN alert sent: %s (%.3f)", toxicity_level, vpin)
            return True

        except Exception as exc:
            logger.error("Failed to send VPIN alert: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Emergency Alerts
    # ------------------------------------------------------------------ #

    def send_emergency_alert(self, message: str) -> bool:
        """
        Send a critical emergency alert.

        Parameters
        ----------
        message : str
            Custom emergency message

        Returns True on success.
        """
        try:
            msg = f"""
🚨🚨🚨 EMERGENCY ALERT 🚨🚨🚨

{message}

Immediate action required!
"""
            self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.critical("Emergency alert sent: %s", message)
            return True

        except Exception as exc:
            logger.error("Failed to send emergency alert: %s", exc)
            return False
