"""
strategy_lab/data_splitter.py
==============================
Sacrosanct Train/Validation/Test split with HARD LOCK on Test Set.

Split definition
----------------
- Training Set   : 2019-01-01  →  2022-12-31  (~60% — hypothesis generation + walk-forward)
- Validation Set : 2023-01-01  →  2023-12-31  (~20% — first unseen data, Gate 9)
- Test Set       : 2024-01-01  →       ∞      (~20% — INTOCABLE until Juan approves)

Enforcement
-----------
The Test Set is private. `get_test()` requires an exact authorization code AND
refuses second access within the same splitter instance. Every unlock is
logged (WARNING level) so contamination attempts are auditable. This is the
*only* safeguard between overfitting and shipping a dead strategy.

Usage
-----
    >>> splitter = DataSplitter(df_mnq_1min)
    >>> train = splitter.get_training()
    >>> val   = splitter.get_validation()
    >>> # During hypothesis research — Test set is LOCKED:
    >>> splitter.get_test("wrong")   # raises PermissionError
    >>> # Only after all 9 gates pass + Juan's approval:
    >>> test = splitter.get_test("JUAN_APPROVED_FINAL_TEST")   # OK once
    >>> splitter.get_test("JUAN_APPROVED_FINAL_TEST")          # raises RuntimeError
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ─── Split Boundaries (inclusive, in data's tz) ──────────────────────────
TRAIN_START_DATE = "2019-01-01"
TRAIN_END_DATE = "2022-12-31"
VALIDATION_START_DATE = "2023-01-01"
VALIDATION_END_DATE = "2023-12-31"
TEST_START_DATE = "2024-01-01"

# The only string that unlocks the Test Set. Must match exactly.
TEST_AUTH_CODE = "JUAN_APPROVED_FINAL_TEST"


@dataclass
class SplitStats:
    """Row counts + date bounds for each partition."""

    train_bars: int
    train_start: Optional[pd.Timestamp]
    train_end: Optional[pd.Timestamp]
    validation_bars: int
    validation_start: Optional[pd.Timestamp]
    validation_end: Optional[pd.Timestamp]
    test_bars: int
    test_start: Optional[pd.Timestamp]
    test_end: Optional[pd.Timestamp]

    def summary(self) -> str:
        return (
            f"SplitStats(\n"
            f"  train      = {self.train_bars:,} bars "
            f"[{self.train_start} → {self.train_end}]\n"
            f"  validation = {self.validation_bars:,} bars "
            f"[{self.validation_start} → {self.validation_end}]\n"
            f"  test       = {self.test_bars:,} bars "
            f"[{self.test_start} → {self.test_end}]  🔒 LOCKED\n"
            f")"
        )


class DataSplitter:
    """
    Splits historical data into Train/Validation/Test and *locks* the
    Test Set behind an auth code + single-use guard.

    Parameters
    ----------
    data : pd.DataFrame
        OHLCV with tz-aware DatetimeIndex. Must be monotonically increasing.

    Attributes
    ----------
    train : pd.DataFrame
        2019-01-01 → 2022-12-31 (inclusive). Safe to read freely.
    validation : pd.DataFrame
        2023-01-01 → 2023-12-31 (inclusive). Safe to read freely.

    Notes
    -----
    The Test Set is stored in ``self._test`` and is intentionally private.
    Accessing it directly (e.g. ``splitter._test``) is considered a
    contamination attempt and should never happen in production code.
    """

    TRAIN_START = TRAIN_START_DATE
    TRAIN_END = TRAIN_END_DATE
    VALIDATION_START = VALIDATION_START_DATE
    VALIDATION_END = VALIDATION_END_DATE
    TEST_START = TEST_START_DATE

    def __init__(self, data: pd.DataFrame):
        if data is None or data.empty:
            raise ValueError("DataSplitter requires non-empty DataFrame.")
        if not isinstance(data.index, pd.DatetimeIndex):
            raise TypeError("DataSplitter requires a DatetimeIndex.")
        if not data.index.is_monotonic_increasing:
            raise ValueError("DataSplitter requires monotonically increasing index.")

        tz = data.index.tz
        train_end = pd.Timestamp(self.TRAIN_END, tz=tz) + pd.Timedelta(days=1)
        val_start = pd.Timestamp(self.VALIDATION_START, tz=tz)
        val_end = pd.Timestamp(self.VALIDATION_END, tz=tz) + pd.Timedelta(days=1)
        test_start = pd.Timestamp(self.TEST_START, tz=tz)

        self.train = data[data.index < train_end].copy()
        self.validation = data[
            (data.index >= val_start) & (data.index < val_end)
        ].copy()

        # Private — never exposed by attribute access, only via get_test()
        self._test = data[data.index >= test_start].copy()
        self._test_accessed = False
        self._access_log: list[str] = []

        logger.info(
            "DataSplitter initialized: train=%d rows, val=%d rows, test=%d rows (LOCKED)",
            len(self.train),
            len(self.validation),
            len(self._test),
        )

    # ─── Public API ──────────────────────────────────────────────────────

    def get_training(self) -> pd.DataFrame:
        """Return a defensive copy of the training partition (2019–2022)."""
        return self.train.copy()

    def get_validation(self) -> pd.DataFrame:
        """Return a defensive copy of the validation partition (2023)."""
        return self.validation.copy()

    def get_test(self, authorization_code: str) -> pd.DataFrame:
        """
        Return the Test Set — only if the caller proves authorization.

        Parameters
        ----------
        authorization_code : str
            Must equal exactly ``JUAN_APPROVED_FINAL_TEST``. Any other
            value — including typos, lowercase, or None — raises.

        Raises
        ------
        PermissionError
            If the auth code is missing or wrong.
        RuntimeError
            If the Test Set has already been accessed on this instance.
            Each candidate gets exactly ONE shot at the Test Set.

        Returns
        -------
        pd.DataFrame
            Defensive copy of the Test Set (2024–∞).
        """
        if authorization_code != TEST_AUTH_CODE:
            self._access_log.append(f"DENIED — bad auth code: {authorization_code!r}")
            logger.error(
                "TEST SET ACCESS DENIED — bad auth code. "
                "Test Set is protected to prevent overfitting contamination."
            )
            raise PermissionError(
                "TEST SET IS LOCKED. Only Juan can unlock with explicit approval. "
                f"Required auth code: {TEST_AUTH_CODE!r}. "
                "This lock exists by design to prevent overfitting."
            )

        if self._test_accessed:
            self._access_log.append("DENIED — already accessed")
            logger.error(
                "TEST SET ALREADY ACCESSED — refusing second read. "
                "Each DataSplitter instance grants ONE Test Set read per candidate."
            )
            raise RuntimeError(
                "TEST SET ALREADY ACCESSED FOR THIS HYPOTHESIS. "
                "Cannot access twice — data is now considered contaminated for this test. "
                "Create a new DataSplitter and a new hypothesis if you need another run."
            )

        self._test_accessed = True
        self._access_log.append("GRANTED — single-use unlock")
        logger.warning(
            "⚠️ TEST SET ACCESSED — one-time unlock granted. "
            "This read is permanent and logged."
        )
        return self._test.copy()

    # ─── Introspection ───────────────────────────────────────────────────

    @property
    def test_accessed(self) -> bool:
        """True once get_test() has been successfully called."""
        return self._test_accessed

    @property
    def access_log(self) -> list[str]:
        """Audit trail of every (allowed or denied) Test Set access attempt."""
        return list(self._access_log)

    def stats(self) -> SplitStats:
        """Return row counts + date bounds for each partition.

        Note: reading the test bar count is metadata-only — does NOT unlock
        the data rows themselves.
        """
        def _bounds(df: pd.DataFrame):
            if df.empty:
                return None, None
            return df.index[0], df.index[-1]

        train_s, train_e = _bounds(self.train)
        val_s, val_e = _bounds(self.validation)
        test_s, test_e = _bounds(self._test)

        return SplitStats(
            train_bars=len(self.train),
            train_start=train_s,
            train_end=train_e,
            validation_bars=len(self.validation),
            validation_start=val_s,
            validation_end=val_e,
            test_bars=len(self._test),
            test_start=test_s,
            test_end=test_e,
        )
