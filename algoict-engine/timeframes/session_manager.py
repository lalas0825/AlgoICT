"""
timeframes/session_manager.py
==============================
Kill zone detection and session range calculation for ICT strategies.

All kill zones are defined in US/Central (CT) in config.py.
All input timestamps must be in US/Central timezone.

Kill Zones (CT):
    asian:          8:00 PM – 12:00 AM CT
    london:         2:00 AM – 5:00 AM CT
    ny_am:          8:30 AM – 11:00 AM CT  (NY AM session — primary)
    silver_bullet:  10:00 AM – 11:00 AM CT
    ny_pm:          1:30 PM – 3:00 PM CT

Session Ranges:
    Asian range:    7:00 PM – 12:00 AM CT of prior evening
    London session: 2:00 AM – 5:00 AM CT
"""

import datetime
import logging

import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

logger = logging.getLogger(__name__)

_CT = "US/Central"


class SessionManager:
    """
    Determines whether a timestamp falls inside a named kill zone and
    calculates session high/low ranges for ICT context.

    All public methods accept timezone-aware pd.Timestamp in US/Central.
    """

    # ------------------------------------------------------------------ #
    # Kill Zone detection                                                  #
    # ------------------------------------------------------------------ #

    def is_kill_zone(self, timestamp: pd.Timestamp, zone: str) -> bool:
        """
        Return True if *timestamp* falls within the named kill zone.

        Parameters
        ----------
        timestamp : pd.Timestamp — must be timezone-aware (US/Central)
        zone      : str — one of 'asian', 'london', 'ny_am', 'silver_bullet', 'ny_pm'

        Returns
        -------
        bool
        """
        if zone not in config.KILL_ZONES:
            raise ValueError(
                f"Unknown zone '{zone}'. Valid: {list(config.KILL_ZONES.keys())}"
            )

        ts_ct = self._to_ct(timestamp)
        zone_cfg = config.KILL_ZONES[zone]
        start_h, start_m = zone_cfg["start"]
        end_h, end_m = zone_cfg["end"]

        bar_time = ts_ct.time()

        start_time = datetime.time(start_h, start_m)
        end_time = datetime.time(end_h, end_m)

        # Asian zone wraps midnight (20:00 → 00:00)
        if zone == "asian":
            return bar_time >= start_time or bar_time < end_time

        # All other zones are within a single calendar day
        return start_time <= bar_time < end_time

    # ------------------------------------------------------------------ #
    # Session range calculation                                            #
    # ------------------------------------------------------------------ #

    def get_asian_range(
        self, date: datetime.date, df_1min: pd.DataFrame
    ) -> tuple[float, float]:
        """
        Calculate the Asian session high/low for the evening preceding *date*.

        Asian range: 7:00 PM CT (prior evening) to 12:00 AM CT (midnight).
        Returns (high, low). Returns (nan, nan) if no data available.

        Parameters
        ----------
        date    : datetime.date — the trading day you want the Asian range for
        df_1min : pd.DataFrame — full 1-min history with CT DatetimeIndex
        """
        # Prior evening: 19:00 CT to 23:59 CT of the *previous* calendar day
        prior_day = date - datetime.timedelta(days=1)

        start = pd.Timestamp(prior_day, tz=_CT).replace(hour=19, minute=0)
        end = pd.Timestamp(date, tz=_CT).replace(hour=0, minute=0)

        session = df_1min.loc[start:end]
        if session.empty:
            logger.debug("No Asian range data for %s", date)
            return (float("nan"), float("nan"))

        return (float(session["high"].max()), float(session["low"].min()))

    def get_london_session(
        self, date: datetime.date, df_1min: pd.DataFrame
    ) -> tuple[float, float]:
        """
        Calculate the London session high/low for *date*.

        London window: 2:00 AM CT to 5:00 AM CT.
        Returns (high, low). Returns (nan, nan) if no data available.

        Parameters
        ----------
        date    : datetime.date — the trading day
        df_1min : pd.DataFrame — full 1-min history with CT DatetimeIndex
        """
        start = pd.Timestamp(date, tz=_CT).replace(hour=2, minute=0)
        end = pd.Timestamp(date, tz=_CT).replace(hour=4, minute=59)  # exclusive of 05:00

        session = df_1min.loc[start:end]
        if session.empty:
            logger.debug("No London session data for %s", date)
            return (float("nan"), float("nan"))

        return (float(session["high"].max()), float(session["low"].min()))

    def get_ny_am_session(
        self, date: datetime.date, df_1min: pd.DataFrame
    ) -> tuple[float, float]:
        """
        Calculate the NY AM session (8:30-11:00 CT) high/low for *date*.
        Convenience helper for confluence checks.
        """
        start = pd.Timestamp(date, tz=_CT).replace(hour=8, minute=30)
        end = pd.Timestamp(date, tz=_CT).replace(hour=11, minute=0)

        session = df_1min.loc[start:end]
        if session.empty:
            return (float("nan"), float("nan"))

        return (float(session["high"].max()), float(session["low"].min()))

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_ct(ts: pd.Timestamp) -> pd.Timestamp:
        """Convert *ts* to US/Central. If already CT, no-op."""
        if ts.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware")
        if str(ts.tz) != _CT:
            return ts.tz_convert(_CT)
        return ts
