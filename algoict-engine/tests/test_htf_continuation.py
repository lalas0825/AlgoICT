"""
tests/test_htf_continuation.py
================================
Unit tests for strategies/htf_continuation.py — HTF Daily Bias Continuation.

Covers:
  - Neutral bias rejection (hard gate)
  - Premium/Discount filter (long in discount only, short in premium only)
  - Pullback proximity check (past_proximal vs pullback_incomplete)
  - No 5min OB/FVG fallback
  - Stop sizing — MIN floor (15pt) and MAX ceiling (80pt)
  - Same-setup cooldown after loss
  - Max trades per zone (1)
  - Past cancel time (last 10min of KZ)
  - News blackout integration
  - Long fire (full happy path)
  - Short fire (mirror)

Run: cd algoict-engine && python -m pytest tests/test_htf_continuation.py -v
"""

import pandas as pd
import pytest
import pytz

from strategies.htf_continuation import HTFContinuationStrategy
from strategies.silver_bullet import Signal
from detectors.order_block import OrderBlockDetector, OrderBlock
from detectors.fair_value_gap import FairValueGapDetector, FVG
from detectors.swing_points import SwingPointDetector, SwingPoint
from detectors.liquidity import LiquidityDetector, LiquidityLevel
from detectors.confluence import ConfluenceScorer
from timeframes.session_manager import SessionManager
from timeframes.htf_bias import BiasResult
from risk.risk_manager import RiskManager


CT = pytz.timezone("US/Central")


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _ts(hour: int = 9, minute: int = 0) -> pd.Timestamp:
    """A timestamp inside the NY AM kill zone by default (08:30-12:00 CT)."""
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
            "open":   [close - 0.5],
            "high":   [close + 1.0],
            "low":    [close - 1.0],
            "close":  [close],
            "volume": [2500],
        },
        index=pd.DatetimeIndex([ts], tz="US/Central"),
    )


def _bias(
    daily: str = "bullish",
    pd_zone: str = "discount",
    weekly: str = "bullish",
) -> BiasResult:
    return BiasResult(
        direction=daily,
        premium_discount=pd_zone,
        htf_levels={},
        confidence="medium",
        weekly_bias=weekly,
        daily_bias=daily,
    )


def _build_ob(
    ts: pd.Timestamp,
    high: float,
    low: float,
    direction: str = "bullish",
    timeframe: str = "5min",
    mitigated: bool = False,
) -> OrderBlock:
    return OrderBlock(
        high=high,
        low=low,
        direction=direction,
        timeframe=timeframe,
        candle_index=0,
        timestamp=ts,
        mitigated=mitigated,
    )


def _build_swing_low(price: float, ts: pd.Timestamp) -> SwingPoint:
    return SwingPoint(price=price, timestamp=ts, type="low", timeframe="5min")


def _build_swing_high(price: float, ts: pd.Timestamp) -> SwingPoint:
    return SwingPoint(price=price, timestamp=ts, type="high", timeframe="5min")


def _build_strategy(
    bias_result: BiasResult,
    obs: list = None,
    fvgs: list = None,
    swing_lows: list = None,
    swing_highs: list = None,
    tracked_levels: list = None,
):
    """Construct an HTFContinuationStrategy with hand-populated detector state."""
    obs = obs or []
    fvgs = fvgs or []
    swing_lows = swing_lows or []
    swing_highs = swing_highs or []
    tracked_levels = tracked_levels or []

    ob_det = OrderBlockDetector()
    ob_det.order_blocks = list(obs)

    fvg_det = FairValueGapDetector()
    fvg_det.fvgs = list(fvgs)

    swing_det = SwingPointDetector()
    swing_det.swing_points = list(swing_lows) + list(swing_highs)

    detectors = {
        "ob": ob_det,
        "fvg": fvg_det,
        "swing_context": swing_det,
        "swing_entry": SwingPointDetector(),  # unused but expected key
        "liquidity": LiquidityDetector(),
        "confluence": ConfluenceScorer(),
        "tracked_levels": list(tracked_levels),
    }

    risk_mgr = RiskManager()
    session_mgr = SessionManager()

    strat = HTFContinuationStrategy(
        detectors=detectors,
        risk_manager=risk_mgr,
        session_manager=session_mgr,
        htf_bias_fn=lambda price: bias_result,
    )
    return strat


def _high_target(price: float, kind: str = "PDH") -> LiquidityLevel:
    return LiquidityLevel(
        price=price, type=kind,
        timestamp=pd.Timestamp("2025-03-02", tz="US/Central"),
    )


def _low_target(price: float, kind: str = "PDL") -> LiquidityLevel:
    return LiquidityLevel(
        price=price, type=kind,
        timestamp=pd.Timestamp("2025-03-02", tz="US/Central"),
    )


# ─── Tests: bias gates ───────────────────────────────────────────────────────


def test_neutral_bias_rejects():
    bias = _bias(daily="neutral", pd_zone="equilibrium")
    strat = _build_strategy(bias)
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts), _make_5min(ts))
    assert sig is None
    assert strat.last_rejection["reason"] == "neutral_bias"


def test_long_in_premium_rejects():
    """Daily bullish + price in PREMIUM (>50%) → should reject (institutional rule)."""
    bias = _bias(daily="bullish", pd_zone="premium")
    strat = _build_strategy(bias)
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts), _make_5min(ts))
    assert sig is None
    assert strat.last_rejection["reason"] == "zone_mismatch"


def test_short_in_discount_rejects():
    """Daily bearish + price in DISCOUNT (<50%) → should reject."""
    bias = _bias(daily="bearish", pd_zone="discount")
    strat = _build_strategy(bias)
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts), _make_5min(ts))
    assert sig is None
    assert strat.last_rejection["reason"] == "zone_mismatch"


def test_equilibrium_zone_accepted_2026_05_01():
    """2026-05-01 — equilibrium is now ACCEPTED for both directions
    (relaxed from strict premium/discount-only). Without setup
    primitives the test still rejects but for `no_5min_block` (post-
    zone-aligned), confirming we passed the zone gate."""
    bias = _bias(daily="bullish", pd_zone="equilibrium")
    strat = _build_strategy(bias)
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts), _make_5min(ts))
    assert sig is None
    # zone_aligned accepted equilibrium → reject came AFTER, on no block.
    assert strat.last_rejection["reason"] == "no_5min_block"


# ─── Tests: setup pre-conditions ─────────────────────────────────────────────


def test_no_block_rejects():
    """Bias + zone OK but no 5min OB or FVG → reject."""
    bias = _bias(daily="bullish", pd_zone="discount")
    strat = _build_strategy(bias)
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is None
    assert strat.last_rejection["reason"] == "no_5min_block"


def test_pullback_incomplete_rejects():
    """OB exists but price is far above proximal → wait for retrace."""
    bias = _bias(daily="bullish", pd_zone="discount")
    # OB at 95-97 (bullish, proximal=97), price at 110 → 13pt above proximal
    ob = _build_ob(_ts(9, 0), high=97.0, low=95.0, direction="bullish")
    strat = _build_strategy(
        bias, obs=[ob],
        tracked_levels=[_high_target(120.0)],
    )
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=110.0), _make_5min(ts, close=110.0))
    assert sig is None
    assert strat.last_rejection["reason"] == "pullback_incomplete"


def test_past_proximal_rejects():
    """Price has BLOWN PAST the OB (bar low far below proximal) → reject."""
    bias = _bias(daily="bullish", pd_zone="discount")
    # OB proximal = 97 (high of bullish OB)
    ob = _build_ob(_ts(9, 0), high=97.0, low=95.0, direction="bullish")
    strat = _build_strategy(
        bias, obs=[ob],
        tracked_levels=[_high_target(120.0)],
    )
    ts = _ts(9, 30)
    # Bar with low 80 (17pt below proximal — way past PROXIMITY_PTS=5).
    five = pd.DataFrame(
        {"open": [82], "high": [85], "low": [80], "close": [82], "volume": [500]},
        index=pd.DatetimeIndex([ts], tz="US/Central"),
    )
    sig = strat.evaluate(_make_1min(ts, close=82.0), five)
    assert sig is None
    assert strat.last_rejection["reason"] == "past_proximal"


# ─── Tests: stop sizing caps ─────────────────────────────────────────────────


def test_stop_min_floor_15pts():
    """Tight 5min OB (only 5pt) — stop should be forced to MIN 15pt floor."""
    bias = _bias(daily="bullish", pd_zone="discount")
    # OB proximal=100, distal=95. Swing low close to entry → would be tiny stop.
    ob = _build_ob(_ts(8, 50), high=100.0, low=95.0, direction="bullish")
    swing = _build_swing_low(price=99.0, ts=_ts(8, 55))  # only 1pt below entry
    strat = _build_strategy(
        bias, obs=[ob],
        swing_lows=[swing],
        tracked_levels=[_high_target(150.0)],
    )
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is not None, f"expected fire; rejected: {strat.last_rejection}"
    # entry = 100 + 0.25 tick = 100.25
    # MIN cap forces stop = entry - 15 = 85.25
    assert sig.entry_price == pytest.approx(100.25, abs=0.01)
    stop_distance = sig.entry_price - sig.stop_price
    assert stop_distance == pytest.approx(15.0, abs=0.01), (
        f"expected MIN floor 15pt, got {stop_distance}"
    )


def test_stop_max_ceiling_80pts():
    """Far swing low (>80pt) — stop should be capped at 80pt MAX."""
    bias = _bias(daily="bullish", pd_zone="discount")
    ob = _build_ob(_ts(8, 50), high=100.0, low=95.0, direction="bullish")
    # Swing low at 0 — would be 100pt below entry → capped to 80pt
    swing = _build_swing_low(price=0.0, ts=_ts(8, 55))
    strat = _build_strategy(
        bias, obs=[ob],
        swing_lows=[swing],
        tracked_levels=[_high_target(200.0)],
    )
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is not None, f"expected fire; rejected: {strat.last_rejection}"
    stop_distance = sig.entry_price - sig.stop_price
    assert stop_distance == pytest.approx(80.0, abs=0.01), (
        f"expected MAX cap 80pt, got {stop_distance}"
    )


def test_stop_structural_within_caps():
    """Swing low at reasonable distance (40pt) → use structural directly."""
    bias = _bias(daily="bullish", pd_zone="discount")
    ob = _build_ob(_ts(8, 50), high=100.0, low=95.0, direction="bullish")
    swing = _build_swing_low(price=60.0, ts=_ts(8, 55))  # 40pt below entry
    strat = _build_strategy(
        bias, obs=[ob],
        swing_lows=[swing],
        tracked_levels=[_high_target(150.0)],
    )
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is not None
    # entry 100.25, stop = swing 60 - 0.25 tick = 59.75 → 40.5pt
    stop_distance = sig.entry_price - sig.stop_price
    assert 40.0 < stop_distance < 41.0, (
        f"expected ~40.5pt structural, got {stop_distance}"
    )


# ─── Tests: lifecycle ─────────────────────────────────────────────────────────


def test_max_trades_per_zone():
    """After MAX_TRADES_PER_ZONE fires, further evals reject."""
    bias = _bias(daily="bullish", pd_zone="discount")
    ob = _build_ob(_ts(8, 50), high=100.0, low=95.0, direction="bullish")
    swing = _build_swing_low(price=70.0, ts=_ts(8, 55))
    strat = _build_strategy(
        bias, obs=[ob],
        swing_lows=[swing],
        tracked_levels=[_high_target(150.0)],
    )
    # Force the cap to 1 for this test (default is 5)
    strat.MAX_TRADES_PER_ZONE = 1

    # First fire — should succeed
    ts1 = _ts(9, 30)
    sig1 = strat.evaluate(_make_1min(ts1, close=100.0), _make_5min(ts1, close=100.0))
    assert sig1 is not None

    # Second eval — must reject due to max trades
    ts2 = _ts(9, 31)
    sig2 = strat.evaluate(_make_1min(ts2, close=100.0), _make_5min(ts2, close=100.0))
    assert sig2 is None
    assert strat.last_rejection["reason"] == "max_trades_per_zone"


def test_same_setup_cooldown_after_loss():
    """notify_trade_closed with PnL < 0 arms the cooldown for SAME entry."""
    bias = _bias(daily="bullish", pd_zone="discount")
    ob = _build_ob(_ts(8, 50), high=100.0, low=95.0, direction="bullish")
    swing = _build_swing_low(price=70.0, ts=_ts(8, 55))
    strat = _build_strategy(
        bias, obs=[ob],
        swing_lows=[swing],
        tracked_levels=[_high_target(150.0)],
    )

    # Simulate a stopped-out trade in rth at entry 100.25
    strat.notify_trade_closed({
        "pnl": -250.0,
        "entry_price": 100.25,
        "exit_time": _ts(9, 0).isoformat(),
        "kill_zone": "rth",
    })
    # Reset trade counter so we don't hit max_trades_per_zone first
    strat._trades_by_zone["rth"] = 0

    # Next eval with same entry within cooldown → should reject
    ts = _ts(9, 30)
    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is None
    assert strat.last_rejection["reason"] == "same_setup_cooldown"


def test_past_cancel_time_rejects():
    """Last 10 min before hard close — silent reject."""
    bias = _bias(daily="bullish", pd_zone="discount")
    ob = _build_ob(_ts(11, 30), high=100.0, low=95.0, direction="bullish")
    swing = _build_swing_low(price=70.0, ts=_ts(11, 30))
    strat = _build_strategy(
        bias, obs=[ob],
        swing_lows=[swing],
        tracked_levels=[_high_target(150.0)],
    )
    # Hard close at 15:00 CT, cancel at 14:50 → 14:55 should reject
    ts = _ts(14, 55)
    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is None
    # Counter should reflect past_cancel_time
    assert strat.reject_counters["past_cancel_time"] >= 1


# ─── Tests: happy path fires ─────────────────────────────────────────────────


def test_long_fires_full_setup():
    """Bullish daily + discount + 5min bull OB + price at proximal → FIRE long."""
    bias = _bias(daily="bullish", pd_zone="discount")
    # OB proximal=100, distal=95
    ob = _build_ob(_ts(8, 50), high=100.0, low=95.0, direction="bullish")
    # Swing low at 80 → 20pt below entry, structural
    swing = _build_swing_low(price=80.0, ts=_ts(8, 55))
    strat = _build_strategy(
        bias, obs=[ob],
        swing_lows=[swing],
        tracked_levels=[_high_target(140.0, "PDH")],
    )
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is not None, f"expected fire; rejected: {strat.last_rejection}"
    assert sig.strategy == "htf_continuation"
    assert sig.direction == "long"
    assert sig.entry_price == pytest.approx(100.25, abs=0.01)
    assert sig.stop_price == pytest.approx(79.75, abs=0.01)  # swing - 1tick
    assert sig.target_price == 140.0
    assert sig.kill_zone == "rth"
    assert sig.contracts >= 1


def test_short_fires_full_setup_mirror():
    """Bearish daily + premium + 5min bear OB + price at proximal → FIRE short."""
    bias = _bias(daily="bearish", pd_zone="premium")
    # Bearish OB: proximal = low=95 (closest to price coming up)
    ob = _build_ob(_ts(8, 50), high=100.0, low=95.0, direction="bearish")
    # Swing high at 115 → 20pt above entry
    swing = _build_swing_high(price=115.0, ts=_ts(8, 55))
    strat = _build_strategy(
        bias, obs=[ob],
        swing_highs=[swing],
        tracked_levels=[_low_target(60.0, "PDL")],
    )
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=95.0), _make_5min(ts, close=95.0))
    assert sig is not None, f"expected fire; rejected: {strat.last_rejection}"
    assert sig.strategy == "htf_continuation"
    assert sig.direction == "short"
    assert sig.entry_price == pytest.approx(94.75, abs=0.01)
    assert sig.stop_price == pytest.approx(115.25, abs=0.01)  # swing + 1tick
    assert sig.target_price == 60.0


def test_fvg_fallback_when_no_ob():
    """No 5min OB but a 5min bullish FVG exists → strategy uses FVG."""
    bias = _bias(daily="bullish", pd_zone="discount")
    fvg = FVG(
        top=100.0, bottom=98.0,
        direction="bullish",
        timeframe="5min",
        candle_index=0,
        timestamp=_ts(8, 50),
        stop_reference=95.0,
    )
    swing = _build_swing_low(price=85.0, ts=_ts(8, 55))
    strat = _build_strategy(
        bias, obs=[], fvgs=[fvg],
        swing_lows=[swing],
        tracked_levels=[_high_target(150.0)],
    )
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is not None, f"expected fire; rejected: {strat.last_rejection}"
    assert sig.entry_price == pytest.approx(100.25, abs=0.01)


# ─── Tests: framework / target gates ─────────────────────────────────────────


def test_no_target_rejects():
    """OB + bias all OK but no target liquidity → reject."""
    bias = _bias(daily="bullish", pd_zone="discount")
    ob = _build_ob(_ts(8, 50), high=100.0, low=95.0, direction="bullish")
    swing = _build_swing_low(price=80.0, ts=_ts(8, 55))
    strat = _build_strategy(
        bias, obs=[ob], swing_lows=[swing],
        tracked_levels=[],   # no target
    )
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is None
    assert strat.last_rejection["reason"] == "no_liquidity_target"


def test_framework_too_short_rejects():
    """Target only 5pt away → below MIN_FRAMEWORK_PTS (10pt)."""
    bias = _bias(daily="bullish", pd_zone="discount")
    ob = _build_ob(_ts(8, 50), high=100.0, low=95.0, direction="bullish")
    swing = _build_swing_low(price=80.0, ts=_ts(8, 55))
    strat = _build_strategy(
        bias, obs=[ob], swing_lows=[swing],
        tracked_levels=[_high_target(105.0)],   # only ~5pt above entry
    )
    ts = _ts(9, 30)

    sig = strat.evaluate(_make_1min(ts, close=100.0), _make_5min(ts, close=100.0))
    assert sig is None
    assert strat.last_rejection["reason"] == "framework_lt_10pts"


# ─── Tests: lifecycle methods ────────────────────────────────────────────────


def test_reset_daily_clears_state():
    bias = _bias(daily="bullish", pd_zone="discount")
    strat = _build_strategy(bias)
    strat._trades_by_zone["ny_am"] = 1
    strat.trades_today = 1
    strat._last_evaluated_bar_ts = _ts(9, 30)

    strat.reset_daily()
    assert strat.trades_today == 0
    assert all(v == 0 for v in strat._trades_by_zone.values())
    assert strat._last_evaluated_bar_ts is None


def test_notify_trade_closed_winner_does_not_arm_cooldown():
    bias = _bias(daily="bullish", pd_zone="discount")
    strat = _build_strategy(bias)
    strat.notify_trade_closed({
        "pnl": 500.0,            # winner
        "entry_price": 100.25,
        "exit_time": _ts(9, 0).isoformat(),
        "kill_zone": "ny_am",
    })
    assert strat._last_stopped_entry_price is None
