"""
tests/test_silver_bullet.py
============================
Unit tests for the 2026-04-20 FVG-based rewrite of
strategies/silver_bullet.py.

Strategy reference (all ICT video sections 2026-04-20):
  - Entry at FVG proximal + 1 tick (section 2.3)
  - Stop at FVG candle-1 extreme ± 1 tick (section 5.1)
  - Target at next unswept liquidity pool in direction, framework ≥ 10 pts
    for MNQ (section 8.1)
  - Three 60-min windows (london_silver_bullet 02:00-03:00 CT,
    silver_bullet 09:00-10:00 CT, pm_silver_bullet 13:00-14:00 CT)
  - No HTF bias required; confluence min = 5/19

Run: cd algoict-engine && python -m pytest tests/test_silver_bullet.py -v
"""

import pandas as pd
import pytest
import pytz

from strategies.silver_bullet import SilverBulletStrategy, Signal
from detectors.market_structure import MarketStructureDetector, StructureEvent
from detectors.fair_value_gap import FairValueGapDetector, FVG
from detectors.order_block import OrderBlockDetector, OrderBlock
from detectors.displacement import DisplacementDetector, Displacement
from detectors.liquidity import LiquidityDetector, LiquidityLevel
from detectors.confluence import ConfluenceScorer
from timeframes.session_manager import SessionManager
from timeframes.htf_bias import BiasResult
from risk.risk_manager import RiskManager


CT = pytz.timezone("US/Central")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _sb_ts(hour: int = 9, minute: int = 15) -> pd.Timestamp:
    """Timestamp inside the AM Silver Bullet kill zone (09:00-10:00 CT)."""
    return pd.Timestamp(CT.localize(pd.Timestamp(2025, 3, 3, hour, minute)))


def _make_1min(ts: pd.Timestamp, close: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open":   [close - 0.1],
            "high":   [close + 0.3],
            "low":    [close - 0.3],
            "close":  [close],
            "volume": [500],
        },
        index=pd.DatetimeIndex([ts], tz="US/Central"),
    )


def _make_5min(ts: pd.Timestamp, close: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open":   [close - 0.2],
            "high":   [close + 0.5],
            "low":    [close - 0.5],
            "close":  [close],
            "volume": [1000],
        },
        index=pd.DatetimeIndex([ts], tz="US/Central"),
    )


def _bullish_bias_fn(price: float) -> BiasResult:
    return BiasResult(
        direction="bullish",
        premium_discount="discount",
        htf_levels={
            "daily_high": 115.0, "daily_low": 95.0,
            "weekly_high": 115.0, "weekly_low": 90.0,
        },
        confidence="high",
        weekly_bias="bullish",
        daily_bias="bullish",
    )


def _neutral_bias_fn(price: float) -> BiasResult:
    return BiasResult(
        direction="neutral",
        premium_discount="equilibrium",
        htf_levels={},
        confidence="low",
        weekly_bias="neutral",
        daily_bias="neutral",
    )


def _build_full_setup(
    bias_fn=_bullish_bias_fn,
    inject_sweep: bool = True,
    inject_fvg: bool = True,
    inject_target: bool = True,
    inject_structure: bool = True,
    ts: pd.Timestamp = None,
):
    """Build a complete Silver Bullet setup.

    Components (dims chosen to pass v2 filters:
    stop distance ≥ 8pts, framework ≥ 10pts):
      - bullish FVG inside AM window (top=101, bottom=99, stop_ref=91 →
        entry=101.25, stop=90.75, stop_dist=10.5pts)
      - SSL sweep before the window
      - 5-min MSS bullish
      - BSL liquidity target at 120.0 (>= 10 pts framework from entry 101.25)
    """
    ts = ts or _sb_ts(9, 20)   # 5 min past arm time (09:15) for safe margin

    structure_det = MarketStructureDetector()
    if inject_structure:
        # SB uses 5-min structure (V9 post-2026-04-23 audit). Option B
        # (1-min) tested + rejected on Q1 backtest due to noise.
        structure_det.events.append(StructureEvent(
            type="MSS", direction="bullish",
            level=98.0, timestamp=ts - pd.Timedelta(minutes=5),
            timeframe="5min",
        ))

    fvg_det = FairValueGapDetector()
    if inject_fvg:
        # FVG must live INSIDE the active KZ window.
        # 2026-04-29 — width bumped 2pt → 3pt to satisfy Fix #6 quality
        # gate (FVG/stop ratio >= 0.20). With stop_ref=91 (stop dist
        # 10.5pt), 3pt FVG = 0.286 ratio (passes), 2pt was 0.190 (fails).
        fvg_det.fvgs.append(FVG(
            top=102.0, bottom=99.0, direction="bullish",
            timeframe="1min", candle_index=10,
            timestamp=ts - pd.Timedelta(minutes=3),
            # Candle-1 low well below bottom so stop distance passes 8pt min.
            stop_reference=91.0,
        ))

    # OBs and displacements are passed to the confluence scorer but not
    # required for entry in the FVG-based SB.
    ob_det = OrderBlockDetector()
    disp_det = DisplacementDetector()

    tracked_levels = []
    if inject_sweep:
        tracked_levels.append(LiquidityLevel(
            price=98.5, type="SSL", swept=True,
            timestamp=ts - pd.Timedelta(minutes=5),
        ))
    if inject_target:
        # BSL >= 10 pts above projected entry (101.25) satisfies the
        # MIN_FRAMEWORK_PTS filter.
        tracked_levels.append(LiquidityLevel(
            price=120.0, type="BSL", swept=False,
            timestamp=ts - pd.Timedelta(hours=1),
        ))

    detectors = {
        "structure":      structure_det,
        "fvg":            fvg_det,
        "ob":             ob_det,
        "displacement":   disp_det,
        "liquidity":      LiquidityDetector(),
        "confluence":     ConfluenceScorer(),
        "tracked_levels": tracked_levels,
    }

    risk = RiskManager()
    session = SessionManager()
    strategy = SilverBulletStrategy(
        detectors=detectors,
        risk_manager=risk,
        session_manager=session,
        htf_bias_fn=bias_fn,
    )

    candles_1 = _make_1min(ts, close=100.0)
    candles_5 = _make_5min(ts, close=100.0)
    return strategy, candles_1, candles_5


# ─── Positive: full setup triggers ───────────────────────────────────────────

class TestPositiveSetup:

    def test_full_setup_returns_signal(self):
        strat, c1, c5 = _build_full_setup()
        signal = strat.evaluate(c1, c5)
        assert signal is not None
        assert isinstance(signal, Signal)

    def test_signal_direction_long(self):
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        assert sig.direction == "long"

    def test_signal_strategy_name(self):
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        assert sig.strategy == "silver_bullet"

    def test_signal_kill_zone_field(self):
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        # v4 "RTH Mode": default KILL_ZONES = (london, ny_am, ny_pm).
        # The _build_full_setup fixture uses 09:20 CT which sits inside ny_am.
        assert sig.kill_zone == "ny_am"

    def test_signal_entry_at_fvg_proximal_plus_tick(self):
        """Long entry = FVG.top + 1 tick (ICT section 2.3)."""
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        # FVG.top = 102.0 (post-2026-04-29 helper bump for FVG quality
        # gate), tick = 0.25 → entry = 102.25
        assert sig.entry_price == pytest.approx(102.25)

    def test_signal_stop_at_candle1_low_minus_tick(self):
        """Long stop = FVG.stop_reference - 1 tick (ICT section 5.1)."""
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        # stop_reference = 91.0, tick = 0.25 → stop = 90.75
        assert sig.stop_price == pytest.approx(90.75)

    def test_signal_target_is_liquidity_pool(self):
        """Target = nearest unswept liquidity pool in direction."""
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        # Target is the BSL at 120.0 (only one above entry).
        assert sig.target_price == pytest.approx(120.0)

    def test_signal_has_confluence_score(self):
        """Confluence score still computed and attached to Signal for
        reporting, even though the v2 strategy no longer gates on it."""
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        assert sig.confluence_score >= 0
        assert isinstance(sig.confluence_breakdown, dict)

    def test_notify_trade_executed_increments_trades_today(self):
        strat, c1, c5 = _build_full_setup()
        assert strat.trades_today == 0
        sig = strat.evaluate(c1, c5)
        assert sig is not None
        assert strat.trades_today == 0   # evaluate() does not advance
        strat.notify_trade_executed(sig)
        assert strat.trades_today == 1


# ─── Negative: each gate rejects ─────────────────────────────────────────────

class TestRejectionGates:

    def test_outside_kill_zone_returns_none(self):
        # v19a-WIDE: KZs are continuous 01:00-15:00 CT. Test outside that:
        # 00:30 CT (before London) or 16:00 CT (after NY PM).
        out_ts = _sb_ts(0, 30)   # before London (01:00 CT)
        strat, _, c5 = _build_full_setup(ts=out_ts)
        c1_out = _make_1min(out_ts, close=100.0)
        assert strat.evaluate(c1_out, c5) is None

    def test_after_kill_zone_returns_none(self):
        """v19a-WIDE: ny_pm ends at 15:00 CT. 15:30 CT is outside all KZs."""
        out_ts = _sb_ts(15, 30)
        strat, _, c5 = _build_full_setup(ts=out_ts)
        c1_out = _make_1min(out_ts, close=100.0)
        assert strat.evaluate(c1_out, c5) is None

    def test_past_cancel_time_returns_none(self):
        """v4: ny_am ends at 12:00, cancels 10min earlier → 11:50 CT."""
        cancel_ts = _sb_ts(11, 50)
        strat, _, c5 = _build_full_setup(ts=cancel_ts)
        c1_cancel = _make_1min(cancel_ts, close=100.0)
        assert strat.evaluate(c1_cancel, c5) is None

    def test_just_before_cancel_time_allowed(self):
        """v4: 11:49 CT — just before ny_am cancel cutoff."""
        early_ts = _sb_ts(11, 49)
        strat, _, c5 = _build_full_setup(ts=early_ts)
        c1_early = _make_1min(early_ts, close=100.0)
        assert strat.evaluate(c1_early, c5) is not None

    def test_neutral_htf_bias_does_NOT_reject(self):
        """ICT: Silver Bullet does not require HTF bias alignment."""
        strat, c1, c5 = _build_full_setup(bias_fn=_neutral_bias_fn)
        assert strat.evaluate(c1, c5) is not None

    def test_no_5min_structure_returns_none(self):
        strat, c1, c5 = _build_full_setup(inject_structure=False)
        assert strat.evaluate(c1, c5) is None

    def test_no_fvg_returns_none(self):
        strat, c1, c5 = _build_full_setup(inject_fvg=False)
        assert strat.evaluate(c1, c5) is None

    def test_no_sweep_returns_none(self):
        strat, c1, c5 = _build_full_setup(inject_sweep=False)
        assert strat.evaluate(c1, c5) is None

    def test_no_liquidity_target_returns_none(self):
        strat, c1, c5 = _build_full_setup(inject_target=False)
        assert strat.evaluate(c1, c5) is None

    def test_framework_below_minimum_returns_none(self):
        """Liquidity target closer than 10 pts fails the framework filter."""
        strat, c1, c5 = _build_full_setup(inject_target=False)
        # BSL at 108 → framework ~7.25 pts from entry 100.75 < 10 pt minimum
        strat.detectors["tracked_levels"].append(LiquidityLevel(
            price=108.0, type="BSL", swept=False,
            timestamp=_sb_ts(8, 30),
        ))
        assert strat.evaluate(c1, c5) is None

    def test_kill_switch_active_returns_none(self):
        strat, c1, c5 = _build_full_setup()
        strat.risk.kill_switch_active = True
        assert strat.evaluate(c1, c5) is None

    def test_profit_cap_active_returns_none(self):
        strat, c1, c5 = _build_full_setup()
        strat.risk.profit_cap_active = True
        assert strat.evaluate(c1, c5) is None

    def test_vpin_halt_returns_none(self):
        strat, c1, c5 = _build_full_setup()
        strat.risk._vpin_halt_active = True
        assert strat.evaluate(c1, c5) is None

    def test_max_trades_reached_returns_none(self):
        """v4 uses MAX_TRADES_PER_ZONE=999 (effectively unlimited). The real
        halt is RiskManager's 3-consecutive-loss kill switch. To test the
        per-zone cap as a GATE, we simulate reaching the cap manually."""
        strat, c1, c5 = _build_full_setup()
        # Fixture ts=09:20 CT → zone is "ny_am".
        strat._trades_by_zone["ny_am"] = strat.MAX_TRADES_PER_ZONE
        assert strat.evaluate(c1, c5) is None

    def test_past_hard_close_returns_none(self):
        late_ts = _sb_ts(15, 30)
        strat, _, c5 = _build_full_setup(ts=late_ts)
        c1_late = _make_1min(late_ts, close=100.0)
        assert strat.evaluate(c1_late, c5) is None

    def test_empty_1min_returns_none(self):
        strat, _, c5 = _build_full_setup()
        empty = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="US/Central"),
        )
        assert strat.evaluate(empty, c5) is None

    def test_empty_5min_returns_none(self):
        strat, c1, _ = _build_full_setup()
        empty = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="US/Central"),
        )
        assert strat.evaluate(c1, empty) is None


# ─── Timeframe: FVG must be on 1-min ─────────────────────────────────────────

class TestTimeframeUsage:

    def test_fvg_on_5min_tf_rejected(self):
        """Silver Bullet entry looks at 1-min FVGs only."""
        ts = _sb_ts(9, 15)
        strat, c1, c5 = _build_full_setup(inject_fvg=False, ts=ts)
        strat.detectors["fvg"].fvgs.append(FVG(
            top=100.5, bottom=99.5, direction="bullish",
            timeframe="5min",   # wrong TF
            candle_index=10, timestamp=ts - pd.Timedelta(minutes=2),
            stop_reference=99.3,
        ))
        assert strat.evaluate(c1, c5) is None

    def test_structure_on_15min_tf_rejected(self):
        """Silver Bullet uses 5-min structure (V9 post-2026-04-23 audit)."""
        ts = _sb_ts(9, 15)
        strat, c1, c5 = _build_full_setup(inject_structure=False, ts=ts)
        strat.detectors["structure"].events.append(StructureEvent(
            type="MSS", direction="bullish",
            level=98.0, timestamp=ts,
            timeframe="15min",   # wrong TF
        ))
        assert strat.evaluate(c1, c5) is None


# ─── Wrong-direction sweep ───────────────────────────────────────────────────

class TestSweepDirection:

    def test_bsl_sweep_rejected_for_long(self):
        """Bullish FVG requires SSL/equal_lows sweep, not BSL."""
        ts = _sb_ts(9, 15)
        strat, c1, c5 = _build_full_setup(inject_sweep=False, ts=ts)
        strat.detectors["tracked_levels"].append(LiquidityLevel(
            price=101.5, type="BSL", swept=True, timestamp=ts,
        ))
        assert strat.evaluate(c1, c5) is None


# ─── Direction determined by FVG ─────────────────────────────────────────────

class TestBearishSetup:

    def test_bearish_fvg_produces_short(self):
        """Bearish FVG → short trade with inverted entry/stop/target logic.

        Dimensions chosen to pass v2 filters:
          - stop distance ≥ 8pts (FVG.bottom=99, stop_ref=109 → stop_dist=10.5)
          - framework ≥ 10pts (SSL target at 88 → 10.75pts from entry 98.75)
        """
        ts = _sb_ts(9, 20)
        strat, c1, c5 = _build_full_setup(
            inject_fvg=False, inject_sweep=False, inject_target=False, ts=ts,
        )
        # Bearish FVG + BSL sweep + SSL target below entry.
        # 2026-04-29 — width 2pt → 3pt for Fix #6 quality gate
        # (3pt / stop_dist 10.5pt = 0.286 ratio passes 0.20 min).
        strat.detectors["fvg"].fvgs.append(FVG(
            top=101.0, bottom=98.0, direction="bearish",
            timeframe="1min", candle_index=10,
            timestamp=ts - pd.Timedelta(minutes=3),
            stop_reference=109.0,   # candle-1 high, well above top
        ))
        strat.detectors["tracked_levels"].append(LiquidityLevel(
            price=105.0, type="BSL", swept=True,
            timestamp=ts - pd.Timedelta(minutes=5),
        ))
        strat.detectors["tracked_levels"].append(LiquidityLevel(
            price=87.0, type="SSL", swept=False,
            timestamp=ts - pd.Timedelta(hours=1),
        ))
        # Need bearish structure too (5-min per V9 post-2026-04-23 audit).
        strat.detectors["structure"].events.clear()
        strat.detectors["structure"].events.append(StructureEvent(
            type="MSS", direction="bearish",
            level=102.0, timestamp=ts - pd.Timedelta(minutes=5),
            timeframe="5min",
        ))
        sig = strat.evaluate(c1, c5)
        assert sig is not None
        assert sig.direction == "short"
        assert sig.entry_price == pytest.approx(97.75)   # bottom 98 - tick
        assert sig.stop_price == pytest.approx(109.25)   # stop_ref + tick
        assert sig.target_price == pytest.approx(87.0)


# ─── Three windows: each zone routes correctly ──────────────────────────────

class TestThreeWindows:

    def test_london_kz_active(self):
        """v4 default KILL_ZONES = (london, ny_am, ny_pm). 02:20 CT is
        inside London (01-04 CT)."""
        ts = _sb_ts(2, 20)
        strat, c1, c5 = _build_full_setup(ts=ts)
        sig = strat.evaluate(c1, c5)
        assert sig is not None
        assert sig.kill_zone == "london"

    def test_ny_pm_window(self):
        """v4: NY PM kill zone is 13:30-15:00 CT (not pm_silver_bullet's
        narrow 13-14). 13:45 CT is inside ny_pm."""
        ts = _sb_ts(13, 45)
        strat, c1, c5 = _build_full_setup(ts=ts)
        sig = strat.evaluate(c1, c5)
        assert sig is not None
        assert sig.kill_zone == "ny_pm"


# ─── Max trades ─────────────────────────────────────────────────────────────

class TestMaxTrades:

    def test_max_trades_is_one_per_zone(self):
        strat, c1, c5 = _build_full_setup()
        sig1 = strat.evaluate(c1, c5)
        assert sig1 is not None
        strat.notify_trade_executed(sig1)
        assert strat.trades_today == 1
        sig2 = strat.evaluate(c1, c5)
        assert sig2 is None


# ─── Reset ───────────────────────────────────────────────────────────────────

class TestReset:

    def test_reset_daily_clears_trades_today(self):
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        strat.notify_trade_executed(sig)
        assert strat.trades_today == 1
        strat.reset_daily()
        assert strat.trades_today == 0

    def test_can_trade_again_after_reset(self):
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        strat.notify_trade_executed(sig)
        strat.reset_daily()
        sig2 = strat.evaluate(c1, c5)
        assert sig2 is not None
