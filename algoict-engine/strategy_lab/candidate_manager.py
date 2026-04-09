"""
strategy_lab/candidate_manager.py
==================================
Persist, rank, and report strategy candidates.

Storage
-------
Candidates are stored as JSON lines in ``data/strategy_lab/candidates.jsonl``.
Each line is one PipelineResult flattened into a dict. We use JSONL (not
a single JSON file) so concurrent overnight batch writes are safe — each
line is atomic.

Ranking
-------
Candidates are scored 0–100:
  * 60 points for gates passed (each of the 9 gates contributes ~6.6 pts)
  * 20 points for Sharpe improvement (normalized vs expected range)
  * 20 points for walk-forward positivity above the 70% threshold

Higher = better. Ties are broken by creation time (earliest first).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .types import BacktestMetrics, GateResult, Hypothesis, PipelineResult
from .walk_forward import WalkForwardResult
from .cross_instrument import CrossInstrumentResult
from .stress_tester import StressTestResult

logger = logging.getLogger(__name__)


DEFAULT_STORE_DIR = Path("data") / "strategy_lab"
CANDIDATE_FILE = "candidates.jsonl"
SESSION_FILE = "sessions.jsonl"


# ─── Persistent record (serialized form of PipelineResult) ──────────────

@dataclass
class CandidateRecord:
    """
    Flat dict-friendly record saved to candidates.jsonl.

    Mirrors the shape consumed by the dashboard's `strategy_candidates`
    Supabase table so we can copy records between the two stores.
    """
    id: str
    hypothesis: dict
    status: str
    score: int
    gates_passed: int
    gates_total: int
    gate_results: dict
    session_id: str
    created_at: str
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    sharpe_improvement: Optional[float] = None
    net_profit_delta: Optional[float] = None
    notes: Optional[str] = None
    mode: Optional[str] = None
    strategy_name: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CandidateRecord":
        return cls(
            id=d["id"],
            hypothesis=d.get("hypothesis", {}),
            status=d.get("status", "pending"),
            score=int(d.get("score", 0)),
            gates_passed=int(d.get("gates_passed", 0)),
            gates_total=int(d.get("gates_total", 9)),
            gate_results=d.get("gate_results", {}),
            session_id=d.get("session_id", ""),
            created_at=d.get("created_at", ""),
            approved_at=d.get("approved_at"),
            approved_by=d.get("approved_by"),
            sharpe_improvement=d.get("sharpe_improvement"),
            net_profit_delta=d.get("net_profit_delta"),
            notes=d.get("notes"),
            mode=d.get("mode"),
            strategy_name=d.get("strategy_name"),
        )


# ─── Manager ────────────────────────────────────────────────────────────

class CandidateManager:
    """
    Read/write candidates + compute rank scores.

    Parameters
    ----------
    store_dir : Path
        Directory where candidates.jsonl + sessions.jsonl live.
        Created on first write if missing.
    """

    def __init__(self, store_dir: Path = DEFAULT_STORE_DIR):
        self.store_dir = Path(store_dir)
        self.candidates_path = self.store_dir / CANDIDATE_FILE

    # ─── Save / load ─────────────────────────────────────────────────────

    def save(self, record: CandidateRecord) -> None:
        """Append one record to the JSONL store. Atomic per line."""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with self.candidates_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), default=str) + "\n")
        logger.debug("Saved candidate %s to %s", record.id, self.candidates_path)

    def save_pipeline_result(
        self,
        result: PipelineResult,
        session_id: str,
        mode: str = "generate",
        strategy_name: str = "",
    ) -> CandidateRecord:
        """Convert a PipelineResult into a CandidateRecord and persist it."""
        record = self._build_record(result, session_id, mode, strategy_name)
        self.save(record)
        return record

    def load_all(self) -> list[CandidateRecord]:
        """Read every candidate record from the JSONL store."""
        if not self.candidates_path.exists():
            return []
        records: list[CandidateRecord] = []
        with self.candidates_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(CandidateRecord.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(
                        "Skipping malformed candidate line %d: %s", line_num, e
                    )
        return records

    def load_one(self, candidate_id: str) -> Optional[CandidateRecord]:
        """Return the first record matching ``candidate_id`` or None."""
        for record in self.load_all():
            if record.id == candidate_id:
                return record
        return None

    def load_session(self, session_id: str) -> list[CandidateRecord]:
        """All records created in a given session."""
        return [r for r in self.load_all() if r.session_id == session_id]

    # ─── Ranking ─────────────────────────────────────────────────────────

    def rank(self, records: Optional[Iterable[CandidateRecord]] = None) -> list[CandidateRecord]:
        """
        Return candidates sorted by score descending.

        Uses the pre-computed ``score`` field from each record — the Lab
        engine is responsible for populating it correctly at save time.
        """
        if records is None:
            records = self.load_all()
        return sorted(
            records,
            key=lambda r: (-r.score, r.created_at),
        )

    def top_n(self, n: int = 10) -> list[CandidateRecord]:
        """Highest-scoring ``n`` candidates across all sessions."""
        return self.rank()[:n]

    # ─── Score computation ──────────────────────────────────────────────

    @staticmethod
    def compute_score(result: PipelineResult) -> int:
        """
        Composite 0–100 score for ranking candidates.

        Breakdown:
          * 60 points — gates passed × (60 / 9)
          * 20 points — Sharpe improvement
              0 if Δ ≤ 0, 20 if Δ ≥ 0.5, linear between
          * 20 points — walk-forward positivity above 70% floor
              0 if pct ≤ 0.70, 20 if pct ≥ 1.0, linear between
        """
        gates_score = (result.gates_passed_count / 9.0) * 60.0

        sharpe_delta = 0.0
        if result.baseline_metrics and result.hypothesis_metrics:
            sharpe_delta = (
                result.hypothesis_metrics.sharpe - result.baseline_metrics.sharpe
            )
        sharpe_score = max(0.0, min(1.0, sharpe_delta / 0.5)) * 20.0

        wf_pct = result.walk_forward_positive_pct
        wf_bonus = max(0.0, min(1.0, (wf_pct - 0.70) / 0.30)) * 20.0

        total = gates_score + sharpe_score + wf_bonus
        return int(round(total))

    # ─── Status transitions ──────────────────────────────────────────────

    def mark_approved(
        self,
        candidate_id: str,
        approver: str,
        notes: Optional[str] = None,
    ) -> CandidateRecord:
        """
        Approve a candidate for Test Set evaluation.

        Rewrites the JSONL store (rare operation — don't use in hot paths).
        """
        records = self.load_all()
        target: Optional[CandidateRecord] = None
        for r in records:
            if r.id == candidate_id:
                r.status = "approved"
                r.approved_at = datetime.now(timezone.utc).isoformat()
                r.approved_by = approver
                if notes:
                    r.notes = notes
                target = r
                break
        if target is None:
            raise KeyError(f"Candidate {candidate_id!r} not found.")
        self._rewrite_all(records)
        return target

    def mark_rejected(self, candidate_id: str, notes: Optional[str] = None) -> CandidateRecord:
        """Mark a candidate as rejected (never promoted to Test Set)."""
        records = self.load_all()
        target: Optional[CandidateRecord] = None
        for r in records:
            if r.id == candidate_id:
                r.status = "rejected"
                if notes:
                    r.notes = notes
                target = r
                break
        if target is None:
            raise KeyError(f"Candidate {candidate_id!r} not found.")
        self._rewrite_all(records)
        return target

    # ─── Internals ──────────────────────────────────────────────────────

    def _build_record(
        self,
        result: PipelineResult,
        session_id: str,
        mode: str,
        strategy_name: str,
    ) -> CandidateRecord:
        gate_dict = {g.gate_name: g.to_dict() for g in result.gates}

        # Make gate_dict match the TS GateResultsData shape for dashboard parity
        gate_results_ui = {}
        for g in result.gates:
            gate_results_ui[g.gate_name] = {
                "passed": g.passed,
                "value": g.metric,
                "threshold": g.threshold,
                "reason": g.reason,
            }

        sharpe_delta = None
        if result.baseline_metrics and result.hypothesis_metrics:
            sharpe_delta = (
                result.hypothesis_metrics.sharpe - result.baseline_metrics.sharpe
            )
        net_profit_delta = None
        if result.baseline_metrics and result.hypothesis_metrics:
            net_profit_delta = (
                result.hypothesis_metrics.total_pnl
                - result.baseline_metrics.total_pnl
            )

        return CandidateRecord(
            id=result.hypothesis.id,
            hypothesis=result.hypothesis.to_dict(),
            status=result.status,
            score=self.compute_score(result),
            gates_passed=result.gates_passed_count,
            gates_total=9,
            gate_results=gate_results_ui,
            session_id=session_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            sharpe_improvement=sharpe_delta,
            net_profit_delta=net_profit_delta,
            notes=None,
            mode=mode,
            strategy_name=strategy_name,
        )

    def _rewrite_all(self, records: list[CandidateRecord]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.candidates_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r.to_dict(), default=str) + "\n")
        tmp.replace(self.candidates_path)
