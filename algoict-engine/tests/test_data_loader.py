"""
tests/test_data_loader.py
=========================
Unit tests for backtest/data_loader.py

Run: cd algoict-engine && python -m pytest tests/test_data_loader.py -v
"""

import io
import os
import tempfile

import pandas as pd
import pytest

from backtest.data_loader import load_futures_data, _find_rth_gaps, _build_continuous


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_databento_csv(rows: list[dict]) -> str:
    """
    Build a minimal Databento-format CSV string.

    rows: list of dicts with keys: ts_event (UTC ISO), open, high, low, close, volume, symbol
    """
    header = "ts_event,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol\n"
    lines = [header]
    for r in rows:
        lines.append(
            f"{r['ts_event']},33,1,12345,"
            f"{r['open']:.3f},{r['high']:.3f},{r['low']:.3f},{r['close']:.3f},"
            f"{r['volume']},{r['symbol']}\n"
        )
    return "".join(lines)


def _write_tmp_csv(content: str) -> str:
    """Write CSV content to a named temp file and return its path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return f.name


def _bar(ts_utc: str, symbol: str = "NQM5", vol: int = 100) -> dict:
    return {
        "ts_event": ts_utc,
        "open": 20000.0,
        "high": 20010.0,
        "low":  19990.0,
        "close": 20005.0,
        "volume": vol,
        "symbol": symbol,
    }


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestLoadFuturesData:

    def test_returns_dataframe(self):
        """load_futures_data returns a non-empty DataFrame."""
        rows = [_bar(f"2025-03-03T14:{m:02d}:00.000000000Z") for m in range(10)]
        csv = _make_databento_csv(rows)
        path = _write_tmp_csv(csv)
        try:
            df = load_futures_data(path)
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 10
        finally:
            os.unlink(path)

    def test_columns(self):
        """Output has exactly: open, high, low, close, volume."""
        rows = [_bar(f"2025-03-03T14:{m:02d}:00.000000000Z") for m in range(5)]
        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path)
            assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        finally:
            os.unlink(path)

    def test_index_is_datetime(self):
        """Index is a DatetimeIndex."""
        rows = [_bar(f"2025-03-03T14:{m:02d}:00.000000000Z") for m in range(5)]
        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path)
            assert isinstance(df.index, pd.DatetimeIndex)
        finally:
            os.unlink(path)

    def test_timezone_is_central(self):
        """Index timezone is US/Central."""
        rows = [_bar(f"2025-03-03T14:{m:02d}:00.000000000Z") for m in range(5)]
        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path)
            tz_str = str(df.index.tz)
            assert "Central" in tz_str or "US/Central" in tz_str or "Chicago" in tz_str
        finally:
            os.unlink(path)

    def test_sorted_ascending(self):
        """Bars are sorted oldest-first."""
        # Provide rows out of order
        rows = [
            _bar("2025-03-03T14:05:00.000000000Z"),
            _bar("2025-03-03T14:03:00.000000000Z"),
            _bar("2025-03-03T14:01:00.000000000Z"),
        ]
        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path)
            assert df.index.is_monotonic_increasing
        finally:
            os.unlink(path)

    def test_no_duplicates(self):
        """Duplicate timestamps are removed (keep last)."""
        rows = [
            _bar("2025-03-03T14:01:00.000000000Z", vol=100),
            _bar("2025-03-03T14:01:00.000000000Z", vol=999),  # duplicate
            _bar("2025-03-03T14:02:00.000000000Z", vol=200),
        ]
        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path)
            assert len(df) == 2
            # keep-last means vol=999 at 14:01
            # Convert ts to UTC for lookup
            bar_14_01 = df.iloc[0]
            assert bar_14_01["volume"] == 999
        finally:
            os.unlink(path)

    def test_spreads_excluded(self):
        """Rows with '-' in symbol (spreads) are dropped."""
        rows = [
            _bar("2025-03-03T14:01:00.000000000Z", symbol="NQM5"),
            _bar("2025-03-03T14:01:00.000000000Z", symbol="NQM5-NQU5"),  # spread
        ]
        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path)
            assert len(df) == 1  # only NQM5
        finally:
            os.unlink(path)

    def test_dtypes_correct(self):
        """Price cols are float64, volume is int."""
        rows = [_bar(f"2025-03-03T14:{m:02d}:00.000000000Z") for m in range(5)]
        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path)
            for col in ["open", "high", "low", "close"]:
                assert pd.api.types.is_float_dtype(df[col]), f"{col} should be float"
            assert pd.api.types.is_integer_dtype(df["volume"]), "volume should be int"
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        """Raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_futures_data("/nonexistent/path/data.csv")

    def test_symbol_filter(self):
        """When symbol_filter is provided, only that contract is returned."""
        rows = [
            _bar("2025-03-03T14:01:00.000000000Z", symbol="NQM5", vol=500),
            _bar("2025-03-03T14:01:00.000000000Z", symbol="NQU5", vol=100),
            _bar("2025-03-03T14:02:00.000000000Z", symbol="NQM5", vol=400),
            _bar("2025-03-03T14:02:00.000000000Z", symbol="NQU5", vol=200),
        ]
        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path, symbol_filter="NQU5")
            assert len(df) == 2
        finally:
            os.unlink(path)

    def test_date_filter(self):
        """start_date / end_date trims the DataFrame."""
        rows = [
            _bar("2025-01-02T14:00:00.000000000Z"),
            _bar("2025-06-01T14:00:00.000000000Z"),
            _bar("2025-12-01T14:00:00.000000000Z"),
        ]
        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path, start_date="2025-05-01", end_date="2025-07-01")
            assert len(df) == 1
        finally:
            os.unlink(path)


class TestRthGapDetection:

    def test_no_gap_during_rth(self):
        """Consecutive 1-min bars during RTH produce no gaps."""
        # 09:30-09:35 CT on a Tuesday
        timestamps = pd.date_range(
            "2025-03-04 09:30", periods=6, freq="1min", tz="US/Central"
        )
        df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100},
            index=timestamps,
        )
        gaps = _find_rth_gaps(df)
        assert len(gaps) == 0

    def test_gap_detected_during_rth(self):
        """A 5-min gap during RTH is detected."""
        base = pd.Timestamp("2025-03-04 10:00", tz="US/Central")
        timestamps = pd.DatetimeIndex([
            base,
            base + pd.Timedelta("1min"),
            base + pd.Timedelta("6min"),  # 5-min gap here
        ])
        df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100},
            index=timestamps,
        )
        gaps = _find_rth_gaps(df)
        assert len(gaps) == 1
        assert gaps[0]["minutes"] == 5

    def test_overnight_gap_ignored(self):
        """Gap between 4 PM and 8 AM is NOT flagged (outside RTH)."""
        timestamps = pd.DatetimeIndex([
            pd.Timestamp("2025-03-03 15:00", tz="US/Central"),
            pd.Timestamp("2025-03-04 09:00", tz="US/Central"),  # overnight gap
        ])
        df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100},
            index=timestamps,
        )
        gaps = _find_rth_gaps(df)
        assert len(gaps) == 0

    def test_weekend_gap_ignored(self):
        """Gap over a weekend is NOT flagged."""
        timestamps = pd.DatetimeIndex([
            pd.Timestamp("2025-02-28 14:00", tz="US/Central"),  # Friday
            pd.Timestamp("2025-03-03 09:00", tz="US/Central"),  # Monday
        ])
        df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100},
            index=timestamps,
        )
        gaps = _find_rth_gaps(df)
        assert len(gaps) == 0


class TestBuildContinuous:

    def test_picks_higher_volume_contract(self):
        """
        When two contracts trade simultaneously, the one with higher daily
        volume is chosen.
        """
        rows = []
        # Same minute: NQM5 has more volume → should be chosen
        for m in range(5):
            ts = f"2025-03-03T14:{m:02d}:00.000000000Z"
            rows.append(_bar(ts, symbol="NQM5", vol=1000))
            rows.append(_bar(ts, symbol="NQH5", vol=100))

        path = _write_tmp_csv(_make_databento_csv(rows))
        try:
            df = load_futures_data(path)
            assert len(df) == 5  # one bar per minute
        finally:
            os.unlink(path)
