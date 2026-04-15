"""
core/heartbeat.py
=================
Periodic heartbeat writer to Supabase.

The heartbeat function writes a timestamp every HEARTBEAT_INTERVAL_S seconds
to the bot_state table. If any write fails, emergency_flatten() is triggered.

Usage (async):
    from core.heartbeat import start_heartbeat

    task = asyncio.create_task(start_heartbeat(supabase_client, risk_manager))
    # ... runs until cancelled
    await task
"""

import asyncio
import logging
from datetime import datetime, timezone

from config import (
    HEARTBEAT_INTERVAL_S,
    HEARTBEAT_OFFLINE_S,
    HEARTBEAT_ALERT_S,
)

logger = logging.getLogger(__name__)


async def start_heartbeat(
    supabase_client,
    risk_manager,
) -> None:
    """
    Periodically write heartbeat to Supabase bot_state.last_heartbeat.

    If a write fails (Supabase down, network error, etc.),
    triggers risk_manager.emergency_flatten().

    This coroutine runs forever until cancelled.

    Parameters
    ----------
    supabase_client : db.supabase_client.SupabaseClient
        Client with update_bot_state() method
    risk_manager : risk.risk_manager.RiskManager
        Risk manager with emergency_flatten() method
    """
    consecutive_failures = 0
    max_consecutive_failures = 3

    while True:
        try:
            ts_utc = datetime.now(timezone.utc).isoformat()
            await asyncio.to_thread(
                supabase_client.update_bot_state, {"last_heartbeat": ts_utc}
            )
            consecutive_failures = 0
            logger.debug("Heartbeat written at %s", ts_utc)

        except Exception as exc:
            consecutive_failures += 1
            logger.error("Heartbeat write failed (%d/%d): %s",
                         consecutive_failures, max_consecutive_failures, exc)

            if consecutive_failures >= max_consecutive_failures:
                logger.critical("Heartbeat FAILED %d times. EMERGENCY FLATTEN.",
                                consecutive_failures)
                try:
                    await risk_manager.emergency_flatten(
                        reason=f"Heartbeat failure: {exc}"
                    )
                except Exception as flatten_exc:
                    logger.exception("Emergency flatten failed: %s", flatten_exc)
                # After flatten, pause before retrying to avoid spam
                consecutive_failures = 0

        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


async def monitor_heartbeat(
    supabase_client,
    risk_manager,
    alert_sender,
) -> None:
    """
    Monitor heartbeat staleness in a separate task.

    Periodically checks last_heartbeat timestamp and sends alerts
    if it's older than HEARTBEAT_OFFLINE_S or HEARTBEAT_ALERT_S.

    Parameters
    ----------
    supabase_client : db.supabase_client.SupabaseClient
    risk_manager   : risk.risk_manager.RiskManager
    alert_sender   : alerts.telegram_bot.TelegramBot
    """
    last_alert_ts = None

    while True:
        try:
            state = await asyncio.to_thread(supabase_client.get_bot_state)
            if not state or "last_heartbeat" not in state:
                await asyncio.sleep(5)
                continue

            last_hb = state["last_heartbeat"]
            if isinstance(last_hb, str):
                from dateutil import parser
                last_hb_ts = parser.isoparse(last_hb)
            else:
                last_hb_ts = last_hb

            now = datetime.now(timezone.utc)
            if last_hb_ts.tzinfo is None:
                last_hb_ts = last_hb_ts.replace(tzinfo=timezone.utc)

            age_s = (now - last_hb_ts).total_seconds()

            # OFFLINE alert (>15s since last heartbeat)
            if age_s > HEARTBEAT_OFFLINE_S:
                logger.warning("Heartbeat OFFLINE (%.1fs old)", age_s)
                if last_alert_ts is None or (now - last_alert_ts).total_seconds() > 60:
                    await alert_sender.send_heartbeat_alert("OFFLINE", age_s)
                    last_alert_ts = now

            # RED ALERT (>30s since last heartbeat) — flatten
            elif age_s > HEARTBEAT_ALERT_S:
                logger.critical("Heartbeat RED ALERT (%.1fs old). FLATTENING.", age_s)
                try:
                    await risk_manager.emergency_flatten(
                        reason=f"Heartbeat RED ALERT: {age_s:.1f}s old"
                    )
                except Exception as exc:
                    logger.exception("Emergency flatten failed: %s", exc)

        except Exception as exc:
            logger.error("Heartbeat monitor error: %s", exc)

        await asyncio.sleep(5)  # Check every 5 seconds
