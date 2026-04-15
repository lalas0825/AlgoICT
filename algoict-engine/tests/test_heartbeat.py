"""
tests/test_heartbeat.py
=======================
Tests for core/heartbeat.py

Note: Heartbeat runs on a 5-second loop, so these are integration-style tests.
"""

import asyncio
import pytest
from datetime import datetime, timezone

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.heartbeat import start_heartbeat


class MockSupabaseClient:
    def __init__(self, fail_count=0):
        self.call_count = 0
        self.fail_count = fail_count
        self.last_state = None

    def update_bot_state(self, state):
        self.call_count += 1
        if self.fail_count > 0 and self.call_count <= self.fail_count:
            raise Exception("Supabase down")
        self.last_state = state


class MockRiskManager:
    def __init__(self):
        self.flatten_called = False
        self.flatten_count = 0
        self.flatten_reason = None

    async def emergency_flatten(self, reason):
        self.flatten_called = True
        self.flatten_count += 1
        self.flatten_reason = reason


class TestStartHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_writes_state(self):
        """Heartbeat should write bot_state with last_heartbeat timestamp."""
        sb = MockSupabaseClient()
        rm = MockRiskManager()

        # Run heartbeat for just 1 second, should write at least once
        task = asyncio.create_task(start_heartbeat(sb, rm))
        await asyncio.sleep(0.5)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        assert sb.call_count >= 1
        assert sb.last_state is not None
        assert "last_heartbeat" in sb.last_state

    @pytest.mark.asyncio
    async def test_heartbeat_records_timestamp(self):
        """Heartbeat should record a valid ISO timestamp."""
        sb = MockSupabaseClient()
        rm = MockRiskManager()

        task = asyncio.create_task(start_heartbeat(sb, rm))
        await asyncio.sleep(0.1)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        assert sb.last_state is not None
        ts = sb.last_state.get("last_heartbeat")
        # Should be ISO format string like 2024-01-02T09:30:00.123456+00:00
        assert isinstance(ts, str)
        assert "T" in ts  # ISO datetime format

    @pytest.mark.asyncio
    async def test_heartbeat_no_premature_flatten(self):
        """Heartbeat should NOT flatten on first write success."""
        sb = MockSupabaseClient()
        rm = MockRiskManager()

        task = asyncio.create_task(start_heartbeat(sb, rm))
        await asyncio.sleep(0.1)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        assert rm.flatten_called is False
