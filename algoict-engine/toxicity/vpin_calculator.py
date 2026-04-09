"""
toxicity/vpin_calculator.py
============================
Volume-Synchronized Probability of Informed Trading (VPIN).

Easley, Lopez de Prado, O'Hara (2010).

Formula (per rolling window of N buckets)
-----------------------------------------
    VPIN = (1 / N) * Sum_i |V_buy_i - V_sell_i| / V

Where:
    N         = number of buckets in the rolling window (default 50)
    V         = bucket size (daily_volume / N)
    V_buy_i   = BVC-classified buy volume in bucket i
    V_sell_i  = BVC-classified sell volume in bucket i

Note:
    |V_buy_i - V_sell_i| is the bucket's "imbalance", and since each bucket
    has volume == V, this is equivalent to:
        VPIN = mean_i(imbalance_i) / V
             = mean_i(|buy_fraction_i - sell_fraction_i|)

This is a pure number in [0, 1].

Toxicity bands (from the skill)
-------------------------------
    < 0.35      -> calm
    0.35 - 0.45 -> normal
    0.45 - 0.55 -> elevated
    0.55 - 0.70 -> high
    > 0.70      -> extreme

Usage
-----
    from toxicity.volume_buckets import VolumeBucketizer
    from toxicity.bulk_classifier import BVCClassifier
    from toxicity.vpin_calculator import VPINCalculator

    bucketizer = VolumeBucketizer(daily_volume=500_000)
    classifier = BVCClassifier()
    calculator = VPINCalculator()

    for bucket in bucketizer.process_dataframe(df_1min):
        classified = classifier.classify(bucket)
        reading = calculator.add(classified)
        if reading:
            print(reading)

    # Or one-shot:
    readings = calculator.process_series(df_1min, daily_volume=500_000)
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .volume_buckets import VolumeBucket, VolumeBucketizer
from .bulk_classifier import BVCClassifier, ClassifiedBucket

logger = logging.getLogger(__name__)


# Standard rolling window
DEFAULT_NUM_BUCKETS = 50


# Toxicity thresholds (per skill)
CALM_MAX = 0.35
NORMAL_MAX = 0.45
ELEVATED_MAX = 0.55
HIGH_MAX = 0.70
# > HIGH_MAX -> extreme


# ---------------------------------------------------------------------------
# Toxicity classification
# ---------------------------------------------------------------------------

def classify_toxicity(vpin: float) -> str:
    """
    Map a VPIN value to one of: calm, normal, elevated, high, extreme.

    Boundaries follow the skill:
        < 0.35  -> calm
        0.35-0.45 -> normal
        0.45-0.55 -> elevated
        0.55-0.70 -> high
        > 0.70  -> extreme
    """
    if vpin > HIGH_MAX:
        return "extreme"
    if vpin > ELEVATED_MAX:
        return "high"
    if vpin > NORMAL_MAX:
        return "elevated"
    if vpin > CALM_MAX:
        return "normal"
    return "calm"


def is_extreme(vpin: float) -> bool:
    """True if VPIN is in the extreme zone (> 0.70)."""
    return vpin > HIGH_MAX


def is_high_or_worse(vpin: float) -> bool:
    """True if VPIN is in the high or extreme zone (> 0.55)."""
    return vpin > ELEVATED_MAX


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class VPINReading:
    """A single VPIN measurement produced when the rolling window is full."""
    vpin: float
    toxicity: str
    timestamp: pd.Timestamp
    bucket_count: int
    bucket_size: float

    def __repr__(self) -> str:
        return (
            f"VPINReading(vpin={self.vpin:.3f} [{self.toxicity}] "
            f"@ {self.timestamp} n={self.bucket_count})"
        )


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

class VPINCalculator:
    """
    Rolling VPIN calculator.

    The calculator stores the last `num_buckets` classified buckets and
    computes VPIN on every new addition once the window is full.
    """

    def __init__(
        self,
        num_buckets: int = DEFAULT_NUM_BUCKETS,
        bucket_size: Optional[float] = None,
    ):
        if num_buckets <= 0:
            raise ValueError(f"num_buckets must be positive, got {num_buckets}")
        self.num_buckets = int(num_buckets)
        self.bucket_size = float(bucket_size) if bucket_size else None
        self._buckets: deque[ClassifiedBucket] = deque(maxlen=self.num_buckets)
        self._history: list[VPINReading] = []

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def ready(self) -> bool:
        """True once the rolling window has `num_buckets` samples."""
        return len(self._buckets) >= self.num_buckets

    @property
    def latest(self) -> Optional[VPINReading]:
        """Return the most recent VPIN reading, or None."""
        return self._history[-1] if self._history else None

    def add(self, classified: ClassifiedBucket) -> Optional[VPINReading]:
        """
        Add one classified bucket. Returns a new VPINReading once the
        rolling window is full, otherwise None.
        """
        self._buckets.append(classified)

        # Set bucket_size from the first bucket if not provided
        if self.bucket_size is None:
            self.bucket_size = float(classified.total_volume)

        if not self.ready:
            return None

        vpin = self._compute_vpin()
        toxicity = classify_toxicity(vpin)
        reading = VPINReading(
            vpin=vpin,
            toxicity=toxicity,
            timestamp=classified.bucket.end_time,
            bucket_count=len(self._buckets),
            bucket_size=self.bucket_size,
        )
        self._history.append(reading)
        return reading

    def history_df(self) -> pd.DataFrame:
        """
        Return all historical readings as a DataFrame indexed by timestamp.

        Columns: vpin, toxicity, bucket_count
        """
        if not self._history:
            return pd.DataFrame(columns=["vpin", "toxicity", "bucket_count"])
        rows = [
            {
                "timestamp": r.timestamp,
                "vpin": r.vpin,
                "toxicity": r.toxicity,
                "bucket_count": r.bucket_count,
            }
            for r in self._history
        ]
        return pd.DataFrame(rows).set_index("timestamp").sort_index()

    def reset(self) -> None:
        """Clear all state."""
        self._buckets.clear()
        self._history.clear()

    # ------------------------------------------------------------------ #
    # One-shot pipeline                                                    #
    # ------------------------------------------------------------------ #

    def process_series(
        self,
        df_1min: pd.DataFrame,
        daily_volume: float = 500_000,
        buckets_per_day: int = 50,
    ) -> pd.DataFrame:
        """
        End-to-end: take a 1-min OHLCV DataFrame, compute all VPIN readings.

        Parameters
        ----------
        df_1min         : 1-min OHLCV DataFrame
        daily_volume    : expected daily volume (used to size buckets)
        buckets_per_day : how many buckets fit in a typical day's volume.
                          Independent from self.num_buckets (the rolling
                          window size used for VPIN).

        Returns
        -------
        pd.DataFrame indexed by timestamp with columns: vpin, toxicity, bucket_count.
        """
        self.reset()

        bucketizer = VolumeBucketizer(
            daily_volume=daily_volume,
            num_buckets=buckets_per_day,
        )
        classifier = BVCClassifier()

        for bucket in bucketizer.process_dataframe(df_1min):
            classified = classifier.classify(bucket)
            self.add(classified)

        return self.history_df()

    # ------------------------------------------------------------------ #
    # Core math                                                            #
    # ------------------------------------------------------------------ #

    def _compute_vpin(self) -> float:
        """
        VPIN = (1/N) * Sum |V_buy - V_sell| / V

        Since each bucket's imbalance is already |V_buy - V_sell| and
        each bucket has volume ~= V, this simplifies to:
            mean(imbalance_i) / V
        """
        imbalances = [b.imbalance for b in self._buckets]
        total_imbalance = float(np.sum(imbalances))

        # Use self.bucket_size as V (set from the first bucket)
        V = float(self.bucket_size) if self.bucket_size else 1.0
        N = float(self.num_buckets)

        vpin = total_imbalance / (N * V) if V > 0 else 0.0
        return float(np.clip(vpin, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Trade tagging + win-rate analysis
# ---------------------------------------------------------------------------

def tag_trades_with_vpin(
    trades: list,
    vpin_series: pd.DataFrame,
) -> list[dict]:
    """
    Tag each trade with the VPIN reading active at its entry_time.

    For each trade we find the latest VPIN reading whose timestamp is
    <= trade.entry_time.

    Parameters
    ----------
    trades      : list[Trade] from a BacktestResult
    vpin_series : DataFrame from VPINCalculator.history_df()

    Returns
    -------
    list[dict] — one dict per trade with keys:
        entry_time, pnl, confluence_score, vpin, toxicity
    """
    if vpin_series.empty:
        return [
            {
                "entry_time": t.entry_time,
                "pnl": t.pnl,
                "confluence_score": t.confluence_score,
                "vpin": None,
                "toxicity": None,
            }
            for t in trades
        ]

    vpin_series = vpin_series.sort_index()
    idx = vpin_series.index

    tagged: list[dict] = []
    for t in trades:
        entry = t.entry_time
        # Find last reading <= entry
        pos = idx.searchsorted(entry, side="right") - 1
        if pos < 0:
            v, tox = None, None
        else:
            row = vpin_series.iloc[pos]
            v = float(row["vpin"])
            tox = str(row["toxicity"])
        tagged.append({
            "entry_time": entry,
            "pnl": float(t.pnl),
            "confluence_score": int(t.confluence_score),
            "vpin": v,
            "toxicity": tox,
        })
    return tagged


@dataclass
class VPINImpactReport:
    """Win-rate + P&L comparison across VPIN bands."""
    total_trades: int
    trades_with_vpin: int
    by_toxicity: dict              # toxicity -> {count, wins, win_rate, total_pnl}
    high_vpin_trades: int          # VPIN > 0.55
    high_vpin_pnl: float
    high_vpin_win_rate: float
    low_vpin_trades: int           # VPIN <= 0.45
    low_vpin_pnl: float
    low_vpin_win_rate: float
    extreme_vpin_trades: int       # VPIN > 0.70
    extreme_vpin_pnl: float        # $ lost (or gained) in extreme periods


def analyze_vpin_impact(tagged_trades: list[dict]) -> VPINImpactReport:
    """
    Compute the impact of VPIN on trade performance.
    """
    total = len(tagged_trades)
    with_vpin = [t for t in tagged_trades if t["vpin"] is not None]

    by_tox: dict[str, dict] = {}
    for level in ("calm", "normal", "elevated", "high", "extreme"):
        group = [t for t in with_vpin if t["toxicity"] == level]
        wins = sum(1 for t in group if t["pnl"] > 0)
        total_pnl = sum(t["pnl"] for t in group)
        win_rate = wins / len(group) if group else 0.0
        by_tox[level] = {
            "count": len(group),
            "wins": wins,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
        }

    high_group = [t for t in with_vpin if (t["vpin"] or 0) > 0.55]
    low_group = [t for t in with_vpin if (t["vpin"] or 0) <= 0.45]
    extreme_group = [t for t in with_vpin if (t["vpin"] or 0) > 0.70]

    def _wr(g): return (sum(1 for t in g if t["pnl"] > 0) / len(g)) if g else 0.0
    def _pnl(g): return sum(t["pnl"] for t in g)

    return VPINImpactReport(
        total_trades=total,
        trades_with_vpin=len(with_vpin),
        by_toxicity=by_tox,
        high_vpin_trades=len(high_group),
        high_vpin_pnl=_pnl(high_group),
        high_vpin_win_rate=_wr(high_group),
        low_vpin_trades=len(low_group),
        low_vpin_pnl=_pnl(low_group),
        low_vpin_win_rate=_wr(low_group),
        extreme_vpin_trades=len(extreme_group),
        extreme_vpin_pnl=_pnl(extreme_group),
    )
