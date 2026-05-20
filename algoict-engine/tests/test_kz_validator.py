"""Tests for agents/kz_validator.py — Camino C2 AI Overlay (SHADOW)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from agents.kz_validator import (
    KZValidatorAgent,
    KZValidatorDecision,
    _VALID_DECISIONS,
)


def _mock_anthropic_response(content_text: str):
    """Build a fake Anthropic API response with the given content."""
    response = MagicMock()
    response.content = [MagicMock(text=content_text)]
    return response


@pytest.fixture
def mock_agent():
    """Build agent with mocked Anthropic client so tests don't hit API."""
    with patch("agents.kz_validator.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        agent = KZValidatorAgent(
            api_key="test-key",
            model="claude-test",
            shadow_mode=True,
        )
        # Attach the client mock so tests can configure response
        agent._client = mock_client
        yield agent


# ─────────────────────────────────────────────────────────────────────
# Decision dataclass
# ─────────────────────────────────────────────────────────────────────

class TestKZValidatorDecision:

    def test_fire_decision_is_valid(self):
        d = KZValidatorDecision(
            kz="ny_am", decision="fire", size_multiplier=1.0,
            confidence=0.7, rationale="ok", model="test", response_ms=100,
        )
        assert d.is_valid
        assert not d.is_skip
        assert not d.is_half

    def test_skip_decision_is_valid_and_flagged(self):
        d = KZValidatorDecision(
            kz="ny_pm", decision="skip", size_multiplier=0.0,
            confidence=0.85, rationale="chop day", model="test",
            response_ms=120,
        )
        assert d.is_valid
        assert d.is_skip

    def test_invalid_decision_string_is_not_valid(self):
        d = KZValidatorDecision(
            kz="london", decision="maybe", size_multiplier=0.5,
            confidence=0.5, rationale="", model="test", response_ms=100,
        )
        assert not d.is_valid

    def test_error_field_invalidates(self):
        d = KZValidatorDecision(
            kz="ny_am", decision="fire", size_multiplier=1.0,
            confidence=0.0, rationale="", model="test", response_ms=0,
            error="api timeout",
        )
        assert not d.is_valid

    def test_db_record_has_required_keys(self):
        d = KZValidatorDecision(
            kz="london", decision="half", size_multiplier=0.5,
            confidence=0.6, rationale="some risk", model="test",
            response_ms=200, context={"k": "v"},
        )
        rec = d.as_db_record()
        for k in ("ts", "kz", "decision", "size_multiplier", "confidence",
                  "rationale", "model", "response_ms", "context"):
            assert k in rec
        assert rec["decision"] == "half"
        assert rec["context"] == {"k": "v"}

    def test_telegram_message_shadow_includes_warning(self):
        d = KZValidatorDecision(
            kz="ny_am", decision="skip", size_multiplier=0.0,
            confidence=0.8, rationale="chop expected",
            model="test", response_ms=100,
        )
        msg = d.as_telegram_message(shadow_mode=True)
        assert "SHADOW" in msg
        assert "SKIP" in msg.upper()
        assert "chop expected" in msg

    def test_telegram_message_active_does_not_include_shadow_tag(self):
        d = KZValidatorDecision(
            kz="ny_pm", decision="fire", size_multiplier=1.0,
            confidence=0.9, rationale="clean setup", model="test",
            response_ms=100,
        )
        msg = d.as_telegram_message(shadow_mode=False)
        assert "SHADOW" not in msg
        assert "FIRE" in msg.upper()


# ─────────────────────────────────────────────────────────────────────
# Agent — happy paths
# ─────────────────────────────────────────────────────────────────────

class TestKZValidatorAgent:

    def test_fire_response_parses(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '{"decision": "fire", "size_multiplier": 1.0, '
            '"confidence": 0.75, "rationale": "neutral context"}'
        )
        ctx = {"kz": "london"}
        d = mock_agent.validate_kz_entry(ctx)
        assert d.is_valid
        assert d.decision == "fire"
        assert d.size_multiplier == 1.0
        assert d.confidence == 0.75
        assert d.rationale == "neutral context"
        assert d.kz == "london"

    def test_skip_response_parses(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '{"decision": "skip", "size_multiplier": 0.0, '
            '"confidence": 0.85, "rationale": "giveback risk"}'
        )
        d = mock_agent.validate_kz_entry({"kz": "ny_pm"})
        assert d.decision == "skip"
        assert d.is_skip
        assert d.size_multiplier == 0.0

    def test_half_response_parses(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '{"decision": "half", "size_multiplier": 0.5, '
            '"confidence": 0.6, "rationale": "mild chop risk"}'
        )
        d = mock_agent.validate_kz_entry({"kz": "ny_am"})
        assert d.decision == "half"
        assert d.is_half
        assert d.size_multiplier == 0.5

    def test_code_fenced_response_is_stripped(self, mock_agent):
        """Claude sometimes wraps JSON in code fences despite instructions."""
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '```json\n{"decision": "fire", "size_multiplier": 1.0, '
            '"confidence": 0.7, "rationale": "ok"}\n```'
        )
        d = mock_agent.validate_kz_entry({"kz": "london"})
        assert d.decision == "fire"
        assert d.rationale == "ok"


# ─────────────────────────────────────────────────────────────────────
# Agent — error handling
# ─────────────────────────────────────────────────────────────────────

class TestKZValidatorErrorHandling:

    def test_invalid_decision_falls_back_to_fire(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '{"decision": "maybe", "size_multiplier": 0.7, '
            '"confidence": 0.5, "rationale": "weird"}'
        )
        d = mock_agent.validate_kz_entry({"kz": "ny_am"})
        # Falls back to "fire" — being judgment-driven by default
        assert d.decision == "fire"
        # Still returns a valid decision (no error)
        assert d.error is None

    def test_malformed_json_sets_error_and_falls_back(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            "not json at all{{{"
        )
        d = mock_agent.validate_kz_entry({"kz": "london"})
        assert d.decision == "fire"  # safe fallback
        assert d.error is not None
        assert "Parse error" in d.rationale

    def test_api_exception_falls_back_to_fire(self, mock_agent):
        mock_agent._client.messages.create.side_effect = RuntimeError(
            "rate limited"
        )
        d = mock_agent.validate_kz_entry({"kz": "ny_pm"})
        assert d.decision == "fire"  # safe fallback — never block trading
        assert d.size_multiplier == 1.0
        assert d.error is not None
        assert "rate limited" in d.error
        assert "API error" in d.rationale

    def test_confidence_is_clamped_to_unit_range(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '{"decision": "fire", "size_multiplier": 1.0, '
            '"confidence": 1.7, "rationale": "ok"}'
        )
        d = mock_agent.validate_kz_entry({"kz": "ny_am"})
        assert 0.0 <= d.confidence <= 1.0

    def test_rationale_truncated_to_500_chars(self, mock_agent):
        long_rat = "x" * 1000
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            f'{{"decision": "fire", "size_multiplier": 1.0, '
            f'"confidence": 0.5, "rationale": "{long_rat}"}}'
        )
        d = mock_agent.validate_kz_entry({"kz": "ny_am"})
        assert len(d.rationale) <= 500


# ─────────────────────────────────────────────────────────────────────
# Prompt construction
# ─────────────────────────────────────────────────────────────────────

class TestPromptConstruction:

    def test_prompt_includes_all_kz_context(self, mock_agent):
        ctx = {
            "kz": "ny_pm",
            "kz_window_ct": "12:00-15:00 CT",
            "current_time_ct": "12:00",
            "today_date": "2026-05-20",
            "trades_today": 3,
            "wins_today": 3,
            "losses_today": 0,
            "daily_pnl": 1500.0,
            "peak_pnl": 1500.0,
            "drawdown_from_peak": 0.0,
            "consecutive_losses": 0,
            "instant_adverse_today": 0,
            "prior_kz_outcomes_str": "London: 3W +$1,500",
            "daily_bias": "bearish",
            "weekly_bias": "bullish",
            "struct_last3": "BOS bear 11:55CT",
            "swc_mood": "risk_on",
            "current_price": "29050.00",
            "session_range_pts": "180",
            "vpin": "n/a",
        }
        prompt = mock_agent._build_prompt(ctx)
        # Spot-check critical context made it into the prompt
        assert "ny_pm" in prompt
        assert "London: 3W +$1,500" in prompt
        assert "29050" in prompt
        assert "risk_on" in prompt
        assert "drawdown" in prompt.lower()
        assert "fire" in prompt.lower() and "skip" in prompt.lower()
        assert "json" in prompt.lower()
