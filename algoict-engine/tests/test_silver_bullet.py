"""
tests/test_silver_bullet.py
============================
Unit tests for strategies/silver_bullet.py

Strategy: build a complete bullish setup that satisfies every gate, then
verify the strategy returns a Signal. Mutate one condition at a time to
verify each gate rejects properly.

Run: cd algoict-engine && python -m pytest tests/test_silver_bullet.py -v
"""

from dataclasses import dataclass

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

def _sb_ts(hour: int = 10, minute: int = 15) -> pd.Timestamp:
    """Timestamp inside Silver Bullet kill zone (10:00–11:00 CT)."""
    return pd.Timestamp(CT.localize(pd.Timestamp(2025, 3, 3, hour, minute)))


def _make_1min(ts: pd.Timestamp, close: float = 100.0) -> pd.DataFrame:
    """Build a tiny 1min DataFrame with a single bar at *ts*."""
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
        htf_levels={"daily_high": 110.0, "daily_low": 95.0,
                    "weekly_high": 115.0, "weekly_low": 90.0},
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
    inject_ob: bool = True,
    inject_displacement: bool = True,
    inject_structure: bool = True,
    ts: pd.Timestamp = None,
):
    """
    Build a complete Silver Bullet setup. Each `inject_*` flag toggles
    one component on/off so individual rejection paths can be tested.

    Returns: (strategy, candles_1min, candles_5min)
    """
    ts = ts or _sb_ts(10, 15)

    # ── Build detectors with state ─────────────────────────────────────
    structure_det = MarketStructureDetector()
    if inject_structure:
        structure_det.events.append(StructureEvent(
            type="MSS", direction="bullish",
            level=98.0, timestamp=ts - pd.Timedelta(minutes=5),
            timeframe="5min",
        ))

    fvg_det = FairValueGapDetector()
    if inject_fvg:
        fvg_det.fvgs.append(FVG(
            top=100.5, bottom=99.5, direction="bullish",
            timeframe="1min", candle_index=10,
            timestamp=ts - pd.Timedelta(minutes=3),
        ))

    ob_det = OrderBlockDetector()
    if inject_ob:
        ob_det.order_blocks.append(OrderBlock(
            high=100.0, low=99.0, direction="bullish",
            timeframe="1min", candle_index=10,
            timestamp=ts - pd.Timedelta(minutes=3),
        ))

    disp_det = DisplacementDetector()
    if inject_displacement:
        disp_det.displacements.append(Displacement(
            direction="bullish", magnitude=5.0, atr=1.0,
            timestamp=ts - pd.Timedelta(minutes=2),
            timeframe="1min", candle_index=11,
        ))

    tracked_levels = []
    if inject_sweep:
        tracked_levels.append(LiquidityLevel(
            price=98.5, type="SSL", swept=True,
            timestamp=ts - pd.Timedelta(minutes=5),
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
        assert sig.kill_zone == "silver_bullet"

    def test_signal_entry_at_ob_high(self):
        """Long entry = OB.high (proximal of bullish OB)."""
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        assert sig.entry_price == pytest.approx(100.0)   # ob.high

    def test_signal_stop_at_ob_low(self):
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        assert sig.stop_price == pytest.approx(99.0)     # ob.low

    def test_signal_target_is_2rr(self):
        """target = entry + 2 × actual_stop_points (1:2 RR)."""
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        # stop_points = 1.0; raw = 250 / (1 × 2.0) = 125 → clamped to 50
        # actual_stop = 250 / (50 × 2.0) = 2.5
        # target = 100.0 + 2 × 2.5 = 105.0
        assert sig.target_price == pytest.approx(105.0)

    def test_signal_contracts_clamped_to_max(self):
        """Stop = 1pt → raw = 125 → clamped to 50."""
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        assert sig.contracts == 50

    def test_signal_has_confluence_score(self):
        strat, c1, c5 = _build_full_setup()
        sig = strat.evaluate(c1, c5)
        assert sig.confluence_score >= 7  # MIN_CONFLUENCE
        assert isinstance(sig.confluence_breakdown, dict)
        assert len(sig.confluence_breakdown) > 0

    def test_signal_increments_trades_today(self):
        strat, c1, c5 = _build_full_setup()
        assert strat.trades_today == 0
        strat.evaluate(c1, c5)
        assert strat.trades_today == 1


# ─── Negative: each gate rejects ─────────────────────────────────────────────

class TestRejectionGates:

    def test_outside_kill_zone_returns_none(self):
        """Timestamp at 09:00 CT — before Silver Bullet (10:00–11:00)."""
        out_ts = _sb_ts(9, 0)
        strat, _, c5 = _build_full_setup(ts=out_ts)
        c1_out = _make_1min(out_ts, close=100.0)
        assert strat.evaluate(c1_out, c5) is None

    def test_after_kill_zone_returns_none(self):
        """Timestamp at 11:30 CT — after Silver Bullet window."""
        out_ts = _sb_ts(11, 30)
        strat, _, c5 = _build_full_setup(ts=out_ts)
        c1_out = _make_1min(out_ts, close=100.0)
        assert strat.evaluate(c1_out, c5) is None

    def test_past_cancel_time_returns_none(self):
        """Timestamp at 10:50 CT — cancel window (no new entries)."""
        cancel_ts = _sb_ts(10, 50)
        strat, _, c5 = _build_full_setup(ts=cancel_ts)
        c1_cancel = _make_1min(cancel_ts, close=100.0)
        assert strat.evaluate(c1_cancel, c5) is None

    def test_at_1051_returns_none(self):
        """10:51 CT — also past cancel time."""
        late_ts = _sb_ts(10, 51)
        strat, _, c5 = _build_full_setup(ts=late_ts)
        c1_late = _make_1min(late_ts, close=100.0)
        assert strat.evaluate(c1_late, c5) is None

    def test_just_before_cancel_time_allowed(self):
        """10:49 CT — just before cancel cutoff, should still evaluate."""
        early_ts = _sb_ts(10, 49)
        strat, _, c5 = _build_full_setup(ts=early_ts)
        c1_early = _make_1min(early_ts, close=100.0)
        # Setup has all detectors injected — should return signal
        assert strat.evaluate(c1_early, c5) is not None

    def test_neutral_htf_bias_returns_none(self):
        strat, c1, c5 = _build_full_setup(bias_fn=_neutral_bias_fn)
        assert strat.evaluate(c1, c5) is None

    def test_no_5min_structure_returns_none(self):
        strat, c1, c5 = _build_full_setup(inject_structure=False)
        assert strat.evaluate(c1, c5) is None

    def test_no_fvg_returns_none(self):
        strat, c1, c5 = _build_full_setup(inject_fvg=False)
        assert strat.evaluate(c1, c5) is None

    def test_no_ob_returns_none(self):
        strat, c1, c5 = _build_full_setup(inject_ob=False)
        assert strat.evaluate(c1, c5) is None

    def test_no_displacement_returns_none(self):
        strat, c1, c5 = _build_full_setup(inject_displacement=False)
        assert strat.evaluate(c1, c5) is None

    def test_no_sweep_returns_none(self):
        strat, c1, c5 = _build_full_setup(inject_sweep=False)
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
        strat.risk._vpin_halted = True
        assert strat.evaluate(c1, c5) is None

    def test_max_trades_reached_returns_none(self):
        strat, c1, c5 = _build_full_setup()
        # silver_bullet zone's cap has been reached (1 trade in silver_bullet)
        strat._trades_by_zone["silver_bullet"] = strat.MAX_TRADES_PER_ZONE
        strat.trades_today = strat.MAX_TRADES_PER_ZONE
        assert strat.evaluate(c1, c5) is None

    def test_past_hard_close_returns_none(self):
        """Timestamp at 15:30 CT — past 3 PM hard close."""
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


# ─── Timeframe-specific: detectors queried on correct TF ─────────────────────

class TestTimeframeUsage:

    def test_fvg_on_1min_tf_only(self):
        """
        Injecting an FVG on '5min' (wrong TF) should be rejected — the
        strategy only queries 1min FVGs for entry.
        """
        ts = _sb_ts(10, 15)
        strat, c1, c5 = _build_full_setup(inject_fvg=False, ts=ts)
        # Inject FVG on wrong timeframe
        strat.detectors["fvg"].fvgs.append(FVG(
            top=100.5, bottom=99.5, direction="bullish",
            timeframe="5min",   # wrong TF
            candle_index=10, timestamp=ts,
        ))
        assert strat.evaluate(c1, c5) is None

    def test_ob_on_1min_tf_only(self):
        """
        Injecting an OB on '5min' (wrong TF) should be rejected — the
        strategy only queries 1min OBs for entry.
        """
        ts = _sb_ts(10, 15)
        strat, c1, c5 = _build_full_setup(inject_ob=False, ts=ts)
        # Inject OB on wrong timeframe
        strat.detectors["ob"].order_blocks.append(OrderBlock(
            high=100.0, low=99.0, direction="bullish",
            timeframe="5min",   # wrong TF
            candle_index=10, timestamp=ts,
        ))
        assert strat.evaluate(c1, c5) is None

    def test_structure_on_5min_tf_only(self):
        """
        Injecting MSS on '15min' (wrong TF) should be rejected — the
        Silver Bullet uses 5min context, not 15min.
        """
        ts = _sb_ts(10, 15)
        strat, c1, c5 = _build_full_setup(inject_structure=False, ts=ts)
        # Inject structure on wrong timeframe
        strat.detectors["structure"].events.append(StructureEvent(
            type="MSS", direction="bullish",
            level=98.0, timestamp=ts,
            timeframe="15min",   # wrong TF — silver bullet needs 5min
        ))
        assert strat.evaluate(c1, c5) is None


# ─── Wrong-direction sweep (bullish setup, BSL swept = wrong) ────────────────

class TestSweepDirection:

    def test_bsl_sweep_rejected_for_long(self):
        """A bullish setup must have an SSL/PDL/PWL/equal_lows sweep, not BSL."""
        ts = _sb_ts(10, 15)
        strat, c1, c5 = _build_full_setup(inject_sweep=False, ts=ts)
        # Inject wrong side sweep
        strat.detectors["tracked_levels"].append(LiquidityLevel(
            price=101.5, type="BSL", swept=True, timestamp=ts,
        ))
        assert strat.evaluate(c1, c5) is None


# ─── Max trades: only 1 per session ─────────────────────────────────────────

class TestMaxTrades:

    def test_max_trades_is_one(self):
        """MAX_TRADES=1: second call blocked."""
        strat, c1, c5 = _build_full_setup()
        sig1 = strat.evaluate(c1, c5)
        assert sig1 is not None
        assert strat.trades_today == 1
        # Second evaluation — should be blocked
        sig2 = strat.evaluate(c1, c5)
        assert sig2 is None

    def test_rr_ratio_is_2(self):
        """Confirm RISK_REWARD constant is 2.0 (not 3.0 like ny_am)."""
        strat, c1, c5 = _build_full_setup()
        assert strat.RISK_REWARD == 2.0


# ─── Reset behavior ──────────────────────────────────────────────────────────

class TestReset:

    def test_reset_daily_clears_trades_today(self):
        strat, c1, c5 = _build_full_setup()
        strat.evaluate(c1, c5)
        assert strat.trades_today == 1
        strat.reset_daily()
        assert strat.trades_today == 0

    def test_can_trade_again_after_reset(self):
        strat, c1, c5 = _build_full_setup()
        strat.evaluate(c1, c5)
        assert strat.trades_today == 1
        strat.reset_daily()
        sig = strat.evaluate(c1, c5)
        assert sig is not None
