"""
tests/test_swc_engine.py
========================
Tests for sentiment/swc_engine.py and sentiment/mood_synthesizer.py

All tests run offline — no Claude API calls.
"""

import datetime
import pytest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentiment.swc_engine import SWCEngine, run_premarket_scan
from sentiment.mood_synthesizer import (
    MoodSynthesizer,
    DailyMoodReport,
    MarketMood,
)
from sentiment.news_scanner import NewsSentimentResult
from sentiment.fedwatch import FedWatchResult


# ---------------------------------------------------------------------------
# MoodSynthesizer — constructor
# ---------------------------------------------------------------------------

class TestMoodSynthesizerConstructor:
    def test_raises_without_anthropic(self):
        with patch("sentiment.mood_synthesizer.ANTHROPIC_AVAILABLE", False):
            with pytest.raises(ImportError, match="anthropic"):
                MoodSynthesizer(api_key="sk-test")

    def test_raises_without_api_key(self):
        with patch("sentiment.mood_synthesizer.ANTHROPIC_AVAILABLE", True):
            # Patch the Anthropic class directly so __init__ doesn't try to connect
            with patch("sentiment.mood_synthesizer.anthropic", create=True) as mock_ant:
                mock_ant.Anthropic = MagicMock(return_value=MagicMock())
                with pytest.raises(ValueError, match="API key"):
                    MoodSynthesizer(api_key="")


# ---------------------------------------------------------------------------
# MoodSynthesizer — _parse_ai_response
# ---------------------------------------------------------------------------

class TestParseAiResponse:
    def _make_synth(self):
        s = MoodSynthesizer.__new__(MoodSynthesizer)
        s._model = "claude-test"
        s._client = MagicMock()
        return s

    def test_parses_clean_json(self):
        synth = self._make_synth()
        raw = '{"market_mood": "risk_on", "confidence": "high", "one_line_summary": "Bullish day", "key_risk": "CPI", "opportunity": "NQ long"}'
        result = synth._parse_ai_response(raw)
        assert result["market_mood"] == "risk_on"
        assert result["confidence"] == "high"

    def test_parses_json_with_code_fences(self):
        synth = self._make_synth()
        raw = '```json\n{"market_mood": "choppy", "confidence": "low", "one_line_summary": "Unclear", "key_risk": "FOMC", "opportunity": "None"}\n```'
        result = synth._parse_ai_response(raw)
        assert result["market_mood"] == "choppy"

    def test_raises_on_no_json(self):
        synth = self._make_synth()
        with pytest.raises(ValueError):
            synth._parse_ai_response("Sorry I cannot respond.")

    def test_invalid_market_mood_defaults_to_choppy(self):
        synth = self._make_synth()
        raw = '{"market_mood": "unknown_value", "confidence": "high", "one_line_summary": "X", "key_risk": "X", "opportunity": "X"}'
        result = synth._parse_ai_response(raw)
        assert result["market_mood"] == "choppy"

    def test_invalid_confidence_defaults_to_low(self):
        synth = self._make_synth()
        raw = '{"market_mood": "risk_on", "confidence": "extreme", "one_line_summary": "X", "key_risk": "X", "opportunity": "X"}'
        result = synth._parse_ai_response(raw)
        assert result["confidence"] == "low"


# ---------------------------------------------------------------------------
# MoodSynthesizer — _build_blackout_windows
# ---------------------------------------------------------------------------

class TestBuildBlackoutWindows:
    def _make_synth(self):
        s = MoodSynthesizer.__new__(MoodSynthesizer)
        s._model = "claude-test"
        s._client = MagicMock()
        return s

    def test_high_risk_event_creates_window(self):
        synth = self._make_synth()

        class MockEvent:
            risk = "high"
            time_ct = "07:30"

        windows = synth._build_blackout_windows([MockEvent()])
        assert len(windows) == 1
        start, end = windows[0]
        # 07:30 - 15min = 07:15, + 15min = 07:45
        assert start == "07:15"
        assert end == "07:45"

    def test_extreme_risk_creates_window(self):
        synth = self._make_synth()

        class MockEvent:
            risk = "extreme"
            time_ct = "13:00"

        windows = synth._build_blackout_windows([MockEvent()])
        assert len(windows) == 1

    def test_low_risk_event_no_window(self):
        synth = self._make_synth()

        class MockEvent:
            risk = "low"
            time_ct = "09:00"

        windows = synth._build_blackout_windows([MockEvent()])
        assert len(windows) == 0

    def test_no_time_skips_event(self):
        synth = self._make_synth()

        class MockEvent:
            risk = "high"
            time_ct = ""

        windows = synth._build_blackout_windows([MockEvent()])
        assert len(windows) == 0

    def test_dict_events_work(self):
        synth = self._make_synth()
        events = [{"risk": "high", "time_ct": "07:30"}]
        windows = synth._build_blackout_windows(events)
        assert len(windows) == 1


# ---------------------------------------------------------------------------
# MoodSynthesizer — _format_headlines (Claude prompt input)
# ---------------------------------------------------------------------------

class TestFormatHeadlines:
    def _make_synth(self):
        s = MoodSynthesizer.__new__(MoodSynthesizer)
        s._model = "claude-test"
        s._client = MagicMock()
        return s

    def test_empty_list_returns_none_marker(self):
        synth = self._make_synth()
        assert synth._format_headlines([]) == "  None"

    def test_formats_dict_headlines(self):
        synth = self._make_synth()
        out = synth._format_headlines([
            {"title": "Fed signals more cuts", "sentiment_label": "Bullish",
             "sentiment_score": 0.6},
        ])
        assert "Fed signals more cuts" in out
        assert "Bullish" in out
        assert "+0.60" in out

    def test_formats_headline_objects(self):
        from sentiment.news_scanner import Headline
        synth = self._make_synth()
        h = Headline(
            title="NVDA earnings beat", source="X", published="",
            sentiment_label="Bullish", sentiment_score=0.9, relevance=1.0,
        )
        out = synth._format_headlines([h])
        assert "NVDA earnings beat" in out

    def test_generate_passes_headlines_to_claude(self):
        """generate() must thread `headlines` into _call_claude."""
        synth = self._make_synth()
        # Stub _call_claude to capture kwargs
        captured = {}
        def _fake(**kwargs):
            captured.update(kwargs)
            return {
                "market_mood": "risk_on", "confidence": "high",
                "one_line_summary": "ok", "key_risk": "none", "opportunity": "ict",
            }
        synth._call_claude = _fake
        synth.generate(
            events=[], event_risk="none",
            headlines=[{"title": "h1", "sentiment_label": "Bullish", "sentiment_score": 0.5}],
        )
        assert "headlines" in captured
        assert len(captured["headlines"]) == 1


# ---------------------------------------------------------------------------
# MoodSynthesizer — generate_from_ai_response (offline API test)
# ---------------------------------------------------------------------------

class TestGenerateFromAiResponse:
    def _make_synth(self):
        s = MoodSynthesizer.__new__(MoodSynthesizer)
        s._model = "claude-test"
        s._client = MagicMock()
        return s

    def test_generates_report_from_response(self):
        synth = self._make_synth()
        ai_resp = '{"market_mood": "risk_on", "confidence": "high", "one_line_summary": "Bullish", "key_risk": "None", "opportunity": "NQ long"}'
        report = synth.generate_from_ai_response(
            ai_response=ai_resp,
            event_risk="none",
            news_sentiment=0.5,
        )
        assert isinstance(report, DailyMoodReport)
        assert report.market_mood == MarketMood.RISK_ON
        assert report.min_confluence_override == 7  # no event
        assert report.position_size_multiplier == 1.0

    def test_high_event_raises_min_confluence(self):
        synth = self._make_synth()
        ai_resp = '{"market_mood": "event_driven", "confidence": "medium", "one_line_summary": "CPI day", "key_risk": "CPI surprise", "opportunity": "Post-release setup"}'
        report = synth.generate_from_ai_response(
            ai_response=ai_resp,
            event_risk="high",
        )
        assert report.min_confluence_override == 9
        assert report.position_size_multiplier == 0.75

    def test_extreme_event_max_caution(self):
        synth = self._make_synth()
        ai_resp = '{"market_mood": "event_driven", "confidence": "low", "one_line_summary": "FOMC", "key_risk": "Fed surprise", "opportunity": "Post-FOMC reversal"}'
        report = synth.generate_from_ai_response(
            ai_response=ai_resp,
            event_risk="extreme",
        )
        assert report.min_confluence_override == 10
        assert report.position_size_multiplier == 0.5

    def test_fallback_on_bad_json(self):
        synth = self._make_synth()
        report = synth.generate_from_ai_response(
            ai_response="this is not json",
            event_risk="none",
        )
        assert report.error is not None
        assert report.source == "fallback"

    def test_as_dict_contains_required_keys(self):
        synth = self._make_synth()
        ai_resp = '{"market_mood": "choppy", "confidence": "low", "one_line_summary": "Unclear", "key_risk": "X", "opportunity": "Y"}'
        report = synth.generate_from_ai_response(ai_resp, event_risk="none")
        d = report.as_dict()
        required = {"market_mood", "confidence", "min_confluence_override", "position_size_multiplier"}
        assert required.issubset(d.keys())


# ---------------------------------------------------------------------------
# SWCEngine — heuristic mood
# ---------------------------------------------------------------------------

class TestSWCEngineHeuristicMood:
    def test_event_driven_on_high_risk(self):
        engine = SWCEngine()
        report = engine._heuristic_mood(
            events=[],
            event_risk="high",
            news_sentiment=0.0,
            fedwatch_shift=0.0,
        )
        assert report.market_mood == MarketMood.EVENT_DRIVEN

    def test_risk_on_positive_news_neutral_fed(self):
        engine = SWCEngine()
        report = engine._heuristic_mood(
            events=[],
            event_risk="none",
            news_sentiment=0.5,
            fedwatch_shift=2.0,
        )
        assert report.market_mood == MarketMood.RISK_ON

    def test_risk_off_hawkish_fed(self):
        engine = SWCEngine()
        report = engine._heuristic_mood(
            events=[],
            event_risk="none",
            news_sentiment=-0.1,
            fedwatch_shift=-8.0,
        )
        assert report.market_mood == MarketMood.RISK_OFF

    def test_choppy_mixed_signals(self):
        engine = SWCEngine()
        report = engine._heuristic_mood(
            events=[],
            event_risk="none",
            news_sentiment=0.1,
            fedwatch_shift=1.0,
        )
        assert report.market_mood == MarketMood.CHOPPY

    def test_returns_daily_mood_report_type(self):
        engine = SWCEngine()
        report = engine._heuristic_mood([], "none", 0.0, 0.0)
        assert isinstance(report, DailyMoodReport)

    def test_extreme_risk_max_caution(self):
        engine = SWCEngine()
        report = engine._heuristic_mood([], "extreme", 0.0, 0.0)
        assert report.min_confluence_override == 10
        assert report.position_size_multiplier == 0.5


# ---------------------------------------------------------------------------
# SWCEngine — run_premarket_scan (full pipeline mocked)
# ---------------------------------------------------------------------------

class TestSWCEngineScan:
    def test_scan_with_no_modules_returns_report(self):
        engine = SWCEngine()
        report = engine.run_premarket_scan(date=datetime.date(2024, 1, 2))
        assert isinstance(report, DailyMoodReport)

    def test_scan_on_fomc_day_is_event_driven(self):
        # 2024-01-31 is an FOMC day
        engine = SWCEngine()
        report = engine.run_premarket_scan(date=datetime.date(2024, 1, 31))
        assert report.market_mood == MarketMood.EVENT_DRIVEN
        assert report.event_risk == "extreme"

    def test_scan_on_cpi_day_has_high_risk(self):
        # 2024-01-11 is CPI day
        engine = SWCEngine()
        report = engine.run_premarket_scan(date=datetime.date(2024, 1, 11))
        assert report.event_risk == "high"
        assert report.min_confluence_override == 9

    def test_scan_normal_day_standard_params(self):
        # 2024-01-03 is a Wednesday (no events)
        engine = SWCEngine()
        report = engine.run_premarket_scan(date=datetime.date(2024, 1, 3))
        assert report.event_risk == "none"
        assert report.min_confluence_override == 7
        assert report.position_size_multiplier == 1.0

    def test_scan_with_mock_news_scanner(self):
        mock_news = MagicMock()
        mock_news.fetch_and_score.return_value = NewsSentimentResult(
            score=0.6, headline_count=10, source="alpha_vantage"
        )
        engine = SWCEngine(news_scanner=mock_news)
        report = engine.run_premarket_scan(date=datetime.date(2024, 1, 3))
        assert report.news_sentiment == 0.6

    def test_scan_with_mock_fedwatch(self):
        mock_fw = MagicMock()
        mock_fw.get_probabilities.return_value = FedWatchResult(
            cut_prob=75.0, hold_prob=23.0, hike_prob=2.0,
            daily_change=8.0, next_meeting_date="2024-03-20"
        )
        engine = SWCEngine(fedwatch_client=mock_fw)
        report = engine.run_premarket_scan(date=datetime.date(2024, 1, 3))
        assert report.fedwatch_shift == 8.0

    def test_news_scanner_failure_returns_zero_sentiment(self):
        mock_news = MagicMock()
        mock_news.fetch_and_score.side_effect = Exception("Network error")
        engine = SWCEngine(news_scanner=mock_news)
        report = engine.run_premarket_scan(date=datetime.date(2024, 1, 3))
        assert report.news_sentiment == 0.0

    def test_fedwatch_failure_returns_neutral(self):
        mock_fw = MagicMock()
        mock_fw.get_probabilities.side_effect = Exception("Timeout")
        engine = SWCEngine(fedwatch_client=mock_fw)
        report = engine.run_premarket_scan(date=datetime.date(2024, 1, 3))
        assert report.fedwatch_shift == 0.0


# ---------------------------------------------------------------------------
# run_premarket_scan (module-level function)
# ---------------------------------------------------------------------------

class TestRunPremarketScan:
    def test_module_function_returns_report(self):
        report = run_premarket_scan(date=datetime.date(2024, 1, 3))
        assert isinstance(report, DailyMoodReport)

    def test_passes_components_to_engine(self):
        mock_news = MagicMock()
        mock_news.fetch_and_score.return_value = NewsSentimentResult(
            score=0.3, headline_count=5, source="alpha_vantage"
        )
        report = run_premarket_scan(
            date=datetime.date(2024, 1, 3),
            news_scanner=mock_news,
        )
        assert report.news_sentiment == 0.3


# ---------------------------------------------------------------------------
# MarketMood enum
# ---------------------------------------------------------------------------

class TestMarketMood:
    def test_risk_on_value(self):
        assert MarketMood.RISK_ON.value == "risk_on"

    def test_all_moods_are_strings(self):
        for mood in MarketMood:
            assert isinstance(mood.value, str)
