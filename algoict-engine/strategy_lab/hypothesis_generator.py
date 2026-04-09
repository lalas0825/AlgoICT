"""
strategy_lab/hypothesis_generator.py
=====================================
Generates ICT-grounded trading hypotheses via Claude API.

Why Claude
----------
The Strategy Lab does NOT optimize parameters blindly. It generates
hypotheses that have a fundamental ICT reason to exist. A trained LLM
is uniquely good at proposing *why* something might work, then we
brute-force verify the *whether*. This keeps us in the "discovery of
mechanisms" space and out of the "curve fitting" hellhole.

Prompt engineering (verbatim from skill spec)
---------------------------------------------
The LLM must produce a JSON array of hypothesis objects with:
  id, name, ict_reasoning, condition, parameters_added, expected_impact, risk

Each hypothesis must have an ICT fundamental reason — NOT "because the
backtest shows". Max 1–2 parameters per hypothesis. One thing at a time.

Graceful degradation
--------------------
If ``anthropic`` isn't installed or the API key is missing, the
generator raises a clear error at first-use rather than at import time.
This lets the module be imported for offline tests.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .types import Hypothesis

logger = logging.getLogger(__name__)


DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 2500
DEFAULT_TEMPERATURE = 0.7  # Some creativity, not chaos
DEFAULT_COUNT = 5


@dataclass
class GenerationContext:
    """
    Context bundle fed into the LLM prompt.

    Every field is optional — the generator adapts gracefully when parts
    of the context aren't available (e.g., first run has no
    previous_hypotheses, early sessions have no post-mortem patterns).
    """
    baseline_stats: dict = field(default_factory=dict)
    loss_patterns: list = field(default_factory=list)
    ict_concepts: list = field(default_factory=list)
    previous_hypotheses: list = field(default_factory=list)
    market_regime_stats: dict = field(default_factory=dict)

    def to_prompt_block(self) -> str:
        """Format as the JSON block used inside the prompt."""
        return json.dumps(
            {
                "baseline_stats": self.baseline_stats,
                "loss_patterns": self.loss_patterns[:10],
                "ict_concepts": self.ict_concepts[:20],
                "previous_hypotheses": self.previous_hypotheses[-20:],
                "market_regime_stats": self.market_regime_stats,
            },
            indent=2,
            default=str,
        )


SYSTEM_PROMPT = """You are a senior ICT quant researcher. Your job is to generate TESTABLE trading hypotheses grounded in ICT methodology.

RULES FOR GENERATING HYPOTHESES:
1. Each hypothesis MUST have a fundamental ICT reason for why it should work.
   "Because the backtest shows..." is NOT a valid reason.
   "Because institutional order flow creates..." IS a valid reason.

2. Each hypothesis should modify AT MOST 1-2 parameters or add 1 condition.
   NOT "change 5 things at once." ONE thing at a time.

3. Focus on the WEAKEST areas first (highest loss patterns from post-mortem).

4. Think about TIME (when), STRUCTURE (what setup), and CONTEXT (what environment).

5. Each hypothesis must be specific enough to code as a boolean condition.

Respond ONLY with a JSON array — no prose, no code fences, no explanation."""


USER_PROMPT_TEMPLATE = """CONTEXT:
{context_json}

Generate {count} hypotheses. For each one provide exactly this JSON structure:
{{
  "id": "H-XXX",
  "name": "Short descriptive name (≤50 chars)",
  "ict_reasoning": "WHY this should work based on ICT theory (2-3 sentences)",
  "condition": "Exact boolean condition to add (pseudocode)",
  "parameters_added": 0,
  "expected_impact": "What metric should improve and by how much",
  "risk": "What could go wrong / why this might be overfitting"
}}

Respond ONLY with a JSON array of {count} such objects."""


class HypothesisGenerator:
    """
    Wraps the Anthropic Messages API to produce ICT-grounded hypotheses.

    Parameters
    ----------
    api_key : str, optional
        Anthropic API key. Defaults to ``ANTHROPIC_API_KEY`` env var.
    model : str
        Claude model ID. Defaults to ``claude-sonnet-4-5``.
    temperature : float
        Sampling temperature (0–1). Lower = more deterministic.
    max_tokens : int
        Response budget.
    client : object, optional
        Pre-built Anthropic client (lets tests inject a mock).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Optional[object] = None,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = client  # Lazy — built on first use if not injected

    # ─── Public API ──────────────────────────────────────────────────────

    def generate(
        self,
        context: GenerationContext,
        count: int = DEFAULT_COUNT,
        id_prefix: str = "H",
        start_id: int = 1,
    ) -> list[Hypothesis]:
        """
        Request ``count`` hypotheses from the LLM and parse the response.

        Parameters
        ----------
        context : GenerationContext
            What the LLM sees about the current state of the strategy.
        count : int
            Number of hypotheses to generate (3–10 reasonable range).
        id_prefix : str
            Prefix for auto-generated IDs (e.g. "H" → "H-001").
        start_id : int
            Starting number for ID assignment.

        Returns
        -------
        list[Hypothesis]
            Parsed hypotheses. The caller is responsible for enforcing
            uniqueness and persisting.
        """
        client = self._get_client()
        prompt = USER_PROMPT_TEMPLATE.format(
            context_json=context.to_prompt_block(),
            count=count,
        )

        logger.info(
            "HypothesisGenerator: requesting %d hypotheses from %s",
            count,
            self.model,
        )

        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = self._extract_text(response)
        raw_json = self._strip_code_fences(raw_text)

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response as JSON: %s", e)
            logger.debug("Raw LLM output: %s", raw_text[:500])
            raise ValueError(
                f"HypothesisGenerator: LLM returned non-JSON response. "
                f"First 200 chars: {raw_text[:200]!r}"
            ) from e

        if not isinstance(data, list):
            raise ValueError(
                f"Expected JSON array, got {type(data).__name__}"
            )

        hypotheses: list[Hypothesis] = []
        for i, item in enumerate(data):
            try:
                # Auto-assign ID if missing or duplicate
                if not item.get("id"):
                    item["id"] = f"{id_prefix}-{start_id + i:03d}"
                hypotheses.append(Hypothesis.from_dict(item))
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("Skipping malformed hypothesis #%d: %s", i, e)

        return hypotheses

    # ─── Internals ───────────────────────────────────────────────────────

    def _get_client(self):
        """Build the Anthropic client lazily (so imports stay cheap)."""
        if self._client is not None:
            return self._client
        try:
            import anthropic  # type: ignore
        except ImportError as e:
            raise ImportError(
                "HypothesisGenerator requires the 'anthropic' package. "
                "Install it with: pip install anthropic"
            ) from e

        if not self.api_key:
            raise RuntimeError(
                "HypothesisGenerator: ANTHROPIC_API_KEY not set. "
                "Pass api_key=... or set the environment variable."
            )

        self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    @staticmethod
    def _extract_text(response) -> str:
        """
        Pull the assistant text out of an Anthropic Messages response.

        Works with both the real ``Message`` object and dict-shaped mocks.
        """
        content = getattr(response, "content", None)
        if content is None and isinstance(response, dict):
            content = response.get("content")
        if not content:
            return ""
        block = content[0]
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text", "")
        return text or ""

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove ```json ... ``` wrappers if the LLM added them anyway."""
        text = text.strip()
        fence = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
        return fence.sub("", text).strip()
