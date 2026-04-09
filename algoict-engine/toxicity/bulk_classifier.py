"""
toxicity/bulk_classifier.py
============================
Bulk Volume Classification (BVC) — Easley, Lopez de Prado, O'Hara (2010).

Classifies each volume bucket into estimated buy_volume and sell_volume
fractions without needing Level 2 tick-by-tick data.

Math (per bucket)
-----------------
    z              = price_change / sigma
    buy_fraction   = Phi(z)                # standard normal CDF
    sell_fraction  = 1 - buy_fraction
    buy_volume     = bucket.volume * buy_fraction
    sell_volume    = bucket.volume * sell_fraction
    imbalance      = |buy_volume - sell_volume|

`sigma` is the rolling standard deviation of recent bucket price changes.
We use an EMA-style update so it adapts to regime changes quickly:

    sigma_new = (1 - alpha) * sigma_old + alpha * |price_change|

with alpha=0.05 (skill's default).

The classifier is stateful: it maintains the rolling sigma across calls,
so a single BVCClassifier instance should be reused across an entire
backtest run (or trading session).
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.stats import norm

from .volume_buckets import VolumeBucket

logger = logging.getLogger(__name__)


# EMA smoothing factor for sigma updates (from the skill spec)
DEFAULT_SIGMA_ALPHA = 0.05

# Minimum absolute price change to seed sigma when no history exists
SIGMA_SEED_FLOOR = 0.01


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedBucket:
    """A volume bucket with BVC buy/sell split."""
    bucket: VolumeBucket
    buy_volume: float
    sell_volume: float
    imbalance: float              # |buy_volume - sell_volume|
    sigma_used: float             # the sigma value used for classification
    z: float                      # price_change / sigma

    @property
    def total_volume(self) -> float:
        return self.bucket.volume

    @property
    def buy_fraction(self) -> float:
        if self.bucket.volume == 0:
            return 0.5
        return self.buy_volume / self.bucket.volume

    def __repr__(self) -> str:
        return (
            f"ClassifiedBucket(dp={self.bucket.price_change:+.2f} "
            f"buy={self.buy_volume:.0f} sell={self.sell_volume:.0f} "
            f"imb={self.imbalance:.0f})"
        )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class BVCClassifier:
    """
    Stateful Bulk Volume Classifier.

    Usage
    -----
        classifier = BVCClassifier()
        for bucket in buckets:
            classified = classifier.classify(bucket)
            print(classified.imbalance)

        # Or batch:
        classified = classifier.classify_all(buckets)
    """

    def __init__(self, sigma_alpha: float = DEFAULT_SIGMA_ALPHA):
        if not (0.0 < sigma_alpha <= 1.0):
            raise ValueError(
                f"sigma_alpha must be in (0, 1], got {sigma_alpha}"
            )
        self.sigma_alpha = float(sigma_alpha)
        self._sigma: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def sigma(self) -> Optional[float]:
        """Current rolling sigma estimate (None if no history yet)."""
        return self._sigma

    def classify(self, bucket: VolumeBucket) -> ClassifiedBucket:
        """
        Classify a single bucket into buy/sell volumes.

        Updates the internal sigma estimate *before* classifying so that
        the sigma used reflects the current bucket. This matches the
        behavior in the skill's reference implementation.
        """
        price_change = bucket.price_change
        abs_dp = abs(price_change)

        if self._sigma is None:
            # First bucket: seed sigma from its own |price_change|
            self._sigma = max(abs_dp, SIGMA_SEED_FLOOR)
        else:
            # EMA update: sigma_new = (1-a)*sigma_old + a*|dp|
            self._sigma = (1.0 - self.sigma_alpha) * self._sigma \
                + self.sigma_alpha * abs_dp
            # Floor to avoid divide-by-zero when the market is perfectly flat
            self._sigma = max(self._sigma, SIGMA_SEED_FLOOR)

        sigma = self._sigma

        # BVC: buy_fraction = CDF(price_change / sigma)
        z = price_change / sigma if sigma > 0 else 0.0
        buy_fraction = float(norm.cdf(z))
        sell_fraction = 1.0 - buy_fraction

        total_v = bucket.volume
        buy_volume = total_v * buy_fraction
        sell_volume = total_v * sell_fraction
        imbalance = abs(buy_volume - sell_volume)

        return ClassifiedBucket(
            bucket=bucket,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            imbalance=imbalance,
            sigma_used=sigma,
            z=z,
        )

    def classify_all(self, buckets: list[VolumeBucket]) -> list[ClassifiedBucket]:
        """Classify a sequence of buckets in order."""
        return [self.classify(b) for b in buckets]

    def reset(self) -> None:
        """Clear the rolling sigma (start fresh)."""
        self._sigma = None


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def buy_fraction_from_z(z: float) -> float:
    """Raw BVC buy-fraction from a normalized z-score."""
    return float(norm.cdf(z))


def classify_buckets(
    buckets: list[VolumeBucket],
    sigma_alpha: float = DEFAULT_SIGMA_ALPHA,
) -> list[ClassifiedBucket]:
    """One-shot classification of a bucket list with a fresh classifier."""
    classifier = BVCClassifier(sigma_alpha=sigma_alpha)
    return classifier.classify_all(buckets)
