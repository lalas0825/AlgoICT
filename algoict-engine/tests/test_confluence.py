"""
tests/test_confluence.py
=========================
Unit tests for detectors/confluence.py

Strategy: build mock detector outputs (FVG, OB, LiquidityLevel, etc.) with
known values, feed them to ConfluenceScorer.score(), and assert the exact
points awarded per factor and the resulting tier.

Run: cd algoict-engine && python -m pytest tests/test_confluence.py -v
"""

import pandas as pd
import pytest

from detectors.confluence import ConfluenceScorer
from detectors.fair_value_gap import FVG
from detectors.order_block import OrderBlock
from detectors.market_structure import StructureEvent
from detectors.liquidity import LiquidityLevel
from timeframes.htf_bias import BiasResult


# ─── Mock factories ──────────────────────────────────────────────────────────

def _ts(hour: int = 9, minute: int = 0) -> pd.Timestamp:
    return pd.Timestamp(f"2025-03-03 {hour:02d}:{minute:02d}", tz="US/Central")


def _mk_bullish_fvg(bottom=99.0, top=101.0) -> FVG:
    return FVG(
        top=top, bottom=bottom, direction="bullish",
        timeframe="5min", candle_index=10, timestamp=_ts(),
    )


def _mk_bearish_fvg(bottom=99.0, top=101.0) -> FVG:
    return FVG(
        top=top, bottom=bottom, direction="bearish",
        timeframe="5min", candle_index=10, timestamp=_ts(),
    )


def _mk_bullish_ob(low=99.0, high=101.0) -> OrderBlock:
    return OrderBlock(
        high=high, low=low, direction="bullish",
        timeframe="5min", candle_index=10, timestamp=_ts(),
    )


def _mk_bearish_ob(low=99.0, high=101.0) -> OrderBlock:
    return OrderBlock(
        high=high, low=low, direction="bearish",
        timeframe="5min", candle_index=10, timestamp=_ts(),
    )


def _mk_swept_ssl(price=99.0) -> LiquidityLevel:
    return LiquidityLevel(price=price, type="SSL", swept=True, timestamp=_ts())


def _mk_swept_bsl(price=101.0) -> LiquidityLevel:
    return LiquidityLevel(price=price, type="BSL", swept=True, timestamp=_ts())


def _mk_pdh(price=110.0) -> LiquidityLevel:
    return LiquidityLevel(price=price, type="PDH", timestamp=_ts())


def _mk_pdl(price=90.0) -> LiquidityLevel:
    return LiquidityLevel(price=price, type="PDL", timestamp=_ts())


def _mk_mss(direction="bullish") -> StructureEvent:
    return StructureEvent(
        type="MSS", direction=direction, level=100.0,
        timestamp=_ts(), timeframe="5min",
    )


def _mk_bias(direction="bullish") -> BiasResult:
    return BiasResult(
        direction=direction, premium_discount="discount",
        htf_levels={}, confidence="high",
        weekly_bias=direction, daily_bias=direction,
    )


# ─── Tests: Individual factors ────────────────────────────────────────────────

class TestIndividualFactors:

    def test_no_factors_zero_score(self):
        scorer = ConfluenceScorer()
        result = scorer.score(direction="long", entry_price=100.0)
        assert result.total_score == 0
        assert result.tier == "no_trade"
        assert result.trade_allowed is False

    def test_liquidity_grab_long(self):
        """Long trade — sweep of SSL counts."""
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            sweep=_mk_swept_ssl(99.0),
        )
        assert result.breakdown.get("liquidity_grab") == 2
        assert result.total_score == 2

    def test_liquidity_grab_wrong_side_no_score(self):
        """Long trade — sweep of BSL is wrong side, no score."""
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            sweep=_mk_swept_bsl(101.0),
        )
        assert "liquidity_grab" not in result.breakdown

    def test_liquidity_grab_unswept_no_score(self):
        """Sweep flag must be True."""
        scorer = ConfluenceScorer()
        ssl = LiquidityLevel(price=99.0, type="SSL", swept=False, timestamp=_ts())
        result = scorer.score(direction="long", entry_price=100.0, sweep=ssl)
        assert "liquidity_grab" not in result.breakdown

    def test_fvg_aligned(self):
        """Long trade — entry inside bullish FVG."""
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            fvgs=[_mk_bullish_fvg(99.0, 101.0)],
        )
        assert result.breakdown.get("fair_value_gap") == 2

    def test_fvg_outside_no_score(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=105.0,
            fvgs=[_mk_bullish_fvg(99.0, 101.0)],
        )
        assert "fair_value_gap" not in result.breakdown

    def test_fvg_wrong_direction_no_score(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            fvgs=[_mk_bearish_fvg(99.0, 101.0)],
        )
        assert "fair_value_gap" not in result.breakdown

    def test_fvg_mitigated_no_score(self):
        scorer = ConfluenceScorer()
        fvg = _mk_bullish_fvg(99.0, 101.0)
        fvg.mitigated = True
        result = scorer.score(direction="long", entry_price=100.0, fvgs=[fvg])
        assert "fair_value_gap" not in result.breakdown

    def test_order_block_aligned(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            obs=[_mk_bullish_ob(99.0, 101.0)],
        )
        assert result.breakdown.get("order_block") == 2

    def test_order_block_wrong_direction(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            obs=[_mk_bearish_ob(99.0, 101.0)],
        )
        assert "order_block" not in result.breakdown

    def test_mss_aligned(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            structure_event=_mk_mss("bullish"),
        )
        assert result.breakdown.get("market_structure_shift") == 2

    def test_mss_wrong_direction(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            structure_event=_mk_mss("bearish"),
        )
        assert "market_structure_shift" not in result.breakdown

    def test_choch_also_counts(self):
        scorer = ConfluenceScorer()
        ev = StructureEvent(type="CHoCH", direction="bullish", level=100.0,
                            timestamp=_ts(), timeframe="5min")
        result = scorer.score(direction="long", entry_price=100.0, structure_event=ev)
        assert result.breakdown.get("market_structure_shift") == 2

    def test_bos_does_not_count(self):
        """BOS is continuation, not a shift — should not score."""
        scorer = ConfluenceScorer()
        ev = StructureEvent(type="BOS", direction="bullish", level=100.0,
                            timestamp=_ts(), timeframe="5min")
        result = scorer.score(direction="long", entry_price=100.0, structure_event=ev)
        assert "market_structure_shift" not in result.breakdown

    def test_kill_zone(self):
        scorer = ConfluenceScorer()
        result = scorer.score(direction="long", entry_price=100.0, kill_zone=True)
        assert result.breakdown.get("kill_zone") == 1

    def test_htf_bias_aligned(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            htf_bias=_mk_bias("bullish"),
        )
        assert result.breakdown.get("htf_bias_aligned") == 1

    def test_htf_bias_misaligned(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            htf_bias=_mk_bias("bearish"),
        )
        assert "htf_bias_aligned" not in result.breakdown

    def test_htf_fvg_alignment(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            htf_fvgs=[_mk_bullish_fvg(99.0, 101.0)],
        )
        assert result.breakdown.get("htf_ob_fvg_alignment") == 1

    def test_htf_ob_alignment(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            htf_obs=[_mk_bullish_ob(99.0, 101.0)],
        )
        assert result.breakdown.get("htf_ob_fvg_alignment") == 1

    def test_target_at_pdh(self):
        """Target within 0.1% of PDH counts."""
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            target_price=110.05,   # within 0.1% of 110.0
            key_levels=[_mk_pdh(110.0)],
        )
        assert result.breakdown.get("target_at_pdh_pdl") == 1

    def test_target_far_from_pdh_no_score(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            target_price=115.0,
            key_levels=[_mk_pdh(110.0)],
        )
        assert "target_at_pdh_pdl" not in result.breakdown

    def test_target_at_pdl_for_short(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="short",
            entry_price=100.0,
            target_price=90.0,
            key_levels=[_mk_pdl(90.0)],
        )
        assert result.breakdown.get("target_at_pdh_pdl") == 1


# ─── Tests: OTE Fibonacci ────────────────────────────────────────────────────

class TestOTE:

    def test_long_in_ote_zone(self):
        """
        Range = 100, swing_low=0, swing_high=100.
        Long OTE = [21.4, 38.2]. entry=30 → in zone.
        """
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=30.0,
            swing_low=0.0,
            swing_high=100.0,
        )
        assert result.breakdown.get("ote_fibonacci") == 1

    def test_long_above_ote(self):
        """entry=50 is above OTE max (38.2) — no score."""
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=50.0,
            swing_low=0.0,
            swing_high=100.0,
        )
        assert "ote_fibonacci" not in result.breakdown

    def test_long_below_ote(self):
        """entry=10 is below OTE min (21.4) — no score."""
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=10.0,
            swing_low=0.0,
            swing_high=100.0,
        )
        assert "ote_fibonacci" not in result.breakdown

    def test_short_in_ote_zone(self):
        """Short OTE = [61.8, 78.6]. entry=70 → in zone."""
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="short",
            entry_price=70.0,
            swing_low=0.0,
            swing_high=100.0,
        )
        assert result.breakdown.get("ote_fibonacci") == 1

    def test_short_outside_ote(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="short",
            entry_price=50.0,
            swing_low=0.0,
            swing_high=100.0,
        )
        assert "ote_fibonacci" not in result.breakdown

    def test_no_swings_no_ote(self):
        scorer = ConfluenceScorer()
        result = scorer.score(direction="long", entry_price=30.0)
        assert "ote_fibonacci" not in result.breakdown

    def test_zero_range_no_ote(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long", entry_price=100.0,
            swing_low=100.0, swing_high=100.0,
        )
        assert "ote_fibonacci" not in result.breakdown


# ─── Tests: Edge module flags ────────────────────────────────────────────────

class TestEdgeModules:

    def test_swc_sentiment(self):
        scorer = ConfluenceScorer()
        result = scorer.score(direction="long", entry_price=100.0,
                              swc_sentiment_aligned=True)
        assert result.breakdown.get("sentiment_alignment") == 1

    def test_gex_wall(self):
        scorer = ConfluenceScorer()
        result = scorer.score(direction="long", entry_price=100.0,
                              gex_wall_aligned=True)
        assert result.breakdown.get("gex_wall_alignment") == 2

    def test_gex_regime(self):
        scorer = ConfluenceScorer()
        result = scorer.score(direction="long", entry_price=100.0,
                              gex_regime_aligned=True)
        assert result.breakdown.get("gamma_regime") == 1

    def test_vpin_sweep(self):
        scorer = ConfluenceScorer()
        result = scorer.score(direction="long", entry_price=100.0,
                              vpin_validated_sweep=True)
        assert result.breakdown.get("vpin_validated_sweep") == 1

    def test_vpin_session(self):
        scorer = ConfluenceScorer()
        result = scorer.score(direction="long", entry_price=100.0,
                              vpin_quality_session=True)
        assert result.breakdown.get("vpin_quality_session") == 1


# ─── Tests: Tier classification ──────────────────────────────────────────────

class TestTiers:

    def test_a_plus_tier(self):
        """Score >= 12 → A+."""
        scorer = ConfluenceScorer()
        # liquidity (2) + fvg (2) + ob (2) + mss (2) + kill_zone (1) +
        # ote (1) + htf_bias (1) + sentiment (1) = 12
        result = scorer.score(
            direction="long",
            entry_price=30.0,
            sweep=_mk_swept_ssl(99.0),
            fvgs=[_mk_bullish_fvg(29.0, 31.0)],
            obs=[_mk_bullish_ob(29.0, 31.0)],
            structure_event=_mk_mss("bullish"),
            kill_zone=True,
            swing_low=0.0, swing_high=100.0,    # OTE: entry=30 in [21.4,38.2]
            htf_bias=_mk_bias("bullish"),
            swc_sentiment_aligned=True,
        )
        assert result.total_score == 12
        assert result.tier == "A+"
        assert result.trade_allowed is True

    def test_high_tier(self):
        """Score 9-11 → high."""
        scorer = ConfluenceScorer()
        # liquidity (2) + fvg (2) + ob (2) + mss (2) + kill_zone (1) = 9
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            sweep=_mk_swept_ssl(99.0),
            fvgs=[_mk_bullish_fvg(99.0, 101.0)],
            obs=[_mk_bullish_ob(99.0, 101.0)],
            structure_event=_mk_mss("bullish"),
            kill_zone=True,
        )
        assert result.total_score == 9
        assert result.tier == "high"
        assert result.trade_allowed is True

    def test_standard_tier(self):
        """Score 7-8 → standard."""
        scorer = ConfluenceScorer()
        # liquidity (2) + fvg (2) + ob (2) + kill_zone (1) = 7
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            sweep=_mk_swept_ssl(99.0),
            fvgs=[_mk_bullish_fvg(99.0, 101.0)],
            obs=[_mk_bullish_ob(99.0, 101.0)],
            kill_zone=True,
        )
        assert result.total_score == 7
        assert result.tier == "standard"
        assert result.trade_allowed is True

    def test_no_trade_tier(self):
        """Score < 7 → no_trade."""
        scorer = ConfluenceScorer()
        # liquidity (2) + fvg (2) = 4
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            sweep=_mk_swept_ssl(99.0),
            fvgs=[_mk_bullish_fvg(99.0, 101.0)],
        )
        assert result.total_score == 4
        assert result.tier == "no_trade"
        assert result.trade_allowed is False

    def test_max_score_all_factors(self):
        """Every factor active — sum of CONFLUENCE_WEIGHTS = 19."""
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=30.0,
            target_price=110.0,
            sweep=_mk_swept_ssl(99.0),
            fvgs=[_mk_bullish_fvg(29.0, 31.0)],
            obs=[_mk_bullish_ob(29.0, 31.0)],
            structure_event=_mk_mss("bullish"),
            kill_zone=True,
            swing_low=0.0, swing_high=100.0,
            htf_bias=_mk_bias("bullish"),
            htf_fvgs=[_mk_bullish_fvg(29.0, 31.0)],
            key_levels=[_mk_pdh(110.0)],
            swc_sentiment_aligned=True,
            gex_wall_aligned=True,
            gex_regime_aligned=True,
            vpin_validated_sweep=True,
            vpin_quality_session=True,
        )
        assert result.total_score == 19
        assert result.tier == "A+"


# ─── Tests: Validation ───────────────────────────────────────────────────────

class TestValidation:

    def test_invalid_direction_raises(self):
        scorer = ConfluenceScorer()
        with pytest.raises(ValueError):
            scorer.score(direction="up", entry_price=100.0)

    def test_short_direction_works(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="short",
            entry_price=100.0,
            sweep=_mk_swept_bsl(101.0),
            fvgs=[_mk_bearish_fvg(99.0, 101.0)],
        )
        assert result.total_score == 4

    def test_result_has_reasons(self):
        scorer = ConfluenceScorer()
        result = scorer.score(
            direction="long",
            entry_price=100.0,
            sweep=_mk_swept_ssl(99.0),
            kill_zone=True,
        )
        assert len(result.reasons) == 2
        assert any("sweep" in r for r in result.reasons)
        assert any("kill" in r for r in result.reasons)
