"""
strategies/silver_bullet.py
============================
ICT Silver Bullet — 1min entry, 5min context, 1:2 RR.

Setup
-----
1. Time:           inside Silver Bullet kill zone (10:00 – 11:00 CT)
2. HTF bias:       Daily/Weekly aligned (not neutral)
3. 5min context:   recent MSS or BOS in HTF direction
4. 1min entry:     liquidity grab + FVG + Order Block + displacement
5. Confluence:     >= MIN_CONFLUENCE (7/20) — uses ConfluenceScorer
6. Cancel:         if timestamp >= 10:50 AM CT, skip (late in window)
7. Risk:           1:2 RR, $250 risk, max 1 trade per session

Entry / Stop / Target
---------------------
Long:
  entry  = OB.high (proximal of bullish OB — where price returns)
  stop   = OB.low  (distal of bullish OB)
  target = entry + 2 × actual_stop_points

Short (mirror):
  entry  = OB.low
  stop   = OB.high
  target = entry - 2 × actual_stop_points

Position sizing uses risk/position_sizer (floor + expand stop).
Position multiplier from risk_manager (SWC/VPIN soft overrides).

The detectors dict must contain populated detector instances:
  detectors = {
      'structure'      : MarketStructureDetector  (with 5min events),
      'fvg'            : FairValueGapDetector    (with 1min FVGs),
      'ob'             : OrderBlockDetector      (with 1min OBs),
      'displacement'   : DisplacementDetector    (with 1min displacements),
      'liquidity'      : LiquidityDetector       (instance),
      'confluence'     : ConfluenceScorer        (instance),
      'tracked_levels' : list[LiquidityLevel]    (recently-checked sweep candidates),
  }
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Callable
import datetime

import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from risk.position_sizer import calculate_position
from timeframes.htf_bias import BiasResult

logger = logging.getLogger(__name__)


def _ts_hm(ts) -> str:
    """Format a bar timestamp as HH:MM for EVAL log lines."""
    try:
        return ts.strftime("%H:%M")
    except AttributeError:
        return str(ts)

# Cancel if we're this close to the end of the kill zone (10 min before 11:00)
_CANCEL_HOUR = 10
_CANCEL_MINUTE = 50


@dataclass
class Signal:
    """Trade signal emitted by a strategy when a setup is found."""

    strategy: str
    symbol: str
    direction: str           # 'long' | 'short'
    entry_price: float
    stop_price: float
    target_price: float
    contracts: int
    confluence_score: int
    confluence_breakdown: dict = field(default_factory=dict)
    timestamp: pd.Timestamp = None
    kill_zone: str = ""

    def __repr__(self) -> str:
        return (
            f"Signal({self.strategy} {self.direction} {self.symbol} "
            f"entry={self.entry_price:.2f} stop={self.stop_price:.2f} "
            f"target={self.target_price:.2f} x{self.contracts} "
            f"score={self.confluence_score} kz={self.kill_zone})"
        )


class SilverBulletStrategy:
    """ICT Silver Bullet — 1min entry during 10:00–11:00 CT kill zone."""

    # Evaluates in both the London SB and NY SB windows.
    # Each kill zone has its own per-zone trade cap; daily total is the sum.
    KILL_ZONES = ("london_silver_bullet", "silver_bullet")
    MAX_TRADES_PER_ZONE = 1
    # Kept for backward compat — reported on the signal if active zone lookup misses.
    KILL_ZONE = "silver_bullet"
    ENTRY_TF = "1min"
    CONTEXT_TF = "5min"
    RISK_REWARD = 2.0
    MAX_TRADES = MAX_TRADES_PER_ZONE * 2  # 2 total (london_sb + ny_sb)
    SYMBOL = "MNQ"

    # Sweep type sets per direction
    _LONG_SWEEP_TYPES = {"SSL", "PDL", "PWL", "equal_lows"}
    _SHORT_SWEEP_TYPES = {"BSL", "PDH", "PWH", "equal_highs"}

    def __init__(
        self,
        detectors: dict,
        risk_manager,
        session_manager,
        htf_bias_fn: Callable[[float], BiasResult],
    ):
        """
        Parameters
        ----------
        detectors      : dict — populated detector instances + 'tracked_levels'
        risk_manager   : RiskManager — daily P&L state + overrides
        session_manager: SessionManager — kill zone checks
        htf_bias_fn    : callable(price) -> BiasResult — HTF bias provider
        """
        self.detectors = detectors
        self.risk = risk_manager
        self.session = session_manager
        self.htf_bias_fn = htf_bias_fn
        self.trades_today: int = 0
        self._trades_by_zone: dict[str, int] = {z: 0 for z in self.KILL_ZONES}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def evaluate(
        self,
        candles_1min: pd.DataFrame,
        candles_5min: pd.DataFrame,
    ) -> Optional[Signal]:
        """
        Run a full strategy evaluation on the latest 1min candle.

        Returns Signal if all conditions met, None otherwise.
        """
        # ── 1. Pre-conditions ──────────────────────────────────────────
        if candles_1min.empty or candles_5min.empty:
            return None

        last_1 = candles_1min.iloc[-1]
        ts = candles_1min.index[-1]
        last_close = float(last_1["close"])

        active_zone = next(
            (kz for kz in self.KILL_ZONES if self.session.is_kill_zone(ts, kz)),
            None,
        )
        if active_zone is None:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=outside_kz",
                _ts_hm(ts),
            )
            return None

        # Cancel check: no new entries at 10:50 CT or later (too close to close)
        ts_time = ts.time() if hasattr(ts, "time") else ts.to_pydatetime().time()
        if ts_time >= datetime.time(_CANCEL_HOUR, _CANCEL_MINUTE):
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=past_cancel_time",
                _ts_hm(ts),
            )
            return None

        if self.risk.check_hard_close(ts):
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=past_hard_close",
                _ts_hm(ts),
            )
            return None

        allowed, reason = self.risk.can_trade()
        if not allowed:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=risk_blocked (%s)",
                _ts_hm(ts), reason,
            )
            return None

        if self._trades_by_zone.get(active_zone, 0) >= self.MAX_TRADES_PER_ZONE:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=max_trades",
                _ts_hm(ts),
            )
            return None

        # ── 2. HTF bias ────────────────────────────────────────────────
        bias = self.htf_bias_fn(last_close)
        if bias.direction == "neutral":
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=htf_neutral",
                _ts_hm(ts),
            )
            return None

        bias_dir = bias.direction                                # 'bullish' | 'bearish'
        direction = "long" if bias_dir == "bullish" else "short"

        # ── 3. 5min context: MSS or BOS in HTF direction ───────────────
        structure_events = self.detectors["structure"].get_events(timeframe="5min")
        aligned = [
            e for e in structure_events
            if e.type in ("MSS", "BOS") and e.direction == bias_dir
        ]
        if not aligned:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=no_valid_setup (no_5min_struct)",
                _ts_hm(ts),
            )
            return None
        last_struct = aligned[-1]

        # ── 4. 1min entry: FVG + OB + Displacement + Sweep ─────────────
        fvgs = self.detectors["fvg"].get_active(
            timeframe="1min", direction=bias_dir,
        )
        if not fvgs:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=no_valid_setup (no_fvg)",
                _ts_hm(ts),
            )
            return None

        obs = self.detectors["ob"].get_active(
            timeframe="1min", direction=bias_dir,
        )
        if not obs:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=no_valid_setup (no_ob)",
                _ts_hm(ts),
            )
            return None
        last_ob = obs[-1]

        displacements = self.detectors["displacement"].get_recent(
            n=5, timeframe="1min", direction=bias_dir,
        )
        if not displacements:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=no_valid_setup (no_displacement)",
                _ts_hm(ts),
            )
            return None

        # Sweep — pulled from tracked_levels (engine maintains; tests inject)
        tracked_levels = self.detectors.get("tracked_levels", [])
        valid_sweep_types = (
            self._LONG_SWEEP_TYPES if direction == "long" else self._SHORT_SWEEP_TYPES
        )
        sweeps = [
            lvl for lvl in tracked_levels
            if lvl.swept and lvl.type in valid_sweep_types
        ]
        if not sweeps:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=no_valid_setup (no_sweep)",
                _ts_hm(ts),
            )
            return None
        sweep = sweeps[-1]

        # ── 5. Entry, Stop, Target (using OB edges) ────────────────────
        if direction == "long":
            entry_price = float(last_ob.high)        # proximal
            stop_price = float(last_ob.low)          # distal
        else:
            entry_price = float(last_ob.low)         # proximal of bearish OB
            stop_price = float(last_ob.high)         # distal

        stop_points = abs(entry_price - stop_price)
        if stop_points <= 0:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=N/A, signal=reject, reason=no_valid_setup (zero_stop)",
                _ts_hm(ts),
            )
            return None

        # Position size with floor + expand stop
        pos = calculate_position(
            stop_points=stop_points,
            risk=config.RISK_PER_TRADE,
            point_value=2.0,                          # MNQ
            max_contracts=config.MAX_CONTRACTS,
        )

        # Apply soft override (SWC/VPIN reductions)
        contracts = max(1, int(pos.contracts * self.risk.position_multiplier))

        # Target at 1:2 RR using the EXPANDED stop (preserves dollar risk)
        if direction == "long":
            target_price = entry_price + (self.RISK_REWARD * pos.actual_stop_points)
        else:
            target_price = entry_price - (self.RISK_REWARD * pos.actual_stop_points)

        # ── 6. Confluence scoring ──────────────────────────────────────
        conf = self.detectors["confluence"].score(
            direction=direction,
            entry_price=entry_price,
            target_price=target_price,
            sweep=sweep,
            fvgs=fvgs,
            obs=obs,
            structure_event=last_struct,
            displacement=displacements[0],
            kill_zone=True,
            htf_bias=bias,
            key_levels=tracked_levels,
        )

        # Effective min confluence respects SWC/VPIN bumps
        min_required = self.risk.effective_min_confluence
        if conf.total_score < min_required:
            logger.info(
                "EVAL silver_bullet [%s]: confluence=%d/20, signal=reject, reason=conf_below_min (%d<%d)",
                _ts_hm(ts), conf.total_score, conf.total_score, min_required,
            )
            return None

        # ── 7. Build signal ────────────────────────────────────────────
        signal = Signal(
            strategy="silver_bullet",
            symbol=self.SYMBOL,
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            contracts=contracts,
            confluence_score=conf.total_score,
            confluence_breakdown=dict(conf.breakdown),
            timestamp=ts,
            kill_zone=active_zone,
        )

        self.trades_today += 1
        self._trades_by_zone[active_zone] = self._trades_by_zone.get(active_zone, 0) + 1
        logger.info(
            "EVAL silver_bullet [%s]: confluence=%d/20, signal=fire, reason=fired | %s",
            _ts_hm(ts), signal.confluence_score, signal,
        )
        return signal

    def reset_daily(self) -> None:
        """Reset trade counters — call at session start."""
        self.trades_today = 0
        self._trades_by_zone = {z: 0 for z in self.KILL_ZONES}
