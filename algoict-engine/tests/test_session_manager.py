"""
tests/test_session_manager.py
==============================
Unit tests for timeframes/session_manager.py

Kill zones are in US/Central (CT) as defined in config.py.

Run: cd algoict-engine && python -m pytest tests/test_session_manager.py -v
"""

import datetime
import math

import pandas as pd
import pytest

from timeframes.session_manager import SessionManager


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ts(time_str: str, date: str = "2025-03-03") -> pd.Timestamp:
    """Build a US/Central timestamp. time_str: 'HH:MM'"""
    return pd.Timestamp(f"{date} {time_str}", tz="US/Central")


def _make_session_df(date: str, start_h: int, end_h: int) -> pd.DataFrame:
    """
    1-min OHLCV from start_h to end_h CT on *date*.
    Prices increase by 1 each minute.
    """
    start = pd.Timestamp(f"{date} {start_h:02d}:00", tz="US/Central")
    periods = (end_h - start_h) * 60
    idx = pd.date_range(start, periods=periods, freq="1min")
    base = 20000.0
    return pd.DataFrame({
        "open":   [base + i for i in range(periods)],
        "high":   [base + i + 5 for i in range(periods)],
        "low":    [base + i - 5 for i in range(periods)],
        "close":  [base + i + 1 for i in range(periods)],
        "volume": [100] * periods,
    }, index=idx)


# ─── Tests: is_kill_zone — NY AM (08:30–11:00 CT) ────────────────────────────

class TestNyAmKillZone:

    def setup_method(self):
        self.sm = SessionManager()

    def test_inside_ny_am_start(self):
        """08:30 CT is inside NY AM kill zone."""
        assert self.sm.is_kill_zone(_ts("08:30"), "ny_am") is True

    def test_inside_ny_am_midpoint(self):
        """09:45 CT is inside NY AM kill zone."""
        assert self.sm.is_kill_zone(_ts("09:45"), "ny_am") is True

    def test_inside_ny_am_end_exclusive(self):
        """12:00 CT is NOT inside NY AM (end is exclusive, window extended to 12:00)."""
        assert self.sm.is_kill_zone(_ts("12:00"), "ny_am") is False

    def test_outside_ny_am_before(self):
        """07:29 CT is before NY AM kill zone (v19a-WIDE: starts 07:30)."""
        assert self.sm.is_kill_zone(_ts("07:29"), "ny_am") is False

    def test_outside_ny_am_after(self):
        """12:30 CT is after NY AM kill zone (extended end = 12:00)."""
        assert self.sm.is_kill_zone(_ts("12:30"), "ny_am") is False

    def test_outside_ny_am_overnight(self):
        """02:00 CT is overnight, not in NY AM."""
        assert self.sm.is_kill_zone(_ts("02:00"), "ny_am") is False


# ─── Tests: is_kill_zone — Silver Bullet (10:00–11:00 CT) ────────────────────

class TestSilverBulletKillZone:

    def setup_method(self):
        self.sm = SessionManager()

    def test_inside_silver_bullet_start(self):
        """09:00 CT is inside Silver Bullet (AM window 09:00-10:00 CT = 10-11 ET)."""
        assert self.sm.is_kill_zone(_ts("09:00"), "silver_bullet") is True

    def test_inside_silver_bullet_mid(self):
        """09:30 CT is inside Silver Bullet."""
        assert self.sm.is_kill_zone(_ts("09:30"), "silver_bullet") is True

    def test_outside_silver_bullet_end(self):
        """10:00 CT is NOT inside Silver Bullet (exclusive end)."""
        assert self.sm.is_kill_zone(_ts("10:00"), "silver_bullet") is False

    def test_outside_silver_bullet_before(self):
        """08:59 CT is before Silver Bullet."""
        assert self.sm.is_kill_zone(_ts("08:59"), "silver_bullet") is False

    def test_silver_bullet_inside_ny_am(self):
        """09:30 CT is inside BOTH silver_bullet AND ny_am."""
        assert self.sm.is_kill_zone(_ts("09:30"), "ny_am") is True
        assert self.sm.is_kill_zone(_ts("09:30"), "silver_bullet") is True


# ─── Tests: is_kill_zone — Asian (20:00–00:00 CT, wraps midnight) ─────────────

class TestAsianKillZone:

    def setup_method(self):
        self.sm = SessionManager()

    def test_inside_asian_evening(self):
        """20:00 CT is inside Asian kill zone."""
        assert self.sm.is_kill_zone(_ts("20:00"), "asian") is True

    def test_inside_asian_late_night(self):
        """23:30 CT is inside Asian kill zone."""
        assert self.sm.is_kill_zone(_ts("23:30"), "asian") is True

    def test_inside_asian_just_after_midnight(self):
        """00:00 CT midnight — Asian ends at 00:00, so 00:00 is NOT inside."""
        assert self.sm.is_kill_zone(_ts("00:00"), "asian") is False

    def test_outside_asian_morning(self):
        """09:00 CT is outside Asian kill zone."""
        assert self.sm.is_kill_zone(_ts("09:00"), "asian") is False


# ─── Tests: is_kill_zone — London (02:00–05:00 CT) ───────────────────────────

class TestLondonKillZone:

    def setup_method(self):
        self.sm = SessionManager()

    def test_inside_london(self):
        """03:00 CT is inside London kill zone."""
        assert self.sm.is_kill_zone(_ts("03:00"), "london") is True

    def test_london_start(self):
        """02:00 CT is inside London kill zone."""
        assert self.sm.is_kill_zone(_ts("02:00"), "london") is True

    def test_london_end_exclusive(self):
        """07:30 CT is NOT inside London (v19a-WIDE: ends 07:30 exclusive)."""
        assert self.sm.is_kill_zone(_ts("07:30"), "london") is False

    def test_outside_london_before(self):
        """00:59 CT is before London (new window starts 01:00)."""
        assert self.sm.is_kill_zone(_ts("00:59"), "london") is False


# ─── Tests: is_kill_zone — Invalid zone ──────────────────────────────────────

class TestInvalidZone:

    def test_unknown_zone_raises(self):
        """Unknown zone name raises ValueError."""
        sm = SessionManager()
        with pytest.raises(ValueError, match="Unknown zone"):
            sm.is_kill_zone(_ts("09:00"), "tokyo")

    def test_naive_timestamp_raises(self):
        """Naive (no tz) timestamp raises ValueError."""
        sm = SessionManager()
        naive_ts = pd.Timestamp("2025-03-03 09:00")  # no tz
        with pytest.raises(ValueError, match="timezone-aware"):
            sm.is_kill_zone(naive_ts, "ny_am")


# ─── Tests: get_asian_range ───────────────────────────────────────────────────

class TestAsianRange:

    def setup_method(self):
        self.sm = SessionManager()

    def test_asian_range_returns_tuple(self):
        """get_asian_range returns (high, low) floats."""
        # Provide bars for the prior evening (19:00-23:59 CT on 2025-03-03)
        df = _make_session_df("2025-03-03", 19, 24)
        high, low = self.sm.get_asian_range(
            datetime.date(2025, 3, 4), df
        )
        assert isinstance(high, float)
        assert isinstance(low, float)
        assert high >= low

    def test_asian_high_is_max_of_evening(self):
        """Asian high = max high of all bars in 19:00-23:59 CT prior evening."""
        df = _make_session_df("2025-03-03", 19, 24)
        high, _ = self.sm.get_asian_range(datetime.date(2025, 3, 4), df)
        expected_high = df["high"].max()
        assert high == expected_high

    def test_asian_low_is_min_of_evening(self):
        """Asian low = min low of all bars in 19:00-23:59 CT prior evening."""
        df = _make_session_df("2025-03-03", 19, 24)
        _, low = self.sm.get_asian_range(datetime.date(2025, 3, 4), df)
        expected_low = df["low"].min()
        assert low == expected_low

    def test_asian_range_no_data_returns_nan(self):
        """Returns (nan, nan) when no prior-evening bars exist."""
        df = _make_session_df("2025-03-03", 9, 16)  # RTH only, no evening bars
        high, low = self.sm.get_asian_range(datetime.date(2025, 3, 4), df)
        assert math.isnan(high)
        assert math.isnan(low)


# ─── Tests: get_london_session ────────────────────────────────────────────────

class TestLondonSession:

    def setup_method(self):
        self.sm = SessionManager()

    def test_london_range_returns_tuple(self):
        """get_london_session returns (high, low) floats."""
        df = _make_session_df("2025-03-03", 2, 6)
        high, low = self.sm.get_london_session(datetime.date(2025, 3, 3), df)
        assert isinstance(high, float)
        assert isinstance(low, float)
        assert high >= low

    def test_london_high_is_max(self):
        """London high = max high of 01:00-04:00 CT bars."""
        df = _make_session_df("2025-03-03", 1, 5)
        london_bars = df.between_time("01:00", "03:59")
        expected_high = london_bars["high"].max()
        high, _ = self.sm.get_london_session(datetime.date(2025, 3, 3), df)
        assert high == pytest.approx(expected_high, rel=1e-6)

    def test_london_low_is_min(self):
        """London low = min low of 01:00-04:00 CT bars."""
        df = _make_session_df("2025-03-03", 1, 5)
        london_bars = df.between_time("01:00", "03:59")
        expected_low = london_bars["low"].min()
        _, low = self.sm.get_london_session(datetime.date(2025, 3, 3), df)
        assert low == pytest.approx(expected_low, rel=1e-6)

    def test_london_no_data_returns_nan(self):
        """Returns (nan, nan) when no London-session bars exist."""
        df = _make_session_df("2025-03-03", 9, 16)  # RTH only
        high, low = self.sm.get_london_session(datetime.date(2025, 3, 3), df)
        assert math.isnan(high)
        assert math.isnan(low)
