"""Tests for core.state_sync — async bot_state writer loop."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core.state_sync import BotStateSync


# ─── Mock client ────────────────────────────────────────────────────────

class FakeClient:
    def __init__(self, fail_after: int = -1, fail_with: Exception | None = None):
        self.writes: list[dict] = []
        self.calls = 0
        self.fail_after = fail_after
        self.fail_with = fail_with or RuntimeError("boom")

    def upsert_bot_state(self, state: dict) -> bool:
        self.calls += 1
        if self.fail_after >= 0 and self.calls > self.fail_after:
            raise self.fail_with
        self.writes.append(dict(state))
        return True


# ─── Construction ──────────────────────────────────────────────────────

class TestConstruction:
    def test_rejects_none_client(self):
        with pytest.raises(ValueError):
            BotStateSync(None, lambda: {})

    def test_rejects_non_positive_interval(self):
        with pytest.raises(ValueError):
            BotStateSync(FakeClient(), lambda: {}, interval_s=0)

    def test_initial_stats(self):
        sync = BotStateSync(FakeClient(), lambda: {})
        stats = sync.stats
        assert stats["total_writes"] == 0
        assert stats["total_failures"] == 0
        assert stats["running"] is False


# ─── Basic async loop ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_tick_writes_state():
    client = FakeClient()
    sync = BotStateSync(
        client,
        lambda: {"vpin": 0.42, "is_running": True},
        interval_s=0.05,
    )
    await sync._tick()
    assert len(client.writes) == 1
    assert client.writes[0]["vpin"] == 0.42
    assert "last_heartbeat" in client.writes[0]  # Auto-stamped


@pytest.mark.asyncio
async def test_loop_runs_and_stops():
    client = FakeClient()

    call_count = 0
    def provider():
        nonlocal call_count
        call_count += 1
        return {"vpin": 0.1 * call_count, "is_running": True}

    sync = BotStateSync(client, provider, interval_s=0.02)

    task = asyncio.create_task(sync.start())
    await asyncio.sleep(0.12)  # Enough for ~5 ticks
    await sync.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert len(client.writes) >= 3
    assert sync.is_running is False
    assert sync.stats["total_writes"] >= 3


@pytest.mark.asyncio
async def test_async_state_provider_supported():
    client = FakeClient()

    async def async_provider():
        await asyncio.sleep(0)  # yield
        return {"vpin": 0.7, "is_running": True}

    sync = BotStateSync(client, async_provider, interval_s=0.02)
    await sync._tick()
    assert client.writes[0]["vpin"] == 0.7


@pytest.mark.asyncio
async def test_non_dict_provider_result_skipped():
    client = FakeClient()
    sync = BotStateSync(client, lambda: "not a dict", interval_s=0.02)
    await sync._tick()
    # Nothing should be written
    assert len(client.writes) == 0


@pytest.mark.asyncio
async def test_provider_exception_increments_failures():
    client = FakeClient()

    def bad_provider():
        raise ValueError("no state")

    sync = BotStateSync(client, bad_provider, interval_s=0.02)
    await sync._tick()
    assert sync.stats["total_failures"] == 1
    assert sync.stats["consecutive_failures"] == 1
    assert len(client.writes) == 0


@pytest.mark.asyncio
async def test_client_exception_handled():
    client = FakeClient(fail_after=0)  # First call already fails
    sync = BotStateSync(client, lambda: {"vpin": 0.5}, interval_s=0.02)
    await sync._tick()
    assert sync.stats["total_failures"] == 1
    assert sync.stats["total_writes"] == 0


@pytest.mark.asyncio
async def test_consecutive_failures_trigger_cooldown():
    """After max_consecutive_failures, cooldown interval grows 10x."""
    client = FakeClient(fail_after=0)
    sync = BotStateSync(
        client,
        lambda: {"vpin": 0.5},
        interval_s=1.0,
        max_consecutive_failures=2,
    )
    # Trigger failures manually
    await sync._tick()
    await sync._tick()
    assert sync._consecutive_failures == 2
    assert sync._cooldown_interval() == 10.0  # 1.0 * 10


@pytest.mark.asyncio
async def test_failure_callback_invoked():
    client = FakeClient(fail_after=0)
    fail_calls: list = []

    def on_fail(exc, count):
        fail_calls.append((str(exc)[:10], count))

    sync = BotStateSync(
        client,
        lambda: {"vpin": 0.5},
        interval_s=0.02,
        on_failure=on_fail,
    )
    await sync._tick()
    assert len(fail_calls) == 1
    assert fail_calls[0][1] == 1


@pytest.mark.asyncio
async def test_async_failure_callback_supported():
    client = FakeClient(fail_after=0)
    fail_calls: list = []

    async def async_on_fail(exc, count):
        await asyncio.sleep(0)
        fail_calls.append(count)

    sync = BotStateSync(
        client,
        lambda: {"vpin": 0.5},
        interval_s=0.02,
        on_failure=async_on_fail,
    )
    await sync._tick()
    assert fail_calls == [1]


@pytest.mark.asyncio
async def test_successful_write_resets_consecutive_failures():
    """After a failure streak, a successful write should reset the counter."""
    # Client fails on calls 1,2 then succeeds on call 3+
    class FlakiClient:
        def __init__(self):
            self.calls = 0
            self.writes = []

        def upsert_bot_state(self, state):
            self.calls += 1
            if self.calls <= 2:
                raise RuntimeError("flaky")
            self.writes.append(state)
            return True

    client = FlakiClient()
    sync = BotStateSync(client, lambda: {"vpin": 0.5}, interval_s=0.02)
    await sync._tick()
    await sync._tick()
    assert sync._consecutive_failures == 2
    await sync._tick()  # This succeeds
    assert sync._consecutive_failures == 0
    assert sync.stats["total_writes"] == 1


@pytest.mark.asyncio
async def test_double_start_is_noop():
    client = FakeClient()
    sync = BotStateSync(client, lambda: {"vpin": 0}, interval_s=0.05)
    task1 = asyncio.create_task(sync.start())
    await asyncio.sleep(0.02)
    # Second start while running — should log warning and return
    await sync.start()
    await sync.stop()
    await asyncio.wait_for(task1, timeout=1.0)


@pytest.mark.asyncio
async def test_heartbeat_stamp_auto_added():
    """state_provider doesn't need to set last_heartbeat; loop does."""
    client = FakeClient()
    sync = BotStateSync(client, lambda: {"vpin": 0.1}, interval_s=0.02)
    await sync._tick()
    stored = client.writes[0]
    assert "last_heartbeat" in stored
    assert "updated_at" in stored


@pytest.mark.asyncio
async def test_provider_heartbeat_not_overwritten():
    """If provider supplies last_heartbeat, use that value."""
    client = FakeClient()
    sync = BotStateSync(
        client,
        lambda: {"vpin": 0.1, "last_heartbeat": "2025-03-10T14:00:00+00:00"},
        interval_s=0.02,
    )
    await sync._tick()
    assert client.writes[0]["last_heartbeat"] == "2025-03-10T14:00:00+00:00"
