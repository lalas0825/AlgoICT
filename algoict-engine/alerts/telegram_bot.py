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
    from telegram import Bot
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, MAX_CONFLUENCE

logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Telegram bot for sending trading alerts.

    All send methods are async (python-telegram-bot v20+).
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

    # ------------------------------------------------------------------ #
    # Factor labels for breakdown rendering
    # ------------------------------------------------------------------ #

    _FACTOR_LABELS: dict = {
        "liquidity_grab":        "Sweep",
        "fair_value_gap":        "FVG",
        "order_block":           "OB",
        "market_structure_shift":"Structure",
        "kill_zone":             "Kill Zone",
        "ote_fibonacci":         "OTE Fib",
        "htf_bias_aligned":      "HTF Bias",
        "htf_ob_fvg_alignment":  "HTF OB/FVG",
        "target_at_pdh_pdl":     "Target Level",
        "sentiment_alignment":   "SWC",
        "gex_wall_alignment":    "GEX Wall",
        "gamma_regime":          "GEX Regime",
        "vpin_validated_sweep":  "VPIN Sweep",
        "vpin_quality_session":  "VPIN Session",
    }

    # ------------------------------------------------------------------ #
    # Signal / Trade Alerts
    # ------------------------------------------------------------------ #

    async def send_signal_fired(
        self,
        signal,
        vpin_value: Optional[float] = None,
        vpin_zone: str = "unknown",
        swc_mood: Optional[str] = None,
        gex_status: str = "no data",
        htf_daily: str = "n/a",
        htf_weekly: str = "n/a",
        size_pct: float = 1.0,
    ) -> bool:
        """Send the rich SIGNAL FIRED alert when a setup is confirmed."""
        try:
            direction = signal.direction.upper()
            bd = signal.confluence_breakdown
            reasons = getattr(signal, "confluence_reasons", [])

            stop_pts  = abs(signal.entry_price - signal.stop_price)
            tgt_pts   = abs(signal.target_price - signal.entry_price)
            rr        = tgt_pts / stop_pts if stop_pts else 0.0
            risk_usd  = stop_pts * 2.0 * signal.contracts  # MNQ $2/pt

            stop_sign  = "-" if signal.direction == "long" else "+"
            tgt_sign   = "+" if signal.direction == "long" else "-"

            lines = [
                "🔔 SIGNAL FIRED",
                f"Strategy: {signal.strategy}",
                f"Kill Zone: {signal.kill_zone}",
                f"Direction: {direction}",
                f"Confluence: {signal.confluence_score}/{MAX_CONFLUENCE}",
                "",
                f"Entry:    ${signal.entry_price:,.2f}",
                f"Stop:     ${signal.stop_price:,.2f} ({stop_sign}{stop_pts:.2f} pts)",
                f"Target:   ${signal.target_price:,.2f} ({tgt_sign}{tgt_pts:.2f} pts, 1:{rr:.1f} RR)",
                f"Contracts: {signal.contracts}x {signal.symbol}",
                f"Risk:     ${risk_usd:,.0f}",
                "",
                "Breakdown:",
            ]

            # ICT scored factors — ✅ if in breakdown
            ict_factors = [
                ("liquidity_grab",        lambda: next((r for r in reasons if "sweep" in r), "swept")),
                ("fair_value_gap",        lambda: next((r for r in reasons if "FVG" in r), "entry inside FVG")),
                ("order_block",           lambda: next((r for r in reasons if "OB" in r), "entry inside OB")),
                ("market_structure_shift",lambda: next((r for r in reasons if any(t in r for t in ("MSS","CHoCH","BOS"))), "confirmed")),
                ("kill_zone",             lambda: signal.kill_zone),
                ("ote_fibonacci",         lambda: "61.8-78.6%"),
                ("htf_bias_aligned",      lambda: htf_daily),
                ("htf_ob_fvg_alignment",  lambda: "HTF overlap"),
                ("target_at_pdh_pdl",     lambda: "at key level"),
                ("sentiment_alignment",   lambda: swc_mood or "aligned"),
                ("gex_wall_alignment",    lambda: "GEX wall"),
                ("gamma_regime",          lambda: "regime aligned"),
                ("vpin_validated_sweep",  lambda: f"{vpin_value:.3f}" if vpin_value else ""),
                ("vpin_quality_session",  lambda: "quality session"),
            ]
            for key, detail_fn in ict_factors:
                if key in bd:
                    pts = bd[key]
                    label = self._FACTOR_LABELS.get(key, key)
                    detail = detail_fn()
                    lines.append(f"✅ {label}: {detail} (+{pts})")

            # Contextual (not scored) — always shown
            vpin_str = f"{vpin_value:.3f}" if vpin_value is not None else "N/A"
            lines.append(f"⬜ VPIN: {vpin_str} ({vpin_zone})")
            mood_str = swc_mood if swc_mood else "N/A"
            lines.append(f"⬜ SWC: {mood_str}")
            lines.append(f"⬜ GEX: {gex_status}")

            lines += [
                "",
                f"HTF: daily={htf_daily}, weekly={htf_weekly} ({size_pct:.0%} size)",
            ]

            msg = "\n".join(lines)
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Signal fired alert sent: %s %s score=%d", signal.strategy, direction, signal.confluence_score)
            return True

        except Exception as exc:
            logger.error("Failed to send signal fired alert: %s", exc)
            return False

    async def send_trade_opened(
        self,
        symbol: str,
        direction: str,
        contracts: int,
        fill_price: float,
    ) -> bool:
        """Send confirmation when entry order is filled."""
        try:
            side = "BUY" if direction == "long" else "SELL"
            msg = f"✅ TRADE OPENED: {side} {contracts}x {symbol} @ ${fill_price:,.2f}"
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Trade opened alert sent: %s %s %dx @ %.2f", symbol, side, contracts, fill_price)
            return True
        except Exception as exc:
            logger.error("Failed to send trade opened alert: %s", exc)
            return False

    async def send_trade_closed(
        self,
        symbol: str,
        pnl: float,
        reason: str,
        close_price: float,
    ) -> bool:
        """Send result when position closes (target hit or stop hit)."""
        try:
            is_win = pnl >= 0
            emoji = "✅" if is_win else "❌"
            outcome = "WIN" if is_win else "LOSS"
            label = "target hit" if reason == "target" else "stop hit"
            msg = f"{emoji} {outcome}: ${abs(pnl):+,.0f} ({label}) @ ${close_price:,.2f} | {symbol}"
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Trade closed alert sent: %s %s pnl=%.2f", symbol, outcome, pnl)
            return True
        except Exception as exc:
            logger.error("Failed to send trade closed alert: %s", exc)
            return False

    async def send_trade_alert(
        self,
        symbol: str,
        side: str,
        contracts: int,
        entry_price: float,
        exit_price: Optional[float] = None,
        pnl: Optional[float] = None,
        confluence_score: Optional[int] = None,
    ) -> bool:
        """Legacy trade alert — kept for backward compatibility with existing callers."""
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

            msg = f"{emoji} {status}\nSymbol: {symbol}\nSide: {side_upper} {contracts}x\n{price_line}\n"
            if pnl is not None:
                pnl_emoji = "📈" if pnl > 0 else "📉"
                msg += f"P&L: {pnl_emoji} ${pnl:+,.2f}\n"
            if confluence_score is not None:
                msg += f"Confluence: {confluence_score}/{MAX_CONFLUENCE}\n"

            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Trade alert sent: %s %s %s", symbol, side_upper, status)
            return True

        except Exception as exc:
            logger.error("Failed to send trade alert: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Kill Switch Alerts
    # ------------------------------------------------------------------ #

    async def send_kill_switch_alert(self, reason: str) -> bool:
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
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.warning("Kill switch alert sent: %s", reason)
            return True

        except Exception as exc:
            logger.error("Failed to send kill switch alert: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Heartbeat Alerts
    # ------------------------------------------------------------------ #

    async def send_heartbeat_alert(
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

            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Heartbeat alert sent: %s", status)
            return True

        except Exception as exc:
            logger.error("Failed to send heartbeat alert: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Daily Summaries
    # ------------------------------------------------------------------ #

    async def send_daily_summary(
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

            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Daily summary sent: %s | P&L: %.2f", date_str, total_pnl)
            return True

        except Exception as exc:
            logger.error("Failed to send daily summary: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # VPIN / Toxicity Alerts
    # ------------------------------------------------------------------ #

    async def send_vpin_alert(
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
            elif toxicity_level == "normalized":
                emoji = "✅"
            elif toxicity_level == "high":
                emoji = "⚠️"
            elif toxicity_level == "elevated":
                emoji = "🔔"
            else:
                emoji = "ℹ️"

            msg = f"""
{emoji} VPIN ALERT

Level: {toxicity_level.upper()}
Value: {vpin:.3f}
"""
            if toxicity_level == "extreme":
                msg += "\nAll positions flattened. Trading halted.\n"
            elif toxicity_level == "normalized":
                msg += "\nVPIN back below 0.70. Trading resumed.\n"
            elif toxicity_level == "high":
                msg += "\nPosition size reduced 25%. Tighter stops.\n"

            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("VPIN alert sent: %s (%.3f)", toxicity_level, vpin)
            return True

        except Exception as exc:
            logger.error("Failed to send VPIN alert: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Daily Mood (SWC pre-market)
    # ------------------------------------------------------------------ #

    async def send_daily_mood(
        self,
        date_str: str,
        mood: str,
        min_confluence: int,
        position_size_pct: float,
        summary: str,
    ) -> bool:
        """
        Send the SWC daily mood briefing (pre-market).

        Non-alert message — uses 📊 emoji and normal formatting.
        Sent once per trading day.

        Parameters
        ----------
        date_str : str — 'YYYY-MM-DD'
        mood : str — e.g. 'Choppy', 'Risk On', 'Risk Off'
        min_confluence : int — required confluence points (max is MAX_CONFLUENCE)
        position_size_pct : float — 0.0–1.0, rendered as percentage
        summary : str — one-line mood summary from SWC
        """
        try:
            msg = (
                f"📊 SWC DAILY MOOD — {date_str}\n"
                f"Mood: {mood}\n"
                f"Min confluence: {min_confluence}/{MAX_CONFLUENCE}\n"
                f"Position size: {position_size_pct:.0%}\n"
                f"{summary}"
            )
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Daily mood sent: %s", mood)
            return True
        except Exception as exc:
            logger.error("Failed to send daily mood: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Emergency Alerts
    # ------------------------------------------------------------------ #

    async def send_emergency_alert(self, message: str) -> bool:
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
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.critical("Emergency alert sent: %s", message)
            return True

        except Exception as exc:
            logger.error("Failed to send emergency alert: %s", exc)
            return False
