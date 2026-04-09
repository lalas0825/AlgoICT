"""
strategy_lab/occam_checker.py
==============================
Gate 8 — Occam's Razor.

Philosophy
----------
Complex hypotheses are easier to curve-fit. Simple hypotheses that work
are more likely to encode a real market mechanism. The rule:

    A hypothesis can add AT MOST 2 new parameters to the existing strategy.

If it needs 5 new knobs to "work", you're not describing an edge — you're
describing a shape of the training data.

Implementation
--------------
We trust the hypothesis generator to declare its ``parameters_added`` count
honestly (it's part of the LLM prompt schema). We also provide a
best-effort fallback that counts numeric literals in the ``condition``
string, for sanity-checking against LLM hallucination.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .types import Hypothesis

logger = logging.getLogger(__name__)


DEFAULT_MAX_NEW_PARAMETERS = 2  # Gate 8 threshold


@dataclass
class OccamResult:
    """Outcome of the complexity check."""
    declared_params: int       # What the LLM said
    estimated_params: int      # What we counted from the condition string
    effective_params: int      # max(declared, estimated) — be strict
    max_allowed: int
    passed: bool
    reason: str

    def summary(self) -> str:
        return (
            f"Occam: declared={self.declared_params} "
            f"estimated={self.estimated_params} "
            f"effective={self.effective_params} "
            f"max={self.max_allowed} "
            f"{'✅' if self.passed else '❌'}"
        )


class OccamChecker:
    """
    Counts parameters that a hypothesis introduces and rejects if > max.

    Two counts are produced and the stricter wins:
      1. ``hypothesis.parameters_added`` — self-reported by the LLM.
      2. A heuristic estimate from the ``condition`` pseudocode that
         counts numeric literals and comparison thresholds.

    The effective param count = max(declared, estimated). This protects
    against an LLM under-reporting complexity.
    """

    # Regex for numeric literals: ints, floats, scientific notation.
    # Deliberately excludes "0" and "1" which are common boolean-ish constants.
    _NUMERIC_RE = re.compile(
        r"(?<![A-Za-z_])-?\b(?!(?:0|1)\b)\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\b"
    )

    def __init__(self, max_new_parameters: int = DEFAULT_MAX_NEW_PARAMETERS):
        if max_new_parameters < 0:
            raise ValueError("max_new_parameters must be >= 0")
        self.max_new_parameters = max_new_parameters

    # ─── Public API ──────────────────────────────────────────────────────

    def check(self, hypothesis: Hypothesis) -> OccamResult:
        """
        Evaluate a hypothesis against the complexity budget.

        Returns
        -------
        OccamResult
            ``.passed`` is True iff effective_params <= max_new_parameters.
        """
        declared = max(0, int(hypothesis.parameters_added))
        estimated = self.estimate_from_condition(hypothesis.condition)
        effective = max(declared, estimated)

        passed = effective <= self.max_new_parameters

        if passed:
            reason = f"Within budget ({effective}/{self.max_new_parameters} params)"
        elif declared > self.max_new_parameters:
            reason = (
                f"Hypothesis declares {declared} new params — "
                f"exceeds budget of {self.max_new_parameters}"
            )
        else:
            reason = (
                f"Condition pseudocode implies {estimated} parameters "
                f"(LLM reported {declared}) — exceeds budget of "
                f"{self.max_new_parameters}"
            )

        logger.debug(
            "Occam check for %s: declared=%d est=%d eff=%d passed=%s",
            hypothesis.id,
            declared,
            estimated,
            effective,
            passed,
        )

        return OccamResult(
            declared_params=declared,
            estimated_params=estimated,
            effective_params=effective,
            max_allowed=self.max_new_parameters,
            passed=passed,
            reason=reason,
        )

    def estimate_from_condition(self, condition: str) -> int:
        """
        Heuristic parameter count from the condition pseudocode.

        Rules:
          * Count distinct numeric literals (excluding 0 and 1 which are
            commonly used as booleans/indices).
          * Each numeric literal typically corresponds to a tunable threshold.

        This is a *lower bound* — we cannot reliably detect arbitrary
        parameters, but we catch obvious cases like
        ``"volume > 1000 AND atr > 2.5 AND streak < 3"`` (3 params).
        """
        if not condition:
            return 0

        matches = self._NUMERIC_RE.findall(condition)
        distinct = {m for m in matches}
        return len(distinct)
