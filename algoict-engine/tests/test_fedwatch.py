"""
tests/test_fedwatch.py
======================
Tests for sentiment/fedwatch.py

All tests run offline — no CME calls.
"""

import pytest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentiment.fedwatch import FedWatchClient, FedWatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    """FedWatchClient with requests mocked."""
    with patch("sentiment.fedwatch.REQUESTS_AVAILABLE", True):
        client = FedWatchClient.__new__(FedWatchClient)
        client._timeout = 15
        mock_session = MagicMock()
        client._session = mock_session
        return client


def _label_response(cut=68.5, hold=30.0, hike=1.5, prev_cut=63.2):
    """Build a CME-style response with label-based probabilities."""
    return {
        "nextMeetingDate": "2024-03-20",
        "probabilities": [
            {"label": "Cut", "probability": cut},
            {"label": "Hold", "probability": hold},
            {"label": "Hike", "probability": hike},
        ],
        "previousProbabilities": [
            {"label": "Cut", "probability": prev_cut},
            {"label": "Hold", "probability": 35.0},
            {"label": "Hike", "probability": 1.8},
        ],
    }


def _bp_response(cut=70.0, hold=28.0, hike=2.0, prev_cut=65.0):
    """Build a CME-style response with basis-point change format."""
    return {
        "nextMeetingDate": "2024-05-01",
        "probabilities": [
            {"bpChange": -25, "probability": cut},
            {"bpChange": 0, "probability": hold},
            {"bpChange": 25, "probability": hike},
        ],
        "previousProbabilities": [
            {"bpChange": -25, "probability": prev_cut},
            {"bpChange": 0, "probability": 33.0},
            {"bpChange": 25, "probability": 2.0},
        ],
    }


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestFedWatchClientConstructor:
    def test_raises_without_requests(self):
        with patch("sentiment.fedwatch.REQUESTS_AVAILABLE", False):
            with pytest.raises(ImportError, match="requests"):
                FedWatchClient()

    def test_constructs_ok(self):
        with patch("sentiment.fedwatch.REQUESTS_AVAILABLE", True):
            with patch("sentiment.fedwatch.requests"):
                client = FedWatchClient(timeout=10)
        assert client._timeout == 10


# ---------------------------------------------------------------------------
# _extract_probs — label format
# ---------------------------------------------------------------------------

class TestExtractProbsLabel:
    def setup_method(self):
        self.client = _make_client()

    def test_extracts_cut_hold_hike(self):
        probs = [
            {"label": "Cut", "probability": 68.5},
            {"label": "Hold", "probability": 30.0},
            {"label": "Hike", "probability": 1.5},
        ]
        cut, hold, hike = self.client._extract_probs(probs)
        assert cut == 68.5
        assert hold == 30.0
        assert hike == 1.5

    def test_handles_lowercase_labels(self):
        probs = [
            {"label": "cut", "probability": 70.0},
            {"label": "hold", "probability": 29.0},
            {"label": "hike", "probability": 1.0},
        ]
        cut, hold, hike = self.client._extract_probs(probs)
        assert cut == 70.0

    def test_handles_alternative_label_decrease(self):
        probs = [{"label": "Decrease", "probability": 75.0}]
        cut, hold, hike = self.client._extract_probs(probs)
        assert cut == 75.0

    def test_handles_unchanged_label(self):
        probs = [{"label": "Unchanged", "probability": 80.0}]
        cut, hold, hike = self.client._extract_probs(probs)
        assert hold == 80.0

    def test_empty_list_returns_zeros(self):
        cut, hold, hike = self.client._extract_probs([])
        assert cut == 0.0 and hold == 0.0 and hike == 0.0


# ---------------------------------------------------------------------------
# _extract_probs_numeric — bp format
# ---------------------------------------------------------------------------

class TestExtractProbsNumeric:
    def setup_method(self):
        self.client = _make_client()

    def test_negative_bp_is_cut(self):
        probs = [{"bpChange": -25, "probability": 68.5}]
        cut, hold, hike = self.client._extract_probs_numeric(probs)
        assert cut == 68.5

    def test_zero_bp_is_hold(self):
        probs = [{"bpChange": 0, "probability": 30.0}]
        cut, hold, hike = self.client._extract_probs_numeric(probs)
        assert hold == 30.0

    def test_positive_bp_is_hike(self):
        probs = [{"bpChange": 25, "probability": 2.0}]
        cut, hold, hike = self.client._extract_probs_numeric(probs)
        assert hike == 2.0


# ---------------------------------------------------------------------------
# _parse_cme_response
# ---------------------------------------------------------------------------

class TestParseCmeResponse:
    def setup_method(self):
        self.client = _make_client()

    def test_parses_label_format(self):
        raw = _label_response(cut=68.5, prev_cut=63.2)
        result = self.client._parse_cme_response(raw)
        assert result.cut_prob == 68.5
        assert result.hold_prob == 30.0
        assert result.hike_prob == 1.5
        assert result.next_meeting_date == "2024-03-20"
        assert result.source == "cme"

    def test_daily_change_positive(self):
        raw = _label_response(cut=68.5, prev_cut=63.2)
        result = self.client._parse_cme_response(raw)
        assert abs(result.daily_change - 5.3) < 0.01

    def test_daily_change_negative(self):
        raw = _label_response(cut=60.0, prev_cut=68.0)
        result = self.client._parse_cme_response(raw)
        assert result.daily_change < 0

    def test_parses_bp_format(self):
        raw = _bp_response(cut=70.0, prev_cut=65.0)
        result = self.client._parse_cme_response(raw)
        assert result.cut_prob == 70.0
        assert abs(result.daily_change - 5.0) < 0.01

    def test_missing_prev_probs_zero_change(self):
        raw = {
            "nextMeetingDate": "2024-03-20",
            "probabilities": [
                {"label": "Cut", "probability": 68.5},
            ],
        }
        result = self.client._parse_cme_response(raw)
        assert result.daily_change == 68.5  # prev was 0


# ---------------------------------------------------------------------------
# FedWatchResult helpers
# ---------------------------------------------------------------------------

class TestFedWatchResult:
    def test_shift_label_dovish(self):
        r = FedWatchResult(50, 45, 5, daily_change=6.0, next_meeting_date="")
        assert r.shift_label == "dovish"

    def test_shift_label_hawkish(self):
        r = FedWatchResult(50, 45, 5, daily_change=-6.0, next_meeting_date="")
        assert r.shift_label == "hawkish"

    def test_shift_label_neutral(self):
        r = FedWatchResult(50, 45, 5, daily_change=2.0, next_meeting_date="")
        assert r.shift_label == "neutral"

    def test_sentiment_score_bullish_high_cut_prob(self):
        # 90% cut prob = bullish for NQ
        r = FedWatchResult(90, 9, 1, daily_change=0.0, next_meeting_date="")
        assert r.sentiment_score > 0.5

    def test_sentiment_score_bearish_low_cut_prob(self):
        # 10% cut prob = hawkish = bearish for NQ
        r = FedWatchResult(10, 85, 5, daily_change=0.0, next_meeting_date="")
        assert r.sentiment_score < -0.5

    def test_sentiment_score_neutral_at_50(self):
        r = FedWatchResult(50, 45, 5, daily_change=0.0, next_meeting_date="")
        assert abs(r.sentiment_score) < 0.2

    def test_is_valid_no_error(self):
        r = FedWatchResult(50, 45, 5, daily_change=0.0, next_meeting_date="2024-03-20")
        assert r.is_valid

    def test_is_valid_false_with_error(self):
        r = FedWatchResult(50, 45, 5, daily_change=0.0, next_meeting_date="", error="timeout")
        assert not r.is_valid


# ---------------------------------------------------------------------------
# get_probabilities — with mocked HTTP
# ---------------------------------------------------------------------------

class TestGetProbabilities:
    def setup_method(self):
        self.client = _make_client()

    def test_success_returns_valid_result(self):
        raw = _label_response()
        self.client._fetch_cme = MagicMock(return_value=raw)
        result = self.client.get_probabilities()
        assert result.is_valid
        assert result.cut_prob == 68.5

    def test_network_error_returns_fallback(self):
        self.client._fetch_cme = MagicMock(side_effect=Exception("Timeout"))
        result = self.client.get_probabilities()
        assert result.source == "fallback"
        assert result.cut_prob == 50.0
        assert result.error is not None

    def test_get_probabilities_from_raw(self):
        raw = _label_response()
        result = self.client.get_probabilities_from_raw(raw)
        assert result.cut_prob == 68.5

    def test_get_probabilities_from_raw_bad_data(self):
        result = self.client.get_probabilities_from_raw({"bad": "data"})
        # Should not crash; returns some result
        assert result is not None
