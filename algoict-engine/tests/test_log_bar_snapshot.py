"""
tests/test_log_bar_snapshot.py
================================
Tests for _log_bar_snapshot kill-zone label in the BAR INFO line.

Verifies that each kill zone — including ny_pm — is reported correctly
in the `kz=<zone>` field of the BAR log line.

Run: cd algoict-engine && python -m pytest tests/test_log_bar_snapshot.py -v
"""

import logging
import pandas as pd
import pytest
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from main import _log_bar_snapshot, EngineState, Components

CT = ZoneInfo("US/Central")


def _make_ts(hour: int, minute: int) -> pd.Timestamp:
    return pd.Timestamp(f"2026-04-15 {hour:02d}:{minute:02d}:00", tz=CT)


def _make_components(ts: pd.Timestamp) -> Components:
    """Build a minimal Components stub with a real SessionManager."""
    from timeframes.session_manager import SessionManager

    sess = SessionManager()
    comps = MagicMock(spec=Components)
    comps.session = sess
    fvg_mock = MagicMock()
    fvg_mock.get_active.return_value = []
    fvg_mock.get_active_ifvgs.return_value = []
    disp_mock = MagicMock()
    disp_mock.get_recent.return_value = []
    comps.detectors = {
        "swing": MagicMock(swing_points=[]),
        "fvg": fvg_mock,
        "ob": MagicMock(**{"get_active.return_value": []}),
        "structure": MagicMock(**{"get_events.return_value": []}),
        "displacement": disp_mock,
        "tracked_levels": [],
    }
    return comps


def _make_state(ts: pd.Timestamp) -> EngineState:
    state = MagicMock(spec=EngineState)
    row = pd.DataFrame(
        {"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5], "volume": [500]},
        index=pd.DatetimeIndex([ts], tz=CT),
    )
    state.bars_1min = row
    state.vpin_status = None
    return state


# ---------------------------------------------------------------------------
# Parametrized: one test per kill zone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hour,minute,expected_kz", [
    # London: 02:00–05:00 CT
    (3, 0,  "london"),
    # NY AM: 08:30–11:00 CT
    (9, 0,  "ny_am"),
    # Silver Bullet: 10:00–11:00 CT (inside NY AM, takes priority based on loop order)
    # Loop order is: london, london_silver_bullet, ny_am, silver_bullet, ny_pm
    # 10:30 CT hits ny_am first, so kz=ny_am (silver_bullet is later in loop)
    # Use a time only inside silver_bullet window to confirm it's detected too
    # silver_bullet: 10:00-11:00; but ny_am also covers this range
    # → kz=ny_am since ny_am appears first in the loop. That's correct behavior.
    # Test ny_pm specifically:
    (13, 30, "ny_pm"),
    (14, 0,  "ny_pm"),
    (14, 59, "ny_pm"),
    # 2026-05-01 v19a-WIDE — KZs widened, no gap between ny_am/ny_pm.
    # 12:00 CT is now START of ny_pm (was outside any zone before).
    (12, 0,  "ny_pm"),
    # Outside all zones: 15:05 CT (after hard close, ny_pm ends 15:00)
    (15, 5,  "none"),
    # Outside all zones: 00:30 CT (before London 01:00 start)
    (0, 30,  "none"),
])
def test_kz_label_in_log(hour, minute, expected_kz, caplog):
    ts = _make_ts(hour, minute)
    comps = _make_components(ts)
    state = _make_state(ts)

    with caplog.at_level(logging.INFO, logger="algoict.main"):
        _log_bar_snapshot(comps, state, ts)

    bar_lines = [r.message for r in caplog.records if r.name == "algoict.main" and "BAR [" in r.message]
    assert bar_lines, "No BAR log line emitted"
    assert f"kz={expected_kz}" in bar_lines[0], (
        f"Expected kz={expected_kz} in: {bar_lines[0]}"
    )
