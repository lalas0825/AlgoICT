"""
tests/test_engine_lock.py
==========================
Regression coverage for the single-instance PID lock that prevents
concurrent engine processes from each firing Market BUY orders for the
same signal. On 2026-04-17, three zombie instances survived overnight
and at 04:31 CT Friday a single London ny_am signal produced 6 orders.
In-process dedup (EngineState.executed_signals,
Strategy._last_evaluated_bar_ts) is necessary but not sufficient —
cross-process startup must be blocked before any component initialises.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Import the module under test. The lock functions live inside main.py
# but main.py performs heavy initialisation on import; we reach into it
# via importlib after adding the engine dir to sys.path.
_ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ENGINE_DIR))

import main as engine_main  # noqa: E402


@pytest.fixture
def isolated_lock(tmp_path, monkeypatch):
    """Redirect the lock file to a tmp path so the tests don't touch
    the real .engine.lock sitting next to main.py on the developer
    machine. Also guarantees we reclaim a clean slate per test."""
    lock_path = tmp_path / "engine.lock"
    monkeypatch.setattr(engine_main, "_LOCK_PATH", lock_path)
    yield lock_path
    # Best-effort cleanup.
    try:
        if lock_path.exists():
            lock_path.unlink()
    except OSError:
        pass


class TestAcquireRelease:
    """Happy-path: acquire writes our PID, release removes the file."""

    def test_acquire_writes_current_pid(self, isolated_lock):
        assert not isolated_lock.exists()
        assert engine_main._acquire_engine_lock() is True
        assert isolated_lock.exists()
        assert isolated_lock.read_text().strip() == str(os.getpid())

    def test_release_removes_the_file(self, isolated_lock):
        engine_main._acquire_engine_lock()
        assert isolated_lock.exists()
        engine_main._release_engine_lock()
        assert not isolated_lock.exists()

    def test_release_is_idempotent(self, isolated_lock):
        engine_main._acquire_engine_lock()
        engine_main._release_engine_lock()
        engine_main._release_engine_lock()  # must not raise

    def test_release_does_not_remove_foreign_lock(self, isolated_lock):
        """If the lock file holds a PID that isn't ours, don't delete it.
        That would let the rightful owner race-lose on next acquire."""
        isolated_lock.write_text("99999")
        engine_main._release_engine_lock()
        assert isolated_lock.exists()
        assert isolated_lock.read_text().strip() == "99999"


class TestConcurrentStartup:
    """The real bug: two engines alive at once."""

    def test_second_acquire_fails_when_live_pid_owns_lock(
        self, isolated_lock, monkeypatch
    ):
        """Simulate a live peer by writing its PID into the lock and
        telling _is_pid_alive to return True for that PID."""
        peer_pid = os.getpid() + 1  # any PID that isn't ours
        isolated_lock.write_text(str(peer_pid))

        monkeypatch.setattr(
            engine_main, "_is_pid_alive",
            lambda pid: pid == peer_pid,
        )

        assert engine_main._acquire_engine_lock() is False
        # Peer's lock must be intact — do not trample it.
        assert isolated_lock.exists()
        assert isolated_lock.read_text().strip() == str(peer_pid)

    def test_stale_lock_is_reclaimed(self, isolated_lock, monkeypatch):
        """If the lock file names a PID that no longer exists, the new
        engine should reclaim it and write its own PID. This covers
        crashes / kill -9 where _release_engine_lock never ran."""
        dead_pid = 424242
        isolated_lock.write_text(str(dead_pid))

        monkeypatch.setattr(engine_main, "_is_pid_alive", lambda pid: False)

        assert engine_main._acquire_engine_lock() is True
        assert isolated_lock.read_text().strip() == str(os.getpid())


class TestBadLockContent:
    """Defensive parsing — a corrupt lock must not trap us forever."""

    def test_garbage_lock_is_reclaimed(self, isolated_lock, monkeypatch):
        isolated_lock.write_text("this is not a pid\n")
        # Ensure _is_pid_alive is never consulted for garbage — acquire
        # should short-circuit once int() fails.
        monkeypatch.setattr(
            engine_main, "_is_pid_alive",
            lambda pid: pytest.fail("should not be called on garbage"),
        )
        assert engine_main._acquire_engine_lock() is True
        assert isolated_lock.read_text().strip() == str(os.getpid())

    def test_empty_lock_is_reclaimed(self, isolated_lock, monkeypatch):
        isolated_lock.write_text("")
        monkeypatch.setattr(engine_main, "_is_pid_alive", lambda pid: False)
        assert engine_main._acquire_engine_lock() is True


class TestIsPidAlive:
    """Sanity check on the liveness probe. Avoids false negatives that
    would let stale-lock reclamation trample an actually-live peer."""

    def test_current_process_is_alive(self):
        assert engine_main._is_pid_alive(os.getpid()) is True

    def test_zero_or_negative_is_dead(self):
        assert engine_main._is_pid_alive(0) is False
        assert engine_main._is_pid_alive(-1) is False

    def test_very_high_pid_likely_dead(self):
        # PID 2**30 is way beyond the typical max. On Linux it hits
        # kernel.pid_max (default 32768 or 4194304); on Windows PIDs are
        # 16-bit. Either way, extremely unlikely to be in use.
        assert engine_main._is_pid_alive(2**30) is False
