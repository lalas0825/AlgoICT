"""
strategy_lab/lab_report.py
===========================
Session summary report generator.

Writes a Markdown report summarizing one Lab session:
  * Hypotheses generated
  * Pass/fail breakdown per gate
  * Surviving candidates with their key metrics
  * Insights (most common failure stage)

Output goes to ``.claude/memory/project/lab-sessions/<session_id>.md``
for long-term memory, plus an optional Telegram-friendly short form.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .candidate_manager import CandidateRecord

logger = logging.getLogger(__name__)


DEFAULT_REPORT_DIR = Path(".claude") / "memory" / "project" / "lab-sessions"


@dataclass
class SessionSummary:
    """Aggregated numbers for one Lab session."""
    session_id: str
    mode: str
    started_at: str
    finished_at: str
    hypotheses_generated: int
    candidates_found: int  # all 9 gates passed
    approved: int
    failed: int
    rejected: int
    best_score: int
    gate_fail_counts: dict[str, int] = field(default_factory=dict)


class LabReport:
    """
    Builds human-readable reports from a collection of CandidateRecord.

    Parameters
    ----------
    report_dir : Path
        Directory where Markdown reports are written.
    """

    def __init__(self, report_dir: Path = DEFAULT_REPORT_DIR):
        self.report_dir = Path(report_dir)

    # ─── Public API ──────────────────────────────────────────────────────

    def build_summary(
        self,
        session_id: str,
        records: Iterable[CandidateRecord],
    ) -> SessionSummary:
        """Aggregate a set of records into a SessionSummary."""
        records = list(records)
        if not records:
            now = datetime.now(timezone.utc).isoformat()
            return SessionSummary(
                session_id=session_id,
                mode="unknown",
                started_at=now,
                finished_at=now,
                hypotheses_generated=0,
                candidates_found=0,
                approved=0,
                failed=0,
                rejected=0,
                best_score=0,
            )

        mode = records[0].mode or "generate"
        started_at = min(r.created_at for r in records if r.created_at)
        finished_at = max(r.created_at for r in records if r.created_at)

        candidates_found = sum(
            1 for r in records if r.gates_passed == r.gates_total and r.gates_total > 0
        )
        approved = sum(1 for r in records if r.status == "approved")
        failed = sum(1 for r in records if r.status == "failed")
        rejected = sum(1 for r in records if r.status == "rejected")
        best_score = max((r.score for r in records), default=0)

        # Which gates failed most often?
        gate_fail_counts: dict[str, int] = {}
        for r in records:
            for name, data in (r.gate_results or {}).items():
                if isinstance(data, dict) and not data.get("passed", False):
                    gate_fail_counts[name] = gate_fail_counts.get(name, 0) + 1

        return SessionSummary(
            session_id=session_id,
            mode=mode,
            started_at=started_at,
            finished_at=finished_at,
            hypotheses_generated=len(records),
            candidates_found=candidates_found,
            approved=approved,
            failed=failed,
            rejected=rejected,
            best_score=best_score,
            gate_fail_counts=gate_fail_counts,
        )

    def write_markdown(
        self,
        summary: SessionSummary,
        records: Iterable[CandidateRecord],
    ) -> Path:
        """Write a Markdown file summarizing the session. Returns the path."""
        self.report_dir.mkdir(parents=True, exist_ok=True)
        path = self.report_dir / f"{summary.session_id}.md"

        records = list(records)
        content = self._render_markdown(summary, records)
        path.write_text(content, encoding="utf-8")
        logger.info("Lab report written: %s", path)
        return path

    def telegram_summary(self, summary: SessionSummary) -> str:
        """Short Telegram-friendly message (≤ 500 chars)."""
        candidates_line = (
            f"🎯 {summary.candidates_found} candidate{'s' if summary.candidates_found != 1 else ''} found"
            if summary.candidates_found > 0
            else "No candidates survived the gates"
        )
        top_fail = "—"
        if summary.gate_fail_counts:
            top_fail = max(summary.gate_fail_counts.items(), key=lambda kv: kv[1])[0]

        return (
            f"🧪 Lab Session {summary.session_id}\n"
            f"Mode: {summary.mode}\n"
            f"Hypotheses: {summary.hypotheses_generated}\n"
            f"{candidates_line}\n"
            f"Best score: {summary.best_score}\n"
            f"Top failure gate: {top_fail}"
        )

    # ─── Internal rendering ──────────────────────────────────────────────

    def _render_markdown(
        self,
        summary: SessionSummary,
        records: list[CandidateRecord],
    ) -> str:
        lines: list[str] = []
        lines.append(f"# Lab Session — {summary.session_id}")
        lines.append("")
        lines.append(f"- **Mode:** `{summary.mode}`")
        lines.append(f"- **Started:** {summary.started_at}")
        lines.append(f"- **Finished:** {summary.finished_at}")
        lines.append(f"- **Hypotheses generated:** {summary.hypotheses_generated}")
        lines.append(f"- **Candidates (all gates passed):** {summary.candidates_found}")
        lines.append(f"- **Approved:** {summary.approved}")
        lines.append(f"- **Rejected:** {summary.rejected}")
        lines.append(f"- **Best score:** {summary.best_score}")
        lines.append("")

        # Gate failure histogram
        if summary.gate_fail_counts:
            lines.append("## Gate Failure Breakdown")
            lines.append("")
            lines.append("| Gate | Failures |")
            lines.append("|------|----------|")
            for gate, count in sorted(
                summary.gate_fail_counts.items(), key=lambda kv: -kv[1]
            ):
                lines.append(f"| `{gate}` | {count} |")
            lines.append("")

        # Winning candidates
        winners = [
            r for r in records
            if r.gates_passed == r.gates_total and r.gates_total > 0
        ]
        if winners:
            lines.append("## Candidates That Passed All 9 Gates")
            lines.append("")
            for r in sorted(winners, key=lambda r: -r.score):
                hyp = r.hypothesis
                lines.append(f"### {r.id} — {hyp.get('name', 'unnamed')}")
                lines.append("")
                lines.append(f"**Score:** {r.score}/100")
                if r.sharpe_improvement is not None:
                    lines.append(f"**Sharpe Δ:** {r.sharpe_improvement:+.3f}")
                if r.net_profit_delta is not None:
                    lines.append(f"**Net profit Δ:** ${r.net_profit_delta:+.0f}")
                lines.append("")
                lines.append(f"**ICT reasoning:**  {hyp.get('ict_reasoning', '—')}")
                lines.append("")
                lines.append(f"**Condition:**  `{hyp.get('condition', '—')}`")
                lines.append("")
                lines.append(f"**Status:** `{r.status}`")
                lines.append("")

        # All hypotheses log (compact)
        lines.append("## All Hypotheses")
        lines.append("")
        lines.append("| ID | Name | Score | Gates | Status | Failure |")
        lines.append("|----|------|-------|-------|--------|---------|")
        for r in sorted(records, key=lambda r: r.id):
            hyp = r.hypothesis
            first_fail = "—"
            for name, data in (r.gate_results or {}).items():
                if isinstance(data, dict) and not data.get("passed", False):
                    first_fail = name
                    break
            lines.append(
                f"| `{r.id}` "
                f"| {hyp.get('name', '—')[:40]} "
                f"| {r.score} "
                f"| {r.gates_passed}/{r.gates_total} "
                f"| {r.status} "
                f"| {first_fail} |"
            )
        lines.append("")

        return "\n".join(lines)
