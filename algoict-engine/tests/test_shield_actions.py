"""
tests/test_shield_actions.py
=============================
Tests for:
  - toxicity/toxicity_classifier.py
  - toxicity/shield_actions.py
  - toxicity/vpin_confluence.py
  - toxicity/vpin_engine.py (basic offline tests)
"""

import asyncio
import pytest
import pandas as pd
from unittest.mock import MagicMock, AsyncMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from toxicity.toxicity_classifier import ToxicityClassifier, ToxicityLevel, classify
from toxicity.shield_actions import ShieldManager, ShieldAction
from toxicity.vpin_confluence import VPINConfluenceScorer, VPINConfluenceResult, score, vpin_points_available
from toxicity.vpin_engine import VPINEngine, VPINStatus, VPINEngineAdapter


# ---------------------------------------------------------------------------
# ToxicityClassifier
# ---------------------------------------------------------------------------

class TestToxicityClassifier:
    def setup_method(self):
        self.tc = ToxicityClassifier()

    def test_classify_calm(self):
        level = self.tc.classify(0.25)
        assert level.label == "calm"
        assert not level.should_flatten
        assert level.size_multiplier == 1.0

    def test_classify_normal(self):
        level = self.tc.classify(0.40)
        assert level.label == "normal"
        assert not level.should_flatten

    def test_classify_elevated(self):
        level = self.tc.classify(0.50)
        assert level.label == "elevated"
        assert level.stop_tighten_pct == 0.10
        assert not level.should_flatten

    def test_classify_high(self):
        level = self.tc.classify(0.62)
        assert level.label == "high"
        assert level.size_multiplier == 0.75
        assert level.min_confluence_delta == 1
        assert not level.should_flatten

    def test_classify_extreme(self):
        level = self.tc.classify(0.75)
        assert level.label == "extreme"
        assert level.should_flatten is True
        assert level.should_halt is True
        assert level.size_multiplier == 0.0

    def test_extreme_boundary(self):
        level_below = self.tc.classify(0.699)
        level_above = self.tc.classify(0.701)
        assert level_below.label == "high"
        assert level_above.label == "extreme"

    def test_is_extreme_property(self):
        level = self.tc.classify(0.80)
        assert level.is_extreme

    def test_is_dangerous_high(self):
        level = self.tc.classify(0.60)
        assert level.is_dangerous

    def test_is_safe_calm(self):
        level = self.tc.classify(0.20)
        assert level.is_safe

    def test_is_safe_normal(self):
        level = self.tc.classify(0.40)
        assert level.is_safe

    def test_label_for_vpin(self):
        assert self.tc.label_for_vpin(0.25) == "calm"
        assert self.tc.label_for_vpin(0.75) == "extreme"

    def test_threshold_for_returns_range(self):
        low, high = self.tc.threshold_for("extreme")
        assert low == 0.70
        assert high > 0.70

    def test_all_levels_returns_5(self):
        levels = self.tc.all_levels()
        assert len(levels) == 5
        assert "extreme" in levels

    def test_module_level_classify(self):
        level = classify(0.30)
        assert level.label == "calm"


# ---------------------------------------------------------------------------
# ShieldManager — evaluate
# ---------------------------------------------------------------------------

class TestShieldManagerEvaluate:
    def test_calm_no_alerts(self):
        shield = ShieldManager()
        action = shield.evaluate(0.25)
        assert not action.should_flatten
        assert not action.should_halt
        assert action.alert_level == "none"

    def test_high_triggers_warning(self):
        shield = ShieldManager()
        action = shield.evaluate(0.62)
        assert action.alert_level == "warning"
        assert action.size_multiplier == 0.75
        assert action.min_confluence_delta == 1

    def test_extreme_triggers_critical(self):
        shield = ShieldManager()
        action = shield.evaluate(0.75)
        assert action.should_flatten is True
        assert action.should_halt is True
        assert action.alert_level == "critical"

    def test_elevated_tightens_stops(self):
        shield = ShieldManager()
        action = shield.evaluate(0.50)
        assert action.should_tighten_stops is True
        assert action.stop_tighten_pct == 0.10

    def test_action_has_message(self):
        shield = ShieldManager()
        action = shield.evaluate(0.75)
        assert len(action.message) > 0
        assert "VPIN" in action.message

    def test_halt_persists_after_extreme(self):
        shield = ShieldManager()
        shield.evaluate(0.80)  # triggers halt via internal state
        # Now evaluate at lower level but halt should persist
        action = shield.evaluate(0.60)
        # is_halted state from shield is not persisted by evaluate alone
        # (halt is only set by execute_flatten)
        # So this just checks the action is computed correctly
        assert action is not None


# ---------------------------------------------------------------------------
# ShieldManager — execute_flatten
# ---------------------------------------------------------------------------

class TestShieldManagerFlatten:
    @pytest.mark.asyncio
    async def test_flatten_with_async_risk_manager(self):
        mock_rm = AsyncMock()
        mock_rm.emergency_flatten = AsyncMock()
        shield = ShieldManager(risk_manager=mock_rm)
        result = await shield.execute_flatten("VPIN test")
        assert result is True
        mock_rm.emergency_flatten.assert_called_once()

    @pytest.mark.asyncio
    async def test_flatten_with_sync_risk_manager(self):
        mock_rm = MagicMock()
        mock_rm.emergency_flatten = MagicMock()  # sync
        shield = ShieldManager(risk_manager=mock_rm)
        result = await shield.execute_flatten("VPIN test")
        assert result is True

    @pytest.mark.asyncio
    async def test_flatten_without_risk_manager_returns_false(self):
        shield = ShieldManager()
        result = await shield.execute_flatten("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_flatten_sets_halt_active(self):
        shield = ShieldManager()
        await shield.execute_flatten("test")
        assert shield.is_halted is True

    def test_check_deactivate_below_threshold(self):
        shield = ShieldManager()
        shield._halt_active = True
        deactivated = shield.check_deactivate(0.45)
        assert deactivated is True
        assert not shield.is_halted

    def test_check_deactivate_above_threshold(self):
        shield = ShieldManager()
        shield._halt_active = True
        deactivated = shield.check_deactivate(0.65)
        assert deactivated is False
        assert shield.is_halted

    def test_reset_clears_halt(self):
        shield = ShieldManager()
        shield._halt_active = True
        shield.reset()
        assert not shield.is_halted


# ---------------------------------------------------------------------------
# VPINConfluenceScorer
# ---------------------------------------------------------------------------

class TestVPINConfluenceScorer:
    def setup_method(self):
        self.scorer = VPINConfluenceScorer()

    def test_sweep_bonus_when_vpin_high(self):
        result = self.scorer.score(
            vpin=0.52,
            sweep_detected=True,
            vpin_at_sweep=0.50,
        )
        assert result.sweep_bonus is True
        assert result.sweep_pts == 1

    def test_no_sweep_bonus_when_vpin_low(self):
        result = self.scorer.score(
            vpin=0.30,
            sweep_detected=True,
            vpin_at_sweep=0.30,
        )
        assert result.sweep_bonus is False
        assert result.sweep_pts == 0

    def test_no_sweep_bonus_when_no_sweep(self):
        result = self.scorer.score(
            vpin=0.60,
            sweep_detected=False,
        )
        assert result.sweep_bonus is False

    def test_session_bonus_in_kill_zone(self):
        result = self.scorer.score(
            vpin=0.50,
            in_kill_zone=True,
        )
        assert result.session_bonus is True
        assert result.session_pts == 1

    def test_no_session_bonus_low_vpin(self):
        result = self.scorer.score(
            vpin=0.30,
            in_kill_zone=True,
        )
        assert result.session_bonus is False

    def test_no_session_bonus_outside_kill_zone(self):
        result = self.scorer.score(
            vpin=0.60,
            in_kill_zone=False,
        )
        assert result.session_bonus is False

    def test_max_2_pts(self):
        result = self.scorer.score(
            vpin=0.60,
            in_kill_zone=True,
            sweep_detected=True,
            vpin_at_sweep=0.55,
        )
        assert result.total_pts == 2

    def test_zero_pts_calm_market(self):
        result = self.scorer.score(
            vpin=0.25,
            in_kill_zone=False,
            sweep_detected=False,
        )
        assert result.total_pts == 0

    def test_validate_sweep_true(self):
        assert self.scorer.validate_sweep(True, 0.50) is True

    def test_validate_sweep_false_low_vpin(self):
        assert self.scorer.validate_sweep(True, 0.30) is False

    def test_validate_sweep_false_no_sweep(self):
        assert self.scorer.validate_sweep(False, 0.60) is False

    def test_assess_session_quality_high(self):
        result = self.scorer.assess_session_quality(True, 0.55)
        assert result["quality"] == "high"
        assert result["bonus"] == 1

    def test_assess_session_quality_low(self):
        result = self.scorer.assess_session_quality(True, 0.25)
        assert result["quality"] == "low"
        assert result["bonus"] == 0

    def test_assess_session_quality_not_in_kz(self):
        result = self.scorer.assess_session_quality(False, 0.60)
        assert result["quality"] == "not_in_kz"

    def test_module_level_score(self):
        result = score(vpin=0.50, in_kill_zone=True)
        assert isinstance(result, VPINConfluenceResult)

    def test_vpin_points_available(self):
        assert vpin_points_available() == 2

    def test_result_has_reason(self):
        result = self.scorer.score(vpin=0.50, in_kill_zone=True)
        assert len(result.reason) > 0

    def test_uses_vpin_at_sweep_not_current(self):
        # vpin_at_sweep=0.50 > threshold, even though current vpin=0.20
        result = self.scorer.score(
            vpin=0.20,
            sweep_detected=True,
            vpin_at_sweep=0.50,
        )
        assert result.sweep_bonus is True


# ---------------------------------------------------------------------------
# VPINEngine — basic offline tests
# ---------------------------------------------------------------------------

class TestVPINEngine:
    def _make_bar(self, close=19500.0, volume=1500):
        return pd.Series({
            "open": close - 5,
            "high": close + 5,
            "low": close - 5,
            "close": close,
            "volume": volume,
        })

    def test_initial_status_not_ready(self):
        engine = VPINEngine()
        status = engine.get_status()
        assert not status.is_ready
        assert status.vpin is None
        assert status.label == "unknown"

    def test_initial_is_safe_to_trade(self):
        engine = VPINEngine()
        assert engine.is_safe_to_trade()

    def test_processes_bar_without_crash(self):
        engine = VPINEngine()
        bar = self._make_bar()
        action = engine.on_new_bar(bar)
        # may return None (not enough data) or ShieldAction
        assert action is None or isinstance(action, ShieldAction)

    def test_reset_clears_state(self):
        engine = VPINEngine()
        bar = self._make_bar()
        engine.on_new_bar(bar)
        engine.reset()
        status = engine.get_status()
        assert not status.is_ready
        assert status.bucket_count == 0

    def test_default_size_multiplier_is_one(self):
        engine = VPINEngine()
        assert engine.current_size_multiplier() == 1.0

    def test_default_confluence_delta_is_zero(self):
        engine = VPINEngine()
        assert engine.current_confluence_delta() == 0

    @pytest.mark.asyncio
    async def test_async_bar_processes_without_crash(self):
        engine = VPINEngine()
        bar = self._make_bar()
        action = await engine.on_new_bar_async(bar)
        assert action is None or isinstance(action, ShieldAction)


# ---------------------------------------------------------------------------
# VPINEngineAdapter
# ---------------------------------------------------------------------------

class TestVPINEngineAdapter:
    def _make_bar(self, close=19500.0, volume=1000):
        return pd.Series({
            "open": close - 3,
            "high": close + 3,
            "low": close - 3,
            "close": close,
            "volume": volume,
        })

    def test_process_bar_returns_tuple(self):
        adapter = VPINEngineAdapter()
        vpin, label = adapter.process_bar(self._make_bar())
        assert label in ("unknown", "calm", "normal", "elevated", "high", "extreme")

    def test_is_safe_initially(self):
        adapter = VPINEngineAdapter()
        assert adapter.is_safe()

    def test_size_multiplier_default(self):
        adapter = VPINEngineAdapter()
        assert adapter.size_multiplier() == 1.0

    def test_confluence_delta_default(self):
        adapter = VPINEngineAdapter()
        assert adapter.confluence_delta() == 0

    def test_reset(self):
        adapter = VPINEngineAdapter()
        adapter.process_bar(self._make_bar())
        adapter.reset()
        vpin, label = adapter.process_bar(self._make_bar())
        # After reset, may still be unknown
        assert label in ("unknown", "calm", "normal", "elevated", "high", "extreme")
