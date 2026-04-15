"""
tests/test_swc_rescan.py
=========================
Unit tests for the scheduled SWC re-scan logic (M15).

Tests cover:
  - Re-scan fires exactly at 00:45 CT (London) and 08:15 CT (NY AM)
  - Flags prevent double-trigger within the same day
  - Daily reset clears both flags
  - Telegram NOT sent when mood is unchanged
  - Telegram IS sent (via send_emergency_alert) when mood changes
  - Log format for both cases
  - API failure retains previous snapshot

Run: cd algoict-engine && python -m pytest tests/test_swc_rescan.py -v
"""

import asyncio
import logging
import pytest
from unittest.mock import MagicMock, patch

from main import (
    _run_swc_rescan,
    SWC_LONDON_HOUR,
    SWC_LONDON_MIN,
    SWC_NY_AM_HOUR,
    SWC_NY_AM_MIN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(mood=None, adj=0, mult=1.0):
    """Minimal EngineState-like stub."""
    class _S:
        swc_snapshot = None
        swc_london_rescan_done = False
        swc_nyam_rescan_done = False

    s = _S()
    if mood is not None:
        s.swc_snapshot = {"mood": mood, "min_confluence_adj": adj, "position_multiplier": mult}
    return s


def _make_components(telegram=None):
    class _C:
        pass
    c = _C()
    c.risk = MagicMock()
    c.risk.set_swc_overrides = MagicMock()
    c.telegram = telegram
    return c


def _swc_dict(mood="risk_on", adj=0, mult=1.0):
    return {"mood": mood, "min_confluence_adj": adj, "position_multiplier": mult}


# ---------------------------------------------------------------------------
# TestScheduleConstants
# ---------------------------------------------------------------------------

class TestScheduleConstants:

    def test_london_hour_is_0(self):
        assert SWC_LONDON_HOUR == 0

    def test_london_min_is_45(self):
        assert SWC_LONDON_MIN == 45

    def test_ny_am_hour_is_8(self):
        assert SWC_NY_AM_HOUR == 8

    def test_ny_am_min_is_15(self):
        assert SWC_NY_AM_MIN == 15


# ---------------------------------------------------------------------------
# TestScheduleTriggerConditions
#   Simulates the main-loop `if` check logic in isolation.
# ---------------------------------------------------------------------------

class TestScheduleTriggerConditions:

    def _london_triggers(self, hour, minute, done):
        return not done and hour == SWC_LONDON_HOUR and minute >= SWC_LONDON_MIN

    def _nyam_triggers(self, hour, minute, done):
        return not done and hour == SWC_NY_AM_HOUR and minute >= SWC_NY_AM_MIN

    # London ---------------------------------------------------------------

    def test_london_triggers_at_0045(self):
        assert self._london_triggers(0, 45, False) is True

    def test_london_triggers_after_0045(self):
        """Any minute >= 45 in hour 0 should trigger (engine polling may land late)."""
        assert self._london_triggers(0, 46, False) is True
        assert self._london_triggers(0, 59, False) is True

    def test_london_does_not_trigger_before_0045(self):
        assert self._london_triggers(0, 44, False) is False
        assert self._london_triggers(0, 0, False) is False

    def test_london_does_not_trigger_at_wrong_hour(self):
        assert self._london_triggers(1, 45, False) is False
        assert self._london_triggers(8, 45, False) is False

    def test_london_no_double_trigger_when_done(self):
        assert self._london_triggers(0, 45, True) is False
        assert self._london_triggers(0, 50, True) is False

    # NY AM ----------------------------------------------------------------

    def test_nyam_triggers_at_0815(self):
        assert self._nyam_triggers(8, 15, False) is True

    def test_nyam_triggers_after_0815(self):
        assert self._nyam_triggers(8, 16, False) is True
        assert self._nyam_triggers(8, 29, False) is True

    def test_nyam_does_not_trigger_before_0815(self):
        assert self._nyam_triggers(8, 14, False) is False
        assert self._nyam_triggers(8, 0, False) is False

    def test_nyam_does_not_trigger_at_wrong_hour(self):
        assert self._nyam_triggers(7, 15, False) is False
        assert self._nyam_triggers(0, 15, False) is False

    def test_nyam_no_double_trigger_when_done(self):
        assert self._nyam_triggers(8, 15, True) is False
        assert self._nyam_triggers(8, 20, True) is False


# ---------------------------------------------------------------------------
# TestDailyReset
# ---------------------------------------------------------------------------

class TestDailyReset:
    """Verify _reset_for_new_day clears rescan flags."""

    def test_reset_clears_swc_london_rescan_done(self):
        from main import _reset_for_new_day, EngineState, Components
        state = MagicMock(spec=EngineState)
        state.swc_london_rescan_done = True
        state.swc_nyam_rescan_done = True

        comps = MagicMock(spec=Components)
        comps.risk = MagicMock()
        comps.ny_am_strategy = MagicMock()
        comps.silver_bullet_strategy = MagicMock()
        comps.detectors = {"tracked_levels": []}

        _reset_for_new_day(comps, state)

        assert state.swc_london_rescan_done is False

    def test_reset_clears_swc_nyam_rescan_done(self):
        from main import _reset_for_new_day, EngineState, Components
        state = MagicMock(spec=EngineState)
        state.swc_london_rescan_done = True
        state.swc_nyam_rescan_done = True

        comps = MagicMock(spec=Components)
        comps.risk = MagicMock()
        comps.ny_am_strategy = MagicMock()
        comps.silver_bullet_strategy = MagicMock()
        comps.detectors = {"tracked_levels": []}

        _reset_for_new_day(comps, state)

        assert state.swc_nyam_rescan_done is False


# ---------------------------------------------------------------------------
# TestRescanFunction
# ---------------------------------------------------------------------------

class TestRescanFunction:

    @pytest.mark.asyncio
    async def test_noop_when_swc_module_unavailable(self):
        """If _SWC_RUN is None the function must return without touching state."""
        state = _make_state(mood="risk_on")
        comps = _make_components()

        with patch("main._SWC_RUN", None):
            await _run_swc_rescan(comps, state, "08:15")

        comps.risk.set_swc_overrides.assert_not_called()
        assert state.swc_snapshot["mood"] == "risk_on"  # unchanged

    @pytest.mark.asyncio
    async def test_applies_new_overrides(self):
        """Successful scan must call set_swc_overrides with new values."""
        state = _make_state(mood="risk_on")
        comps = _make_components()
        fresh = _swc_dict(mood="risk_off", adj=2, mult=0.75)

        with patch("main._SWC_RUN", return_value=fresh):
            await _run_swc_rescan(comps, state, "08:15")

        comps.risk.set_swc_overrides.assert_called_once_with(2, 0.75)

    @pytest.mark.asyncio
    async def test_updates_snapshot(self):
        state = _make_state(mood="risk_on")
        comps = _make_components()
        fresh = _swc_dict(mood="choppy", adj=1, mult=0.9)

        with patch("main._SWC_RUN", return_value=fresh):
            await _run_swc_rescan(comps, state, "08:15")

        assert state.swc_snapshot["mood"] == "choppy"

    # ------------------------------------------------------------------ #
    # Telegram behaviour
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_no_telegram_when_mood_unchanged(self):
        tg = MagicMock()
        state = _make_state(mood="risk_on")
        comps = _make_components(telegram=tg)
        fresh = _swc_dict(mood="risk_on")  # same mood

        with patch("main._SWC_RUN", return_value=fresh):
            await _run_swc_rescan(comps, state, "08:15")

        tg.send_emergency_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_sent_when_mood_changes(self):
        tg = MagicMock()
        state = _make_state(mood="risk_on")
        comps = _make_components(telegram=tg)
        fresh = _swc_dict(mood="risk_off", adj=2, mult=0.75)

        with patch("main._SWC_RUN", return_value=fresh):
            await _run_swc_rescan(comps, state, "08:15")

        tg.send_emergency_alert.assert_called_once()
        msg = tg.send_emergency_alert.call_args.args[0]
        assert "risk_on" in msg
        assert "risk_off" in msg

    @pytest.mark.asyncio
    async def test_no_telegram_when_no_previous_snapshot_but_same_mood(self):
        """If old_mood is None (no prior scan) telegram is NOT sent — mood can't have 'changed'."""
        tg = MagicMock()
        state = _make_state()           # no previous snapshot
        comps = _make_components(telegram=tg)
        fresh = _swc_dict(mood="risk_on")

        with patch("main._SWC_RUN", return_value=fresh):
            await _run_swc_rescan(comps, state, "08:15")

        # old_mood is None → condition `old_mood is not None and new_mood != old_mood` is False
        tg.send_emergency_alert.assert_not_called()

    # ------------------------------------------------------------------ #
    # Log format
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_log_mood_changed_format(self, caplog):
        state = _make_state(mood="choppy")
        comps = _make_components()
        fresh = _swc_dict(mood="risk_on")

        with caplog.at_level(logging.INFO):
            with patch("main._SWC_RUN", return_value=fresh):
                await _run_swc_rescan(comps, state, "08:15")

        assert "mood changed" in caplog.text
        assert "08:15 CT" in caplog.text
        assert "choppy" in caplog.text
        assert "risk_on" in caplog.text

    @pytest.mark.asyncio
    async def test_log_mood_unchanged_format(self, caplog):
        state = _make_state(mood="risk_on")
        comps = _make_components()
        fresh = _swc_dict(mood="risk_on")

        with caplog.at_level(logging.INFO):
            with patch("main._SWC_RUN", return_value=fresh):
                await _run_swc_rescan(comps, state, "00:45")

        assert "mood unchanged" in caplog.text
        assert "00:45 CT" in caplog.text
        assert "risk_on" in caplog.text

    # ------------------------------------------------------------------ #
    # Failure handling
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_api_failure_retains_snapshot(self):
        state = _make_state(mood="risk_on")
        comps = _make_components()

        with patch("main._SWC_RUN", side_effect=RuntimeError("timeout")):
            await _run_swc_rescan(comps, state, "08:15")

        assert state.swc_snapshot["mood"] == "risk_on"
        comps.risk.set_swc_overrides.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_failure_no_telegram(self):
        """On scan failure the rescan function must not send any Telegram alerts."""
        tg = MagicMock()
        state = _make_state(mood="risk_on")
        comps = _make_components(telegram=tg)

        with patch("main._SWC_RUN", side_effect=RuntimeError("timeout")):
            await _run_swc_rescan(comps, state, "08:15")

        tg.send_emergency_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_failure_does_not_raise(self):
        """Failure must be swallowed — engine must keep running."""
        state = _make_state(mood="risk_on")
        comps = _make_components()

        with patch("main._SWC_RUN", side_effect=ConnectionError("AV down")):
            await _run_swc_rescan(comps, state, "00:45")  # must not raise
