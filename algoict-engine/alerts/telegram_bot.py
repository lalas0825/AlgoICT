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

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, MAX_CONFLUENCE, MNQ_POINT_VALUE,
    SB_APPLICABLE_FACTORS, SB_APPLICABLE_MAX,
    TELEGRAM_VERBOSITY, TELEGRAM_THROTTLE_SEC,
)
import time as _time_mod

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
        # Throttling state: {(alert_type, bucket_key): last_sent_epoch}.
        # Callers pass bucket_key to differentiate within the same alert_type
        # (e.g. (kz, reject_reason) so NY AM's reject alerts don't throttle
        # London's). See config.TELEGRAM_THROTTLE_SEC for the per-type floors.
        self._last_alert_ts: dict[tuple, float] = {}
        self._verbosity = TELEGRAM_VERBOSITY
        logger.info(
            "TelegramBot initialized (chat_id: %s, verbosity=%s)",
            chat_id, self._verbosity,
        )

    # ------------------------------------------------------------------ #
    # Throttling / verbosity helpers
    # ------------------------------------------------------------------ #

    def _should_send(
        self,
        alert_type: str,
        bucket_key: tuple = (),
        min_verbosity: str = "normal",
    ) -> bool:
        """
        Gate + throttle an alert call. Returns True if allowed (and updates
        the throttle clock); False if suppressed.

        Parameters
        ----------
        alert_type : str — key into config.TELEGRAM_THROTTLE_SEC (e.g. "sweep")
        bucket_key : tuple — extra discriminators so similar alerts don't
                     collide (e.g. (kz, reason) for near-miss rejects).
        min_verbosity : "quiet" | "normal" | "verbose" — minimum verbosity
                     level at which this alert type is permitted to send.
        """
        levels = {"quiet": 0, "normal": 1, "verbose": 2}
        if levels.get(self._verbosity, 1) < levels.get(min_verbosity, 1):
            return False

        throttle_s = TELEGRAM_THROTTLE_SEC.get(alert_type, 0)
        if throttle_s <= 0:
            return True

        now = _time_mod.time()
        key = (alert_type,) + tuple(bucket_key)
        last = self._last_alert_ts.get(key, 0.0)
        if now - last < throttle_s:
            return False
        self._last_alert_ts[key] = now
        return True

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
            risk_usd  = stop_pts * MNQ_POINT_VALUE * signal.contracts

            stop_sign  = "-" if signal.direction == "long" else "+"
            tgt_sign   = "+" if signal.direction == "long" else "-"

            # For Silver Bullet, also compute + show the SB-applicable
            # sub-score (out of 10) so the number is interpretable on the
            # SB-specific scale — the full /19 is kept for historical
            # comparability (Option B — see SILVER_BULLET_STRATEGY_GUIDE §8).
            conf_line = f"Confluence: {signal.confluence_score}/{MAX_CONFLUENCE}"
            if signal.strategy == "silver_bullet":
                sb_sub = sum(
                    pts for key, pts in (signal.confluence_breakdown or {}).items()
                    if key in SB_APPLICABLE_FACTORS
                )
                conf_line += f" (SB: {sb_sub}/{SB_APPLICABLE_MAX})"

            lines = [
                "🔔 SIGNAL FIRED",
                f"Strategy: {signal.strategy}",
                f"Kill Zone: {signal.kill_zone}",
                f"Direction: {direction}",
                conf_line,
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

    async def send_trailing_stop_update(
        self,
        symbol: str,
        direction: str,
        old_stop: float,
        new_stop: float,
    ) -> bool:
        """Notify when trailing stop tightens by a meaningful amount."""
        try:
            delta = new_stop - old_stop if direction == "long" else old_stop - new_stop
            sign = "+" if delta >= 0 else ""
            msg = (
                f"TRAIL: {symbol} {direction.upper()} stop "
                f"{old_stop:.2f} → {new_stop:.2f} ({sign}{delta:.1f}pts)"
            )
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Trailing stop alert sent: %s %.2f → %.2f", symbol, old_stop, new_stop)
            return True
        except Exception as exc:
            logger.error("Failed to send trailing stop alert: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Verbose "what the bot sees" alerts (kill-zone context, sweeps,
    # near-miss rejections, MSS events). All are verbosity + throttle-
    # gated via self._should_send().
    # ------------------------------------------------------------------ #

    async def send_kz_enter(
        self,
        kz: str,
        ts_str: str,
        daily_bias: str = "n/a",
        weekly_bias: str = "n/a",
        tracked_levels: Optional[list] = None,
        vpin: Optional[float] = None,
        vpin_zone: str = "n/a",
        swc_mood: Optional[str] = None,
    ) -> bool:
        """
        Announce the bot entering a fresh kill zone.

        Shows the context the bot will use to judge setups: HTF bias, which
        key levels are still unswept (potential targets), VPIN state, SWC
        mood. One alert per KZ transition.
        """
        if not self._should_send("kz_enter", (kz,), min_verbosity="normal"):
            return False
        try:
            lines = [
                f"KZ ARMED — {kz.upper()} at {ts_str}",
                f"Bias:     daily={daily_bias} weekly={weekly_bias}",
            ]
            if tracked_levels:
                # Group active (unswept) vs swept
                active = [l for l in tracked_levels if not getattr(l, "swept", False)]
                swept = [l for l in tracked_levels if getattr(l, "swept", False)]
                # Show max 6 active levels to keep message compact
                for l in active[:6]:
                    lines.append(
                        f"  - {getattr(l, 'type', '?')} @ "
                        f"{getattr(l, 'price', 0):.2f} (active)"
                    )
                if len(active) > 6:
                    lines.append(f"  ... (+{len(active) - 6} more active)")
                if swept:
                    lines.append(f"Swept this day: {len(swept)} level(s)")
            if vpin is not None:
                lines.append(f"VPIN:     {vpin:.3f} ({vpin_zone})")
            if swc_mood:
                lines.append(f"SWC mood: {swc_mood}")
            msg = "\n".join(lines)
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("KZ enter alert sent: %s", kz)
            return True
        except Exception as exc:
            logger.debug("Failed to send KZ enter alert: %s", exc)
            return False

    async def send_kz_summary(
        self,
        kz: str,
        ts_str: str,
        stats: dict,
    ) -> bool:
        """
        Summarize everything that happened inside a kill zone after it closed.

        Parameters
        ----------
        kz : str — kill zone name that just closed
        ts_str : str — human-friendly timestamp for the close
        stats : dict — aggregate counters, expected keys:
            fvgs_seen      : int  — new FVGs formed inside this KZ
            sweeps         : int  — liquidity levels swept inside this KZ
            evaluations    : int  — bars where strategy.evaluate() was called
            rejections     : int  — evaluate() calls that returned None
            reject_reasons : dict[str, int]  — counts by reason
            signals_fired  : int  — signals that passed all gates
            trades_taken   : int  — trades actually executed
            pnl            : float — realized PnL inside this KZ (if known)
        """
        if not self._should_send("kz_summary", (kz,), min_verbosity="normal"):
            return False
        try:
            lines = [
                f"KZ CLOSED — {kz.upper()} at {ts_str}",
                f"Evaluations: {stats.get('evaluations', 0)}",
                f"FVGs seen:   {stats.get('fvgs_seen', 0)}",
                f"Sweeps:      {stats.get('sweeps', 0)}",
                f"Signals fired: {stats.get('signals_fired', 0)}",
                f"Trades taken: {stats.get('trades_taken', 0)}",
            ]
            pnl = stats.get("pnl")
            if pnl is not None:
                sign = "+" if pnl >= 0 else ""
                lines.append(f"Realized P&L: {sign}${pnl:,.2f}")
            reasons = stats.get("reject_reasons") or {}
            if reasons:
                lines.append("")
                lines.append("Top reject reasons:")
                # Show top 4 reasons
                ordered = sorted(reasons.items(), key=lambda x: -x[1])[:4]
                for r, n in ordered:
                    lines.append(f"  - {r}: {n}x")
            msg = "\n".join(lines)
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("KZ summary alert sent: %s", kz)
            return True
        except Exception as exc:
            logger.debug("Failed to send KZ summary: %s", exc)
            return False

    async def send_sweep_detected(
        self,
        level_type: str,
        price: float,
        kz: str,
        candle_high: float,
        candle_low: float,
        candle_close: float,
        ts_str: str = "",
    ) -> bool:
        """
        Announce a liquidity sweep — a key level got taken (wick-through,
        close-back). This is what the bot waits for before looking for a
        direction-matching FVG to enter on.
        """
        # The sweep itself only fires once per level (level.swept flips to
        # True), so no secondary throttle needed. But we still gate on
        # verbosity so "quiet" users don't get these.
        if not self._should_send("sweep", (level_type, round(price, 2)),
                                 min_verbosity="normal"):
            return False
        try:
            # Which side did the sweep clean? BSL-ish types: wick above + close below.
            bsl_types = {"BSL", "PDH", "PWH", "equal_highs"}
            if level_type in bsl_types:
                direction = "UP-wick (sell-side)"
                implication = "watch for 5m MSS bearish + 1m bearish FVG"
            else:
                direction = "DOWN-wick (buy-side)"
                implication = "watch for 5m MSS bullish + 1m bullish FVG"

            msg = (
                f"LIQUIDITY SWEPT — {kz.upper()} {ts_str}\n"
                f"Level:   {level_type} @ {price:.2f}\n"
                f"Candle:  H={candle_high:.2f} L={candle_low:.2f} "
                f"C={candle_close:.2f}\n"
                f"Type:    {direction}\n"
                f"Watch:   {implication}"
            )
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Sweep alert sent: %s @ %.2f", level_type, price)
            return True
        except Exception as exc:
            logger.debug("Failed to send sweep alert: %s", exc)
            return False

    async def send_signal_near_miss(
        self,
        strategy: str,
        kz: str,
        ts_str: str,
        reason: str,
        details: Optional[dict] = None,
    ) -> bool:
        """
        Announce a rejected signal that was structurally close to firing.

        Only sent for rejects that are "interesting" — setups that had most
        gates passed but failed one specific check (e.g. framework 8pts vs
        10pt minimum). Not sent for routine rejects (outside_kz, max_trades,
        past_cancel_time).

        Throttled to 1 alert per (kz, reason) every 5 min — otherwise a
        rejected setup would fire every minute for 10 minutes straight.
        """
        if not self._should_send("near_miss", (kz, reason),
                                 min_verbosity="verbose"):
            return False
        try:
            lines = [
                f"NEAR-MISS — {strategy} rejected in {kz.upper()} at {ts_str}",
                f"Reason: {reason}",
            ]
            if details:
                for k, v in details.items():
                    lines.append(f"  {k}: {v}")
            msg = "\n".join(lines)
            await self._bot.send_message(chat_id=self._chat_id, text=msg)
            logger.info("Near-miss alert sent: %s/%s", kz, reason)
            return True
        except Exception as exc:
            logger.debug("Failed to send near-miss alert: %s", exc)
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
        toxicity_level : "calm", "normal", "elevated", "high", "extreme",
            "normalized"

        Returns True on success.

        2026-04-24 Bug H4: respect TELEGRAM_VERBOSITY. Previously ALL
        VPIN transitions fired an alert regardless of verbosity, so
        `quiet` mode still got 5-10 VPIN chatter alerts/day. Now:
          - extreme  → always fires (critical, bypasses verbosity)
          - normalized → always fires (recovery from halt)
          - high / elevated → normal verbosity + (kz, level) throttle
          - calm / normal → verbose only
        """
        # Critical levels bypass verbosity + throttle.
        critical = toxicity_level in ("extreme", "normalized")
        if not critical:
            if toxicity_level in ("high", "elevated"):
                if not self._should_send("vpin", (toxicity_level,), min_verbosity="normal"):
                    return False
            else:
                # calm / normal — only verbose users want these.
                if not self._should_send("vpin", (toxicity_level,), min_verbosity="verbose"):
                    return False

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
