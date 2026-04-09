"""
backtest/databento_loader.py
=============================
Loader for Databento OHLCV-1m CSV dumps.

Why a dedicated loader
----------------------
Databento's OHLCV-1m schema is NOT the simple
``timestamp,open,high,low,close,volume`` shape that
``backtest.data_loader.load_data_csv`` expects. A raw dump includes:

  * ``ts_event``       — ISO 8601 nanosecond UTC timestamp
  * ``rtype``          — record type (33 = OHLCV-1m)
  * ``publisher_id``   — CME publisher id
  * ``instrument_id``  — unique per-contract id
  * ``open/high/low/close/volume``
  * ``symbol``         — contract code (e.g. ``NQZ4``) OR calendar spread
                         (e.g. ``NQH9-NQM9``)

For a 6-year NQ dump you get 3.6M+ rows spread across ~33 quarterly
contracts + ~82 calendar spreads.  The backtester wants a **single
continuous 1-min OHLCV series** in America/Chicago — so we need to:

  1. Drop calendar spreads (symbols with ``-``)
  2. Pick the front-month contract at every minute by volume
  3. Parse UTC → tz-aware DatetimeIndex, convert to America/Chicago
  4. Return the standard 5-column df that the backtester consumes

Memory note
-----------
Loading the full 3.6M-row 415 MB CSV takes ~30–60 s and ~400 MB RAM.
If ``start_date`` / ``end_date`` are supplied we apply them *after* the
read (pandas doesn't support pushdown on CSV) but we subset early to
free memory before the volume-based dedupe step.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# Columns the backtester's downstream code needs
_STANDARD_COLUMNS = ["open", "high", "low", "close", "volume"]

# Databento CSV columns we actually care about; ignore the rest
_USE_COLUMNS = [
    "ts_event",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
]

# Front-month picker: rows whose symbol contains "-" are calendar spreads
_SPREAD_MARKER = "-"


def load_databento_ohlcv_1m(
    csv_path: str | Path,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    symbol_prefix: str = "NQ",
) -> pd.DataFrame:
    """
    Load a Databento OHLCV-1m CSV dump and return a continuous 1-min
    OHLCV DataFrame in America/Chicago timezone.

    Parameters
    ----------
    csv_path : str | Path
        Path to the Databento CSV dump.
    start_date, end_date : str, optional
        Inclusive date bounds in ``YYYY-MM-DD``. Applied after read
        but before the expensive front-month dedupe.
    symbol_prefix : str
        Contract root to keep (default ``"NQ"``). Rows whose symbol
        doesn't start with this prefix are dropped — useful when a
        single dump contains multiple instruments.

    Returns
    -------
    pd.DataFrame
        Index: tz-aware DatetimeIndex in ``America/Chicago``.
        Columns: ``open, high, low, close, volume``.
        One row per unique minute; the row at each minute comes from
        the most-traded contract at that minute (front-month proxy).

    Raises
    ------
    FileNotFoundError
        If ``csv_path`` doesn't exist.
    ValueError
        If the CSV is missing required Databento columns, or the date
        filter ends up with zero rows.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Databento CSV not found: {path}")

    logger.info("Reading Databento CSV: %s (%.1f MB)",
                path, path.stat().st_size / 1024 / 1024)

    df = pd.read_csv(path, usecols=_USE_COLUMNS)

    missing = set(_USE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(
            f"CSV is missing Databento columns: {missing}. "
            f"Is this really an OHLCV-1m dump?"
        )

    logger.info("Loaded %d raw rows", len(df))

    # ─── Step 1: Drop calendar spreads ──────────────────────────────────
    is_spread = df["symbol"].str.contains(_SPREAD_MARKER, regex=False, na=False)
    n_spreads = int(is_spread.sum())
    df = df[~is_spread]
    logger.info("Dropped %d calendar-spread rows, %d remain", n_spreads, len(df))

    # ─── Step 2: Filter by symbol prefix (NQ, ES, etc.) ─────────────────
    if symbol_prefix:
        keep = df["symbol"].str.startswith(symbol_prefix)
        n_dropped = int((~keep).sum())
        df = df[keep]
        if n_dropped:
            logger.info(
                "Dropped %d rows not matching prefix %r, %d remain",
                n_dropped, symbol_prefix, len(df),
            )

    if df.empty:
        raise ValueError(
            f"No rows left after spread+prefix filter "
            f"(prefix={symbol_prefix!r}). Is the file the right instrument?"
        )

    # ─── Step 3: Parse timestamps (nanosecond ISO → UTC → Chicago) ──────
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)

    # ─── Step 4: Early date filter (saves memory for the dedupe step) ───
    if start_date:
        start_ts = pd.Timestamp(start_date, tz="UTC")
        df = df[df["ts_event"] >= start_ts]
    if end_date:
        # End date is inclusive — add a day to catch the 23:59 bar
        end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)
        df = df[df["ts_event"] < end_ts]

    if df.empty:
        raise ValueError(
            f"No rows after date filter "
            f"(start={start_date}, end={end_date})"
        )

    logger.info("%d rows in date range", len(df))

    # ─── Step 5: Front-month pick via max-volume dedupe per minute ──────
    # Sort so that within each ts_event, the highest-volume row is first,
    # then drop_duplicates keeps only the first row per ts_event.
    df = df.sort_values(
        ["ts_event", "volume"],
        ascending=[True, False],
    )
    before = len(df)
    df = df.drop_duplicates(subset="ts_event", keep="first")
    logger.info(
        "Deduplicated %d rows → %d unique minutes (front-month continuous)",
        before, len(df),
    )

    # ─── Step 6: Convert index to America/Chicago + final shape ─────────
    df = df.set_index("ts_event")
    df.index = df.index.tz_convert("America/Chicago")
    df = df.sort_index()

    out = df[_STANDARD_COLUMNS].copy()

    # Safety: ensure numeric dtypes (Databento should already be numeric)
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0).astype("int64")

    # Drop any rows where OHLC parse failed
    na_count = int(out[["open", "high", "low", "close"]].isna().any(axis=1).sum())
    if na_count:
        logger.warning("Dropping %d rows with NaN OHLC", na_count)
        out = out.dropna(subset=["open", "high", "low", "close"])

    logger.info(
        "Databento loader done: %d bars (%s → %s)",
        len(out),
        out.index[0] if not out.empty else "∅",
        out.index[-1] if not out.empty else "∅",
    )
    return out


def scan_databento_metadata(csv_path: str | Path) -> dict:
    """
    Read only metadata columns (ts_event, symbol, volume) and return
    a summary dict. Used by diagnostic scripts to understand a dump
    without loading the full OHLC into memory.

    Returns
    -------
    dict
        ``total_rows``, ``date_start``, ``date_end``, ``n_symbols``,
        ``n_straight``, ``n_spreads``, ``top_contracts`` (list of
        (symbol, volume) sorted desc), ``all_symbols``.
    """
    path = Path(csv_path)
    df = pd.read_csv(path, usecols=["ts_event", "symbol", "volume"])

    total = len(df)
    first_ts = df["ts_event"].iloc[0] if total else None
    last_ts = df["ts_event"].iloc[-1] if total else None

    spreads_mask = df["symbol"].str.contains(_SPREAD_MARKER, regex=False, na=False)
    straight = df[~spreads_mask]

    n_syms = int(df["symbol"].nunique())
    n_spreads = int(spreads_mask.sum())
    n_straight = int((~spreads_mask).sum())

    top = (
        straight.groupby("symbol")["volume"].sum()
        .sort_values(ascending=False)
        .head(15)
    )
    top_contracts = [(sym, int(vol)) for sym, vol in top.items()]

    return {
        "total_rows": total,
        "date_start": first_ts,
        "date_end": last_ts,
        "n_symbols": n_syms,
        "n_straight_rows": n_straight,
        "n_spread_rows": n_spreads,
        "top_contracts": top_contracts,
        "all_symbols": sorted(df["symbol"].unique().tolist()),
    }
