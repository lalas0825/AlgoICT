"""
core/state_sync.py
==================
Full bot_state synchronization loop.

Why this exists alongside core/heartbeat.py
-------------------------------------------
``core/heartbeat.py`` only writes ``last_heartbeat`` (timestamp) and
triggers emergency flatten on failure — its job is liveness detection.

``state_sync.py`` writes the FULL bot_state payload every N seconds:
VPIN, P&L, position count, SWC mood, GEX regime, shield status, etc.
This is what keeps the dashboard's PnLCard, VPINGauge, SentimentCard,
GammaRegimeIndicator, and RiskGauge up to date.

They can coexist: heartbeat runs at 5s, state_sync at 5s, and the row
gets updated in place. Or you can run state_sync alone and drop the
older heartbeat loop — state_sync also writes last_heartbeat, so the
dashboard's staleness detection works either way.

Usage
-----
    from core.state_sync import BotStateSync
    from db.supabase_lab_client import get_lab_client

    client = get_lab_client()
    if client is None:
        # Engine runs without live state publishing
        return

    def current_state() -> dict:
        return {
            "is_running": True,
            "vpin": vpin_engine.current(),
            "toxicity_level": vpin_engine.label(),
            "pnl_today": risk_manager.pnl_today,
            "position_count": len(broker.open_positions),
            # ...
        }

    sync = BotStateSync(client, current_state, interval_s=5.0)
    task = asyncio.create_task(sync.start())

    # At shutdown:
    await sync.stop()
    await task
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Union

logger = logging.getLogger(__name__)


# Type for state provider — either sync or async, both accepted
StateProvider = Callable[[], Union[dict, Awaitable[dict]]]


DEFAULT_INTERVAL_S = 5.0
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5


class BotStateSync:
    """
    Periodic full bot_state writer.

    Parameters
    ----------
    client : SupabaseLabClient
        Must have an ``upsert_bot_state(dict) -> bool`` method.
    state_provider : callable
        Returns the current state dict. Can be sync or async. Called
        once per interval. Returning an empty dict is fine — the loop
        still writes the heartbeat timestamp.
    interval_s : float
        Seconds between writes. Default 5s.
    max_consecutive_failures : int
        After this many consecutive failed writes, the loop sleeps
        longer (10x interval) and resumes — this prevents hot-looping
        during a Supabase outage while still recovering automatically.
    on_failure : callable, optional
        Called with the exception and consecutive count on each failure.
        Use for alerts / Telegram pings. Sync or async both accepted.
    """

    def __init__(
        self,
        client: Any,
        state_provider: StateProvider,
        interval_s: float = DEFAULT_INTERVAL_S,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        on_failure: Optional[Callable] = None,
    ):
        if client is None:
            raise ValueError("BotStateSync requires a non-None client")
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")

        self._client = client
        self._state_provider = state_provider
        self._interval_s = interval_s
        self._max_failures = max_consecutive_failures
        self._on_failure = on_failure

        self._running = False
        self._consecutive_failures = 0
        self._total_writes = 0
        self._total_failures = 0
        self._last_write_at: Optional[datetime] = None
        self._stop_event: Optional[asyncio.Event] = None

    # ─── Stats ──────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {
            "running": self._running,
            "total_writes": self._total_writes,
            "total_failures": self._total_failures,
            "consecutive_failures": self._consecutive_failures,
            "last_write_at": (
                self._last_write_at.isoformat() if self._last_write_at else None
            ),
        }

    # ─── Loop ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Run the sync loop until ``stop()`` is called.

        This is the coroutine to wrap in ``asyncio.create_task()``. It
        never raises — all errors are logged and the loop continues.
        """
        if self._running:
            logger.warning("BotStateSync.start() called while already running")
            return

        self._running = True
        self._stop_event = asyncio.Event()
        logger.info(
            "BotStateSync started (interval=%.1fs, max_failures=%d)",
            self._interval_s,
            self._max_failures,
        )

        try:
            while self._running:
                await self._tick()
                # Sleep for interval OR until stop is signaled
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._cooldown_interval(),
                    )
                    # If we reach here, stop was signaled during sleep
                    break
                except asyncio.TimeoutError:
                    continue
        finally:
            self._running = False
            logger.info(
                "BotStateSync stopped (writes=%d, failures=%d)",
                self._total_writes,
                self._total_failures,
            )

    async def stop(self) -> None:
        """Signal the loop to exit after the current tick."""
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()

    def _cooldown_interval(self) -> float:
        """
        Back off after consecutive failures so a Supabase outage doesn't
        pin the event loop at 100% retrying.
        """
        if self._consecutive_failures >= self._max_failures:
            return self._interval_s * 10.0
        return self._interval_s

    async def _tick(self) -> None:
        """One iteration: fetch state → write → update counters."""
        try:
            state = await _maybe_await(self._state_provider())
        except Exception as e:
            logger.exception("state_provider raised: %s", e)
            self._consecutive_failures += 1
            self._total_failures += 1
            await self._handle_failure(e)
            return

        if not isinstance(state, dict):
            logger.error(
                "state_provider returned %s, expected dict — skipping tick",
                type(state).__name__,
            )
            return

        # Always stamp with server-side heartbeat so the dashboard's
        # staleness detection keeps working even if the caller forgot.
        state.setdefault("last_heartbeat", datetime.now(timezone.utc).isoformat())
        state.setdefault("updated_at", datetime.now(timezone.utc).isoformat())

        # upsert_bot_state is sync (supabase-py is sync under the hood).
        # Wrap in asyncio.to_thread so we don't block the event loop.
        try:
            ok = await asyncio.to_thread(self._client.upsert_bot_state, state)
        except Exception as e:
            self._consecutive_failures += 1
            self._total_failures += 1
            logger.exception("upsert_bot_state raised: %s", e)
            await self._handle_failure(e)
            return

        if ok:
            self._consecutive_failures = 0
            self._total_writes += 1
            self._last_write_at = datetime.now(timezone.utc)
            logger.debug(
                "bot_state synced (writes=%d)", self._total_writes
            )
        else:
            self._consecutive_failures += 1
            self._total_failures += 1
            await self._handle_failure(RuntimeError("upsert_bot_state returned False"))

    async def _handle_failure(self, exc: Exception) -> None:
        """Invoke optional failure callback and log cool-down state."""
        if self._consecutive_failures >= self._max_failures:
            logger.warning(
                "BotStateSync: %d consecutive failures — backing off 10x",
                self._consecutive_failures,
            )
        if self._on_failure is not None:
            try:
                result = self._on_failure(exc, self._consecutive_failures)
                if inspect.isawaitable(result):
                    await result
            except Exception as cb_exc:
                logger.exception("on_failure callback raised: %s", cb_exc)


# ─── Helpers ────────────────────────────────────────────────────────────

async def _maybe_await(result: Any) -> Any:
    """Await if the value is a coroutine, otherwise return as-is."""
    if inspect.isawaitable(result):
        return await result
    return result
