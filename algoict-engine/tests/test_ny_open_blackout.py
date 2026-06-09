"""NY-open blackout pending-cancel (2026-06-09): in the cash-open buffer window
no new evals AND resting limits are cancelled so they can't fill on the wick.
Config defaults: BEFORE=10, AFTER=15, events=[(7,30),(8,30)] CT →
blackouts [07:20,07:45) and [08:20,08:45)."""
from datetime import datetime

import config
from strategies.silver_bullet import is_ny_open_blackout


def t(h, m):
    return datetime(2026, 6, 9, h, m)


def test_0830_window():
    assert is_ny_open_blackout(t(8, 20)) is True   # window start (inclusive)
    assert is_ny_open_blackout(t(8, 31)) is True   # the live 6/9 wick-fill time
    assert is_ny_open_blackout(t(8, 44)) is True
    assert is_ny_open_blackout(t(8, 45)) is False   # end (exclusive)
    assert is_ny_open_blackout(t(8, 19)) is False   # just before


def test_0730_window():
    assert is_ny_open_blackout(t(7, 20)) is True
    assert is_ny_open_blackout(t(7, 30)) is True
    assert is_ny_open_blackout(t(7, 45)) is False


def test_outside_windows():
    for h, m in [(3, 0), (6, 0), (8, 0), (10, 0), (13, 30)]:
        assert is_ny_open_blackout(t(h, m)) is False


def test_buffer_disabled(monkeypatch):
    monkeypatch.setattr(config, "NY_OPEN_BUFFER_BEFORE_MIN", 0)
    monkeypatch.setattr(config, "NY_OPEN_BUFFER_AFTER_MIN", 0)
    assert is_ny_open_blackout(t(8, 30)) is False  # buffer off => never blackout
