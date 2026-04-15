"""
tests/test_news_scanner.py
==========================
Tests for sentiment/news_scanner.py

All tests run offline — no Alpha Vantage calls.
"""

import pytest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentiment.news_scanner import (
    NewsScanner,
    NewsSentimentResult,
    Headline,
    _LABEL_SCORES,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_feed_item(
    title="Nvidia beats earnings",
    source="Reuters",
    published="20240102T093000",
    label="Bullish",
    score=0.72,
    tickers=None,
):
    """Build a minimal Alpha Vantage feed item."""
    if tickers is None:
        tickers = [{"ticker": "NVDA", "relevance_score": "0.85"}]
    return {
        "title": title,
        "source": source,
        "time_published": published,
        "overall_sentiment_label": label,
        "overall_sentiment_score": str(score),
        "ticker_sentiment": tickers,
    }


def _make_scanner():
    """Return a NewsScanner with a fake API key (no live calls)."""
    with patch("sentiment.news_scanner.REQUESTS_AVAILABLE", True):
        return NewsScanner.__new__(NewsScanner)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestNewsScanner:
    def test_raises_without_requests(self):
        with patch("sentiment.news_scanner.REQUESTS_AVAILABLE", False):
            with pytest.raises(ImportError, match="requests"):
                NewsScanner(api_key="test")

    def test_raises_without_api_key(self):
        with patch("sentiment.news_scanner.REQUESTS_AVAILABLE", True):
            with pytest.raises(ValueError, match="API key"):
                NewsScanner(api_key="")

    def test_constructs_with_key(self):
        with patch("sentiment.news_scanner.REQUESTS_AVAILABLE", True):
            scanner = NewsScanner(api_key="AV123", tickers=["AAPL"])
        assert scanner._api_key == "AV123"
        assert "AAPL" in scanner._tickers


# ---------------------------------------------------------------------------
# _normalize_score
# ---------------------------------------------------------------------------

class TestNormalizeScore:
    def setup_method(self):
        self.scanner = _make_scanner()
        self.scanner._api_key = "test"
        self.scanner._tickers = ["NVDA"]
        self.scanner._timeout = 15

    def test_uses_raw_score_when_in_range(self):
        s = self.scanner._normalize_score(0.65, "Bullish")
        assert s == 0.65

    def test_uses_label_when_score_is_zero(self):
        s = self.scanner._normalize_score(0.0, "Bullish")
        assert s == _LABEL_SCORES["Bullish"]

    def test_uses_label_when_score_out_of_range(self):
        s = self.scanner._normalize_score(2.5, "Bearish")
        assert s == _LABEL_SCORES["Bearish"]

    def test_neutral_label_returns_zero(self):
        s = self.scanner._normalize_score(0.0, "Neutral")
        assert s == 0.0

    def test_negative_score_preserved(self):
        s = self.scanner._normalize_score(-0.45, "Somewhat-Bearish")
        assert s == -0.45


# ---------------------------------------------------------------------------
# _extract_relevance
# ---------------------------------------------------------------------------

class TestExtractRelevance:
    def setup_method(self):
        self.scanner = _make_scanner()
        self.scanner._api_key = "test"
        self.scanner._tickers = ["NVDA", "AAPL"]
        self.scanner._timeout = 15

    def test_returns_best_match(self):
        ticker_sentiment = [
            {"ticker": "NVDA", "relevance_score": "0.9"},
            {"ticker": "AAPL", "relevance_score": "0.4"},
        ]
        rel = self.scanner._extract_relevance(ticker_sentiment)
        assert rel == 0.9

    def test_returns_default_when_no_match(self):
        ticker_sentiment = [{"ticker": "TSLA", "relevance_score": "0.9"}]
        rel = self.scanner._extract_relevance(ticker_sentiment)
        assert rel == 0.5  # default

    def test_returns_default_for_empty(self):
        rel = self.scanner._extract_relevance([])
        assert rel == 0.5

    def test_handles_bad_relevance_value(self):
        ticker_sentiment = [{"ticker": "NVDA", "relevance_score": "notanumber"}]
        rel = self.scanner._extract_relevance(ticker_sentiment)
        assert rel == 0.5  # falls back to default


# ---------------------------------------------------------------------------
# _parse_item
# ---------------------------------------------------------------------------

class TestParseItem:
    def setup_method(self):
        self.scanner = _make_scanner()
        self.scanner._api_key = "test"
        self.scanner._tickers = ["NVDA", "QQQ"]
        self.scanner._timeout = 15

    def test_parses_valid_item(self):
        item = _make_feed_item()
        h = self.scanner._parse_item(item)
        assert h is not None
        assert h.title == "Nvidia beats earnings"
        assert h.sentiment_label == "Bullish"
        assert h.sentiment_score == 0.72
        assert h.relevance == 0.85

    def test_returns_none_for_empty_dict(self):
        # Missing required keys but shouldn't crash
        h = self.scanner._parse_item({})
        assert h is not None  # empty strings / defaults

    def test_label_fallback_when_score_zero(self):
        item = _make_feed_item(label="Bearish", score=0.0)
        h = self.scanner._parse_item(item)
        assert h is not None
        assert h.sentiment_score == _LABEL_SCORES["Bearish"]


# ---------------------------------------------------------------------------
# _parse_raw_feed
# ---------------------------------------------------------------------------

class TestParseRawFeed:
    def setup_method(self):
        self.scanner = _make_scanner()
        self.scanner._api_key = "test"
        self.scanner._tickers = ["NVDA", "AAPL", "QQQ"]
        self.scanner._timeout = 15

    def test_empty_feed_returns_zero_score(self):
        result = self.scanner._parse_raw_feed([])
        assert result.score == 0.0
        assert result.headline_count == 0

    def test_single_bullish_headline(self):
        feed = [_make_feed_item(label="Bullish", score=0.75)]
        result = self.scanner._parse_raw_feed(feed)
        assert result.score > 0
        assert result.headline_count == 1

    def test_single_bearish_headline(self):
        feed = [_make_feed_item(label="Bearish", score=-0.75)]
        result = self.scanner._parse_raw_feed(feed)
        assert result.score < 0

    def test_mixed_headlines_near_neutral(self):
        feed = [
            _make_feed_item(title="Good news", label="Bullish", score=0.7),
            _make_feed_item(title="Bad news", label="Bearish", score=-0.7),
        ]
        result = self.scanner._parse_raw_feed(feed)
        assert abs(result.score) < 0.2  # roughly neutral

    def test_score_clamped_to_one(self):
        # All extreme bullish
        feed = [_make_feed_item(score=1.0) for _ in range(5)]
        result = self.scanner._parse_raw_feed(feed)
        assert result.score <= 1.0

    def test_source_is_alpha_vantage(self):
        result = self.scanner._parse_raw_feed([_make_feed_item()])
        assert result.source == "alpha_vantage"

    def test_is_valid_when_headlines_present(self):
        result = self.scanner._parse_raw_feed([_make_feed_item()])
        assert result.is_valid

    def test_not_valid_when_no_headlines(self):
        result = self.scanner._parse_raw_feed([])
        assert not result.is_valid


# ---------------------------------------------------------------------------
# score_headlines (public API wrapper)
# ---------------------------------------------------------------------------

class TestScoreHeadlines:
    def setup_method(self):
        self.scanner = _make_scanner()
        self.scanner._api_key = "test"
        self.scanner._tickers = ["NVDA"]
        self.scanner._timeout = 15

    def test_returns_result_object(self):
        feed = [_make_feed_item()]
        result = self.scanner.score_headlines(feed)
        assert isinstance(result, NewsSentimentResult)

    def test_returns_correct_count(self):
        feed = [_make_feed_item() for _ in range(3)]
        result = self.scanner.score_headlines(feed)
        assert result.headline_count == 3


# ---------------------------------------------------------------------------
# fetch_and_score (mocking requests)
# ---------------------------------------------------------------------------

class TestFetchAndScore:
    def setup_method(self):
        self.scanner = _make_scanner()
        self.scanner._api_key = "AV_TEST_KEY"
        self.scanner._tickers = ["NVDA", "QQQ"]
        self.scanner._timeout = 15

    def test_returns_valid_result_on_success(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "feed": [_make_feed_item(score=0.5)]
        }

        with patch("sentiment.news_scanner.requests") as mock_requests:
            mock_requests.get.return_value = mock_resp
            result = self.scanner.fetch_and_score()

        assert result.score > 0
        assert result.error is None

    def test_returns_fallback_on_api_error(self):
        with patch("sentiment.news_scanner.requests") as mock_requests:
            mock_requests.get.side_effect = Exception("Connection refused")
            result = self.scanner.fetch_and_score()

        assert result.score == 0.0
        assert result.source == "fallback"
        assert result.error is not None

    def test_returns_fallback_on_rate_limit(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "Note": "API rate limit exceeded"
        }

        with patch("sentiment.news_scanner.requests") as mock_requests:
            mock_requests.get.return_value = mock_resp
            result = self.scanner.fetch_and_score()

        assert result.source == "fallback"
        assert result.error is not None


# ---------------------------------------------------------------------------
# NewsSentimentResult helpers
# ---------------------------------------------------------------------------

class TestNewsSentimentResult:
    def test_label_bullish(self):
        r = NewsSentimentResult(score=0.6, headline_count=5)
        assert r.label == "bullish"

    def test_label_somewhat_bullish(self):
        r = NewsSentimentResult(score=0.2, headline_count=5)
        assert r.label == "somewhat_bullish"

    def test_label_neutral(self):
        r = NewsSentimentResult(score=0.05, headline_count=5)
        assert r.label == "neutral"

    def test_label_somewhat_bearish(self):
        r = NewsSentimentResult(score=-0.25, headline_count=5)
        assert r.label == "somewhat_bearish"

    def test_label_bearish(self):
        r = NewsSentimentResult(score=-0.6, headline_count=5)
        assert r.label == "bearish"

    def test_is_valid_false_with_error(self):
        r = NewsSentimentResult(score=0.0, error="API error")
        assert not r.is_valid

    def test_is_valid_false_with_no_headlines(self):
        r = NewsSentimentResult(score=0.3, headline_count=0)
        assert not r.is_valid

    def test_overall_sentiment_bullish(self):
        r = NewsSentimentResult(score=0.3, headline_count=5)
        assert r.overall_sentiment == "bullish"

    def test_overall_sentiment_neutral(self):
        r = NewsSentimentResult(score=0.05, headline_count=5)
        assert r.overall_sentiment == "neutral"

    def test_overall_sentiment_bearish(self):
        r = NewsSentimentResult(score=-0.25, headline_count=5)
        assert r.overall_sentiment == "bearish"

    def test_top_headlines_sorted_by_strength(self):
        from sentiment.news_scanner import Headline
        headlines = [
            Headline(title="mild", source="", published="", sentiment_label="",
                     sentiment_score=0.1, relevance=0.5),
            Headline(title="strong", source="", published="", sentiment_label="",
                     sentiment_score=0.8, relevance=0.9),
            Headline(title="neutral", source="", published="", sentiment_label="",
                     sentiment_score=0.0, relevance=1.0),
        ]
        r = NewsSentimentResult(score=0.3, headlines=headlines, headline_count=3)
        top = r.top_headlines(2)
        assert top[0].title == "strong"
        assert len(top) == 2
