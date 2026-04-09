"""
agents/post_mortem.py
======================
Post-Mortem Agent — analyzes losing trades using Claude API.

Called automatically after each loss to identify:
  - WHY the trade failed
  - What market context was missed
  - Specific parameter adjustment to make
  - Recurring patterns across multiple losses

Output is saved to Supabase `post_mortems` table and sent via Telegram.

Categories (9 types):
    htf_misread       : HTF bias was wrong or misread
    premature_entry   : Entered before confirmation
    stop_too_tight    : Stop was inside noise
    stop_too_wide     : Stop too wide, risk/reward distorted
    news_event        : Moved by unexpected fundamental news
    false_signal      : ICT pattern was there but price didn't follow
    overtrading       : Took trade outside kill zone / rules
    htf_resistance    : Ran into unmitigated HTF level
    other             : Doesn't fit other categories

Severity:
    low    : Learning point, acceptable loss within rules
    medium : Avoidable mistake, adjust parameters
    high   : Rule violation or recurring pattern — immediate action

Usage:
    from agents.post_mortem import PostMortemAgent, analyze_loss
    agent = PostMortemAgent(api_key="sk-...")
    result = agent.analyze_loss(trade, market_context)
    print(result.category)
    print(result.recommendation)

    # For main.py integration (module-level function):
    from agents.post_mortem import analyze_loss
    result = analyze_loss(trade=trade, market_context=ctx)
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1500

_VALID_CATEGORIES = {
    "htf_misread",
    "premature_entry",
    "stop_too_tight",
    "stop_too_wide",
    "news_event",
    "false_signal",
    "overtrading",
    "htf_resistance",
    "other",
}

_VALID_SEVERITIES = {"low", "medium", "high"}

# How many same-category losses trigger a pattern alert
_PATTERN_THRESHOLD = 3


# ---------------------------------------------------------------------------
# PostMortemResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class PostMortemResult:
    """Structured post-mortem analysis of a losing trade."""

    trade_id: str
    reason: str                         # Why the trade failed
    htf_analysis: str                   # Was HTF bias correct?
    entry_analysis: str                 # Was the entry timing right?
    stop_analysis: str                  # Was the stop placed correctly?
    pattern_to_avoid: str               # Specific pattern to not repeat
    recommendation: str                 # Concrete parameter/rule adjustment
    category: str                       # One of _VALID_CATEGORIES
    severity: str                       # 'low' | 'medium' | 'high'
    pnl: float = 0.0                    # Negative for losses
    source: str = "claude"              # 'claude' | 'fallback'
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None

    @property
    def is_high_severity(self) -> bool:
        return self.severity == "high"

    def as_db_record(self) -> dict:
        """Format for Supabase post_mortems table."""
        return {
            "trade_id": self.trade_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason_category": self.category,
            "analysis": self.reason,
            "lesson": self.recommendation,
            "htf_analysis": self.htf_analysis,
            "entry_analysis": self.entry_analysis,
            "stop_analysis": self.stop_analysis,
            "pattern_to_avoid": self.pattern_to_avoid,
            "severity": self.severity,
            "pnl": self.pnl,
        }

    def as_telegram_message(self) -> str:
        """Format for Telegram notification."""
        sev_emoji = {"low": "", "medium": "", "high": ""}[self.severity]
        return (
            f"Post-Mortem {sev_emoji}\n\n"
            f"Loss: ${abs(self.pnl):,.0f}\n"
            f"Category: {self.category}\n"
            f"Reason: {self.reason}\n\n"
            f"Lesson: {self.recommendation}"
        )


# ---------------------------------------------------------------------------
# PostMortemAgent
# ---------------------------------------------------------------------------

class PostMortemAgent:
    """
    Analyzes losing trades using Claude API.

    Parameters
    ----------
    api_key : str
        Anthropic API key.
    model : str
        Claude model ID.
    supabase_client : optional
        SupabaseClient instance for saving results.
    telegram_bot : optional
        TelegramBot instance for notifications.
    """

    def __init__(
        self,
        api_key: str = ANTHROPIC_API_KEY,
        model: str = _MODEL,
        supabase_client=None,
        telegram_bot=None,
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
        self._supabase = supabase_client
        self._telegram = telegram_bot
        logger.info("PostMortemAgent initialized (model: %s)", model)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyze_loss(
        self,
        trade: dict,
        market_context: Optional[dict] = None,
    ) -> PostMortemResult:
        """
        Analyze a losing trade and return structured insights.

        Parameters
        ----------
        trade : dict
            Trade record with keys: id, strategy, direction, entry_price,
            exit_price, entry_time, exit_time, pnl, confluence_score,
            ict_concepts (list), kill_zone, stop_points, contracts.
        market_context : dict | None
            Market state at time of trade: weekly_bias, daily_bias,
            structure_15min, active_fvgs, news_events, etc.

        Returns
        -------
        PostMortemResult
        """
        if market_context is None:
            market_context = {}

        try:
            prompt = self._build_prompt(trade, market_context)
            result = self._call_claude(prompt, trade)

            if self._supabase is not None:
                self._save_to_db(result)

            if self._telegram is not None:
                self._send_telegram(result)

            return result

        except Exception as exc:
            logger.error("PostMortemAgent.analyze_loss failed: %s", exc)
            return self._fallback_result(trade, str(exc))

    def analyze_from_ai_response(
        self,
        ai_response: str,
        trade: dict,
    ) -> PostMortemResult:
        """
        Build a PostMortemResult from a pre-generated AI response.
        Useful for testing without a live API call.
        """
        try:
            data = self._parse_response(ai_response)
            return self._build_result(data, trade)
        except Exception as exc:
            return self._fallback_result(trade, str(exc))

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _call_claude(self, prompt: str, trade: dict) -> PostMortemResult:
        """Call Claude API and parse response."""
        message = self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        content = message.content[0].text
        data = self._parse_response(content)
        return self._build_result(data, trade)

    def _build_prompt(self, trade: dict, ctx: dict) -> str:
        """Build the analysis prompt for Claude."""
        ict_concepts = trade.get("ict_concepts", [])
        if isinstance(ict_concepts, list):
            ict_str = ", ".join(ict_concepts) if ict_concepts else "none specified"
        else:
            ict_str = str(ict_concepts)

        return f"""You are an expert ICT (Inner Circle Trader) analyst reviewing a losing MNQ futures trade.
Respond ONLY with a valid JSON object, no other text, no code fences.

LOSING TRADE DATA:
- Trade ID: {trade.get("id", "unknown")}
- Strategy: {trade.get("strategy", "unknown")}
- Direction: {trade.get("direction", trade.get("side", "unknown"))}
- Entry price: {trade.get("entry_price", "N/A")}
- Exit price: {trade.get("exit_price", "N/A")}
- Entry time: {trade.get("entry_time", "N/A")}
- Exit time: {trade.get("exit_time", "N/A")}
- Loss: ${abs(float(trade.get("pnl", 0))):.2f}
- Contracts: {trade.get("contracts", 1)}
- Stop size: {trade.get("stop_points", "N/A")} points
- Confluence score: {trade.get("confluence_score", "N/A")}/20
- ICT concepts used: {ict_str}
- Kill Zone: {trade.get("kill_zone", "N/A")}

MARKET CONTEXT AT TIME OF TRADE:
- Weekly HTF bias: {ctx.get("weekly_bias", "N/A")}
- Daily HTF bias: {ctx.get("daily_bias", "N/A")}
- 15min structure: {ctx.get("structure_15min", "N/A")}
- Active FVGs: {ctx.get("active_fvgs", "N/A")}
- VPIN at entry: {ctx.get("vpin", "N/A")}
- News events today: {ctx.get("news_events", "none")}
- Price action after stop: {ctx.get("price_after_stop", "N/A")}

ANALYSIS REQUIRED:
Analyze this trade from an ICT perspective. What went wrong?

Respond with this exact JSON structure:
{{
  "reason": "<1-2 sentences: why did this trade fail?>",
  "htf_analysis": "<Was the HTF bias correctly read? What was missed?>",
  "entry_analysis": "<Was entry timing/location correct? Any premature entry signs?>",
  "stop_analysis": "<Was stop placement appropriate? Too tight, too wide, wrong location?>",
  "pattern_to_avoid": "<Specific ICT pattern or scenario to avoid in future>",
  "recommendation": "<ONE concrete, actionable adjustment to rules or parameters>",
  "category": "<exactly one of: htf_misread|premature_entry|stop_too_tight|stop_too_wide|news_event|false_signal|overtrading|htf_resistance|other>",
  "severity": "<exactly one of: low|medium|high>"
}}"""

    def _parse_response(self, content: str) -> dict:
        """Extract and validate JSON from Claude response."""
        # Strip code fences
        text = re.sub(r"```(?:json)?", "", content).strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON in response: {content[:200]}")

        data = json.loads(text[start:end])

        # Validate and normalize
        required = {"reason", "htf_analysis", "entry_analysis", "stop_analysis",
                    "pattern_to_avoid", "recommendation", "category", "severity"}
        for key in required:
            if key not in data:
                data[key] = ""

        # Normalize category
        cat = data.get("category", "other").lower().strip()
        if cat not in _VALID_CATEGORIES:
            data["category"] = "other"
        else:
            data["category"] = cat

        # Normalize severity
        sev = data.get("severity", "medium").lower().strip()
        if sev not in _VALID_SEVERITIES:
            data["severity"] = "medium"
        else:
            data["severity"] = sev

        return data

    def _build_result(self, data: dict, trade: dict) -> PostMortemResult:
        """Build PostMortemResult from parsed data and trade record."""
        trade_id = str(trade.get("id") or trade.get("trade_id") or "unknown")
        pnl = float(trade.get("pnl", 0.0))

        return PostMortemResult(
            trade_id=trade_id,
            reason=data.get("reason", ""),
            htf_analysis=data.get("htf_analysis", ""),
            entry_analysis=data.get("entry_analysis", ""),
            stop_analysis=data.get("stop_analysis", ""),
            pattern_to_avoid=data.get("pattern_to_avoid", ""),
            recommendation=data.get("recommendation", ""),
            category=data.get("category", "other"),
            severity=data.get("severity", "medium"),
            pnl=pnl,
            source="claude",
        )

    def _save_to_db(self, result: PostMortemResult) -> None:
        """Save analysis to Supabase post_mortems table."""
        try:
            self._supabase.write_post_mortem(result.as_db_record())
        except Exception as exc:
            logger.error("Failed to save post-mortem to DB: %s", exc)

    def _send_telegram(self, result: PostMortemResult) -> None:
        """Send post-mortem summary to Telegram."""
        try:
            self._telegram.send_emergency_alert(result.as_telegram_message())
        except Exception as exc:
            logger.error("Failed to send post-mortem to Telegram: %s", exc)

    def _fallback_result(self, trade: dict, error: str) -> PostMortemResult:
        """Return a minimal result when AI analysis fails."""
        logger.warning("PostMortemAgent fallback: %s", error)
        trade_id = str(trade.get("id") or trade.get("trade_id") or "unknown")
        pnl = float(trade.get("pnl", 0.0))

        return PostMortemResult(
            trade_id=trade_id,
            reason="AI analysis unavailable",
            htf_analysis="",
            entry_analysis="",
            stop_analysis="",
            pattern_to_avoid="",
            recommendation="Review trade manually",
            category="other",
            severity="low",
            pnl=pnl,
            source="fallback",
            error=error,
        )


# ---------------------------------------------------------------------------
# Module-level function (used by main.py via _try_import)
# ---------------------------------------------------------------------------

def analyze_loss(
    trade: dict,
    market_context: Optional[dict] = None,
    api_key: str = ANTHROPIC_API_KEY,
    supabase_client=None,
    telegram_bot=None,
) -> PostMortemResult:
    """
    Module-level function for main.py integration.

    main.py calls: _POST_MORTEM = _try_import("agents.post_mortem", "analyze_loss")
    Then: result = _POST_MORTEM(trade=trade, market_context=ctx)
    """
    if not ANTHROPIC_AVAILABLE or not api_key:
        logger.warning("PostMortem: anthropic not available or no API key")
        return PostMortemResult(
            trade_id=str(trade.get("id", "unknown")),
            reason="anthropic not available",
            htf_analysis="",
            entry_analysis="",
            stop_analysis="",
            pattern_to_avoid="",
            recommendation="Review trade manually",
            category="other",
            severity="low",
            pnl=float(trade.get("pnl", 0.0)),
            source="fallback",
            error="anthropic not available",
        )

    agent = PostMortemAgent(
        api_key=api_key,
        supabase_client=supabase_client,
        telegram_bot=telegram_bot,
    )
    return agent.analyze_loss(trade=trade, market_context=market_context)
