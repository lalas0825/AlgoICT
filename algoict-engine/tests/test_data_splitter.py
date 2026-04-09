"""Tests for strategy_lab.data_splitter — the Test Set lock is sacred."""

from __future__ import annotations

import pandas as pd
import pytest

from strategy_lab.data_splitter import (
    DataSplitter,
    TEST_AUTH_CODE,
    TRAIN_END_DATE,
    VALIDATION_END_DATE,
)


# ─── Fixtures ───────────────────────────────────────────────────────────

def _make_data(start: str = "2019-01-01", end: str = "2025-06-30") -> pd.DataFrame:
    """Daily OHLCV covering the full historical range we care about."""
    idx = pd.date_range(start=start, end=end, freq="D", tz="US/Central")
    n = len(idx)
    return pd.DataFrame(
        {
            "open": [100.0 + i * 0.01 for i in range(n)],
            "high": [101.0 + i * 0.01 for i in range(n)],
            "low": [99.0 + i * 0.01 for i in range(n)],
            "close": [100.5 + i * 0.01 for i in range(n)],
            "volume": [1000] * n,
        },
        index=idx,
    )


@pytest.fixture
def full_data():
    return _make_data()


# ─── Construction + partitioning ────────────────────────────────────────

class TestConstruction:
    def test_rejects_empty_dataframe(self):
        with pytest.raises(ValueError, match="non-empty"):
            DataSplitter(pd.DataFrame())

    def test_rejects_non_datetime_index(self):
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        with pytest.raises(TypeError, match="DatetimeIndex"):
            DataSplitter(df)

    def test_rejects_non_monotonic_index(self):
        idx = pd.to_datetime(["2020-01-01", "2019-01-01", "2021-01-01"]).tz_localize(
            "US/Central"
        )
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=idx)
        with pytest.raises(ValueError, match="monotonically"):
            DataSplitter(df)

    def test_accepts_valid_data(self, full_data):
        splitter = DataSplitter(full_data)
        assert splitter.train is not None
        assert splitter.validation is not None


class TestPartitioning:
    def test_train_ends_at_2022_12_31(self, full_data):
        splitter = DataSplitter(full_data)
        last = splitter.train.index[-1]
        assert last.year == 2022
        assert last.month == 12
        # Last train bar must be within the training range
        assert str(last.date()) <= TRAIN_END_DATE

    def test_validation_covers_2023_only(self, full_data):
        splitter = DataSplitter(full_data)
        val = splitter.validation
        assert val.index[0].year == 2023
        assert val.index[-1].year == 2023
        assert str(val.index[-1].date()) <= VALIDATION_END_DATE

    def test_test_starts_in_2024(self, full_data):
        splitter = DataSplitter(full_data)
        stats = splitter.stats()
        assert stats.test_start.year == 2024

    def test_no_overlap_between_partitions(self, full_data):
        splitter = DataSplitter(full_data)
        train_set = set(splitter.train.index)
        val_set = set(splitter.validation.index)
        assert train_set.isdisjoint(val_set)

    def test_partitions_cover_full_data(self, full_data):
        splitter = DataSplitter(full_data)
        total = (
            len(splitter.train)
            + len(splitter.validation)
            + splitter.stats().test_bars
        )
        assert total == len(full_data)

    def test_get_training_returns_copy(self, full_data):
        splitter = DataSplitter(full_data)
        t1 = splitter.get_training()
        t1["close"] = -999.0  # Should not mutate splitter state
        t2 = splitter.get_training()
        assert (t2["close"] != -999.0).all()

    def test_get_validation_returns_copy(self, full_data):
        splitter = DataSplitter(full_data)
        v1 = splitter.get_validation()
        v1["close"] = -999.0
        v2 = splitter.get_validation()
        assert (v2["close"] != -999.0).all()


# ─── The Lock — these are the critical tests ──────────────────────────

class TestTestSetLock:
    def test_raises_permission_error_on_wrong_auth(self, full_data):
        splitter = DataSplitter(full_data)
        with pytest.raises(PermissionError, match="LOCKED"):
            splitter.get_test("wrong_code")

    def test_raises_permission_error_on_empty_auth(self, full_data):
        splitter = DataSplitter(full_data)
        with pytest.raises(PermissionError, match="LOCKED"):
            splitter.get_test("")

    def test_raises_permission_error_on_lowercase(self, full_data):
        splitter = DataSplitter(full_data)
        with pytest.raises(PermissionError):
            splitter.get_test(TEST_AUTH_CODE.lower())

    def test_raises_permission_error_on_none(self, full_data):
        splitter = DataSplitter(full_data)
        with pytest.raises(PermissionError):
            splitter.get_test(None)  # type: ignore[arg-type]

    def test_correct_auth_returns_data(self, full_data):
        splitter = DataSplitter(full_data)
        test = splitter.get_test(TEST_AUTH_CODE)
        assert isinstance(test, pd.DataFrame)
        assert not test.empty
        assert test.index[0].year == 2024

    def test_test_access_is_one_shot(self, full_data):
        splitter = DataSplitter(full_data)
        splitter.get_test(TEST_AUTH_CODE)  # first access OK
        with pytest.raises(RuntimeError, match="ALREADY ACCESSED"):
            splitter.get_test(TEST_AUTH_CODE)

    def test_test_accessed_flag_tracks_state(self, full_data):
        splitter = DataSplitter(full_data)
        assert splitter.test_accessed is False
        splitter.get_test(TEST_AUTH_CODE)
        assert splitter.test_accessed is True

    def test_failed_auth_does_not_burn_the_one_shot(self, full_data):
        """Wrong codes should not count as 'access' — user can retry with right code."""
        splitter = DataSplitter(full_data)
        with pytest.raises(PermissionError):
            splitter.get_test("wrong")
        assert splitter.test_accessed is False
        # Correct code still works after a failed attempt
        test = splitter.get_test(TEST_AUTH_CODE)
        assert not test.empty

    def test_test_returns_copy(self, full_data):
        splitter = DataSplitter(full_data)
        test = splitter.get_test(TEST_AUTH_CODE)
        test["close"] = -999.0
        # Mutating the returned copy should not affect anything else
        # (can't re-read to verify due to one-shot rule, but we can check
        # the private _test attribute was not modified)
        assert (splitter._test["close"] != -999.0).all()

    def test_access_log_records_attempts(self, full_data):
        splitter = DataSplitter(full_data)
        assert splitter.access_log == []
        with pytest.raises(PermissionError):
            splitter.get_test("wrong")
        assert len(splitter.access_log) == 1
        assert "DENIED" in splitter.access_log[0]

        splitter.get_test(TEST_AUTH_CODE)
        assert len(splitter.access_log) == 2
        assert "GRANTED" in splitter.access_log[1]

        with pytest.raises(RuntimeError):
            splitter.get_test(TEST_AUTH_CODE)
        assert len(splitter.access_log) == 3
        assert "DENIED — already accessed" in splitter.access_log[2]


class TestStats:
    def test_stats_include_all_partitions(self, full_data):
        splitter = DataSplitter(full_data)
        stats = splitter.stats()
        assert stats.train_bars > 0
        assert stats.validation_bars > 0
        assert stats.test_bars > 0

    def test_stats_does_not_unlock_test_set(self, full_data):
        """Reading stats should be metadata-only — no unlock consumed."""
        splitter = DataSplitter(full_data)
        _ = splitter.stats()
        assert splitter.test_accessed is False
        # Test Set still accessible with proper auth
        test = splitter.get_test(TEST_AUTH_CODE)
        assert not test.empty

    def test_summary_string_mentions_lock(self, full_data):
        splitter = DataSplitter(full_data)
        summary = splitter.stats().summary()
        assert "LOCKED" in summary
