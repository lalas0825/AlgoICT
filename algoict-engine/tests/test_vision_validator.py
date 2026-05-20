"""Tests for vision_validator + chart_renderer (Camino C4)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from agents.vision_validator import (
    VisionValidatorAgent,
    VisionValidatorDecision,
    _VALID_DECISIONS,
)


def _mock_anthropic_response(content_text: str):
    response = MagicMock()
    response.content = [MagicMock(text=content_text)]
    return response


@pytest.fixture
def mock_agent():
    with patch("agents.vision_validator.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        agent = VisionValidatorAgent(
            api_key="test-key",
            model="claude-test",
            shadow_mode=True,
        )
        agent._client = mock_client
        yield agent


# ─────────────────────────────────────────────────────────────────────
# Decision dataclass
# ─────────────────────────────────────────────────────────────────────

class TestVisionDecision:

    def test_fire_decision_is_valid(self):
        d = VisionValidatorDecision(
            kz="london", decision="fire", size_multiplier=1.0,
            confidence=0.8, rationale="clean FVG, sweep took out PDL",
            model="test", response_ms=2500, images_used=2,
        )
        assert d.is_valid
        assert not d.is_skip
        assert not d.is_half

    def test_invalid_decision_string_is_not_valid(self):
        d = VisionValidatorDecision(
            kz="ny_am", decision="maybe", size_multiplier=0.5,
            confidence=0.5, rationale="", model="t", response_ms=100,
            images_used=1,
        )
        assert not d.is_valid

    def test_db_record_excludes_image_b64(self):
        d = VisionValidatorDecision(
            kz="london", decision="half", size_multiplier=0.5,
            confidence=0.6, rationale="mild chop", model="t",
            response_ms=200, images_used=2,
            context={"signal": {}, "chart_1min_b64": "BIG", "chart_5min_b64": "ALSO BIG"},
        )
        rec = d.as_db_record()
        assert "chart_1min_b64" not in rec["context"]
        assert "chart_5min_b64" not in rec["context"]
        assert rec["images_used"] == 2

    def test_telegram_message_shadow_includes_warning(self):
        d = VisionValidatorDecision(
            kz="ny_am", decision="skip", size_multiplier=0.0,
            confidence=0.85, rationale="FVG looks like noise gap",
            model="t", response_ms=100, images_used=2,
        )
        msg = d.as_telegram_message(shadow_mode=True)
        assert "VISION-SHADOW" in msg
        assert "SKIP" in msg.upper()
        assert "FVG looks like noise gap" in msg
        assert "images 2" in msg


# ─────────────────────────────────────────────────────────────────────
# Agent — happy paths
# ─────────────────────────────────────────────────────────────────────

class TestVisionAgentHappy:

    def test_fire_response_parses(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '{"decision": "fire", "size_multiplier": 1.0, '
            '"confidence": 0.75, "rationale": "clean setup, FVG real"}'
        )
        ctx = {"kz": "london", "signal": {"direction": "long"}}
        d = mock_agent.validate_signal_with_charts(
            ctx, chart_1min_b64="fake_b64", chart_5min_b64="fake_b64_2",
        )
        assert d.is_valid
        assert d.decision == "fire"
        assert d.images_used == 2

    def test_skip_with_one_image(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '{"decision": "skip", "size_multiplier": 0.0, '
            '"confidence": 0.9, "rationale": "FVG is noise gap"}'
        )
        d = mock_agent.validate_signal_with_charts(
            {"kz": "ny_am"}, chart_1min_b64="b64", chart_5min_b64=None,
        )
        assert d.decision == "skip"
        assert d.images_used == 1

    def test_zero_images_still_works(self, mock_agent):
        """Both chart generations failed — should still return a decision."""
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '{"decision": "fire", "size_multiplier": 1.0, '
            '"confidence": 0.5, "rationale": "no charts, fallback"}'
        )
        d = mock_agent.validate_signal_with_charts(
            {"kz": "london"}, chart_1min_b64=None, chart_5min_b64=None,
        )
        assert d.images_used == 0
        assert d.decision == "fire"


# ─────────────────────────────────────────────────────────────────────
# Error handling
# ─────────────────────────────────────────────────────────────────────

class TestVisionAgentErrors:

    def test_api_exception_falls_back_to_fire(self, mock_agent):
        mock_agent._client.messages.create.side_effect = RuntimeError("timeout")
        d = mock_agent.validate_signal_with_charts(
            {"kz": "london"}, chart_1min_b64="b64",
        )
        assert d.decision == "fire"
        assert d.size_multiplier == 1.0
        assert d.error is not None
        assert "timeout" in d.error

    def test_malformed_json_falls_back(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            "not json at all{"
        )
        d = mock_agent.validate_signal_with_charts(
            {"kz": "ny_am"}, chart_1min_b64="b64",
        )
        assert d.decision == "fire"
        assert d.error is not None

    def test_confidence_clamped(self, mock_agent):
        mock_agent._client.messages.create.return_value = _mock_anthropic_response(
            '{"decision": "fire", "size_multiplier": 1.0, '
            '"confidence": 1.7, "rationale": "ok"}'
        )
        d = mock_agent.validate_signal_with_charts(
            {"kz": "london"}, chart_1min_b64="b64",
        )
        assert 0.0 <= d.confidence <= 1.0


# ─────────────────────────────────────────────────────────────────────
# Prompt construction
# ─────────────────────────────────────────────────────────────────────

class TestVisionPrompt:

    def test_two_images_prompt_describes_both(self, mock_agent):
        ctx = {"kz": "london", "signal": {"direction": "long"}}
        prompt = mock_agent._build_prompt(ctx, images_used=2)
        assert "TWO chart images" in prompt
        assert "1-min chart" in prompt
        assert "5-min HTF" in prompt

    def test_one_image_prompt_describes_one(self, mock_agent):
        ctx = {"kz": "ny_am"}
        prompt = mock_agent._build_prompt(ctx, images_used=1)
        assert "ONE chart image" in prompt

    def test_zero_images_warns_text_only(self, mock_agent):
        ctx = {"kz": "ny_pm"}
        prompt = mock_agent._build_prompt(ctx, images_used=0)
        assert "no chart images attached" in prompt.lower() or "text context only" in prompt.lower()

    def test_prompt_includes_validation_instructions(self, mock_agent):
        prompt = mock_agent._build_prompt({"kz": "london", "signal": {}}, 2)
        # Spot-check the visual validation instructions
        assert "VALIDATE THE BOT" in prompt
        assert "FVG" in prompt
        assert "sweep" in prompt.lower()
        assert "json" in prompt.lower()
