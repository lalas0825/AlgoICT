"""
strategy_lab/lab_engine.py
===========================
Strategy Lab pipeline orchestrator.

Pipeline order (per hypothesis)
-------------------------------
    1. Training baseline + hypothesis backtest       (Gates 1–3)
    2. Walk-forward validation                       (Gate 4)
    3. Cross-instrument validation                   (Gate 5)
    4. Stress tests (noise, shift, sparse, slippage) (Gates 6–7)
    5. Occam's Razor complexity check                (Gate 8)
    6. Validation set run (2023)                     (Gate 9)

All 9 gates are evaluated even if earlier gates fail — the dashboard
needs to show WHICH gates failed, not just THAT the pipeline stopped.

CLI
---
    python -m strategy_lab.lab_engine --mode generate --count 5
    python -m strategy_lab.lab_engine --mode overnight --count 20
    python -m strategy_lab.lab_engine --approve H-001 --auth JUAN_APPROVED_FINAL_TEST
    python -m strategy_lab.lab_engine --list
    python -m strategy_lab.lab_engine --detail H-001
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from .types import (
    BacktestMetrics,
    BacktestRunner,
    Hypothesis,
    PipelineResult,
)
from .data_splitter import DataSplitter
from .walk_forward import WalkForwardValidator
from .stress_tester import StressTester
from .cross_instrument import CrossInstrumentValidator
from .occam_checker import OccamChecker
from .anti_overfit_gates import AntiOverfitGates, StageResults
from .candidate_manager import CandidateManager
from .lab_report import LabReport

logger = logging.getLogger(__name__)


@dataclass
class LabEngineConfig:
    """All tunables in one place."""
    strategy_name: str = "ny_am_reversal"
    mode: str = "generate"
    count: int = 5
    store_dir: Path = Path("data") / "strategy_lab"


class LabEngine:
    """
    Orchestrates the full 9-gate pipeline for a list of hypotheses.

    Injection points
    ----------------
    Because the Lab is strategy-agnostic, the caller must provide:

      * ``splitter``    — DataSplitter already built from historical data
      * ``runner``      — BacktestRunner callable
      * ``xi_datasets`` — dict[symbol → DataFrame] for cross-instrument Gate 5

    The engine never touches the Test Set (splitter.get_test requires auth).
    """

    def __init__(
        self,
        splitter: DataSplitter,
        runner: BacktestRunner,
        xi_datasets: dict[str, pd.DataFrame],
        config: Optional[LabEngineConfig] = None,
        candidate_manager: Optional[CandidateManager] = None,
        report: Optional[LabReport] = None,
    ):
        self.splitter = splitter
        self.runner = runner
        self.xi_datasets = xi_datasets
        self.config = config or LabEngineConfig()
        self.candidates = candidate_manager or CandidateManager(
            self.config.store_dir
        )
        self.report = report or LabReport()
        self.gates = AntiOverfitGates()

    # ─── Pipeline core ───────────────────────────────────────────────────

    def run_pipeline(self, hypothesis: Hypothesis) -> PipelineResult:
        """
        Execute all 9 gates for one hypothesis and return the full result.
        """
        logger.info("=" * 60)
        logger.info("Pipeline start: %s — %s", hypothesis.id, hypothesis.name)
        result = PipelineResult(hypothesis=hypothesis, status="running")

        training = self.splitter.get_training()
        validation = self.splitter.get_validation()

        # --- Stage 1-3: Training backtests ------------------------------
        logger.info("[%s] Stage 1: training baseline + hypothesis backtest",
                    hypothesis.id)
        baseline_metrics = self.runner(
            training, use_hypothesis=False, hypothesis_config=None
        )
        hyp_metrics = self.runner(
            training,
            use_hypothesis=True,
            hypothesis_config=hypothesis.config,
        )
        result.baseline_metrics = baseline_metrics
        result.hypothesis_metrics = hyp_metrics

        # --- Stage 4: Walk-forward --------------------------------------
        logger.info("[%s] Stage 4: walk-forward", hypothesis.id)
        wf = WalkForwardValidator(self.runner)
        wf_result = wf.validate(training, hypothesis_config=hypothesis.config)
        result.walk_forward_positive_pct = wf_result.positive_percentage

        # --- Stage 5: Cross-instrument ----------------------------------
        logger.info("[%s] Stage 5: cross-instrument", hypothesis.id)
        xi = CrossInstrumentValidator(self.runner)
        xi_result = xi.validate(self.xi_datasets, hypothesis_config=hypothesis.config)
        result.instruments_passing = xi_result.instruments_passing

        # --- Stage 6-7: Stress tests ------------------------------------
        logger.info("[%s] Stage 6: stress tests", hypothesis.id)
        stress = StressTester(self.runner)
        stress_result = stress.run_all_tests(training, hypothesis_config=hypothesis.config)
        result.noise_resilience = 1.0 - stress_result.max_degradation
        result.inversion_loses = stress_result.inversion_loses

        # --- Stage 9: Validation set ------------------------------------
        logger.info("[%s] Stage 9: validation set (2023)", hypothesis.id)
        val_baseline = self.runner(
            validation, use_hypothesis=False, hypothesis_config=None
        )
        val_hyp = self.runner(
            validation,
            use_hypothesis=True,
            hypothesis_config=hypothesis.config,
        )
        result.validation_improvement = val_hyp.sharpe - val_baseline.sharpe

        # --- Run all 9 gates --------------------------------------------
        stage = StageResults(
            training_baseline=baseline_metrics,
            training_hypothesis=hyp_metrics,
            walk_forward=wf_result,
            cross_instrument=xi_result,
            stress=stress_result,
            validation_baseline=val_baseline,
            validation_hypothesis=val_hyp,
        )
        result.gates = self.gates.run_all_gates(hypothesis, stage)

        # --- Finalize status --------------------------------------------
        if result.all_gates_passed:
            result.status = "passed"
        else:
            result.status = "failed"
            # Record the first failed stage for debugging
            for g in result.gates:
                if not g.passed:
                    result.failure_stage = g.gate_name
                    break

        result.score = self.candidates.compute_score(result)

        logger.info(
            "[%s] Pipeline done: %s (%d/9 gates, score=%d)",
            hypothesis.id,
            result.status,
            result.gates_passed_count,
            result.score,
        )
        return result

    def run_batch(
        self,
        hypotheses: list[Hypothesis],
        session_id: Optional[str] = None,
        mode: str = "generate",
    ) -> list[PipelineResult]:
        """
        Run ``run_pipeline`` for every hypothesis and persist each result.
        Returns the full list of PipelineResult objects.
        """
        session_id = session_id or self._new_session_id()
        results: list[PipelineResult] = []
        for h in hypotheses:
            try:
                result = self.run_pipeline(h)
            except Exception as e:
                logger.exception("Pipeline crashed on %s: %s", h.id, e)
                result = PipelineResult(
                    hypothesis=h,
                    status="failed",
                    failure_stage=f"exception: {type(e).__name__}",
                )
            results.append(result)
            self.candidates.save_pipeline_result(
                result,
                session_id=session_id,
                mode=mode,
                strategy_name=self.config.strategy_name,
            )

        # Write session report
        session_records = self.candidates.load_session(session_id)
        summary = self.report.build_summary(session_id, session_records)
        self.report.write_markdown(summary, session_records)

        return results

    # ─── Approval flow (unlocks Test Set) ───────────────────────────────

    def approve_and_test(
        self,
        candidate_id: str,
        approver: str,
        auth_code: str,
    ) -> dict:
        """
        Approve a candidate and run it ONCE against the Test Set (2024+).

        This is the only place in the codebase that calls
        ``splitter.get_test()``. The auth code is passed through and the
        splitter enforces the lock.
        """
        record = self.candidates.load_one(candidate_id)
        if record is None:
            raise KeyError(f"Candidate {candidate_id!r} not found.")
        if record.gates_passed != record.gates_total:
            raise ValueError(
                f"Candidate {candidate_id} has not passed all 9 gates "
                f"({record.gates_passed}/{record.gates_total}). "
                "Cannot promote to Test Set."
            )

        # Single-use unlock — will raise if wrong code or already used
        test_data = self.splitter.get_test(auth_code)
        logger.warning("⚠️ Test Set unlocked for %s by %s", candidate_id, approver)

        # Reconstruct the hypothesis to run on the test set
        hyp = Hypothesis.from_dict(record.hypothesis)

        baseline = self.runner(test_data, use_hypothesis=False, hypothesis_config=None)
        with_hyp = self.runner(test_data, use_hypothesis=True, hypothesis_config=hyp.config)

        sharpe_delta = with_hyp.sharpe - baseline.sharpe
        pnl_delta = with_hyp.total_pnl - baseline.total_pnl
        passed = sharpe_delta > 0

        # Persist approval + note
        note = (
            f"TEST SET RESULT: Sharpe Δ={sharpe_delta:+.3f}, "
            f"P&L Δ=${pnl_delta:+.0f}, "
            f"{'PASSED ✅' if passed else 'FAILED ❌'}"
        )
        self.candidates.mark_approved(candidate_id, approver, notes=note)

        return {
            "candidate_id": candidate_id,
            "baseline_sharpe": baseline.sharpe,
            "hypothesis_sharpe": with_hyp.sharpe,
            "sharpe_delta": sharpe_delta,
            "pnl_delta": pnl_delta,
            "passed": passed,
        }

    # ─── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _new_session_id() -> str:
        return datetime.now(timezone.utc).strftime("LAB-%Y%m%d-%H%M%S")


# ─── CLI ────────────────────────────────────────────────────────────────

def _cli_list(store_dir: Path) -> int:
    mgr = CandidateManager(store_dir)
    records = mgr.rank()
    if not records:
        print("No candidates yet.")
        return 0
    print(f"{'ID':<8} {'Score':>5}  {'Gates':>6}  {'Status':<10} {'Name'}")
    print("-" * 70)
    for r in records:
        name = r.hypothesis.get("name", "—")[:40]
        print(
            f"{r.id:<8} {r.score:>5}  "
            f"{r.gates_passed}/{r.gates_total:<3}  "
            f"{r.status:<10} {name}"
        )
    return 0


def _cli_detail(store_dir: Path, candidate_id: str) -> int:
    mgr = CandidateManager(store_dir)
    record = mgr.load_one(candidate_id)
    if record is None:
        print(f"Candidate {candidate_id!r} not found.")
        return 1
    print(f"=== {record.id} ===")
    print(f"Name:        {record.hypothesis.get('name', '—')}")
    print(f"Status:      {record.status}")
    print(f"Score:       {record.score}/100")
    print(f"Gates:       {record.gates_passed}/{record.gates_total}")
    print(f"Session:     {record.session_id}")
    print(f"Created:     {record.created_at}")
    if record.sharpe_improvement is not None:
        print(f"Sharpe Δ:    {record.sharpe_improvement:+.3f}")
    if record.net_profit_delta is not None:
        print(f"Net P&L Δ:   ${record.net_profit_delta:+.0f}")
    print()
    print("ICT reasoning:")
    print(f"  {record.hypothesis.get('ict_reasoning', '—')}")
    print()
    print("Condition:")
    print(f"  {record.hypothesis.get('condition', '—')}")
    print()
    print("Gate results:")
    for name, data in (record.gate_results or {}).items():
        if isinstance(data, dict):
            mark = "✅" if data.get("passed") else "❌"
            print(f"  {mark} {name}: {data.get('reason', '—')}")
    if record.notes:
        print()
        print(f"Notes: {record.notes}")
    return 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="strategy_lab.lab_engine",
        description="AlgoICT Strategy Lab — hypothesis generator + validator",
    )
    p.add_argument("--mode", choices=("generate", "overnight"), default=None)
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--list", action="store_true", help="List all candidates")
    p.add_argument("--detail", metavar="ID", help="Show detail for one candidate")
    p.add_argument("--approve", metavar="ID", help="Approve candidate for Test Set")
    p.add_argument("--auth", default="", help="Test Set auth code (required with --approve)")
    p.add_argument("--approver", default="juan", help="Approver name")
    p.add_argument(
        "--store-dir",
        type=Path,
        default=Path("data") / "strategy_lab",
        help="Candidate store directory",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_argparser().parse_args(argv)

    if args.list:
        return _cli_list(args.store_dir)

    if args.detail:
        return _cli_detail(args.store_dir, args.detail)

    if args.approve:
        if not args.auth:
            print("--auth is required with --approve")
            return 2
        # Approval path requires a live engine with real data — not
        # constructible in a pure CLI context without user setup. We
        # only mark the status here.  Full Test Set run happens via
        # a driver script that instantiates LabEngine with real data.
        mgr = CandidateManager(args.store_dir)
        try:
            rec = mgr.mark_approved(
                args.approve,
                approver=args.approver,
                notes=f"CLI approval; auth={args.auth[:6]}…",
            )
            print(f"Approved {rec.id}. Run the driver script to evaluate on Test Set.")
            return 0
        except KeyError as e:
            print(f"Error: {e}")
            return 1

    if args.mode:
        print(
            "Direct --mode run requires a driver script that supplies "
            "a DataSplitter and BacktestRunner. See docs for "
            "`LabEngine.run_batch`. This CLI supports --list, --detail, "
            "and --approve without a driver."
        )
        return 0

    build_argparser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
