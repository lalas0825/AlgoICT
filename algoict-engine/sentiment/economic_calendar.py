"""
sentiment/economic_calendar.py
================================
Hardcoded economic calendar for 2019-2025.

Provides get_event_risk(date) -> str with levels:
  'none' | 'low' | 'medium' | 'high' | 'extreme'

Risk mapping:
  extreme : FOMC meeting days, Fed rate decisions
  high    : CPI, Core CPI, NFP (Non-Farm Payrolls)
  medium  : Retail Sales, GDP (Advance/Preliminary/Final), PPI, PCE, JOLTS
  low     : PMI, Consumer Confidence, Housing data, ISM

Usage:
    from sentiment.economic_calendar import get_event_risk, get_events_on_date
    risk = get_event_risk(date(2024, 1, 5))  # -> 'high' (NFP day)
"""

import datetime
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------

@dataclass
class EconomicEvent:
    date: datetime.date
    name: str
    risk: str           # 'low' | 'medium' | 'high' | 'extreme'
    time_ct: str = ""   # approximate CT release time, e.g. "07:30"
    notes: str = ""

    def __repr__(self) -> str:
        return f"EconomicEvent({self.date} {self.name!r} [{self.risk}])"


# ---------------------------------------------------------------------------
# Risk hierarchy (used when multiple events on same day)
# ---------------------------------------------------------------------------

_RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "extreme": 4}


def _max_risk(risks: list[str]) -> str:
    return max(risks, key=lambda r: _RISK_ORDER.get(r, 0))


# ---------------------------------------------------------------------------
# Hardcoded calendar
# ---------------------------------------------------------------------------
# Sources: Fed Reserve FOMC meeting schedule, BLS CPI/NFP release dates,
#          BEA GDP release dates (2019-2025).
# ---------------------------------------------------------------------------

def _d(y, m, d) -> datetime.date:
    return datetime.date(y, m, d)


# ── FOMC Meeting Days (rate decision day = Day 2 of 2-day meeting) ─────────
_FOMC: list[datetime.date] = [
    # 2019
    _d(2019, 1, 30), _d(2019, 3, 20), _d(2019, 5, 1),
    _d(2019, 6, 19), _d(2019, 7, 31), _d(2019, 9, 18),
    _d(2019, 10, 30), _d(2019, 12, 11),
    # 2020
    _d(2020, 1, 29), _d(2020, 3, 3), _d(2020, 3, 15),  # emergency cuts
    _d(2020, 4, 29), _d(2020, 6, 10), _d(2020, 7, 29),
    _d(2020, 9, 16), _d(2020, 11, 5), _d(2020, 12, 16),
    # 2021
    _d(2021, 1, 27), _d(2021, 3, 17), _d(2021, 4, 28),
    _d(2021, 6, 16), _d(2021, 7, 28), _d(2021, 9, 22),
    _d(2021, 11, 3), _d(2021, 12, 15),
    # 2022
    _d(2022, 1, 26), _d(2022, 3, 16), _d(2022, 5, 4),
    _d(2022, 6, 15), _d(2022, 7, 27), _d(2022, 9, 21),
    _d(2022, 11, 2), _d(2022, 12, 14),
    # 2023
    _d(2023, 2, 1), _d(2023, 3, 22), _d(2023, 5, 3),
    _d(2023, 6, 14), _d(2023, 7, 26), _d(2023, 9, 20),
    _d(2023, 11, 1), _d(2023, 12, 13),
    # 2024
    _d(2024, 1, 31), _d(2024, 3, 20), _d(2024, 5, 1),
    _d(2024, 6, 12), _d(2024, 7, 31), _d(2024, 9, 18),
    _d(2024, 11, 7), _d(2024, 12, 18),
    # 2025
    _d(2025, 1, 29), _d(2025, 3, 19), _d(2025, 5, 7),
    _d(2025, 6, 18), _d(2025, 7, 30), _d(2025, 9, 17),
    _d(2025, 10, 29), _d(2025, 12, 10),
]

# ── CPI Release Dates ──────────────────────────────────────────────────────
_CPI: list[datetime.date] = [
    # 2019
    _d(2019, 1, 11), _d(2019, 2, 13), _d(2019, 3, 12),
    _d(2019, 4, 10), _d(2019, 5, 10), _d(2019, 6, 12),
    _d(2019, 7, 11), _d(2019, 8, 13), _d(2019, 9, 12),
    _d(2019, 10, 10), _d(2019, 11, 13), _d(2019, 12, 11),
    # 2020
    _d(2020, 1, 14), _d(2020, 2, 13), _d(2020, 3, 11),
    _d(2020, 4, 10), _d(2020, 5, 12), _d(2020, 6, 10),
    _d(2020, 7, 14), _d(2020, 8, 12), _d(2020, 9, 11),
    _d(2020, 10, 13), _d(2020, 11, 12), _d(2020, 12, 10),
    # 2021
    _d(2021, 1, 13), _d(2021, 2, 10), _d(2021, 3, 10),
    _d(2021, 4, 13), _d(2021, 5, 12), _d(2021, 6, 10),
    _d(2021, 7, 13), _d(2021, 8, 11), _d(2021, 9, 14),
    _d(2021, 10, 13), _d(2021, 11, 10), _d(2021, 12, 10),
    # 2022
    _d(2022, 1, 12), _d(2022, 2, 10), _d(2022, 3, 10),
    _d(2022, 4, 12), _d(2022, 5, 11), _d(2022, 6, 10),
    _d(2022, 7, 13), _d(2022, 8, 10), _d(2022, 9, 13),
    _d(2022, 10, 13), _d(2022, 11, 10), _d(2022, 12, 13),
    # 2023
    _d(2023, 1, 12), _d(2023, 2, 14), _d(2023, 3, 14),
    _d(2023, 4, 12), _d(2023, 5, 10), _d(2023, 6, 13),
    _d(2023, 7, 12), _d(2023, 8, 10), _d(2023, 9, 13),
    _d(2023, 10, 12), _d(2023, 11, 14), _d(2023, 12, 12),
    # 2024
    _d(2024, 1, 11), _d(2024, 2, 13), _d(2024, 3, 12),
    _d(2024, 4, 10), _d(2024, 5, 15), _d(2024, 6, 12),
    _d(2024, 7, 11), _d(2024, 8, 14), _d(2024, 9, 11),
    _d(2024, 10, 10), _d(2024, 11, 13), _d(2024, 12, 11),
    # 2025
    _d(2025, 1, 15), _d(2025, 2, 12), _d(2025, 3, 12),
    _d(2025, 4, 10), _d(2025, 5, 13), _d(2025, 6, 11),
    _d(2025, 7, 11), _d(2025, 8, 12), _d(2025, 9, 11),
    _d(2025, 10, 15), _d(2025, 11, 13), _d(2025, 12, 10),
]

# ── NFP Release Dates (first Friday of each month, BLS) ────────────────────
_NFP: list[datetime.date] = [
    # 2019
    _d(2019, 1, 4), _d(2019, 2, 1), _d(2019, 3, 8),
    _d(2019, 4, 5), _d(2019, 5, 3), _d(2019, 6, 7),
    _d(2019, 7, 5), _d(2019, 8, 2), _d(2019, 9, 6),
    _d(2019, 10, 4), _d(2019, 11, 1), _d(2019, 12, 6),
    # 2020
    _d(2020, 1, 10), _d(2020, 2, 7), _d(2020, 3, 6),
    _d(2020, 4, 3), _d(2020, 5, 8), _d(2020, 6, 5),
    _d(2020, 7, 2), _d(2020, 8, 7), _d(2020, 9, 4),
    _d(2020, 10, 2), _d(2020, 11, 6), _d(2020, 12, 4),
    # 2021
    _d(2021, 1, 8), _d(2021, 2, 5), _d(2021, 3, 5),
    _d(2021, 4, 2), _d(2021, 5, 7), _d(2021, 6, 4),
    _d(2021, 7, 2), _d(2021, 8, 6), _d(2021, 9, 3),
    _d(2021, 10, 8), _d(2021, 11, 5), _d(2021, 12, 3),
    # 2022
    _d(2022, 1, 7), _d(2022, 2, 4), _d(2022, 3, 4),
    _d(2022, 4, 1), _d(2022, 5, 6), _d(2022, 6, 3),
    _d(2022, 7, 8), _d(2022, 8, 5), _d(2022, 9, 2),
    _d(2022, 10, 7), _d(2022, 11, 4), _d(2022, 12, 2),
    # 2023
    _d(2023, 1, 6), _d(2023, 2, 3), _d(2023, 3, 10),
    _d(2023, 4, 7), _d(2023, 5, 5), _d(2023, 6, 2),
    _d(2023, 7, 7), _d(2023, 8, 4), _d(2023, 9, 1),
    _d(2023, 10, 6), _d(2023, 11, 3), _d(2023, 12, 8),
    # 2024
    _d(2024, 1, 5), _d(2024, 2, 2), _d(2024, 3, 8),
    _d(2024, 4, 5), _d(2024, 5, 3), _d(2024, 6, 7),
    _d(2024, 7, 5), _d(2024, 8, 2), _d(2024, 9, 6),
    _d(2024, 10, 4), _d(2024, 11, 1), _d(2024, 12, 6),
    # 2025
    _d(2025, 1, 10), _d(2025, 2, 7), _d(2025, 3, 7),
    _d(2025, 4, 4), _d(2025, 5, 2), _d(2025, 6, 6),
    _d(2025, 7, 3), _d(2025, 8, 1), _d(2025, 9, 5),
    _d(2025, 10, 3), _d(2025, 11, 7), _d(2025, 12, 5),
]

# ── GDP Advance / Preliminary / Final + PCE + PPI ─────────────────────────
# medium risk events — selected major releases
_MEDIUM_EVENTS: list[tuple[datetime.date, str]] = [
    # 2019
    (_d(2019, 1, 30), "GDP Advance Q4 2018"),  # note: same day as FOMC (FOMC wins)
    (_d(2019, 2, 28), "GDP Second Q4 2018"),
    (_d(2019, 3, 28), "GDP Third Q4 2018"),
    (_d(2019, 3, 29), "PCE Feb 2019"),
    (_d(2019, 4, 26), "GDP Advance Q1 2019"),
    (_d(2019, 7, 26), "GDP Advance Q2 2019"),
    (_d(2019, 9, 26), "PCE Aug 2019"),
    (_d(2019, 10, 30), "GDP Advance Q3 2019"),
    (_d(2019, 12, 20), "PCE Nov 2019"),
    # Retail Sales (selected months)
    (_d(2019, 1, 16), "Retail Sales Dec 2018"),
    (_d(2019, 2, 15), "Retail Sales Jan 2019"),
    (_d(2019, 3, 11), "Retail Sales Feb 2019"),  # same day as CPI (CPI wins)
    (_d(2019, 4, 18), "Retail Sales Mar 2019"),
    (_d(2019, 5, 15), "Retail Sales Apr 2019"),
    (_d(2019, 6, 14), "Retail Sales May 2019"),
    (_d(2019, 7, 16), "Retail Sales Jun 2019"),
    (_d(2019, 8, 15), "Retail Sales Jul 2019"),
    (_d(2019, 9, 13), "Retail Sales Aug 2019"),
    (_d(2019, 10, 17), "Retail Sales Sep 2019"),
    (_d(2019, 11, 15), "Retail Sales Oct 2019"),
    (_d(2019, 12, 13), "Retail Sales Nov 2019"),
    # 2020
    (_d(2020, 1, 30), "GDP Advance Q4 2019"),
    (_d(2020, 4, 29), "GDP Advance Q1 2020"),
    (_d(2020, 7, 30), "GDP Advance Q2 2020"),
    (_d(2020, 10, 29), "GDP Advance Q3 2020"),
    # 2021
    (_d(2021, 1, 28), "GDP Advance Q4 2020"),
    (_d(2021, 4, 29), "GDP Advance Q1 2021"),
    (_d(2021, 7, 29), "GDP Advance Q2 2021"),
    (_d(2021, 10, 28), "GDP Advance Q3 2021"),
    # 2022
    (_d(2022, 1, 27), "GDP Advance Q4 2021"),
    (_d(2022, 4, 28), "GDP Advance Q1 2022"),
    (_d(2022, 7, 28), "GDP Advance Q2 2022"),
    (_d(2022, 10, 27), "GDP Advance Q3 2022"),
    # 2023
    (_d(2023, 1, 26), "GDP Advance Q4 2022"),
    (_d(2023, 4, 27), "GDP Advance Q1 2023"),
    (_d(2023, 7, 27), "GDP Advance Q2 2023"),
    (_d(2023, 10, 26), "GDP Advance Q3 2023"),
    # 2024
    (_d(2024, 1, 25), "GDP Advance Q4 2023"),
    (_d(2024, 4, 25), "GDP Advance Q1 2024"),
    (_d(2024, 7, 25), "GDP Advance Q2 2024"),
    (_d(2024, 10, 30), "GDP Advance Q3 2024"),
    # 2025
    (_d(2025, 1, 30), "GDP Advance Q4 2024"),
    (_d(2025, 4, 30), "GDP Advance Q1 2025"),
    (_d(2025, 7, 30), "GDP Advance Q2 2025"),
    (_d(2025, 10, 30), "GDP Advance Q3 2025"),
    # PCE (personal consumption expenditures — Fed's preferred inflation gauge)
    (_d(2022, 1, 28), "PCE Dec 2021"),
    (_d(2022, 2, 25), "PCE Jan 2022"),
    (_d(2022, 3, 31), "PCE Feb 2022"),
    (_d(2022, 4, 29), "PCE Mar 2022"),
    (_d(2022, 5, 27), "PCE Apr 2022"),
    (_d(2022, 6, 30), "PCE May 2022"),
    (_d(2022, 7, 29), "PCE Jun 2022"),
    (_d(2022, 8, 26), "PCE Jul 2022"),
    (_d(2022, 9, 30), "PCE Aug 2022"),
    (_d(2022, 10, 28), "PCE Sep 2022"),
    (_d(2022, 11, 30), "PCE Oct 2022"),
    (_d(2022, 12, 23), "PCE Nov 2022"),
    (_d(2023, 1, 27), "PCE Dec 2022"),
    (_d(2023, 2, 24), "PCE Jan 2023"),
    (_d(2023, 3, 31), "PCE Feb 2023"),
    (_d(2023, 4, 28), "PCE Mar 2023"),
    (_d(2023, 5, 26), "PCE Apr 2023"),
    (_d(2023, 6, 30), "PCE May 2023"),
    (_d(2023, 7, 28), "PCE Jun 2023"),
    (_d(2023, 8, 31), "PCE Jul 2023"),
    (_d(2023, 9, 29), "PCE Aug 2023"),
    (_d(2023, 10, 27), "PCE Sep 2023"),
    (_d(2023, 11, 30), "PCE Oct 2023"),
    (_d(2023, 12, 22), "PCE Nov 2023"),
    (_d(2024, 1, 26), "PCE Dec 2023"),
    (_d(2024, 2, 29), "PCE Jan 2024"),
    (_d(2024, 3, 29), "PCE Feb 2024"),
    (_d(2024, 4, 26), "PCE Mar 2024"),
    (_d(2024, 5, 31), "PCE Apr 2024"),
    (_d(2024, 6, 28), "PCE May 2024"),
    (_d(2024, 7, 26), "PCE Jun 2024"),
    (_d(2024, 8, 30), "PCE Jul 2024"),
    (_d(2024, 9, 27), "PCE Aug 2024"),
    (_d(2024, 10, 31), "PCE Sep 2024"),
    (_d(2024, 11, 27), "PCE Oct 2024"),
    (_d(2024, 12, 20), "PCE Nov 2024"),
    (_d(2025, 1, 31), "PCE Dec 2024"),
    (_d(2025, 2, 28), "PCE Jan 2025"),
    (_d(2025, 3, 28), "PCE Feb 2025"),
    (_d(2025, 4, 30), "PCE Mar 2025"),
    (_d(2025, 5, 30), "PCE Apr 2025"),
    (_d(2025, 6, 27), "PCE May 2025"),
    (_d(2025, 7, 31), "PCE Jun 2025"),
    (_d(2025, 8, 29), "PCE Jul 2025"),
    (_d(2025, 9, 26), "PCE Aug 2025"),
    (_d(2025, 10, 31), "PCE Sep 2025"),
    (_d(2025, 11, 26), "PCE Oct 2025"),
    (_d(2025, 12, 19), "PCE Nov 2025"),
]


# ---------------------------------------------------------------------------
# Build lookup dict: date -> list[EconomicEvent]
# ---------------------------------------------------------------------------

def _build_calendar() -> dict[datetime.date, list[EconomicEvent]]:
    cal: dict[datetime.date, list[EconomicEvent]] = {}

    for d in _FOMC:
        cal.setdefault(d, []).append(
            EconomicEvent(d, "FOMC", "extreme", "13:00", "Fed rate decision + statement")
        )

    for d in _CPI:
        cal.setdefault(d, []).append(
            EconomicEvent(d, "CPI", "high", "07:30", "Consumer Price Index")
        )

    for d in _NFP:
        cal.setdefault(d, []).append(
            EconomicEvent(d, "NFP", "high", "07:30", "Non-Farm Payrolls")
        )

    for d, name in _MEDIUM_EVENTS:
        cal.setdefault(d, []).append(
            EconomicEvent(d, name, "medium", "07:30")
        )

    return cal


_CALENDAR: dict[datetime.date, list[EconomicEvent]] = _build_calendar()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_events_on_date(date: datetime.date) -> list[EconomicEvent]:
    """Return all economic events on the given date."""
    if isinstance(date, datetime.datetime):
        date = date.date()
    return _CALENDAR.get(date, [])


def get_event_risk(date: datetime.date) -> str:
    """
    Return the highest risk level for any events on the given date.

    Returns
    -------
    'none' | 'low' | 'medium' | 'high' | 'extreme'
    """
    if isinstance(date, datetime.datetime):
        date = date.date()

    events = _CALENDAR.get(date, [])
    if not events:
        return "none"

    risk = _max_risk([e.risk for e in events])
    logger.debug("Event risk on %s: %s (%s)", date, risk, [e.name for e in events])
    return risk


def get_upcoming_events(
    from_date: datetime.date,
    days_ahead: int = 7,
) -> list[EconomicEvent]:
    """
    Return all events in the next `days_ahead` calendar days (inclusive).
    Sorted by date ascending.
    """
    if isinstance(from_date, datetime.datetime):
        from_date = from_date.date()

    results = []
    for i in range(days_ahead + 1):
        d = from_date + datetime.timedelta(days=i)
        results.extend(_CALENDAR.get(d, []))
    return sorted(results, key=lambda e: e.date)


def is_high_impact_day(date: datetime.date) -> bool:
    """True if the date has any high or extreme risk event."""
    return get_event_risk(date) in ("high", "extreme")
