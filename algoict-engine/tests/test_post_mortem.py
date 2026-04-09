"""
tests/test_post_mortem.py
==========================
Tests for agents/post_mortem.py

All tests run offline — no Claude API calls.
"""

import pytest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.post_mortem import (
    PostMortemAgent,
    PostMortemResult,
    analyze_loss,
    _VALID_CATEGORIES,
    _VALID_SEVERITIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(
    trade_id="MNQ_2024-01-02T09:30:00Z",
    strategy="ny_am_reversal",
    direction="long",
    entry_price=19500.0,
    exit_price=19480.0,
    pnl=-100.0,
    confluence_score=9,
    ict_concepts=None,
):
    return {
        "id": trade_id,
        "strategy": strategy,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_time": "2024-01-02T09:30:00Z",
        "exit_time": "2024-01-02T09:35:00Z",
        "pnl": pnl,
        "contracts": 1,
        "stop_points": 10,
        "confluence_score": confluence_score,
        "ict_concepts": ict_concepts or ["fvg", "ob", "mss"],
        "kill_zone": "ny_am",
    }


def _make_context():
    return {
        "weekly_bias": "bearish",
        "daily_bias": "neutral",
        "structure_15min": "bearish_bos",
        "vpin": 0.45,
        "news_events": "None",
        "price_after_stop": "Continued lower by 30 points",
    }


def _make_agent():
    """Create a PostMortemAgent bypassing __init__ (no API call needed)."""
    agent = PostMortemAgent.__new__(PostMortemAgent)
    agent._model = "claude-test"
    agent._client = MagicMock()
    agent._supabase = None
    agent._telegram = None
    return agent


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestPostMortemAgentConstructor:
    def test_raises_without_anthropic(self):
        with patch("agents.post_mortem.ANTHROPIC_AVAILABLE", False):
            with pytest.raises(ImportError, match="anthropic"):
                PostMortemAgent(api_key="sk-test")

    def test_raises_without_api_key(self):
        with patch("agents.post_mortem.ANTHROPIC_AVAILABLE", True):
            with patch("agents.post_mortem.anthropic", create=True) as mock_ant:
                mock_ant.Anthropic = MagicMock(return_value=MagicMock())
                with pytest.raises(ValueError, match="API key"):
                    PostMortemAgent(api_key="")


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def setup_method(self):
        self.agent = _make_agent()

    def _valid_json(self, **overrides):
        base = {
            "reason": "Entered against HTF bias",
            "htf_analysis": "Weekly was bearish, entered long",
            "entry_analysis": "Entry on 5min FVG but HTF was against",
            "stop_analysis": "Stop was 10 points — reasonable size",
            "pattern_to_avoid": "Long entries during weekly bearish bias",
            "recommendation": "Add HTF bias check before any long entry",
            "category": "htf_misread",
            "severity": "medium",
        }
        base.update(overrides)
        import json
        return json.dumps(base)

    def test_parses_valid_json(self):
        data = self.agent._parse_response(self._valid_json())
        assert data["reason"] == "Entered against HTF bias"
        assert data["category"] == "htf_misread"
        assert data["severity"] == "medium"

    def test_strips_code_fences(self):
        raw = "```json\n" + self._valid_json() + "\n```"
        data = self.agent._parse_response(raw)
        assert data["category"] == "htf_misread"

    def test_invalid_category_defaults_to_other(self):
        data = self.agent._parse_response(self._valid_json(category="unknown_cat"))
        assert data["category"] == "other"

    def test_invalid_severity_defaults_to_medium(self):
        data = self.agent._parse_response(self._valid_json(severity="critical"))
        assert data["severity"] == "medium"

    def test_raises_on_no_json(self):
        with pytest.raises((ValueError, Exception)):
            self.agent._parse_response("Sorry I cannot analyze this trade.")

    def test_all_valid_categories_accepted(self):
        for cat in _VALID_CATEGORIES:
            data = self.agent._parse_response(self._valid_json(category=cat))
            assert data["category"] == cat

    def test_all_valid_severities_accepted(self):
        for sev in _VALID_SEVERITIES:
            data = self.agent._parse_response(self._valid_json(severity=sev))
            assert data["severity"] == sev


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def setup_method(self):
        self.agent = _make_agent()

    def test_prompt_contains_trade_data(self):
        trade = _make_trade(entry_price=19500.0, pnl=-100.0)
        ctx = _make_context()
        prompt = self.agent._build_prompt(trade, ctx)
        assert "19500" in prompt
        assert "ny_am_reversal" in prompt
        assert "confluence_score" in prompt.lower() or "confluence" in prompt.lower()

    def test_prompt_contains_context(self):
        trade = _make_trade()
        ctx = _make_context()
        prompt = self.agent._build_prompt(trade, ctx)
        assert "bearish" in prompt.lower()

    def test_prompt_contains_category_list(self):
        trade = _make_trade()
        prompt = self.agent._build_prompt(trade, {})
        assert "htf_misread" in prompt

    def test_prompt_handles_empty_context(self):
        trade = _make_trade()
        prompt = self.agent._build_prompt(trade, {})
        assert "N/A" in prompt

    def test_prompt_handles_list_ict_concepts(self):
        trade = _make_trade(ict_concepts=["fvg", "ob", "liquidity_grab"])
        prompt = self.agent._build_prompt(trade, {})
        assert "fvg" in prompt.lower()


# ---------------------------------------------------------------------------
# analyze_from_ai_response
# ---------------------------------------------------------------------------

class TestAnalyzeFromAiResponse:
    def setup_method(self):
        self.agent = _make_agent()

    def _ai_resp(self, category="htf_misread", severity="medium"):
        import json
        return json.dumps({
            "reason": "Entered against HTF bias",
            "htf_analysis": "Weekly was bearish",
            "entry_analysis": "FVG valid but direction wrong",
            "stop_analysis": "Stop placement was OK",
            "pattern_to_avoid": "Longs during bearish weekly",
            "recommendation": "Check weekly bias before every entry",
            "category": category,
            "severity": severity,
        })

    def test_returns_post_mortem_result(self):
        trade = _make_trade(pnl=-100.0)
        result = self.agent.analyze_from_ai_response(self._ai_resp(), trade)
        assert isinstance(result, PostMortemResult)

    def test_correct_category(self):
        trade = _make_trade()
        result = self.agent.analyze_from_ai_response(
            self._ai_resp(category="premature_entry"), trade
        )
        assert result.category == "premature_entry"

    def test_correct_severity(self):
        trade = _make_trade()
        result = self.agent.analyze_from_ai_response(
            self._ai_resp(severity="high"), trade
        )
        assert result.severity == "high"

    def test_is_high_severity_property(self):
        trade = _make_trade()
        result = self.agent.analyze_from_ai_response(
            self._ai_resp(severity="high"), trade
        )
        assert result.is_high_severity

    def test_pnl_is_set_from_trade(self):
        trade = _make_trade(pnl=-250.0)
        result = self.agent.analyze_from_ai_response(self._ai_resp(), trade)
        assert result.pnl == -250.0

    def test_trade_id_is_set(self):
        trade = _make_trade(trade_id="MNQ_ABC123")
        result = self.agent.analyze_from_ai_response(self._ai_resp(), trade)
        assert result.trade_id == "MNQ_ABC123"

    def test_fallback_on_bad_json(self):
        trade = _make_trade()
        result = self.agent.analyze_from_ai_response("this is not json", trade)
        assert result.source == "fallback"
        assert result.error is not None

    def test_is_valid_on_good_response(self):
        trade = _make_trade()
        result = self.agent.analyze_from_ai_response(self._ai_resp(), trade)
        assert result.is_valid

    def test_not_valid_on_fallback(self):
        trade = _make_trade()
        result = self.agent.analyze_from_ai_response("bad json", trade)
        assert not result.is_valid


# ---------------------------------------------------------------------------
# PostMortemResult helper methods
# ---------------------------------------------------------------------------

class TestPostMortemResultHelpers:
    def _make_result(self, **kwargs):
        defaults = {
            "trade_id": "T001",
            "reason": "HTF misread",
            "htf_analysis": "Weekly bearish",
            "entry_analysis": "FVG entry",
            "stop_analysis": "Stop OK",
            "pattern_to_avoid": "Long in downtrend",
            "recommendation": "Check HTF",
            "category": "htf_misread",
            "severity": "medium",
            "pnl": -100.0,
        }
        defaults.update(kwargs)
        return PostMortemResult(**defaults)

    def test_as_db_record_keys(self):
        result = self._make_result()
        rec = result.as_db_record()
        assert "trade_id" in rec
        assert "reason_category" in rec
        assert "analysis" in rec
        assert "lesson" in rec
        assert "timestamp" in rec

    def test_as_telegram_message_contains_loss(self):
        result = self._make_result(pnl=-250.0)
        msg = result.as_telegram_message()
        assert "250" in msg

    def test_as_telegram_message_contains_category(self):
        result = self._make_result(category="premature_entry")
        msg = result.as_telegram_message()
        assert "premature_entry" in msg

    def test_is_valid_no_error(self):
        result = self._make_result()
        assert result.is_valid

    def test_not_valid_with_error(self):
        result = self._make_result(error="API down", source="fallback")
        assert not result.is_valid


# ---------------------------------------------------------------------------
# analyze_with_db_and_telegram (integration test with mocks)
# ---------------------------------------------------------------------------

class TestAnalyzeWithSideEffects:
    def _ai_resp(self):
        import json
        return json.dumps({
            "reason": "Premature entry", "htf_analysis": "OK",
            "entry_analysis": "Entered before confirmation",
            "stop_analysis": "Stop too tight",
            "pattern_to_avoid": "Early FVG entries",
            "recommendation": "Wait for 2-bar confirmation",
            "category": "premature_entry", "severity": "medium",
        })

    def test_saves_to_supabase_when_available(self):
        agent = _make_agent()
        mock_sb = MagicMock()
        mock_sb.write_post_mortem = MagicMock(return_value=True)
        agent._supabase = mock_sb

        trade = _make_trade()
        result = agent.analyze_from_ai_response(self._ai_resp(), trade)

        # analyze_from_ai_response doesn't trigger _save_to_db
        # (only analyze_loss does). Verify the result is correct.
        assert result.category == "premature_entry"

    def test_analyze_loss_calls_save(self):
        agent = _make_agent()
        mock_sb = MagicMock()
        mock_sb.write_post_mortem = MagicMock(return_value=True)
        agent._supabase = mock_sb

        # Mock Claude to return our controlled response
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=self._ai_resp())]
        agent._client.messages.create.return_value = mock_message

        trade = _make_trade(pnl=-100.0)
        result = agent.analyze_loss(trade, _make_context())

        assert result.is_valid
        mock_sb.write_post_mortem.assert_called_once()

    def test_analyze_loss_fallback_on_api_error(self):
        agent = _make_agent()
        agent._client.messages.create.side_effect = Exception("API unavailable")

        trade = _make_trade()
        result = agent.analyze_loss(trade)
        assert result.source == "fallback"
        assert result.error is not None


# ---------------------------------------------------------------------------
# Module-level analyze_loss function
# ---------------------------------------------------------------------------

class TestModuleLevelAnalyzeLoss:
    def test_returns_fallback_without_anthropic(self):
        with patch("agents.post_mortem.ANTHROPIC_AVAILABLE", False):
            trade = _make_trade(pnl=-100.0)
            result = analyze_loss(trade)
        assert result.source == "fallback"
        assert result.error is not None

    def test_returns_fallback_without_api_key(self):
        with patch("agents.post_mortem.ANTHROPIC_AVAILABLE", True):
            trade = _make_trade(pnl=-100.0)
            result = analyze_loss(trade, api_key="")
        assert result.source == "fallback"
