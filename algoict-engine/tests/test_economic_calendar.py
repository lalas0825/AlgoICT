"""
tests/test_economic_calendar.py
================================
Tests for sentiment/economic_calendar.py
"""

import datetime
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentiment.economic_calendar import (
    get_event_risk,
    get_events_on_date,
    get_upcoming_events,
    is_high_impact_day,
    EconomicEvent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _d(y, m, d):
    return datetime.date(y, m, d)


# ---------------------------------------------------------------------------
# FOMC dates → extreme
# ---------------------------------------------------------------------------

class TestFOMC:
    def test_fomc_2023_dec(self):
        assert get_event_risk(_d(2023, 12, 13)) == "extreme"

    def test_fomc_2024_jan(self):
        assert get_event_risk(_d(2024, 1, 31)) == "extreme"

    def test_fomc_2024_mar(self):
        assert get_event_risk(_d(2024, 3, 20)) == "extreme"

    def test_fomc_2024_may(self):
        assert get_event_risk(_d(2024, 5, 1)) == "extreme"

    def test_fomc_2024_sep(self):
        assert get_event_risk(_d(2024, 9, 18)) == "extreme"

    def test_fomc_2025_jan(self):
        assert get_event_risk(_d(2025, 1, 29)) == "extreme"

    def test_fomc_event_name(self):
        events = get_events_on_date(_d(2024, 1, 31))
        fomc_events = [e for e in events if e.name == "FOMC"]
        assert len(fomc_events) >= 1
        assert fomc_events[0].risk == "extreme"

    def test_fomc_2022_jun(self):
        # Biggest hike meeting
        assert get_event_risk(_d(2022, 6, 15)) == "extreme"

    def test_fomc_2022_nov(self):
        assert get_event_risk(_d(2022, 11, 2)) == "extreme"

    def test_fomc_2025_mar(self):
        assert get_event_risk(_d(2025, 3, 19)) == "extreme"


# ---------------------------------------------------------------------------
# CPI dates → high
# ---------------------------------------------------------------------------

class TestCPI:
    def test_cpi_2023_jun(self):
        assert get_event_risk(_d(2023, 6, 13)) == "high"

    def test_cpi_2024_jan(self):
        assert get_event_risk(_d(2024, 1, 11)) == "high"

    def test_cpi_2024_apr(self):
        assert get_event_risk(_d(2024, 4, 10)) == "high"

    def test_cpi_2024_oct(self):
        assert get_event_risk(_d(2024, 10, 10)) == "high"

    def test_cpi_2025_jan(self):
        assert get_event_risk(_d(2025, 1, 15)) == "high"

    def test_cpi_2025_sep(self):
        assert get_event_risk(_d(2025, 9, 11)) == "high"

    def test_cpi_event_name(self):
        events = get_events_on_date(_d(2024, 1, 11))
        cpi_events = [e for e in events if e.name == "CPI"]
        assert len(cpi_events) >= 1

    def test_cpi_2022_oct_inflation_peak(self):
        # Oct 2022 — highest CPI in 40 years
        assert get_event_risk(_d(2022, 10, 13)) == "high"


# ---------------------------------------------------------------------------
# NFP dates → high
# ---------------------------------------------------------------------------

class TestNFP:
    def test_nfp_2024_jan(self):
        assert get_event_risk(_d(2024, 1, 5)) == "high"

    def test_nfp_2024_mar(self):
        assert get_event_risk(_d(2024, 3, 8)) == "high"

    def test_nfp_2024_jun(self):
        assert get_event_risk(_d(2024, 6, 7)) == "high"

    def test_nfp_2024_sep(self):
        assert get_event_risk(_d(2024, 9, 6)) == "high"

    def test_nfp_2025_jan(self):
        assert get_event_risk(_d(2025, 1, 10)) == "high"

    def test_nfp_2025_may(self):
        assert get_event_risk(_d(2025, 5, 2)) == "high"

    def test_nfp_event_name(self):
        events = get_events_on_date(_d(2024, 1, 5))
        nfp_events = [e for e in events if e.name == "NFP"]
        assert len(nfp_events) >= 1
        assert nfp_events[0].risk == "high"


# ---------------------------------------------------------------------------
# Medium events
# ---------------------------------------------------------------------------

class TestMediumEvents:
    def test_gdp_advance_2024_q1(self):
        assert get_event_risk(_d(2024, 4, 25)) == "medium"

    def test_gdp_advance_2023_q4(self):
        assert get_event_risk(_d(2023, 1, 26)) == "medium"

    def test_pce_2024_jan(self):
        assert get_event_risk(_d(2024, 1, 26)) == "medium"

    def test_pce_2023_jun(self):
        assert get_event_risk(_d(2023, 6, 30)) == "medium"

    def test_medium_event_risk_level(self):
        events = get_events_on_date(_d(2024, 1, 26))  # PCE
        assert any(e.risk == "medium" for e in events)


# ---------------------------------------------------------------------------
# No event days
# ---------------------------------------------------------------------------

class TestNoEvents:
    def test_regular_wednesday(self):
        # A Wednesday with no known events
        assert get_event_risk(_d(2024, 1, 3)) == "none"

    def test_empty_day_returns_none(self):
        assert get_event_risk(_d(2024, 2, 5)) == "none"

    def test_weekend_no_events(self):
        # Weekend (Saturday)
        assert get_event_risk(_d(2024, 1, 6)) == "none"

    def test_random_trading_day(self):
        # Should return 'none' for a quiet day
        assert get_event_risk(_d(2024, 3, 5)) == "none"


# ---------------------------------------------------------------------------
# Risk hierarchy (FOMC wins over CPI on same day)
# ---------------------------------------------------------------------------

class TestRiskHierarchy:
    def test_fomc_overrides_medium(self):
        # Some FOMC days may also have other events; FOMC should win
        # 2020 Jan 29 = FOMC + GDP
        risk = get_event_risk(_d(2020, 1, 29))
        assert risk == "extreme"

    def test_fomc_overrides_cpi(self):
        # 2024 Jun 12 = FOMC + CPI (both on same day!)
        risk = get_event_risk(_d(2024, 6, 12))
        assert risk == "extreme"

    def test_multiple_events_max_wins(self):
        # Manually verify that if a day has both high and medium,
        # we get 'high' back
        from sentiment.economic_calendar import _max_risk
        assert _max_risk(["medium", "high", "low"]) == "high"
        assert _max_risk(["extreme", "high"]) == "extreme"
        assert _max_risk(["none"]) == "none"


# ---------------------------------------------------------------------------
# get_events_on_date
# ---------------------------------------------------------------------------

class TestGetEventsOnDate:
    def test_returns_list(self):
        events = get_events_on_date(_d(2024, 1, 31))
        assert isinstance(events, list)

    def test_no_events_returns_empty(self):
        events = get_events_on_date(_d(2024, 1, 3))
        assert events == []

    def test_event_has_required_fields(self):
        events = get_events_on_date(_d(2024, 1, 31))
        for e in events:
            assert hasattr(e, "date")
            assert hasattr(e, "name")
            assert hasattr(e, "risk")

    def test_accepts_datetime(self):
        # Should handle datetime objects, not just dates
        dt = datetime.datetime(2024, 1, 31, 10, 0)
        events = get_events_on_date(dt)
        assert len(events) >= 1


# ---------------------------------------------------------------------------
# get_upcoming_events
# ---------------------------------------------------------------------------

class TestGetUpcomingEvents:
    def test_returns_sorted(self):
        events = get_upcoming_events(_d(2024, 1, 1), days_ahead=30)
        dates = [e.date for e in events]
        assert dates == sorted(dates)

    def test_window_respected(self):
        events = get_upcoming_events(_d(2024, 1, 1), days_ahead=7)
        end = _d(2024, 1, 8)
        for e in events:
            assert e.date <= end

    def test_includes_start_date(self):
        # NFP Jan 5 2024 — start exactly on that date
        events = get_upcoming_events(_d(2024, 1, 5), days_ahead=0)
        assert any(e.name == "NFP" for e in events)

    def test_zero_days_returns_today_only(self):
        events = get_upcoming_events(_d(2024, 1, 5), days_ahead=0)
        for e in events:
            assert e.date == _d(2024, 1, 5)


# ---------------------------------------------------------------------------
# is_high_impact_day
# ---------------------------------------------------------------------------

class TestIsHighImpactDay:
    def test_fomc_is_high_impact(self):
        assert is_high_impact_day(_d(2024, 1, 31)) is True

    def test_cpi_is_high_impact(self):
        assert is_high_impact_day(_d(2024, 1, 11)) is True

    def test_nfp_is_high_impact(self):
        assert is_high_impact_day(_d(2024, 1, 5)) is True

    def test_medium_not_high_impact(self):
        assert is_high_impact_day(_d(2024, 1, 26)) is False  # PCE = medium

    def test_quiet_day_not_high_impact(self):
        assert is_high_impact_day(_d(2024, 1, 3)) is False


# ---------------------------------------------------------------------------
# Coverage integrity
# ---------------------------------------------------------------------------

class TestCoverage:
    def test_2019_has_fomc_events(self):
        fomc_count = sum(
            1 for m in range(1, 13)
            for d in range(1, 32)
            if _safe_date(2019, m, d) and
            any(e.name == "FOMC" for e in get_events_on_date(_safe_date(2019, m, d)))
        )
        assert fomc_count == 8  # 8 FOMC meetings in 2019

    def test_2024_has_12_cpi_releases(self):
        cpi_count = sum(
            1 for m in range(1, 13)
            for d in range(1, 32)
            if _safe_date(2024, m, d) and
            any(e.name == "CPI" for e in get_events_on_date(_safe_date(2024, m, d)))
        )
        assert cpi_count == 12

    def test_2024_has_12_nfp_releases(self):
        nfp_count = sum(
            1 for m in range(1, 13)
            for d in range(1, 32)
            if _safe_date(2024, m, d) and
            any(e.name == "NFP" for e in get_events_on_date(_safe_date(2024, m, d)))
        )
        assert nfp_count == 12

    def test_calendar_spans_2019_to_2025(self):
        from sentiment.economic_calendar import _CALENDAR
        years = {d.year for d in _CALENDAR.keys()}
        for y in range(2019, 2026):
            assert y in years


def _safe_date(y, m, d):
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Finnhub live fetcher — mocked HTTP
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock
from sentiment.economic_calendar import FinnhubCalendar, get_live_events


class TestFinnhubCalendarParsing:
    def _fake_response(self, items):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"economicCalendar": items}
        return resp

    def test_parse_fomc_bumps_to_extreme(self):
        cal = FinnhubCalendar(api_key="test-key")
        items = [
            {"country": "US", "event": "FOMC Meeting Statement",
             "impact": "high", "time": "2026-04-30 18:00:00"},
        ]
        with patch("sentiment.economic_calendar.requests.get",
                   return_value=self._fake_response(items)):
            events = cal.fetch_events(datetime.date(2026, 4, 30))
        assert len(events) == 1
        assert events[0].risk == "extreme"
        assert "FOMC" in events[0].name

    def test_parse_cpi_bumps_to_high(self):
        cal = FinnhubCalendar(api_key="test-key")
        items = [
            {"country": "US", "event": "CPI m/m",
             "impact": "medium", "time": "2026-04-10 12:30:00"},
        ]
        with patch("sentiment.economic_calendar.requests.get",
                   return_value=self._fake_response(items)):
            events = cal.fetch_events(datetime.date(2026, 4, 10))
        assert len(events) == 1
        assert events[0].risk == "high"

    def test_parse_filters_non_us(self):
        cal = FinnhubCalendar(api_key="test-key")
        items = [
            {"country": "JP", "event": "GDP", "impact": "high", "time": "2026-04-10 00:00:00"},
            {"country": "US", "event": "Retail Sales", "impact": "medium", "time": "2026-04-10 12:30:00"},
        ]
        with patch("sentiment.economic_calendar.requests.get",
                   return_value=self._fake_response(items)):
            events = cal.fetch_events(datetime.date(2026, 4, 10))
        assert len(events) == 1
        assert "Retail" in events[0].name

    def test_api_failure_returns_empty(self):
        cal = FinnhubCalendar(api_key="test-key")
        with patch("sentiment.economic_calendar.requests.get",
                   side_effect=RuntimeError("boom")):
            events = cal.fetch_events(datetime.date(2026, 4, 10))
        assert events == []

    def test_missing_api_key_raises(self):
        with patch("config.FINNHUB_API_KEY", ""):
            with pytest.raises(ValueError):
                FinnhubCalendar(api_key="")


class TestGetLiveEvents:
    def test_falls_back_to_hardcoded_when_finnhub_empty(self):
        """No live data → hardcoded calendar is returned."""
        fake_cal = MagicMock()
        fake_cal.fetch_events.return_value = []
        events = get_live_events(datetime.date(2024, 1, 31), calendar=fake_cal)
        # 2024-01-31 is a known FOMC date in the hardcoded calendar
        assert any(e.risk == "extreme" for e in events)

    def test_uses_finnhub_when_available(self):
        fake_cal = MagicMock()
        fake_cal.fetch_events.return_value = [
            EconomicEvent(
                date=datetime.date(2026, 4, 15),
                name="Live CPI", risk="high", time_ct="07:30",
            )
        ]
        events = get_live_events(datetime.date(2026, 4, 15), calendar=fake_cal)
        assert len(events) == 1
        assert events[0].name == "Live CPI"
