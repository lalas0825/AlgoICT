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

from config import (
    ANTHROPIC_API_KEY,
    AI_MODEL_POST_MORTEM,
    MAX_CONFLUENCE,
    SB_APPLICABLE_MAX,
    SB_LIVE_FACTORS,
    SB_LIVE_MAX,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default model comes from config.AI_MODEL_POST_MORTEM — never hardcode.
_MODEL = AI_MODEL_POST_MORTEM
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
        """Build the analysis prompt for Claude.

        2026-05-04 — strategy-aware. Silver Bullet has a different framework
        than NY AM Reversal:
          - SB scoring is /10 (8 SB-applicable factors), not /19
          - SB does NOT require HTF bias (informational only — sweep determines
            direction, not HTF)
          - SB gates are: sweep + 1min FVG + 5min MSS/BOS + framework ≥ 10pt
          - SB enters at FVG.proximal + 1tick (NOT OTE 61.8-78.6 retrace)
          - Common SB failure modes: sweep stale/invalidated, FVG too thin,
            5min struct misaligned, KZ chop, framework too short.
        """
        ict_concepts = trade.get("ict_concepts", [])
        if isinstance(ict_concepts, list):
            ict_str = ", ".join(ict_concepts) if ict_concepts else "none specified"
        else:
            ict_str = str(ict_concepts)

        strategy = str(trade.get("strategy", "unknown")).lower()
        is_sb = strategy == "silver_bullet"

        # Strategy-specific framework block
        if is_sb:
            live_factors_str = ", ".join(sorted(SB_LIVE_FACTORS))
            framework_block = f"""STRATEGY: Silver Bullet v19a-WIDE (FVG-only, no HTF requirement)
- KZ: London 01:00-07:30 CT, NY AM 07:30-12:00 CT, NY PM 12:00-15:00 CT

HARD GATES (all 6 passed if a trade fired — these are NOT analysis points):
  1. Kill zone active (London / NY AM / NY PM CT)
  2. 1-min FVG (not yet mitigated) formed inside the active KZ window
  3. Opposite-side liquidity sweep, NOT invalidated by close-back:
     long → swept SSL/PDL/PWL/AL/LL/NAL/NPL/equal_lows
     short → swept BSL/PDH/PWH/AH/LH/NAH/NPH/equal_highs
  4. 5-min MSS/BOS/CHoCH aligned with FVG direction (recent: <60min old,
     <2 opposite events in last 30min, no immediate counter-CHoCH)
  5. Stop ≥ 15 pts (config.SB_MIN_STOP_POINTS) — sweep must be of REAL
     liquidity (D1/W1 swings on MNQ are 20-50pt), not 5-7pt noise pivots
  6. Target ≥ 2R from stop (config.SB_MIN_TARGET_RR) — picks nearest
     unswept pool that satisfies 2× stop_pts. Mathematical floor for
     positive expectancy at backtest-historical WR ~63%.

ENTRY MODEL:
- DIRECTION: determined by 1-min FVG direction (NOT HTF bias).
  HTF bias is INFORMATIONAL only — SB can countertrend HTF if all
  6 hard gates pass.
- ENTRY: FVG.proximal +/- 1 tick (NOT OTE retrace 61.8-78.6%)
- STOP: FVG candle-1 extreme +/- 1 tick (structural)
- TARGET: nearest unswept pool ≥ 2R away
- TRAIL: last 5-min swing if trade-management=trailing

QUALITY EXTRAS (soft score — does NOT gate fire, just signals quality):
- confluence_score is /{SB_LIVE_MAX} (LIVE-attainable max, not theoretical 10).
  GEX + VPIN factors auto-zero because those modules aren't running.
- Live factors that CAN score: {live_factors_str}
  * target_at_pdh_pdl (+1) — target is at PDH/PDL/PWH/PWL (not session level)
  * order_block (+2) — OB overlaps the entry zone (Inst. Orderflow Drill)
  * htf_bias_aligned (+1) — D1/W1 bias matches trade direction
  * sentiment_alignment (+1) — SWC mood matches trade direction
- Score interpretation:
  * 0/5 = structurally valid but zero quality bonus (still a real setup,
    just no extras — losers expected as part of WR 63% statistical loss bucket)
  * 1-2/5 = standard quality
  * 3+/5 = high quality
  * 5/5 = A+ (all extras aligned)

KNOWN-OFF FACTORS (do NOT mention as failure modes):
- VPIN_SHIELD_ENABLED = False — VPIN is not gating, not scoring, irrelevant
- No GEX options data loader — GEX walls / gamma regime irrelevant
- These will return when modules are wired; for now they're dead config.

COMMON FAILURE MODES (qualitative — apply when score is low):
- Sweep was technically valid but already faded (low conviction; price
  already retraced before bot fired)
- FVG too narrow relative to 5-min displacement (noise gap, not real
  imbalance) — caught by SB_FVG_QUALITY when enabled
- 5-min MSS happened but immediate counter-CHoCH followed (chop)
- Trade entered against fresh D1/W1 reaction off PDH/PDL — passes hard
  gates but HTF context unfavorable (htf_bias_aligned would be 0)
- KZ window edge: setup formed in last 5-10 min of KZ (low time for
  development), pre-arm or past-cancel rejection should have caught"""
            confluence_max = SB_LIVE_MAX
        else:
            framework_block = f"""STRATEGY: NY AM Reversal (OTE retracement)
- KZ: NY AM (08:30-11:00 CT canonical)
- ENTRY MODEL: HTF bias + 5min OB + 15min structure + OTE retrace 61.8-78.6%
- DIRECTION: determined by HTF (Daily + Weekly) bias
- SCORING: confluence_score is /{MAX_CONFLUENCE} (full 19-factor scoring applies)"""
            confluence_max = MAX_CONFLUENCE

        return f"""You are an expert ICT (Inner Circle Trader) analyst reviewing a losing MNQ futures trade.
Respond ONLY with a valid JSON object, no other text, no code fences.

{framework_block}

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
- Confluence score: {trade.get("confluence_score", "N/A")}/{confluence_max}{" (SB live-attainable; 0 = no extras, 1-2 = standard, 3-4 = high, 5 = A+)" if is_sb else ""}
- ICT concepts used: {ict_str}
- Kill Zone: {trade.get("kill_zone", "N/A")}

MARKET CONTEXT AT TIME OF TRADE:
- Weekly HTF bias: {ctx.get("weekly_bias", "N/A")}{" (informational for SB)" if is_sb else ""}
- Daily HTF bias: {ctx.get("daily_bias", "N/A")}{" (informational for SB)" if is_sb else ""}
- 5min structure: {ctx.get("structure_5min", ctx.get("structure_15min", "N/A"))}
- Active FVGs: {ctx.get("active_fvgs", "N/A")}
- Recent sweeps: {ctx.get("recent_sweeps", "N/A")}
- VPIN at entry: {ctx.get("vpin", "N/A")}
- News events today: {ctx.get("news_events", "none")}
- Price action after stop: {ctx.get("price_after_stop", "N/A")}

ANALYSIS REQUIRED:
Analyze this trade against the strategy's actual framework above. Be specific
about which gate or condition failed in PRACTICE (the gates all PASSED to fire,
so the failure is qualitative — was the setup low-conviction? Was the sweep
already faded? Did 5min struct flip immediately?).

Do NOT invent failure modes from a different strategy (e.g. don't blame "OTE
fib retrace" for an SB trade — SB doesn't use OTE).

Respond with this exact JSON structure:
{{
  "reason": "<1-2 sentences: why did this trade fail in this strategy's terms?>",
  "htf_analysis": "<{'For SB: HTF is informational only. Was bias aligned or against the trade? If against, was the setup strong enough to justify countertrend?' if is_sb else 'Was the HTF bias correctly read? What was missed?'}>",
  "entry_analysis": "<{'For SB: Was the FVG proximal entry timing right? Was the FVG significant or noise?' if is_sb else 'Was entry timing/location correct? Any premature entry signs?'}>",
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
        """Send post-mortem summary to Telegram (sync-safe wrapper over async API)."""
        import asyncio

        coro = self._telegram.send_emergency_alert(result.as_telegram_message())
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)  # fire-and-forget inside running loop
        except RuntimeError:
            try:
                asyncio.run(coro)
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
