"""
tests/test_ny_am_reversal.py
=============================
Unit tests for strategies/ny_am_reversal.py

Strategy: build a complete bullish setup that satisfies every gate, then
verify the strategy returns a Signal. Mutate one condition at a time to
verify each gate rejects properly.

Run: cd algoict-engine && python -m pytest tests/test_ny_am_reversal.py -v
"""

from dataclasses import dataclass

import pandas as pd
import pytest
import pytz

from strategies.ny_am_reversal import NYAMReversalStrategy, Signal
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

def _ny_am_ts(hour: int = 9, minute: int = 30) -> pd.Timestamp:
    """Timestamp inside NY AM kill zone (8:30–11:00 CT)."""
    return pd.Timestamp(CT.localize(pd.Timestamp(2025, 3, 3, hour, minute)))


def _make_5min(ts: pd.Timestamp, close: float = 100.0) -> pd.DataFrame:
    """Build a tiny 5min DataFrame with a single bar at *ts*."""
    return pd.DataFrame(
        {
            "open":  [close - 0.2],
            "high":  [close + 0.5],
            "low":   [close - 0.5],
            "close": [close],
            "volume": [1000],
        },
        index=pd.DatetimeIndex([ts], tz="US/Central"),
    )


def _make_15min(ts: pd.Timestamp, close: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open":  [close - 0.5],
            "high":  [close + 1.0],
            "low":   [close - 1.0],
            "close": [close],
            "volume": [3000],
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
    Build a complete NY AM Reversal setup. Each `inject_*` flag toggles
    one component on/off so individual rejection paths can be tested.

    Returns: (strategy, candles_5min, candles_15min)
    """
    ts = ts or _ny_am_ts(9, 30)

    # ── Build detectors with state ─────────────────────────────────────
    structure_det = MarketStructureDetector()
    if inject_structure:
        structure_det.events.append(StructureEvent(
            type="MSS", direction="bullish",
            level=98.0, timestamp=ts - pd.Timedelta(minutes=15),
            timeframe="15min",
        ))

    fvg_det = FairValueGapDetector()
    if inject_fvg:
        fvg_det.fvgs.append(FVG(
            top=100.5, bottom=99.5, direction="bullish",
            timeframe="5min", candle_index=10,
            timestamp=ts - pd.Timedelta(minutes=10),
        ))

    ob_det = OrderBlockDetector()
    if inject_ob:
        ob_det.order_blocks.append(OrderBlock(
            high=100.0, low=99.0, direction="bullish",
            timeframe="5min", candle_index=10,
            timestamp=ts - pd.Timedelta(minutes=10),
        ))

    disp_det = DisplacementDetector()
    if inject_displacement:
        disp_det.displacements.append(Displacement(
            direction="bullish", magnitude=5.0, atr=1.0,
            timestamp=ts - pd.Timedelta(minutes=5),
            timeframe="5min", candle_index=11,
        ))

    tracked_levels = []
    if inject_sweep:
        tracked_levels.append(LiquidityLevel(
            price=98.5, type="SSL", swept=True,
            timestamp=ts - pd.Timedelta(minutes=20),
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
    strategy = NYAMReversalStrategy(
        detectors=detectors,
        risk_manager=risk,
        session_manager=session,
        htf_bias_fn=bias_fn,
    )

    candles_5 = _make_5min(ts, close=100.0)
    candles_15 = _make_15min(ts, close=100.0)
    return strategy, candles_5, candles_15


# ─── Positive: full setup triggers ───────────────────────────────────────────

class TestPositiveSetup:

    def test_full_setup_returns_signal(self):
        strat, c5, c15 = _build_full_setup()
        signal = strat.evaluate(c5, c15)
        assert signal is not None
        assert isinstance(signal, Signal)

    def test_signal_direction_long(self):
        strat, c5, c15 = _build_full_setup()
        sig = strat.evaluate(c5, c15)
        assert sig.direction == "long"

    def test_signal_strategy_name(self):
        strat, c5, c15 = _build_full_setup()
        sig = strat.evaluate(c5, c15)
        assert sig.strategy == "ny_am_reversal"

    def test_signal_kill_zone_field(self):
        strat, c5, c15 = _build_full_setup()
        sig = strat.evaluate(c5, c15)
        assert sig.kill_zone == "ny_am"

    def test_signal_entry_at_ob_high(self):
        """Long entry = OB.high (proximal of bullish OB)."""
        strat, c5, c15 = _build_full_setup()
        sig = strat.evaluate(c5, c15)
        assert sig.entry_price == pytest.approx(100.0)   # ob.high

    def test_signal_stop_at_ob_low(self):
        strat, c5, c15 = _build_full_setup()
        sig = strat.evaluate(c5, c15)
        assert sig.stop_price == pytest.approx(99.0)     # ob.low

    def test_signal_target_is_3rr(self):
        """target = entry + 3 × actual_stop_points."""
        strat, c5, c15 = _build_full_setup()
        sig = strat.evaluate(c5, c15)
        # stop_points = 1.0; risk=$250 / (1*2.0) = 125 raw → 50 contracts (max)
        # actual_stop = 250 / (50*2.0) = 2.5
        # target = 100.0 + 3 × 2.5 = 107.5
        assert sig.target_price == pytest.approx(107.5)

    def test_signal_contracts_clamped_to_max(self):
        """Stop = 1pt → raw = 125 → clamped to 50."""
        strat, c5, c15 = _build_full_setup()
        sig = strat.evaluate(c5, c15)
        assert sig.contracts == 50

    def test_signal_has_confluence_score(self):
        strat, c5, c15 = _build_full_setup()
        sig = strat.evaluate(c5, c15)
        assert sig.confluence_score >= 7  # MIN_CONFLUENCE
        assert isinstance(sig.confluence_breakdown, dict)
        assert len(sig.confluence_breakdown) > 0

    def test_signal_increments_trades_today(self):
        strat, c5, c15 = _build_full_setup()
        assert strat.trades_today == 0
        strat.evaluate(c5, c15)
        assert strat.trades_today == 1


# ─── Negative: each gate rejects ─────────────────────────────────────────────

class TestRejectionGates:

    def test_outside_kill_zone_returns_none(self):
        """Timestamp at 14:00 CT — past NY AM (08:30–11:00)."""
        out_ts = _ny_am_ts(14, 0)
        strat, _, c15 = _build_full_setup(ts=out_ts)
        c5_out = _make_5min(out_ts, close=100.0)
        assert strat.evaluate(c5_out, c15) is None

    def test_neutral_htf_bias_returns_none(self):
        strat, c5, c15 = _build_full_setup(bias_fn=_neutral_bias_fn)
        assert strat.evaluate(c5, c15) is None

    def test_no_15min_structure_returns_none(self):
        strat, c5, c15 = _build_full_setup(inject_structure=False)
        assert strat.evaluate(c5, c15) is None

    def test_no_fvg_returns_none(self):
        strat, c5, c15 = _build_full_setup(inject_fvg=False)
        assert strat.evaluate(c5, c15) is None

    def test_no_ob_returns_none(self):
        strat, c5, c15 = _build_full_setup(inject_ob=False)
        assert strat.evaluate(c5, c15) is None

    def test_no_displacement_returns_none(self):
        strat, c5, c15 = _build_full_setup(inject_displacement=False)
        assert strat.evaluate(c5, c15) is None

    def test_no_sweep_returns_none(self):
        strat, c5, c15 = _build_full_setup(inject_sweep=False)
        assert strat.evaluate(c5, c15) is None

    def test_kill_switch_active_returns_none(self):
        strat, c5, c15 = _build_full_setup()
        strat.risk.kill_switch_active = True
        assert strat.evaluate(c5, c15) is None

    def test_profit_cap_active_returns_none(self):
        strat, c5, c15 = _build_full_setup()
        strat.risk.profit_cap_active = True
        assert strat.evaluate(c5, c15) is None

    def test_vpin_halt_returns_none(self):
        strat, c5, c15 = _build_full_setup()
        strat.risk._vpin_halted = True
        assert strat.evaluate(c5, c15) is None

    def test_max_trades_reached_returns_none(self):
        strat, c5, c15 = _build_full_setup()
        strat.trades_today = 2   # MAX_TRADES = 2
        assert strat.evaluate(c5, c15) is None

    def test_past_hard_close_returns_none(self):
        """Timestamp at 15:30 CT — past 3 PM hard close."""
        late_ts = _ny_am_ts(15, 30)   # well outside kill zone too
        strat, _, c15 = _build_full_setup(ts=late_ts)
        c5_late = _make_5min(late_ts, close=100.0)
        assert strat.evaluate(c5_late, c15) is None

    def test_empty_dataframe_returns_none(self):
        strat, _, c15 = _build_full_setup()
        empty = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="US/Central"),
        )
        assert strat.evaluate(empty, c15) is None


# ─── Wrong-direction sweep (bullish setup, BSL swept = wrong) ────────────────

class TestSweepDirection:

    def test_bsl_sweep_rejected_for_long(self):
        """A bullish setup must have an SSL/PDL/PWL/equal_lows sweep, not BSL."""
        ts = _ny_am_ts(9, 30)
        strat, c5, c15 = _build_full_setup(inject_sweep=False, ts=ts)
        # Inject the WRONG side sweep
        strat.detectors["tracked_levels"].append(LiquidityLevel(
            price=101.5, type="BSL", swept=True, timestamp=ts,
        ))
        assert strat.evaluate(c5, c15) is None


# ─── Reset behavior ──────────────────────────────────────────────────────────

class TestReset:

    def test_reset_daily_clears_trades_today(self):
        strat, c5, c15 = _build_full_setup()
        strat.evaluate(c5, c15)
        assert strat.trades_today == 1
        strat.reset_daily()
        assert strat.trades_today == 0
