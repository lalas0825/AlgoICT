"""
agents/kz_validator.py
=======================
AI Overlay — per-SIGNAL trade validator (Camino C2, SHADOW mode).

2026-05-20 refactor: switched from per-KZ to per-signal validation.
Per-KZ was mechanical (at London open with no prior trades, Claude
always says "fire — clean slate" — no real information). Per-signal
gives Claude the actual setup details (FVG zone, sweep, structure,
RR, score) + session state, so the vote is contextually meaningful.

Called RIGHT AFTER the bot generates a signal (in shadow mode, before
limit is placed; bot does not wait — vote logs async). Sends full
setup context to Claude and receives: fire / skip / half + rationale.

Modes:
  - SHADOW (default, `KZ_VALIDATOR_SHADOW_MODE=True`): decision is logged
    to Supabase + Telegram but the bot DOES NOT obey — continues with
    canonical strategy. Used to collect data on whether AI overlay would
    have improved outcomes (counterfactual analysis after 3 weeks).
  - ACTIVE (`KZ_VALIDATOR_SHADOW_MODE=False`, Phase 2 — NOT yet enabled):
    bot would obey the decision: skip/half-size new entries for the KZ.

Decision criteria (Phase 2 ship): counterfactual P&L (if obeyed) > actual
P&L by some margin (e.g., +10%) over 3-week shadow period (~45-60 KZ
entries). Run `scripts/ai_overlay_counterfactual.py` to compute.

Failure modes to watch for during shadow:
  - Claude too cautious → skips too much → undertrade
  - Claude rationalizes anything (decisions look thoughtful but aren't
    predictive)
  - Sample size insufficient in 3 weeks (only ~45-60 KZ entries — might
    extend to 6 weeks for stronger signal)

Usage:
    from agents.kz_validator import KZValidatorAgent, validate_kz_entry

    agent = KZValidatorAgent(api_key="sk-...")
    decision = agent.validate_kz_entry(context_dict)
    print(decision.decision, decision.rationale)

    # Module-level convenience
    decision = validate_kz_entry(context_dict)
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

from config import ANTHROPIC_API_KEY, cfg

logger = logging.getLogger(__name__)

_VALID_DECISIONS = {"fire", "skip", "half"}
_DEFAULT_MAX_TOKENS = 600

# Default model — kept as constant default; overridable by config.
# Falls back to mood_synthesis model if AI_MODEL_KZ_VALIDATOR not defined.
_DEFAULT_MODEL_FALLBACK = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Decision dataclass
# ---------------------------------------------------------------------------

@dataclass
class KZValidatorDecision:
    """AI decision for a single KZ entry event."""

    kz: str
    decision: str             # "fire" | "skip" | "half"
    size_multiplier: float    # 1.0 | 0.5 | 0.0 (or anything Claude returns)
    confidence: float         # 0.0 - 1.0
    rationale: str            # max ~500 chars
    model: str
    response_ms: int
    context: dict = field(default_factory=dict)  # full context sent
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None and self.decision in _VALID_DECISIONS

    @property
    def is_skip(self) -> bool:
        return self.decision == "skip"

    @property
    def is_half(self) -> bool:
        return self.decision == "half"

    def as_db_record(self) -> dict:
        """Format for Supabase ai_overlay_decisions table."""
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kz": self.kz,
            "decision": self.decision,
            "size_multiplier": float(self.size_multiplier),
            "confidence": float(self.confidence),
            "rationale": self.rationale[:500],
            "model": self.model,
            "response_ms": int(self.response_ms),
            "context": self.context,
            "error": self.error,
        }

    def as_telegram_message(self, shadow_mode: bool = True) -> str:
        """Format for Telegram notification."""
        emoji = {"fire": "[FIRE]", "half": "[HALF]", "skip": "[SKIP]"}.get(
            self.decision, "[?]"
        )
        tag = "[SHADOW] " if shadow_mode else ""
        head = (
            f"{tag}AI Overlay - KZ {self.kz.upper()}\n"
            f"{emoji} {self.decision.upper()} "
            f"(size {self.size_multiplier:.1f}x, conf {self.confidence:.2f})\n"
        )
        if shadow_mode:
            head += f"Rationale: {self.rationale}\n(SHADOW: bot continues canonical)"
        else:
            head += f"Rationale: {self.rationale}"
        return head


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class KZValidatorAgent:
    """Validates KZ entries via Claude API in shadow or active mode."""

    def __init__(
        self,
        api_key: str = ANTHROPIC_API_KEY,
        model: Optional[str] = None,
        supabase_client=None,
        telegram_bot=None,
        shadow_mode: bool = True,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        if not api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY in .env"
            )

        # Use explicit model arg, else config, else fallback
        self._model = (
            model
            or cfg("AI_MODEL_KZ_VALIDATOR", None)
            or cfg("AI_MODEL_MOOD_SYNTHESIS", _DEFAULT_MODEL_FALLBACK)
        )
        self._max_tokens = max_tokens
        self._client = anthropic.Anthropic(api_key=api_key)
        self._supabase = supabase_client
        self._telegram = telegram_bot
        self._shadow_mode = shadow_mode
        logger.info(
            "KZValidatorAgent initialized (model=%s, shadow=%s)",
            self._model, shadow_mode,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def validate_kz_entry(self, context: dict) -> KZValidatorDecision:
        """Send context to Claude, return decision (sync, ~1-3 sec)."""
        kz = context.get("kz", "unknown")
        prompt = self._build_prompt(context)
        start = datetime.now()
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = message.content[0].text
            elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
            decision = self._parse_response(response_text, context, elapsed_ms)
            logger.info(
                "KZValidator [%s] -> %s mult=%.1f conf=%.2f (%dms)",
                kz, decision.decision, decision.size_multiplier,
                decision.confidence, elapsed_ms,
            )
            return decision
        except Exception as exc:
            elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)
            logger.error("KZValidator API call failed for %s: %s", kz, exc)
            return KZValidatorDecision(
                kz=kz, decision="fire", size_multiplier=1.0,
                confidence=0.0, rationale=f"API error fallback: {exc}",
                model=self._model, response_ms=elapsed_ms,
                context=context, error=str(exc),
            )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _build_prompt(self, ctx: dict) -> str:
        """Build the per-signal validation prompt for Claude."""
        prior_str = ctx.get("prior_kz_outcomes_str", "No prior KZs today")
        events_str = ctx.get("high_impact_events", "none")
        # Signal block — per-trade is the primary use case (2026-05-20)
        sig = ctx.get("signal", {})
        signal_block = ""
        if sig:
            signal_block = f"""

PROPOSED TRADE (just fired by the SB strategy, awaiting your vote):
- Direction: {sig.get('direction', 'unknown').upper()}
- Entry: {sig.get('entry_price', 'n/a')} (limit, +/- 1 tick from FVG proximal)
- Stop: {sig.get('stop_price', 'n/a')}  ({sig.get('stop_pts', 'n/a')} pts risk)
- Target: {sig.get('target_price', 'n/a')} ({sig.get('target_type', 'n/a')}, {sig.get('framework_pts', 'n/a')} pts reward)
- R:R: {sig.get('actual_rr', 'n/a')}
- Contracts: {sig.get('contracts', 'n/a')}
- Confluence score: {sig.get('confluence_score', 'n/a')}/5 (SB-live; 0=structural-only, 5=A+)
- KZ: {sig.get('kill_zone', ctx.get('kz', 'unknown'))}
- Sweep type: {sig.get('sweep_type', 'n/a')}
- FVG zone: {sig.get('fvg_zone', 'n/a')}
"""
        return f"""You are an expert ICT (Inner Circle Trader) trade validator for a Silver Bullet (SB) MNQ futures bot.
Your job: given the proposed trade + current market/session context, decide whether the bot should fire this trade at full size, half size, or skip entirely.

Respond ONLY with valid JSON, no other text, no code fences.
{signal_block}
KZ ABOUT TO OPEN / CURRENTLY ACTIVE:
- KZ name: {ctx.get('kz', 'unknown')}
- KZ window CT: {ctx.get('kz_window_ct', 'unknown')}
- Current time CT: {ctx.get('current_time_ct', 'unknown')}
- Today's date: {ctx.get('today_date', 'unknown')}

DAY STATE SO FAR:
- Trades taken: {ctx.get('trades_today', 0)} (W: {ctx.get('wins_today', 0)}, L: {ctx.get('losses_today', 0)})
- Daily P&L: ${float(ctx.get('daily_pnl', 0)):,.2f}
- Intraday peak P&L: ${float(ctx.get('peak_pnl', 0)):,.2f}
- Drawdown from peak: ${float(ctx.get('drawdown_from_peak', 0)):,.2f}
- Consecutive losses: {ctx.get('consecutive_losses', 0)}
- Kill switch active: {ctx.get('kill_switch_active', False)}
- MLL zone: {ctx.get('mll_zone', 'normal')}
- Instant-adverse losses today (MFE < 0.5R): {ctx.get('instant_adverse_today', 0)}

PRIOR KZ OUTCOMES TODAY:
{prior_str}

HTF CONTEXT:
- Daily HTF bias: {ctx.get('daily_bias', 'n/a')}
- Weekly HTF bias: {ctx.get('weekly_bias', 'n/a')}
- Current local bias (zone): {ctx.get('current_bias', 'n/a')}
- Last 5-min struct events: {ctx.get('struct_last3', 'n/a')}
- Last displacement: {ctx.get('last_disp', 'n/a')}

MACRO / SWC:
- SWC mood: {ctx.get('swc_mood', 'n/a')}
- SWC confidence: {ctx.get('swc_confidence', 'n/a')}
- High-impact events today: {events_str}
- News sentiment: {ctx.get('news_sentiment', 'n/a')}

PRICE STATE:
- Current price (MNQ): {ctx.get('current_price', 'n/a')}
- Session range so far: {ctx.get('session_range_pts', 'n/a')} pts
- VPIN: {ctx.get('vpin', 'n/a')} ({ctx.get('vpin_zone', 'n/a')})

DECISION FRAMEWORK:
The Silver Bullet (SB) v19a-WIDE strategy operates THROUGHOUT the full KZ window (e.g. London 01:00-07:30 CT), NOT restricted to ICT canonical 1-hour sub-windows (02-03 CT, 09-10 CT, 14-15 CT). Wide mode is validated by 7-year backtest with +97.9% P&L boost vs narrow. Do NOT skip a signal just because it fires outside the canonical 1-hour window — that's normal behavior.

If you're seeing a signal, ALL hard gates already passed:
  1. Active KZ
  2. 1-min FVG (unmitigated, inside KZ)
  3. Opposite-side liquidity sweep (NOT invalidated by close-back)
  4. 5-min MSS/BOS/CHoCH aligned with FVG direction
  5. Stop >= 15 pts (SB_MIN_STOP_POINTS) — real sweep, not noise
  6. Target >= 2R from stop (next unswept pool)
  7. Bias direction NOT contradicting last 5-min struct event

So you do NOT need to second-guess structural validity. SB also does NOT require HTF bias alignment — countertrend setups are intentional (mean-reversion plays). Confluence score is NOT a useful baseline gate (cross-period proven — score=0 is the HIGHEST WR bucket).

Historical 3-year expectancy: +14.7% P&L with NY_OPEN_BUFFER shipped.

Per-trade risks to evaluate (think like an experienced ICT discretionary trader looking at THIS specific setup in THIS specific context):
- "Late in move" risk: if session range is already large and the trade is fading at the EXTREME, the move may be exhausted.
- "Counter-bias clarity" risk: trade direction vs HTF + last_disp + struct alignment. Counter-trend setups CAN work (mean reversion) but need stronger structural confirmation.
- "Recent failure pattern" risk: if N instant-adverse losses today and trade is in same KZ → market is rejecting this edge today.
- "Macro headwind": high-impact event window nearby.
- "FVG quality": tiny FVG vs noisy candle, or FVG already partially mitigated.
- "Sweep conviction": clean liquidity sweep vs marginal pivot break.
- "Giveback exposure": if day is already +$X and current KZ is post-peak, elevated chop risk.

DECISIONS:
- "fire" → execute trade at full size (size_multiplier = 1.0). Default when context is neutral/supportive.
- "half" → execute at half size (size_multiplier = 0.5). When edge probably still positive but context is mildly risky.
- "skip" → reject the trade (size_multiplier = 0.0). Only when SPECIFIC reason this trade is meaningfully worse than baseline expectancy.

IMPORTANT — be JUDGMENT-driven. SB has positive baseline expectancy; do NOT over-skip. Default to "fire" unless there's a concrete reason to reduce or reject. Skip is for setups where you can articulate WHY this trade is worse than the SB historical average, not generic caution.

RESPONSE FORMAT (strict JSON, max ~300 char rationale):
{{
  "decision": "fire" | "skip" | "half",
  "size_multiplier": 1.0 | 0.5 | 0.0,
  "confidence": 0.0 to 1.0,
  "rationale": "concise reason ~200-300 chars — reference specific signal/context facts"
}}"""

    def _parse_response(
        self,
        response_text: str,
        context: dict,
        elapsed_ms: int,
    ) -> KZValidatorDecision:
        """Parse Claude's JSON response into a decision."""
        kz = context.get("kz", "unknown")
        clean = response_text.strip()
        # Strip code fences if Claude added them despite instructions
        if clean.startswith("```"):
            m = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", clean, re.S)
            if m:
                clean = m.group(1).strip()
            else:
                # Best-effort strip just the leading fence
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean

        try:
            data = json.loads(clean)
            decision = str(data.get("decision", "fire")).lower().strip()
            if decision not in _VALID_DECISIONS:
                logger.warning(
                    "KZValidator: invalid decision '%s' for %s; falling back to 'fire'",
                    decision, kz,
                )
                decision = "fire"

            # Default size_multiplier matches decision unless explicitly provided
            default_mult = {"fire": 1.0, "half": 0.5, "skip": 0.0}[decision]
            size_mult = float(data.get("size_multiplier", default_mult))
            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))  # clamp
            rationale = str(data.get("rationale", ""))[:500]

            return KZValidatorDecision(
                kz=kz,
                decision=decision,
                size_multiplier=size_mult,
                confidence=confidence,
                rationale=rationale,
                model=self._model,
                response_ms=elapsed_ms,
                context=context,
            )
        except Exception as exc:
            logger.error(
                "KZValidator parse failed for %s: %s\nResponse[:300]: %s",
                kz, exc, response_text[:300],
            )
            return KZValidatorDecision(
                kz=kz, decision="fire", size_multiplier=1.0,
                confidence=0.0, rationale=f"Parse error: {exc}",
                model=self._model, response_ms=elapsed_ms,
                context=context, error=str(exc),
            )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def validate_kz_entry(
    context: dict,
    api_key: str = ANTHROPIC_API_KEY,
    model: Optional[str] = None,
    shadow_mode: bool = True,
) -> KZValidatorDecision:
    """One-shot convenience: build agent, call validator, return decision."""
    agent = KZValidatorAgent(
        api_key=api_key, model=model, shadow_mode=shadow_mode,
    )
    return agent.validate_kz_entry(context)
