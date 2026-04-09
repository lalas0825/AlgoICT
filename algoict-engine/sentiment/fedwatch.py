"""
sentiment/fedwatch.py
=====================
Fetches CME FedWatch rate-cut probabilities for the next FOMC meeting.

Uses CME Group's publicly accessible FedWatch endpoint to get:
  - cut_prob: probability (0-100) of a rate cut at the next meeting
  - hold_prob: probability of hold
  - hike_prob: probability of a hike
  - hawkish_dovish_shift: change vs yesterday (+ve = more dovish)
  - next_meeting_date: string of next FOMC date

NQ/MNQ interpretation:
  - Increasing cut probability  -> risk-on, bullish for NQ
  - Decreasing cut probability  -> hawkish, bearish for NQ
  - Shift > +5%                  -> meaningful dovish move
  - Shift < -5%                  -> meaningful hawkish move

CME FedWatch URL (unofficial/public scrape target):
  https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html
  JSON: https://www.cmegroup.com/CmeWS/mvc/MktData/FedWatch/

Note: CME does not provide a free public JSON API — we scrape the public
page or use their public data endpoints. If unavailable, returns a neutral
default with error set.

Usage:
    from sentiment.fedwatch import FedWatchClient
    client = FedWatchClient()
    result = client.get_probabilities()
    print(result.cut_prob)          # e.g. 68.5
    print(result.shift_label)       # "dovish" | "hawkish" | "neutral"
"""

import logging
from dataclasses import dataclass
from typing import Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Threshold to call a shift meaningful
_SHIFT_DOVISH_THRESHOLD = 5.0    # % point increase in cut prob = dovish
_SHIFT_HAWKISH_THRESHOLD = -5.0  # % point decrease in cut prob = hawkish

# CME public data endpoint (subject to change)
_CME_BASE = "https://www.cmegroup.com"
_FEDWATCH_ENDPOINT = "/CmeWS/mvc/MktData/FedWatch/"

_DEFAULT_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FedWatchResult:
    """Probability snapshot for the next FOMC meeting."""

    cut_prob: float         # 0-100: probability of a rate cut
    hold_prob: float        # 0-100: probability of hold
    hike_prob: float        # 0-100: probability of a hike
    daily_change: float     # Change in cut_prob vs yesterday (positive = more dovish)
    next_meeting_date: str  # "YYYY-MM-DD" or human-readable
    source: str = "cme"     # "cme" | "fallback"
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None

    @property
    def shift_label(self) -> str:
        """'dovish' | 'hawkish' | 'neutral'"""
        if self.daily_change >= _SHIFT_DOVISH_THRESHOLD:
            return "dovish"
        elif self.daily_change <= _SHIFT_HAWKISH_THRESHOLD:
            return "hawkish"
        return "neutral"

    @property
    def sentiment_score(self) -> float:
        """
        Convert FedWatch data into a -1.0 to +1.0 score for NQ.
        High cut probability = bullish for NQ = +ve score.
        """
        # Normalize cut_prob from [0, 100] -> [-1, +1]
        # 50% = neutral (0.0), 100% = +1.0, 0% = -1.0
        base = (self.cut_prob - 50.0) / 50.0
        # Add shift momentum (scaled down)
        momentum = self.daily_change / 100.0
        return round(max(-1.0, min(1.0, base + momentum)), 4)

    def __repr__(self) -> str:
        return (
            f"FedWatchResult(cut={self.cut_prob:.1f}% "
            f"hold={self.hold_prob:.1f}% "
            f"shift={self.daily_change:+.1f}% "
            f"[{self.shift_label}])"
        )


# ---------------------------------------------------------------------------
# FedWatchClient
# ---------------------------------------------------------------------------

class FedWatchClient:
    """
    Fetches CME FedWatch rate probabilities.

    Since CME does not offer a free public JSON API, this client:
      1. Attempts to parse the CME public data endpoint.
      2. Falls back to a neutral result on any error.

    For production, consider a paid data provider (e.g. Quandl, FRED)
    or subscribe to CME DataMine for reliable access.

    Parameters
    ----------
    timeout : int
        HTTP timeout in seconds.
    """

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT):
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests package not installed. Run: pip install requests"
            )
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; AlgoICT/1.0; "
                "+https://github.com/algoict)"
            ),
            "Accept": "application/json, text/html, */*",
        })
        logger.info("FedWatchClient initialized")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_probabilities(self) -> FedWatchResult:
        """
        Fetch and return FedWatch probabilities for the next FOMC meeting.

        Returns a neutral FedWatchResult with error set if the fetch fails.
        """
        try:
            raw = self._fetch_cme()
            return self._parse_cme_response(raw)
        except Exception as exc:
            logger.warning("FedWatchClient.get_probabilities failed: %s", exc)
            return self._neutral_fallback(str(exc))

    def get_probabilities_from_raw(self, raw: dict) -> FedWatchResult:
        """
        Parse a pre-fetched CME response dict.

        Useful for testing without a live API call.
        """
        try:
            return self._parse_cme_response(raw)
        except Exception as exc:
            return self._neutral_fallback(str(exc))

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _fetch_cme(self) -> dict:
        """Fetch raw JSON from CME FedWatch endpoint."""
        url = _CME_BASE + _FEDWATCH_ENDPOINT
        resp = self._session.get(url, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _parse_cme_response(self, raw: dict) -> FedWatchResult:
        """
        Parse CME FedWatch JSON response.

        CME response structure (approximate):
        {
            "nextMeetingDate": "2024-03-20",
            "probabilities": [
                {"label": "Cut", "probability": 68.5},
                {"label": "Hold", "probability": 30.0},
                {"label": "Hike", "probability": 1.5},
            ],
            "previousProbabilities": [
                {"label": "Cut", "probability": 63.2},
                ...
            ]
        }

        The exact schema varies — we handle multiple known formats.
        """
        # Try to extract next meeting date
        next_meeting = raw.get("nextMeetingDate", "") or raw.get("meetingDate", "")

        # Parse current probabilities
        probs = raw.get("probabilities", [])
        prev_probs = raw.get("previousProbabilities", [])

        cut_prob, hold_prob, hike_prob = self._extract_probs(probs)
        prev_cut, _, _ = self._extract_probs(prev_probs)

        daily_change = round(cut_prob - prev_cut, 2)

        return FedWatchResult(
            cut_prob=cut_prob,
            hold_prob=hold_prob,
            hike_prob=hike_prob,
            daily_change=daily_change,
            next_meeting_date=next_meeting,
            source="cme",
        )

    def _extract_probs(self, probs_list: list) -> tuple:
        """
        Extract (cut, hold, hike) from a list of probability dicts.

        Handles multiple known label formats.
        """
        cut = hold = hike = 0.0

        for item in probs_list:
            label = str(item.get("label", "")).lower()
            try:
                val = float(item.get("probability", 0.0))
            except (ValueError, TypeError):
                val = 0.0

            if "cut" in label or "decrease" in label or "lower" in label:
                cut += val
            elif "hike" in label or "increase" in label or "raise" in label:
                hike += val
            elif "hold" in label or "unchanged" in label or "no change" in label:
                hold += val

        # If all zeros, check for numeric keys (some formats use 0/-25/-50)
        if cut == 0 and hold == 0 and hike == 0:
            cut, hold, hike = self._extract_probs_numeric(probs_list)

        return round(cut, 2), round(hold, 2), round(hike, 2)

    def _extract_probs_numeric(self, probs_list: list) -> tuple:
        """
        Handle numeric-keyed formats where basis-point changes are the keys.
        e.g. {"bpChange": -25, "probability": 68.5}
        """
        cut = hold = hike = 0.0

        for item in probs_list:
            bp = item.get("bpChange", 0)
            try:
                val = float(item.get("probability", 0.0))
                bp = int(bp)
            except (ValueError, TypeError):
                continue

            if bp < 0:
                cut += val
            elif bp > 0:
                hike += val
            else:
                hold += val

        return cut, hold, hike

    def _neutral_fallback(self, error: str) -> FedWatchResult:
        """Return a neutral result when data is unavailable."""
        logger.warning("FedWatch using neutral fallback: %s", error)
        return FedWatchResult(
            cut_prob=50.0,
            hold_prob=45.0,
            hike_prob=5.0,
            daily_change=0.0,
            next_meeting_date="unknown",
            source="fallback",
            error=error,
        )
