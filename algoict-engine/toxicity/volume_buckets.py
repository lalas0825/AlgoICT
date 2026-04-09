"""
toxicity/volume_buckets.py
===========================
Volume-time bucketing for VPIN.

VPIN is computed in "volume time" — every time a fixed number of contracts
have been traded, we close a bucket. With daily_volume=500,000 and the
standard 50 buckets per window, each bucket holds 10,000 contracts.

For live trading we'd accumulate ticks from the WebSocket. For backtesting
we accumulate 1-min bars (the skill explicitly states this is an acceptable
approximation). A single 1-min bar may over-fill the current bucket; we
close the current bucket at the threshold and carry the overflow into the
next bucket using linear allocation.

Bucket contents
---------------
Each completed bucket has:
  - volume:       total contracts (always == bucket_size, except possibly the
                  final bucket which may be partial)
  - start_price:  price at the first contract in the bucket
  - end_price:    price at the last contract in the bucket
  - price_change: end_price - start_price
  - start_time:   timestamp of the first bar that contributed
  - end_time:     timestamp of the last bar that contributed
  - n_bars:       how many 1-min bars contributed

The BVC classifier (bulk_classifier.py) consumes these buckets.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Standard: 50 buckets per VPIN window
DEFAULT_NUM_BUCKETS = 50


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class VolumeBucket:
    """A completed volume bucket."""
    volume: float                 # total contracts in this bucket
    start_price: float
    end_price: float
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    n_bars: int = 1               # number of 1-min bars that contributed

    @property
    def price_change(self) -> float:
        return self.end_price - self.start_price

    def __repr__(self) -> str:
        return (
            f"VolumeBucket(vol={self.volume:.0f} "
            f"{self.start_price:.2f}->{self.end_price:.2f} "
            f"dp={self.price_change:+.2f} bars={self.n_bars})"
        )


# ---------------------------------------------------------------------------
# Bucketizer
# ---------------------------------------------------------------------------

class VolumeBucketizer:
    """
    Accumulates 1-min OHLCV bars into fixed-volume buckets.

    Usage
    -----
        bucketizer = VolumeBucketizer(daily_volume=500_000, num_buckets=50)
        # bucket_size = 500_000 / 50 = 10_000

        # Feed bars one at a time:
        for ts, row in df_1min.iterrows():
            new_buckets = bucketizer.add_bar(
                ts, row["open"], row["close"], row["volume"],
            )
            for b in new_buckets:
                print(b)

        # Or in one call:
        all_buckets = bucketizer.process_dataframe(df_1min)
    """

    def __init__(
        self,
        daily_volume: float = 500_000,
        num_buckets: int = DEFAULT_NUM_BUCKETS,
    ):
        if daily_volume <= 0:
            raise ValueError(f"daily_volume must be positive, got {daily_volume}")
        if num_buckets <= 0:
            raise ValueError(f"num_buckets must be positive, got {num_buckets}")

        self.daily_volume = float(daily_volume)
        self.num_buckets = int(num_buckets)
        self.bucket_size = self.daily_volume / self.num_buckets

        # State for the in-progress bucket
        self._cur_volume: float = 0.0
        self._cur_start_price: Optional[float] = None
        self._cur_end_price: Optional[float] = None
        self._cur_start_time: Optional[pd.Timestamp] = None
        self._cur_end_time: Optional[pd.Timestamp] = None
        self._cur_n_bars: int = 0

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def add_bar(
        self,
        timestamp: pd.Timestamp,
        open_price: float,
        close_price: float,
        volume: float,
    ) -> list[VolumeBucket]:
        """
        Feed a single 1-min OHLC bar. May produce zero, one, or several
        completed buckets if the bar's volume spans multiple buckets.

        Returns
        -------
        list[VolumeBucket] — buckets completed by this bar (may be empty).
        """
        if volume <= 0:
            return []

        completed: list[VolumeBucket] = []
        remaining = float(volume)

        # Price interpolation inside the bar: linear from open -> close
        # proportional to cumulative volume.
        bar_price_span = close_price - open_price
        bar_volume = float(volume)
        consumed_in_bar = 0.0

        def price_at(consumed_fraction: float) -> float:
            return open_price + bar_price_span * consumed_fraction

        while remaining > 0:
            if self._cur_volume == 0:
                # Starting a fresh bucket at the current intra-bar price
                self._cur_start_price = price_at(consumed_in_bar / bar_volume)
                self._cur_start_time = timestamp
                self._cur_n_bars = 0

            # How much volume can still fit in the current bucket?
            capacity = self.bucket_size - self._cur_volume

            if remaining < capacity:
                # Bar fits entirely in current bucket -> just update state
                self._cur_volume += remaining
                consumed_in_bar += remaining
                self._cur_end_price = price_at(consumed_in_bar / bar_volume)
                self._cur_end_time = timestamp
                self._cur_n_bars += 1
                remaining = 0
            else:
                # Fill the bucket to exactly bucket_size and emit it
                self._cur_volume += capacity
                consumed_in_bar += capacity
                self._cur_end_price = price_at(consumed_in_bar / bar_volume)
                self._cur_end_time = timestamp
                self._cur_n_bars += 1

                completed.append(VolumeBucket(
                    volume=self._cur_volume,
                    start_price=self._cur_start_price,
                    end_price=self._cur_end_price,
                    start_time=self._cur_start_time,
                    end_time=self._cur_end_time,
                    n_bars=self._cur_n_bars,
                ))

                # Reset for next bucket
                self._cur_volume = 0.0
                self._cur_start_price = None
                self._cur_end_price = None
                self._cur_start_time = None
                self._cur_end_time = None
                self._cur_n_bars = 0

                remaining -= capacity

        return completed

    def process_dataframe(self, df: pd.DataFrame) -> list[VolumeBucket]:
        """
        Consume an entire 1-min OHLCV DataFrame and return all completed
        buckets. The in-progress bucket (if any) is NOT returned.

        Expected columns: open, close, volume. Index is DatetimeIndex.
        """
        buckets: list[VolumeBucket] = []
        if df.empty:
            return buckets

        opens = df["open"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        volumes = df["volume"].to_numpy(dtype=float)
        ts_index = df.index

        for i in range(len(df)):
            new_buckets = self.add_bar(
                ts_index[i], opens[i], closes[i], volumes[i],
            )
            buckets.extend(new_buckets)

        return buckets

    def flush(self) -> Optional[VolumeBucket]:
        """
        Emit the current in-progress bucket (even if partial) and reset state.
        Returns None if no bucket is in progress.
        """
        if self._cur_volume == 0:
            return None

        bucket = VolumeBucket(
            volume=self._cur_volume,
            start_price=self._cur_start_price or 0.0,
            end_price=self._cur_end_price or 0.0,
            start_time=self._cur_start_time or pd.Timestamp("1970-01-01"),
            end_time=self._cur_end_time or pd.Timestamp("1970-01-01"),
            n_bars=self._cur_n_bars,
        )
        self._cur_volume = 0.0
        self._cur_start_price = None
        self._cur_end_price = None
        self._cur_start_time = None
        self._cur_end_time = None
        self._cur_n_bars = 0
        return bucket

    def reset(self) -> None:
        """Clear all in-progress state."""
        self._cur_volume = 0.0
        self._cur_start_price = None
        self._cur_end_price = None
        self._cur_start_time = None
        self._cur_end_time = None
        self._cur_n_bars = 0
