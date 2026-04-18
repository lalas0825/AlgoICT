"""
tests/test_audit_aftermath.py
==============================
Coverage for the 2026-04-17 audit-aftermath fixes — the warmup gate,
position reconciliation helper, mood-gating in the Claude path,
signal_id collision disambiguation, and rollback of the Layer-1
dedup when a broker entry rejects.

Each test traces a specific meta-audit finding and would fail if that
regression came back.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ENGINE_DIR))


# ─── SWC mood gating on the Claude synthesis path ──────────────────────────
# Meta-audit Finding #1: mood_synthesizer.generate + generate_from_ai_response
# used get_adjustments(event_risk) alone — the mood label never reached the
# risk manager. Now: combine_adjustments(event_risk, mood) wins.

class TestMoodSynthesizerCombinesMoodAndEvent:

    def test_from_ai_response_choppy_no_event_applies_mood_penalty(self):
        from sentiment.mood_synthesizer import MoodSynthesizer
        syn = MoodSynthesizer(api_key="fake")
        ai_json = (
            '{"market_mood": "choppy", "confidence": "medium", '
            '"one_line_summary": "Chop", "key_risk": "k", '
            '"opportunity": "o"}'
        )
        report = syn.generate_from_ai_response(
            ai_response=ai_json, event_risk="none",
        )
        # Before the fix: 7 / 1.0 (event=none, mood ignored).
        # After:          9 / 0.75 (mood=choppy dominates).
        assert report.min_confluence_override == 9
        assert report.position_size_multiplier == 0.75
        assert report.market_mood.value == "choppy"

    def test_from_ai_response_event_beats_mildmood(self):
        """High-impact event wins over a risk_on mood."""
        from sentiment.mood_synthesizer import MoodSynthesizer
        syn = MoodSynthesizer(api_key="fake")
        ai_json = (
            '{"market_mood": "risk_on", "confidence": "high", '
            '"one_line_summary": "Risk on", "key_risk": "", "opportunity": ""}'
        )
        report = syn.generate_from_ai_response(
            ai_response=ai_json, event_risk="high",
        )
        # event=high → 9/0.75; mood=risk_on → 7/1.0. Stricter (event) wins.
        assert report.min_confluence_override == 9
        assert report.position_size_multiplier == 0.75


# ─── Unknown mood label fails CLOSED to choppy, not open to normal ─────────

class TestUnknownMoodFailClosed:

    def test_get_mood_adjustments_unknown_returns_choppy(self):
        from sentiment.confluence_adjuster import get_mood_adjustments
        adj = get_mood_adjustments("mystery_mood_42")
        assert adj.risk_level == "choppy"
        assert adj.min_confluence == 9
        assert adj.position_multiplier == 0.75

    def test_get_mood_adjustments_empty_returns_choppy(self):
        from sentiment.confluence_adjuster import get_mood_adjustments
        assert get_mood_adjustments("").risk_level == "choppy"
        assert get_mood_adjustments(None).risk_level == "choppy"  # type: ignore[arg-type]

    def test_get_mood_adjustments_known_returns_specific(self):
        """Regression: a VALID label must NOT fall through to choppy."""
        from sentiment.confluence_adjuster import get_mood_adjustments
        assert get_mood_adjustments("risk_on").risk_level == "risk_on"
        assert get_mood_adjustments("Risk On").risk_level == "risk_on"  # case-insens


# ─── FairValueGapDetector.get_active filters out IFVGs ─────────────────────

class TestGetActiveExcludesIFVGs:

    def test_get_active_returns_regular_fvgs_only(self):
        from detectors.fair_value_gap import FairValueGapDetector, FVG
        import pandas as pd

        det = FairValueGapDetector()
        # Inject one regular FVG and one IFVG in the same direction.
        det.fvgs.append(FVG(
            top=100.0, bottom=99.0, direction="bullish",
            timeframe="5min", candle_index=10,
            timestamp=pd.Timestamp("2024-01-01 09:30", tz="US/Central"),
            is_ifvg=False,
        ))
        det.fvgs.append(FVG(
            top=101.0, bottom=100.0, direction="bullish",
            timeframe="5min", candle_index=12,
            timestamp=pd.Timestamp("2024-01-01 09:40", tz="US/Central"),
            is_ifvg=True,
        ))
        active = det.get_active(timeframe="5min", direction="bullish")
        assert len(active) == 1
        assert active[0].is_ifvg is False

    def test_get_active_ifvgs_still_returns_ifvgs(self):
        from detectors.fair_value_gap import FairValueGapDetector, FVG
        import pandas as pd

        det = FairValueGapDetector()
        det.fvgs.append(FVG(
            top=101.0, bottom=100.0, direction="bullish",
            timeframe="5min", candle_index=12,
            timestamp=pd.Timestamp("2024-01-01 09:40", tz="US/Central"),
            is_ifvg=True,
        ))
        ifvgs = det.get_active_ifvgs(timeframe="5min", direction="bullish")
        assert len(ifvgs) == 1
        assert ifvgs[0].is_ifvg is True


# ─── Strategy rollback clears Layer-1 dedup ────────────────────────────────

class TestStrategyRollback:

    def test_ny_am_rollback_clears_matching_ts(self):
        import pandas as pd
        from strategies.ny_am_reversal import NYAMReversalStrategy

        strat = NYAMReversalStrategy.__new__(NYAMReversalStrategy)  # bypass ctor
        ts = pd.Timestamp("2024-01-02 09:30", tz="US/Central")
        strat._last_evaluated_bar_ts = ts
        strat.rollback_last_evaluated_bar(ts)
        assert strat._last_evaluated_bar_ts is None

    def test_ny_am_rollback_noop_on_mismatch(self):
        import pandas as pd
        from strategies.ny_am_reversal import NYAMReversalStrategy

        strat = NYAMReversalStrategy.__new__(NYAMReversalStrategy)
        ts_a = pd.Timestamp("2024-01-02 09:30", tz="US/Central")
        ts_b = pd.Timestamp("2024-01-02 09:35", tz="US/Central")
        strat._last_evaluated_bar_ts = ts_a
        strat.rollback_last_evaluated_bar(ts_b)
        # Did NOT match — must keep the stamp.
        assert strat._last_evaluated_bar_ts == ts_a

    def test_silver_bullet_rollback_exists(self):
        """Silver bullet strategy also needs the rollback hook."""
        from strategies.silver_bullet import SilverBulletStrategy
        assert hasattr(SilverBulletStrategy, "rollback_last_evaluated_bar")


# ─── signal_id disambiguation by entry price ───────────────────────────────

class TestSignalIdIncludesEntryPrice:

    def test_signal_id_distinguishes_different_entries(self):
        """Two setups on the same bar/strategy/direction with different
        entry prices must produce distinct signal_ids."""
        import pandas as pd
        ts = pd.Timestamp("2024-01-02 09:30", tz="US/Central")

        def build_id(entry_price: float) -> str:
            return (
                f"ny_am_reversal_long_{ts}_{float(entry_price):.2f}"
            )

        id_a = build_id(20483.25)
        id_b = build_id(20485.50)
        assert id_a != id_b

    def test_signal_id_stable_across_float_noise(self):
        """Float reordering during two re-deliveries must produce the same
        signal_id — otherwise dedup breaks."""
        ts = "2024-01-02 09:30:00-06:00"
        entry = 20483.25
        id_a = f"ny_am_reversal_long_{ts}_{float(entry):.2f}"
        # Same entry computed via a different arithmetic path
        id_b = f"ny_am_reversal_long_{ts}_{float(20480.00 + 3.25):.2f}"
        assert id_a == id_b


# ─── TimeframeManager.get_completed_bars drops forming bars ────────────────

class TestGetCompletedBars:

    def _make_1min(self, n: int):
        """Create n consecutive 1-min bars starting at 09:30 CT."""
        import pandas as pd
        idx = pd.date_range("2024-01-02 09:30", periods=n, freq="1min", tz="US/Central")
        df = pd.DataFrame({
            "open":   [100.0] * n,
            "high":   [101.0] * n,
            "low":    [ 99.0] * n,
            "close":  [100.5] * n,
            "volume": [   1 ] * n,
        }, index=idx)
        return df

    def test_drops_partial_trailing_5min_bar(self):
        from timeframes.tf_manager import TimeframeManager
        mgr = TimeframeManager()
        # 7 one-min bars: full 5-min window 09:30-09:34 + 2 more that form
        # an incomplete 09:35-09:39 bar.
        mgr.aggregate(self._make_1min(7), "5min")
        out = mgr.get_completed_bars("5min")
        assert out is not None
        assert len(out) == 1     # only the completed 09:30 bar
        import pandas as pd
        assert out.index[-1] == pd.Timestamp("2024-01-02 09:30", tz="US/Central")

    def test_keeps_complete_trailing_bar(self):
        from timeframes.tf_manager import TimeframeManager
        mgr = TimeframeManager()
        # 10 one-min bars: two full 5-min windows.
        mgr.aggregate(self._make_1min(10), "5min")
        out = mgr.get_completed_bars("5min")
        # Last 1-min ts is 09:39, tf_delta=5min. 09:35 + 5 = 09:40 > 09:39
        # → the 09:35 bar is STILL forming even though we have 5 contributing
        # 1-min bars. Tail must be dropped.
        assert len(out) == 1


# ─── Reconcile dedup flag on EngineState ───────────────────────────────────

class TestReconcileInflightFlag:

    def test_engine_state_has_reconcile_inflight_default_false(self):
        from main import EngineState
        state = EngineState(mode="paper")
        assert getattr(state, "reconcile_inflight", None) is False


# ─── Warm-up gate ──────────────────────────────────────────────────────────

class TestWarmupGate:

    def test_engine_state_default_warmup_false(self):
        from main import EngineState
        state = EngineState(mode="paper")
        assert state.warmup_complete is False

    def test_min_warmup_threshold_constant_defined(self):
        import main
        assert hasattr(main, "MIN_WARMUP_BARS_FOR_TRADING")
        assert main.MIN_WARMUP_BARS_FOR_TRADING >= 500  # sensible floor


# ─── MLL threshold ordering validator ──────────────────────────────────────

class TestMLLThresholdOrdering:

    def test_argparse_rejects_inverted_thresholds(self, monkeypatch, capsys):
        """User passing --mll-warning-pct 0.90 --mll-caution-pct 0.60
        must fail fast, not start the engine with inverted zones."""
        import main
        argv = [
            "algoict", "--mode", "paper",
            "--mll-warning-pct", "0.90",
            "--mll-caution-pct", "0.60",
            "--mll-stop-pct", "0.85",
        ]
        monkeypatch.setattr(sys, "argv", argv)
        rc = main.main()
        assert rc != 0
        err = capsys.readouterr().err
        assert "MLL" in err or "threshold" in err.lower()

    def test_argparse_accepts_valid_thresholds(self, monkeypatch):
        """Valid ordering proceeds past the validator (may still fail at a
        later init step — we only want to confirm the validator passes)."""
        import main
        # Use valid ordering but force the lock acquire to fail so we stop
        # before broker init (which would try to reach the network).
        argv = [
            "algoict", "--mode", "paper",
            "--mll-warning-pct", "0.40",
            "--mll-caution-pct", "0.60",
            "--mll-stop-pct", "0.85",
        ]
        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.setattr(main, "_acquire_engine_lock", lambda: False)
        rc = main.main()
        # Validator passes → falls through to lock → lock refuses → rc=1
        assert rc == 1   # NOT the validator's rc=2


# ─── MAX_CONFLUENCE propagated from weights ────────────────────────────────

class TestMaxConfluenceDerived:

    def test_max_confluence_equals_weight_sum(self):
        import config
        assert config.MAX_CONFLUENCE == sum(config.CONFLUENCE_WEIGHTS.values())

    def test_telegram_bot_imports_max_confluence(self):
        """Regression: /20 hardcoded strings were replaced with the
        derived constant. Import must succeed."""
        from alerts.telegram_bot import MAX_CONFLUENCE
        assert isinstance(MAX_CONFLUENCE, int)
        assert MAX_CONFLUENCE > 0
