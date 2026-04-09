"""
sentiment/news_scanner.py
=========================
Fetches financial news headlines and computes an aggregate sentiment score
for the NQ/tech sector using Alpha Vantage News Sentiment API.

Sentiment score ranges from -1.0 (fully bearish) to +1.0 (fully bullish).

Alpha Vantage News API (free tier: 25 requests/day):
  GET https://www.alphavantage.co/query
  ?function=NEWS_SENTIMENT
  &tickers=AAPL,MSFT,NVDA,QQQ,SPY
  &apikey=<KEY>

Usage:
    from sentiment.news_scanner import NewsScanner
    scanner = NewsScanner(api_key="YOUR_KEY")
    result = scanner.fetch_and_score()
    print(result.score)        # -1.0 to +1.0
    print(result.headlines)    # list of Headline objects
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from config import ALPHA_VANTAGE_API_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.alphavantage.co/query"

# Tickers that are most relevant to NQ/MNQ performance
_DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "QQQ"]

# Alpha Vantage sentiment label -> numeric score
_LABEL_SCORES = {
    "Bearish": -0.75,
    "Somewhat-Bearish": -0.30,
    "Neutral": 0.0,
    "Somewhat-Bullish": 0.30,
    "Bullish": 0.75,
}

# Max headlines to process (API may return 50+)
_MAX_HEADLINES = 20


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Headline:
    title: str
    source: str
    published: str          # ISO datetime string
    sentiment_label: str    # e.g. "Bullish", "Neutral"
    sentiment_score: float  # -1.0 to +1.0 (from _LABEL_SCORES or raw API score)
    relevance: float        # 0.0 to 1.0 ticker relevance score


@dataclass
class NewsSentimentResult:
    score: float                         # Aggregate -1.0 to +1.0
    headlines: list[Headline] = field(default_factory=list)
    headline_count: int = 0
    source: str = "alpha_vantage"        # "alpha_vantage" | "fallback"
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None and self.headline_count > 0

    @property
    def label(self) -> str:
        if self.score >= 0.5:
            return "bullish"
        elif self.score >= 0.15:
            return "somewhat_bullish"
        elif self.score <= -0.5:
            return "bearish"
        elif self.score <= -0.15:
            return "somewhat_bearish"
        return "neutral"


# ---------------------------------------------------------------------------
# NewsScanner
# ---------------------------------------------------------------------------

class NewsScanner:
    """
    Fetches top financial headlines and computes aggregate sentiment.

    Parameters
    ----------
    api_key : str
        Alpha Vantage API key. Falls back to ALPHA_VANTAGE_API_KEY env var.
    tickers : list[str]
        Tickers to scan. Defaults to NQ-correlated tech names.
    timeout : int
        HTTP timeout in seconds.
    """

    def __init__(
        self,
        api_key: str = ALPHA_VANTAGE_API_KEY,
        tickers: Optional[list] = None,
        timeout: int = 15,
    ):
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests package not installed. Run: pip install requests"
            )
        if not api_key:
            raise ValueError(
                "Alpha Vantage API key required. Set ALPHA_VANTAGE_API_KEY in .env"
            )

        self._api_key = api_key
        self._tickers = tickers or _DEFAULT_TICKERS
        self._timeout = timeout
        logger.info("NewsScanner initialized (tickers: %s)", self._tickers)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def fetch_and_score(self) -> NewsSentimentResult:
        """
        Fetch headlines from Alpha Vantage and return aggregate sentiment.

        Returns a NewsSentimentResult with score in [-1.0, +1.0].
        Returns score=0.0 with error set if the API call fails.
        """
        try:
            raw = self._fetch_raw()
            return self._parse_response(raw)
        except Exception as exc:
            logger.error("NewsScanner.fetch_and_score failed: %s", exc)
            return NewsSentimentResult(
                score=0.0,
                source="fallback",
                error=str(exc),
            )

    def score_headlines(self, raw_items: list) -> NewsSentimentResult:
        """
        Parse a pre-fetched list of Alpha Vantage 'feed' items.

        Useful for testing without a live API call.
        """
        return self._parse_raw_feed(raw_items)

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _fetch_raw(self) -> dict:
        """Make the Alpha Vantage API request and return raw JSON."""
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ",".join(self._tickers),
            "limit": _MAX_HEADLINES,
            "apikey": self._api_key,
        }
        resp = requests.get(_BASE_URL, params=params, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()

        if "Note" in data:
            raise RuntimeError(f"Alpha Vantage rate limit: {data['Note']}")
        if "Information" in data:
            raise RuntimeError(f"Alpha Vantage API info: {data['Information']}")
        if "feed" not in data:
            raise RuntimeError(f"Unexpected response format: {list(data.keys())}")

        return data

    def _parse_response(self, raw: dict) -> NewsSentimentResult:
        """Parse full Alpha Vantage response dict."""
        feed = raw.get("feed", [])
        return self._parse_raw_feed(feed)

    def _parse_raw_feed(self, feed: list) -> NewsSentimentResult:
        """Parse a list of feed items into a NewsSentimentResult."""
        headlines = []
        scores = []

        for item in feed[:_MAX_HEADLINES]:
            headline = self._parse_item(item)
            if headline is None:
                continue
            headlines.append(headline)
            # Weight by relevance (0.5 minimum weight so all articles count)
            weight = max(headline.relevance, 0.5)
            scores.append(headline.sentiment_score * weight)

        if not scores:
            logger.warning("NewsScanner: no valid headlines parsed")
            return NewsSentimentResult(
                score=0.0,
                headlines=[],
                headline_count=0,
                source="alpha_vantage",
            )

        # Weighted average normalized by total weight
        total_weight = sum(max(h.relevance, 0.5) for h in headlines)
        weighted_sum = sum(
            h.sentiment_score * max(h.relevance, 0.5) for h in headlines
        )
        avg_score = weighted_sum / total_weight if total_weight > 0 else 0.0
        # Clamp to [-1, +1]
        avg_score = max(-1.0, min(1.0, avg_score))

        logger.info(
            "NewsScanner: %d headlines, score=%.3f (%s)",
            len(headlines),
            avg_score,
            "bullish" if avg_score > 0 else "bearish" if avg_score < 0 else "neutral",
        )

        return NewsSentimentResult(
            score=round(avg_score, 4),
            headlines=headlines,
            headline_count=len(headlines),
            source="alpha_vantage",
        )

    def _parse_item(self, item: dict) -> Optional[Headline]:
        """Parse a single feed item. Returns None if malformed."""
        try:
            title = item.get("title", "")
            source = item.get("source", "")
            published = item.get("time_published", "")

            # Overall sentiment from API
            label = item.get("overall_sentiment_label", "Neutral")
            raw_score = float(item.get("overall_sentiment_score", 0.0))

            # Prefer API's numeric score; map to our [-1, +1] range
            # Alpha Vantage uses a slightly different scale (~0-1 per direction)
            # but overall_sentiment_score is already -1 to +1
            sentiment_score = self._normalize_score(raw_score, label)

            # Ticker relevance: use max relevance across our target tickers
            relevance = self._extract_relevance(item.get("ticker_sentiment", []))

            return Headline(
                title=title,
                source=source,
                published=published,
                sentiment_label=label,
                sentiment_score=sentiment_score,
                relevance=relevance,
            )

        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("Failed to parse headline item: %s", exc)
            return None

    def _normalize_score(self, raw_score: float, label: str) -> float:
        """
        Normalize Alpha Vantage sentiment score to [-1.0, +1.0].

        Alpha Vantage overall_sentiment_score is typically in [-1, 1].
        Use label fallback if score seems off.
        """
        if -1.0 <= raw_score <= 1.0 and raw_score != 0.0:
            return round(raw_score, 4)
        # Fallback to label mapping
        return _LABEL_SCORES.get(label, 0.0)

    def _extract_relevance(self, ticker_sentiment: list) -> float:
        """
        Extract the highest relevance score for our target tickers.
        Returns 0.5 (neutral weight) if no tickers match.
        """
        if not ticker_sentiment:
            return 0.5

        target_set = set(self._tickers)
        best = 0.5

        for ts in ticker_sentiment:
            ticker = ts.get("ticker", "")
            if ticker in target_set:
                try:
                    rel = float(ts.get("relevance_score", 0.5))
                    best = max(best, rel)
                except (ValueError, TypeError):
                    pass

        return round(best, 4)
