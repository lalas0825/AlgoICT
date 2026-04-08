"""
detectors/market_structure.py
==============================
ICT Market Structure detector — tracks BOS, CHoCH, and MSS events as a
state machine, per timeframe, evolving over time.

Definitions
-----------
BOS  (Break of Structure): close beyond the most recent swing in the
                           direction of the current trend (continuation).
CHoCH (Change of Character): close beyond the most recent swing AGAINST
                             the current trend (first sign of reversal).
MSS  (Market Structure Shift): a CHoCH confirmed by follow-through —
                               the next candle's close continues in the
                               new direction beyond the CHoCH candle's
                               close. State officially flips on MSS.

Per-timeframe state machine
---------------------------
    neutral ── BOS up   ──> bullish
            ── BOS down ──> bearish

    bullish ── BOS up   ──> bullish (continuation)
            ── CHoCH down ──> bullish + pending CHoCH
                              └── follow-through ──> MSS bearish ──> bearish

    bearish ── BOS down ──> bearish (continuation)
            ── CHoCH up   ──> bearish + pending CHoCH
                              └── follow-through ──> MSS bullish ──> bullish

The detector consumes a `SwingPointDetector` populated with the same
timeframe's swing history.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detectors.swing_points import SwingPoint, SwingPointDetector

logger = logging.getLogger(__name__)


@dataclass
class StructureEvent:
    """A market structure event detected on a given timeframe."""

    type: str          # 'BOS' | 'CHoCH' | 'MSS'
    direction: str     # 'bullish' | 'bearish'
    level: float       # the swing level that was broken
    timestamp: pd.Timestamp
    timeframe: str

    def __repr__(self) -> str:
        return (
            f"StructureEvent({self.type} {self.direction} @ {self.level:.2f}, "
            f"tf={self.timeframe}, ts={self.timestamp})"
        )


class MarketStructureDetector:
    """
    Tracks BOS / CHoCH / MSS evolution per timeframe.

    Each timeframe runs an independent state machine — call ``update()``
    once per new candle on each timeframe you care about.
    """

    def __init__(self):
        self.state: dict[str, str] = {}
        self.events: list[StructureEvent] = []

        # Per-tf pending CHoCH (event + bar close, for follow-through check)
        self._pending_choch: dict[str, Optional[StructureEvent]] = {}
        self._pending_choch_close: dict[str, float] = {}

        # Per-tf set of swing timestamps already consumed by an event
        self._consumed_high_ts: dict[str, set] = {}
        self._consumed_low_ts: dict[str, set] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def update(
        self,
        candles: pd.DataFrame,
        swing_points: SwingPointDetector,
        timeframe: str,
    ) -> list[StructureEvent]:
        """
        Process the latest candle and emit any new structure events.

        Parameters
        ----------
        candles      : pd.DataFrame — full OHLCV history up to current bar (CT tz)
        swing_points : SwingPointDetector — already populated for *timeframe*
        timeframe    : str — e.g. '5min', '15min'

        Returns
        -------
        list[StructureEvent] — events newly emitted on this update
        """
        if candles.empty:
            return []

        last_close = float(candles.iloc[-1]["close"])
        last_ts = candles.index[-1]

        new_events: list[StructureEvent] = []

        consumed_h = self._consumed_high_ts.setdefault(timeframe, set())
        consumed_l = self._consumed_low_ts.setdefault(timeframe, set())

        # ── Step 1: try to confirm a pending CHoCH ────────────────────
        pending = self._pending_choch.get(timeframe)
        if pending is not None:
            choch_close = self._pending_choch_close[timeframe]

            confirmed = False
            if pending.direction == "bearish" and last_close < choch_close:
                mss = self._make_event(
                    "MSS", "bearish", pending.level, last_ts, timeframe,
                )
                new_events.append(mss)
                self.state[timeframe] = "bearish"
                confirmed = True
            elif pending.direction == "bullish" and last_close > choch_close:
                mss = self._make_event(
                    "MSS", "bullish", pending.level, last_ts, timeframe,
                )
                new_events.append(mss)
                self.state[timeframe] = "bullish"
                confirmed = True

            if confirmed:
                self._pending_choch[timeframe] = None
                self._pending_choch_close.pop(timeframe, None)
                self.events.extend(new_events)
                return new_events

        # ── Step 2: most recent unconsumed swings strictly before now ─
        latest_sh = self._latest_unconsumed_swing(
            swing_points, "high", timeframe, last_ts, consumed_h,
        )
        latest_sl = self._latest_unconsumed_swing(
            swing_points, "low", timeframe, last_ts, consumed_l,
        )

        broke_high = latest_sh is not None and last_close > latest_sh.price
        broke_low = latest_sl is not None and last_close < latest_sl.price

        state = self.state.get(timeframe, "neutral")

        # ── Step 3: state machine ─────────────────────────────────────
        if state == "neutral":
            if broke_high:
                ev = self._make_event(
                    "BOS", "bullish", latest_sh.price, last_ts, timeframe,
                )
                new_events.append(ev)
                self.state[timeframe] = "bullish"
                consumed_h.add(latest_sh.timestamp)
            elif broke_low:
                ev = self._make_event(
                    "BOS", "bearish", latest_sl.price, last_ts, timeframe,
                )
                new_events.append(ev)
                self.state[timeframe] = "bearish"
                consumed_l.add(latest_sl.timestamp)

        elif state == "bullish":
            if broke_high:
                ev = self._make_event(
                    "BOS", "bullish", latest_sh.price, last_ts, timeframe,
                )
                new_events.append(ev)
                consumed_h.add(latest_sh.timestamp)
            elif broke_low:
                ev = self._make_event(
                    "CHoCH", "bearish", latest_sl.price, last_ts, timeframe,
                )
                new_events.append(ev)
                self._pending_choch[timeframe] = ev
                self._pending_choch_close[timeframe] = last_close
                consumed_l.add(latest_sl.timestamp)

        elif state == "bearish":
            if broke_low:
                ev = self._make_event(
                    "BOS", "bearish", latest_sl.price, last_ts, timeframe,
                )
                new_events.append(ev)
                consumed_l.add(latest_sl.timestamp)
            elif broke_high:
                ev = self._make_event(
                    "CHoCH", "bullish", latest_sh.price, last_ts, timeframe,
                )
                new_events.append(ev)
                self._pending_choch[timeframe] = ev
                self._pending_choch_close[timeframe] = last_close
                consumed_h.add(latest_sh.timestamp)

        self.events.extend(new_events)
        return new_events

    def get_state(self, timeframe: str) -> str:
        """Return current trend state for *timeframe* (defaults to 'neutral')."""
        return self.state.get(timeframe, "neutral")

    def get_events(
        self,
        timeframe: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> list[StructureEvent]:
        """Return all emitted events, optionally filtered by tf and/or type."""
        result = list(self.events)
        if timeframe is not None:
            result = [e for e in result if e.timeframe == timeframe]
        if type_filter is not None:
            result = [e for e in result if e.type == type_filter]
        return result

    def reset(self) -> None:
        """Clear all state — useful between sessions or backtests."""
        self.state.clear()
        self.events.clear()
        self._pending_choch.clear()
        self._pending_choch_close.clear()
        self._consumed_high_ts.clear()
        self._consumed_low_ts.clear()

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _latest_unconsumed_swing(
        swing_points: SwingPointDetector,
        swing_type: str,
        timeframe: str,
        before_ts: pd.Timestamp,
        consumed_ts: set,
    ) -> Optional[SwingPoint]:
        """
        Most recent swing of *swing_type* on *timeframe* whose timestamp is
        strictly less than *before_ts* and not yet consumed.
        """
        candidates = [
            sp for sp in swing_points.swing_points
            if sp.type == swing_type
            and sp.timeframe == timeframe
            and sp.timestamp < before_ts
            and sp.timestamp not in consumed_ts
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda sp: sp.timestamp)

    @staticmethod
    def _make_event(
        ev_type: str,
        direction: str,
        level: float,
        ts: pd.Timestamp,
        tf: str,
    ) -> StructureEvent:
        ev = StructureEvent(
            type=ev_type,
            direction=direction,
            level=level,
            timestamp=ts,
            timeframe=tf,
        )
        logger.debug("Structure event: %s", ev)
        return ev
