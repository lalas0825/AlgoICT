"""Tests for FVG quality filters (2026-05-22).

Coverage:
1. Detector-side metric computation (displacement_ratio + quadrant_position
   on `FVG` dataclass populated by `FairValueGapDetector.detect`).
2. Gate decision logic (3 filters: displacement / sweep linkage / quadrant)
   isolated as pure-function-style tests, mirroring the gate in
   strategies/silver_bullet.py lines ~1600-1694.
3. Shadow vs active mode behavior of the gate output.

The gate logic is mirrored (not imported) for the same reason as
test_htf_weak_gate.py: keep tests isolated from the full evaluate()
pipeline, which carries many side-effects and global state.
"""
import pandas as pd
import pytest

from detectors.fair_value_gap import FVG, FairValueGapDetector


# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────

def _make_df(
    highs: list,
    lows: list,
    opens: list = None,
    closes: list = None,
    tz: str = "US/Central",
    freq: str = "1min",
) -> pd.DataFrame:
    n = len(highs)
    assert n == len(lows)
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    if opens is None:
        opens = closes[:]
    assert n == len(opens) == len(closes)
    idx = pd.date_range("2025-03-03 09:00", periods=n, freq=freq, tz=tz)
    return pd.DataFrame({
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": [100] * n,
    }, index=idx)


def _evaluate_fvg_quality_gate(
    *,
    require_disp: bool = False,
    min_disp: float = 2.0,
    require_link: bool = False,
    link_bars: int = 10,
    require_quad: bool = False,
    fvg_disp_ratio: float = 1.0,
    fvg_quad_pos: float = 0.5,
    fvg_ts: pd.Timestamp = None,
    sweep_ts: pd.Timestamp = None,
    direction: str = "long",
) -> dict:
    """Mirror of the FVG quality gate decision logic (silver_bullet.py
    ~1600-1694). Returns dict with `issues` and `gate_fires` (would the
    gate produce any issues at all)."""
    if not (require_disp or require_link or require_quad):
        return {"issues": [], "gate_fires": False, "sweep_linked": True}

    quality_issues = []

    # Filter 1: displacement
    if require_disp and fvg_disp_ratio < min_disp:
        quality_issues.append(
            f"low_displacement_{fvg_disp_ratio:.2f}<{min_disp:.1f}"
        )

    # Filter 2: sweep linkage (sweep within N bars BEFORE fvg ts)
    sweep_linked = False
    try:
        if sweep_ts is not None and fvg_ts is not None:
            delta_min = (fvg_ts - sweep_ts).total_seconds() / 60.0
            if 0 <= delta_min <= link_bars:
                sweep_linked = True
    except Exception:
        sweep_linked = True
    if require_link and not sweep_linked:
        quality_issues.append("no_sweep_linkage")

    # Filter 3: quadrant placement
    if require_quad:
        if direction == "long" and fvg_quad_pos > 0.5:
            quality_issues.append(
                f"bull_fvg_in_premium_{fvg_quad_pos:.2f}"
            )
        elif direction == "short" and fvg_quad_pos < 0.5:
            quality_issues.append(
                f"bear_fvg_in_discount_{fvg_quad_pos:.2f}"
            )

    return {
        "issues": quality_issues,
        "gate_fires": bool(quality_issues),
        "sweep_linked": sweep_linked,
    }


# ───────────────────────────────────────────────────────────────────────
# Detector-side: displacement_ratio computation
# ───────────────────────────────────────────────────────────────────────

class TestFVGDisplacementRatio:
    """Verify `FVG.displacement_ratio` is set by `detect()`."""

    def test_field_exists_and_defaults_to_1(self):
        """FVG dataclass default for displacement_ratio is 1.0."""
        fvg = FVG(
            top=15.0, bottom=10.0, direction="bullish",
            timeframe="5min", candle_index=1,
            timestamp=pd.Timestamp("2025-03-03 09:01", tz="US/Central"),
        )
        assert fvg.displacement_ratio == 1.0

    def test_huge_c2_body_yields_high_displacement(self):
        """When c2 body is much larger than prior avg, ratio is high."""
        # Build 25 small-body bars, then a huge c2 candle creating bullish FVG.
        # First 22 bars: tiny bodies, no gap (price flat-ish)
        highs = [100.5] * 22
        lows = [99.5] * 22
        opens = [100.0] * 22
        closes = [100.0] * 22
        # idx 22 (c1): small bar, high=100.5
        highs.append(100.5); lows.append(99.5); opens.append(100.0); closes.append(100.0)
        # idx 23 (c2): huge body explosion (open=100 -> close=120). Body=20.
        highs.append(120.5); lows.append(99.8); opens.append(100.0); closes.append(120.0)
        # idx 24 (c3): low=110 → bullish FVG between highs[22]=100.5 and lows[24]=110
        highs.append(115.0); lows.append(110.0); opens.append(112.0); closes.append(113.0)

        df = _make_df(highs, lows, opens=opens, closes=closes)
        det = FairValueGapDetector()
        fvgs = det.detect(df, "1min")

        assert len(fvgs) == 1
        # Avg body of prior 20 bars (idx 3..22) ≈ 0.0 (all opens=closes=100),
        # divide-by-zero guard returns 1.0 — so displacement default fires.
        # Add nonzero body to prior bars to make this meaningful.
        # Re-do with prior bodies = 1.0 each
        opens2 = [99.5] * 22 + [100.0]
        closes2 = [100.5] * 22 + [100.0]
        # c2: huge body
        opens2.append(100.0); closes2.append(120.0)
        # c3
        opens2.append(112.0); closes2.append(113.0)
        df2 = _make_df(highs, lows, opens=opens2, closes=closes2)
        det2 = FairValueGapDetector()
        fvgs2 = det2.detect(df2, "1min")
        assert len(fvgs2) == 1
        fvg = fvgs2[0]
        # c2 body=20, prior avg body=1.0 → ratio=20.0
        assert fvg.displacement_ratio > 10.0

    def test_small_c2_body_yields_low_displacement(self):
        """When c2 body is similar to prior avg, ratio ≈ 1.0."""
        # All bars roughly similar bodies = 1.0
        # idx 0..23: uniform candles, body=1.0, open=99.5, close=100.5
        opens = [99.5] * 24
        closes = [100.5] * 24
        highs = [100.7] * 24
        lows = [99.3] * 24

        # idx 24 (c2): small body=1.0, body high gaps up for a bullish FVG
        # Need bullish FVG: highs[c2-1] < lows[c2+1]
        # idx 23 (c1) high=100.7. Need idx 25 (c3) low > 100.7
        # idx 24 (c2): small body, but creates an upper wick high
        opens.append(100.5); closes.append(100.6); highs.append(102.0); lows.append(100.4)
        # idx 25 (c3): low=101.0 → bullish FVG [100.7, 101.0]
        opens.append(101.5); closes.append(101.8); highs.append(102.0); lows.append(101.0)

        df = _make_df(highs, lows, opens=opens, closes=closes)
        det = FairValueGapDetector()
        fvgs = det.detect(df, "1min")
        assert len(fvgs) == 1
        fvg = fvgs[0]
        # c2 body=0.1, prior avg body=1.0 → ratio=0.1
        assert fvg.displacement_ratio < 0.5

    def test_displacement_for_short_lookback(self):
        """Edge case: c2 has <K prior bars (lookback truncated)."""
        # 3-bar sequence with bullish FVG at i=1
        highs = [10, 13, 18]
        lows = [8, 11, 15]
        opens = [9, 12, 17]
        closes = [9, 12, 17]
        df = _make_df(highs, lows, opens=opens, closes=closes)
        det = FairValueGapDetector()
        fvgs = det.detect(df, "5min")
        assert len(fvgs) == 1
        # i=1, lookback_start = max(0, 1-20) = 0, prior = [idx 0 body = 0.0]
        # avg_body = 0.0 → divide-by-zero guard returns 1.0
        assert fvgs[0].displacement_ratio == 1.0


# ───────────────────────────────────────────────────────────────────────
# Detector-side: quadrant_position computation
# ───────────────────────────────────────────────────────────────────────

class TestFVGQuadrantPosition:
    """Verify `FVG.quadrant_position` is set by `detect()`."""

    def test_field_exists_and_defaults_to_half(self):
        """FVG dataclass default for quadrant_position is 0.5."""
        fvg = FVG(
            top=15.0, bottom=10.0, direction="bullish",
            timeframe="5min", candle_index=1,
            timestamp=pd.Timestamp("2025-03-03 09:01", tz="US/Central"),
        )
        assert fvg.quadrant_position == 0.5

    def test_fvg_in_lower_quadrant_yields_low_position(self):
        """Bullish FVG near the low of the dealing range → quad_pos < 0.3."""
        # Build 60 bars of upper range, then create bullish FVG near bottom.
        # Range high ~ 200, low ~ 100.
        # First 60 bars: cycle through high
        highs = [200.0] * 60
        lows = [195.0] * 60
        opens = [197.0] * 60
        closes = [198.0] * 60
        # Now drop to near 100 and create a bullish FVG there
        # idx 60: drop bar
        highs.append(150.0); lows.append(100.0); opens.append(145.0); closes.append(105.0)
        # idx 61 (c1): low bar high=110
        highs.append(110.0); lows.append(95.0); opens.append(102.0); closes.append(108.0)
        # idx 62 (c2): doji at 108
        highs.append(112.0); lows.append(106.0); opens.append(108.0); closes.append(109.0)
        # idx 63 (c3): low=115 → bullish FVG [110, 115], mid=112.5
        highs.append(125.0); lows.append(115.0); opens.append(120.0); closes.append(123.0)

        df = _make_df(highs, lows, opens=opens, closes=closes)
        det = FairValueGapDetector()
        fvgs = det.detect(df, "1min")
        # We should detect exactly the i=62 FVG (bullish, [110, 115])
        bull = [f for f in fvgs if f.direction == "bullish" and f.bottom == 110.0]
        assert len(bull) == 1
        fvg = bull[0]
        # mid=112.5; range over prior 60 bars (idx 3..63) ≈ [95, 200], size 105
        # pos = (112.5 - 95) / 105 ≈ 0.166
        assert fvg.quadrant_position < 0.3

    def test_fvg_in_upper_quadrant_yields_high_position(self):
        """Bearish FVG near the top of the dealing range → quad_pos > 0.7."""
        # First 60 bars: lower range ~ [100, 150]
        highs = [150.0] * 60
        lows = [100.0] * 60
        opens = [125.0] * 60
        closes = [125.0] * 60
        # Now rally to ~200 and create a bearish FVG there.
        # Bearish FVG condition: lows[i-1] > highs[i+1]
        # idx 60: surge bar (lift to 200)
        highs.append(200.0); lows.append(155.0); opens.append(160.0); closes.append(195.0)
        # idx 61 (c1): pin candle low=185 → c1.low becomes "ceiling" of FVG
        highs.append(200.0); lows.append(185.0); opens.append(195.0); closes.append(190.0)
        # idx 62 (c2): doji small body in upper range
        highs.append(192.0); lows.append(180.0); opens.append(188.0); closes.append(187.0)
        # idx 63 (c3): drop bar high=170 → bearish FVG [170, 185], mid=177.5
        highs.append(170.0); lows.append(160.0); opens.append(168.0); closes.append(163.0)

        df = _make_df(highs, lows, opens=opens, closes=closes)
        det = FairValueGapDetector()
        fvgs = det.detect(df, "1min")
        # Bearish FVG at i=62: top=lows[61]=185, bottom=highs[63]=170
        bear = [f for f in fvgs if f.direction == "bearish" and f.top == 185.0]
        assert len(bear) == 1
        fvg = bear[0]
        # mid=177.5; range over prior 60 bars (idx 3..63) ≈ [100, 200], size 100
        # pos = (177.5 - 100) / 100 ≈ 0.775
        assert fvg.quadrant_position > 0.7

    def test_zero_range_returns_half(self):
        """When the dealing range is degenerate (zero size), pos defaults 0.5."""
        # All bars flat at same OHLC
        highs = [100.0] * 5
        lows = [100.0] * 5
        opens = [100.0] * 5
        closes = [100.0] * 5
        df = _make_df(highs, lows, opens=opens, closes=closes)
        det = FairValueGapDetector()
        # No FVG forms because no gap. But we want to verify the helper
        # doesn't crash; the field default is 0.5 anyway.
        fvgs = det.detect(df, "5min")
        # Either we got no FVG (no gap) or the position is 0.5
        for fvg in fvgs:
            assert fvg.quadrant_position == 0.5


# ───────────────────────────────────────────────────────────────────────
# Gate logic: Filter 1 — Displacement
# ───────────────────────────────────────────────────────────────────────

class TestDisplacementFilter:

    def test_disabled_does_not_fire(self):
        out = _evaluate_fvg_quality_gate(
            require_disp=False, fvg_disp_ratio=0.1,
        )
        assert not out["gate_fires"]

    def test_low_displacement_fires(self):
        out = _evaluate_fvg_quality_gate(
            require_disp=True, min_disp=2.0, fvg_disp_ratio=0.5,
        )
        assert out["gate_fires"]
        assert any("low_displacement" in i for i in out["issues"])

    def test_at_threshold_does_not_fire(self):
        """Exactly at threshold passes (uses strict < ratio < min)."""
        out = _evaluate_fvg_quality_gate(
            require_disp=True, min_disp=2.0, fvg_disp_ratio=2.0,
        )
        assert not out["gate_fires"]

    def test_above_threshold_does_not_fire(self):
        out = _evaluate_fvg_quality_gate(
            require_disp=True, min_disp=2.0, fvg_disp_ratio=3.5,
        )
        assert not out["gate_fires"]

    def test_custom_threshold_3(self):
        """min_disp=3.0; ratio=2.5 should fire."""
        out = _evaluate_fvg_quality_gate(
            require_disp=True, min_disp=3.0, fvg_disp_ratio=2.5,
        )
        assert out["gate_fires"]


# ───────────────────────────────────────────────────────────────────────
# Gate logic: Filter 2 — Sweep Linkage
# ───────────────────────────────────────────────────────────────────────

class TestSweepLinkageFilter:

    def setup_method(self):
        self.tz = "US/Central"
        # Fix a reference ts; sweep at base, FVG offset varies per test.
        self.base = pd.Timestamp("2025-03-03 09:00", tz=self.tz)

    def test_disabled_does_not_fire(self):
        out = _evaluate_fvg_quality_gate(
            require_link=False,
            fvg_ts=self.base + pd.Timedelta(minutes=100),
            sweep_ts=self.base,
            link_bars=10,
        )
        assert not out["gate_fires"]

    def test_sweep_within_lookback_passes(self):
        """Sweep 5 min before FVG, lookback=10 → linked, gate passes."""
        out = _evaluate_fvg_quality_gate(
            require_link=True,
            fvg_ts=self.base + pd.Timedelta(minutes=5),
            sweep_ts=self.base,
            link_bars=10,
        )
        assert not out["gate_fires"]
        assert out["sweep_linked"]

    def test_sweep_outside_lookback_fires(self):
        """Sweep 30 min before FVG, lookback=10 → not linked, gate fires."""
        out = _evaluate_fvg_quality_gate(
            require_link=True,
            fvg_ts=self.base + pd.Timedelta(minutes=30),
            sweep_ts=self.base,
            link_bars=10,
        )
        assert out["gate_fires"]
        assert "no_sweep_linkage" in out["issues"]

    def test_sweep_after_fvg_fires(self):
        """Sweep AFTER FVG (negative delta) → not linked, gate fires."""
        out = _evaluate_fvg_quality_gate(
            require_link=True,
            fvg_ts=self.base,
            sweep_ts=self.base + pd.Timedelta(minutes=5),
            link_bars=10,
        )
        assert out["gate_fires"]
        assert "no_sweep_linkage" in out["issues"]

    def test_no_sweep_at_all_fires(self):
        """No sweep_ts present → unlinked, gate fires."""
        out = _evaluate_fvg_quality_gate(
            require_link=True,
            fvg_ts=self.base,
            sweep_ts=None,
            link_bars=10,
        )
        assert out["gate_fires"]
        assert "no_sweep_linkage" in out["issues"]

    def test_zero_delta_passes(self):
        """Sweep exactly at FVG ts (delta=0) → linked, passes."""
        out = _evaluate_fvg_quality_gate(
            require_link=True,
            fvg_ts=self.base,
            sweep_ts=self.base,
            link_bars=10,
        )
        assert not out["gate_fires"]


# ───────────────────────────────────────────────────────────────────────
# Gate logic: Filter 3 — Quadrant Placement
# ───────────────────────────────────────────────────────────────────────

class TestQuadrantFilter:

    def test_disabled_does_not_fire(self):
        out = _evaluate_fvg_quality_gate(
            require_quad=False, fvg_quad_pos=0.9, direction="long",
        )
        assert not out["gate_fires"]

    def test_bull_fvg_in_discount_passes(self):
        """LONG signal with bull FVG in lower half (pos < 0.5) → pass."""
        out = _evaluate_fvg_quality_gate(
            require_quad=True, fvg_quad_pos=0.2, direction="long",
        )
        assert not out["gate_fires"]

    def test_bull_fvg_in_premium_fires(self):
        """LONG signal with bull FVG in upper half (pos > 0.5) → fire."""
        out = _evaluate_fvg_quality_gate(
            require_quad=True, fvg_quad_pos=0.8, direction="long",
        )
        assert out["gate_fires"]
        assert any("bull_fvg_in_premium" in i for i in out["issues"])

    def test_bear_fvg_in_premium_passes(self):
        """SHORT signal with bear FVG in upper half (pos > 0.5) → pass."""
        out = _evaluate_fvg_quality_gate(
            require_quad=True, fvg_quad_pos=0.8, direction="short",
        )
        assert not out["gate_fires"]

    def test_bear_fvg_in_discount_fires(self):
        """SHORT signal with bear FVG in lower half (pos < 0.5) → fire."""
        out = _evaluate_fvg_quality_gate(
            require_quad=True, fvg_quad_pos=0.2, direction="short",
        )
        assert out["gate_fires"]
        assert any("bear_fvg_in_discount" in i for i in out["issues"])

    def test_at_midpoint_does_not_fire_long(self):
        """LONG signal with FVG at midpoint (pos = 0.5) → neither extreme."""
        out = _evaluate_fvg_quality_gate(
            require_quad=True, fvg_quad_pos=0.5, direction="long",
        )
        assert not out["gate_fires"]

    def test_at_midpoint_does_not_fire_short(self):
        out = _evaluate_fvg_quality_gate(
            require_quad=True, fvg_quad_pos=0.5, direction="short",
        )
        assert not out["gate_fires"]


# ───────────────────────────────────────────────────────────────────────
# Gate logic: combined filters
# ───────────────────────────────────────────────────────────────────────

class TestCombinedFilters:

    def test_all_disabled_skips_gate_entirely(self):
        out = _evaluate_fvg_quality_gate(
            require_disp=False, require_link=False, require_quad=False,
            fvg_disp_ratio=0.1, fvg_quad_pos=0.9, direction="long",
        )
        assert not out["gate_fires"]
        assert out["issues"] == []

    def test_all_three_fire_simultaneously(self):
        """Worst-case setup: low disp + no sweep link + bull in premium."""
        base = pd.Timestamp("2025-03-03 09:00", tz="US/Central")
        out = _evaluate_fvg_quality_gate(
            require_disp=True, min_disp=2.0,
            require_link=True, link_bars=10,
            require_quad=True,
            fvg_disp_ratio=0.5,            # low
            fvg_ts=base + pd.Timedelta(minutes=60),
            sweep_ts=base,                  # 60 min ago, outside 10-bar lookback
            fvg_quad_pos=0.9,               # premium
            direction="long",
        )
        assert out["gate_fires"]
        assert len(out["issues"]) == 3
        assert any("low_displacement" in i for i in out["issues"])
        assert "no_sweep_linkage" in out["issues"]
        assert any("bull_fvg_in_premium" in i for i in out["issues"])

    def test_two_fire_third_passes(self):
        """Low disp + no sweep but quadrant OK."""
        base = pd.Timestamp("2025-03-03 09:00", tz="US/Central")
        out = _evaluate_fvg_quality_gate(
            require_disp=True, min_disp=2.0,
            require_link=True, link_bars=10,
            require_quad=True,
            fvg_disp_ratio=0.5,
            fvg_ts=base + pd.Timedelta(minutes=60),
            sweep_ts=base,
            fvg_quad_pos=0.2,
            direction="long",
        )
        assert out["gate_fires"]
        assert len(out["issues"]) == 2
        assert any("bull_fvg_in_premium" not in i for i in out["issues"])

    def test_all_pass_means_signal_proceeds(self):
        """ICT-perfect setup: high disp + linked sweep + discount entry."""
        base = pd.Timestamp("2025-03-03 09:00", tz="US/Central")
        out = _evaluate_fvg_quality_gate(
            require_disp=True, min_disp=2.0,
            require_link=True, link_bars=10,
            require_quad=True,
            fvg_disp_ratio=3.5,            # high (passes)
            fvg_ts=base + pd.Timedelta(minutes=5),
            sweep_ts=base,                  # 5 min ago, within lookback (passes)
            fvg_quad_pos=0.15,              # deep discount for LONG (passes)
            direction="long",
        )
        assert not out["gate_fires"]
        assert out["issues"] == []


# ───────────────────────────────────────────────────────────────────────
# Shadow vs Active mode semantics (config-level test)
# ───────────────────────────────────────────────────────────────────────

class TestShadowVsActiveMode:
    """Verify the config flag drives the action without coupling the test
    to silver_bullet.evaluate's full pipeline. The actual return-None vs
    log-and-continue branching is in silver_bullet.py ~1685-1694."""

    def test_shadow_default_is_true(self):
        """Default config must be shadow mode (do not act on signals)."""
        import config
        assert config.cfg("SB_FVG_QUALITY_SHADOW_MODE", True) is True

    def test_all_gate_flags_default_off(self):
        """No gate enabled by default — ship safely."""
        import config
        assert config.cfg("SB_FVG_REQUIRE_DISPLACEMENT", False) is False
        assert config.cfg("SB_FVG_REQUIRE_LINKED_SWEEP", False) is False
        assert config.cfg("SB_FVG_REQUIRE_QUADRANT", False) is False

    def test_min_displacement_default(self):
        import config
        assert float(config.cfg("SB_FVG_MIN_DISPLACEMENT", 2.0)) == 2.0

    def test_sweep_lookback_default(self):
        import config
        assert int(config.cfg("SB_FVG_SWEEP_LOOKBACK_BARS", 10)) == 10
