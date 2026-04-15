"""
sentiment/mood_synthesizer.py
==============================
Uses Claude API to synthesize a Daily Market Mood from all sentiment inputs.

Inputs:
    - Economic events today (from economic_calendar.py)
    - Event risk level (none/low/medium/high/extreme)
    - News sentiment score (-1.0 to +1.0)
    - FedWatch rate probability shift

Output (DailyMoodReport):
    - market_mood: MarketMood enum
    - confidence: "low" | "medium" | "high"
    - one_line_summary: human-readable
    - key_risk: biggest risk factor
    - opportunity: best opportunity
    - min_confluence_override: int (from confluence_adjuster)
    - position_size_multiplier: float (from confluence_adjuster)
    - news_blackout_windows: list of (start_ct, end_ct) tuples

Usage:
    from sentiment.mood_synthesizer import MoodSynthesizer
    synth = MoodSynthesizer(api_key="sk-...")
    report = synth.generate(events, "high", news_score=-0.3, fedwatch_result)
"""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from config import ANTHROPIC_API_KEY
from sentiment.confluence_adjuster import get_adjustments

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default model comes from config.AI_MODEL_MOOD_SYNTHESIS — never hardcode.
from config import AI_MODEL_MOOD_SYNTHESIS as _MODEL
_MAX_TOKENS = 600

# News blackout: minutes before/after a high-impact event
_BLACKOUT_BEFORE_MINUTES = 15
_BLACKOUT_AFTER_MINUTES = 15


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MarketMood(str, Enum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    EVENT_DRIVEN = "event_driven"
    CHOPPY = "choppy"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DailyMoodReport:
    """Complete daily mood assessment for use by the trading engine."""

    market_mood: MarketMood
    confidence: str                         # "low" | "medium" | "high"
    one_line_summary: str
    key_risk: str
    opportunity: str

    # Risk adjustments (from confluence_adjuster, confirmed by AI)
    event_risk: str                         # "none" | "low" | "medium" | "high" | "extreme"
    min_confluence_override: int            # 7-10
    position_size_multiplier: float         # 0.5 - 1.0
    news_blackout_windows: list = field(default_factory=list)   # [(start_ct, end_ct), ...]

    # Source data
    news_sentiment: float = 0.0             # -1.0 to +1.0
    fedwatch_shift: float = 0.0             # % point change in cut prob
    source: str = "claude"                  # "claude" | "fallback"
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None

    def as_dict(self) -> dict:
        return {
            "market_mood": self.market_mood.value,
            "confidence": self.confidence,
            "one_line_summary": self.one_line_summary,
            "key_risk": self.key_risk,
            "opportunity": self.opportunity,
            "event_risk": self.event_risk,
            "min_confluence_override": self.min_confluence_override,
            "position_size_multiplier": self.position_size_multiplier,
            "news_blackout_windows": self.news_blackout_windows,
            "news_sentiment": self.news_sentiment,
            "fedwatch_shift": self.fedwatch_shift,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# MoodSynthesizer
# ---------------------------------------------------------------------------

class MoodSynthesizer:
    """
    Generates a Daily Mood Report using the Claude API.

    Combines economic events, news sentiment, and FedWatch probabilities
    into a coherent daily assessment for the AlgoICT trading engine.

    Parameters
    ----------
    api_key : str
        Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
    model : str
        Claude model to use. Defaults to claude-sonnet.
    """

    def __init__(
        self,
        api_key: str = ANTHROPIC_API_KEY,
        model: str = _MODEL,
    ):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        if not api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY in .env"
            )

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        logger.info("MoodSynthesizer initialized (model: %s)", model)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def generate(
        self,
        events: list,
        event_risk: str,
        news_sentiment: float = 0.0,
        fedwatch_cut_prob: float = 50.0,
        fedwatch_shift: float = 0.0,
        headlines: Optional[list] = None,
    ) -> DailyMoodReport:
        """
        Generate a Daily Mood Report.

        Parameters
        ----------
        events : list
            List of EconomicEvent objects (or dicts) for today.
        event_risk : str
            Highest risk level for today ('none'|'low'|'medium'|'high'|'extreme').
        news_sentiment : float
            News sentiment score from NewsScanner (-1.0 to +1.0).
        fedwatch_cut_prob : float
            Current probability of a rate cut at next FOMC (0-100).
        fedwatch_shift : float
            Change in cut probability vs yesterday (+ = more dovish).
        headlines : list, optional
            Top Headline objects (or dicts) from NewsScanner. When provided,
            they are fed into the Claude prompt for richer context.

        Returns
        -------
        DailyMoodReport
        """
        try:
            # Get baseline adjustments from confluence_adjuster
            adj = get_adjustments(event_risk)

            # Build blackout windows for high-impact events
            blackout_windows = self._build_blackout_windows(events)

            # Call Claude API
            ai_result = self._call_claude(
                events=events,
                event_risk=event_risk,
                news_sentiment=news_sentiment,
                fedwatch_cut_prob=fedwatch_cut_prob,
                fedwatch_shift=fedwatch_shift,
                headlines=headlines or [],
            )

            return DailyMoodReport(
                market_mood=MarketMood(ai_result.get("market_mood", "choppy")),
                confidence=ai_result.get("confidence", "low"),
                one_line_summary=ai_result.get("one_line_summary", ""),
                key_risk=ai_result.get("key_risk", ""),
                opportunity=ai_result.get("opportunity", ""),
                event_risk=event_risk,
                min_confluence_override=adj["min_confluence"],
                position_size_multiplier=adj["position_multiplier"],
                news_blackout_windows=blackout_windows,
                news_sentiment=news_sentiment,
                fedwatch_shift=fedwatch_shift,
                source="claude",
            )

        except Exception as exc:
            logger.error("MoodSynthesizer.generate failed: %s", exc)
            return self._fallback_report(event_risk, news_sentiment, fedwatch_shift, str(exc))

    def generate_from_ai_response(
        self,
        ai_response: str,
        event_risk: str,
        news_sentiment: float = 0.0,
        fedwatch_shift: float = 0.0,
        blackout_windows: Optional[list] = None,
    ) -> DailyMoodReport:
        """
        Build a DailyMoodReport from a pre-generated AI response string.

        Useful for testing without a live API call.
        """
        try:
            adj = get_adjustments(event_risk)
            ai_result = self._parse_ai_response(ai_response)

            return DailyMoodReport(
                market_mood=MarketMood(ai_result.get("market_mood", "choppy")),
                confidence=ai_result.get("confidence", "low"),
                one_line_summary=ai_result.get("one_line_summary", ""),
                key_risk=ai_result.get("key_risk", ""),
                opportunity=ai_result.get("opportunity", ""),
                event_risk=event_risk,
                min_confluence_override=adj["min_confluence"],
                position_size_multiplier=adj["position_multiplier"],
                news_blackout_windows=blackout_windows or [],
                news_sentiment=news_sentiment,
                fedwatch_shift=fedwatch_shift,
                source="claude",
            )
        except Exception as exc:
            return self._fallback_report(event_risk, news_sentiment, fedwatch_shift, str(exc))

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _call_claude(
        self,
        events: list,
        event_risk: str,
        news_sentiment: float,
        fedwatch_cut_prob: float,
        fedwatch_shift: float,
        headlines: Optional[list] = None,
    ) -> dict:
        """Call Claude API and return parsed JSON response."""
        events_str = self._format_events(events)
        headlines_str = self._format_headlines(headlines or [])

        prompt = f"""You are a senior macro trader assessing today's market conditions for NQ/MNQ futures trading.

TODAY'S CONTEXT:
- Economic events today:
{events_str}
- Event risk level: {event_risk}
- Top market headlines:
{headlines_str}
- Aggregate news sentiment: {news_sentiment:+.2f} (-1.0 = very bearish, +1.0 = very bullish)
- FedWatch rate cut probability: {fedwatch_cut_prob:.1f}%
- FedWatch daily shift: {fedwatch_shift:+.1f}% (positive = more dovish)

INSTRUCTIONS:
Weigh the economic calendar AND the headlines together to produce one daily
assessment for NQ/MNQ intraday trading.

Respond ONLY in valid JSON with exactly these keys:
{{
  "market_mood": "risk_on" | "risk_off" | "event_driven" | "choppy",
  "confidence": "low" | "medium" | "high",
  "one_line_summary": "<brief 1-sentence assessment>",
  "key_risk": "<single biggest risk factor today>",
  "opportunity": "<best potential opportunity today>"
}}

market_mood rules:
- risk_on: Low event risk, positive news sentiment, dovish Fed shift
- risk_off: High event risk, negative news sentiment, hawkish Fed shift
- event_driven: Major event (FOMC/CPI/NFP) dominates the session
- choppy: Mixed signals, no clear directional bias"""

        message = self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )

        content = message.content[0].text
        return self._parse_ai_response(content)

    def _parse_ai_response(self, content: str) -> dict:
        """Extract JSON from Claude response (may have markdown fences)."""
        # Strip code fences if present
        text = re.sub(r"```(?:json)?", "", content).strip()
        # Find first JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON object found in response: {content[:200]}")

        data = json.loads(text[start:end])

        # Validate required keys
        required = {"market_mood", "confidence", "one_line_summary", "key_risk", "opportunity"}
        missing = required - set(data.keys())
        if missing:
            raise ValueError(f"Missing keys in AI response: {missing}")

        # Validate market_mood is valid
        valid_moods = {m.value for m in MarketMood}
        if data["market_mood"] not in valid_moods:
            data["market_mood"] = "choppy"

        # Validate confidence
        if data["confidence"] not in ("low", "medium", "high"):
            data["confidence"] = "low"

        return data

    def _format_events(self, events: list) -> str:
        """Format events list for the prompt."""
        if not events:
            return "  None"

        lines = []
        for e in events:
            if hasattr(e, "name"):
                lines.append(f"  - {e.name} [{e.risk}] at {e.time_ct} CT")
            elif isinstance(e, dict):
                lines.append(f"  - {e.get('name', '?')} [{e.get('risk', '?')}] at {e.get('time_ct', '?')} CT")
        return "\n".join(lines) if lines else "  None"

    def _format_headlines(self, headlines: list) -> str:
        """Format top-N Headline objects (or dicts) for the Claude prompt."""
        if not headlines:
            return "  None"
        lines = []
        for h in headlines:
            title = getattr(h, "title", None) or (h.get("title") if isinstance(h, dict) else "")
            label = getattr(h, "sentiment_label", None) or (h.get("sentiment_label") if isinstance(h, dict) else "")
            score = getattr(h, "sentiment_score", None)
            if score is None and isinstance(h, dict):
                score = h.get("sentiment_score", 0.0)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0
            if title:
                lines.append(f"  - \"{title}\" [{label} {score:+.2f}]")
        return "\n".join(lines) if lines else "  None"

    def _build_blackout_windows(self, events: list) -> list:
        """
        Build list of (start_ct, end_ct) blackout windows for high-impact events.

        Returns time strings in "HH:MM" format.
        """
        windows = []

        for e in events:
            # Only blackout for high/extreme risk events
            risk = getattr(e, "risk", None) or (e.get("risk") if isinstance(e, dict) else None)
            time_ct = getattr(e, "time_ct", None) or (e.get("time_ct") if isinstance(e, dict) else None)

            if risk not in ("high", "extreme") or not time_ct:
                continue

            try:
                h, m = map(int, time_ct.split(":"))
                # Calculate start (before event)
                total_start = h * 60 + m - _BLACKOUT_BEFORE_MINUTES
                # Calculate end (after event)
                total_end = h * 60 + m + _BLACKOUT_AFTER_MINUTES

                start_str = f"{total_start // 60:02d}:{total_start % 60:02d}"
                end_str = f"{total_end // 60:02d}:{total_end % 60:02d}"
                windows.append((start_str, end_str))
            except (ValueError, AttributeError):
                continue

        return windows

    def _fallback_report(
        self,
        event_risk: str,
        news_sentiment: float,
        fedwatch_shift: float,
        error: str,
    ) -> DailyMoodReport:
        """Return a conservative fallback report when AI is unavailable."""
        logger.warning("MoodSynthesizer using fallback: %s", error)

        try:
            adj = get_adjustments(event_risk)
        except Exception:
            adj = {"min_confluence": 7, "position_multiplier": 1.0}

        # Simple heuristic mood determination
        if event_risk in ("high", "extreme"):
            mood = MarketMood.EVENT_DRIVEN
        elif news_sentiment >= 0.3:
            mood = MarketMood.RISK_ON
        elif news_sentiment <= -0.3:
            mood = MarketMood.RISK_OFF
        else:
            mood = MarketMood.CHOPPY

        return DailyMoodReport(
            market_mood=mood,
            confidence="low",
            one_line_summary=f"Fallback mood: {mood.value} (AI unavailable)",
            key_risk="AI synthesis unavailable",
            opportunity="Standard ICT setups only",
            event_risk=event_risk,
            min_confluence_override=adj["min_confluence"],
            position_size_multiplier=adj["position_multiplier"],
            news_blackout_windows=[],
            news_sentiment=news_sentiment,
            fedwatch_shift=fedwatch_shift,
            source="fallback",
            error=error,
        )
