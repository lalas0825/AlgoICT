"""
backtest/data_loader.py
=======================
Loads and normalizes historical futures data from Databento OHLCV-1m CSV.

Key decisions:
- Builds a continuous front-month contract: at each 1-min bar, the active contract
  is the one with the highest rolling daily volume. This replicates natural roll.
- Timestamps converted to US/Central timezone (CT) — all downstream logic uses CT.
- Spreads (symbol contains '-') are excluded entirely.
- Only RTH gaps (08:30-15:15 CT) are flagged; overnight/weekend gaps are expected.
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# RTH window in CT
RTH_START = "08:30"
RTH_END = "15:15"
MAX_RTH_GAP_MINUTES = 2


def load_futures_data(
    filepath: str,
    symbol_filter: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load a Databento OHLCV-1m CSV and return a clean DataFrame with a
    continuous front-month series.

    Parameters
    ----------
    filepath : str
        Path to the Databento .ohlcv-1m.csv file.
    symbol_filter : str, optional
        Force a specific contract symbol (e.g. 'NQM5'). If None, builds the
        continuous series automatically by choosing the highest-volume contract
        at each timestamp.
    start_date : str, optional  e.g. '2023-01-01'
    end_date   : str, optional  e.g. '2025-12-31'

    Returns
    -------
    pd.DataFrame
        DatetimeIndex in US/Central, columns: open, high, low, close, volume.
        Sorted ascending, no duplicates.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")

    logger.info("Reading %s ...", path.name)

    df_raw = pd.read_csv(
        filepath,
        usecols=["ts_event", "open", "high", "low", "close", "volume", "symbol"],
        dtype={
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "volume": "int64",
            "symbol": "str",
        },
    )

    # ── 1. Remove spreads ──────────────────────────────────────────────────
    df_raw = df_raw[~df_raw["symbol"].str.contains("-", na=False)].copy()

    # ── 2. Parse timestamps → UTC → Central ───────────────────────────────
    df_raw["ts_event"] = pd.to_datetime(df_raw["ts_event"], utc=True)
    df_raw["ts_event"] = df_raw["ts_event"].dt.tz_convert("US/Central")

    # ── 3. Optional date filter ────────────────────────────────────────────
    if start_date:
        df_raw = df_raw[df_raw["ts_event"] >= pd.Timestamp(start_date, tz="US/Central")]
    if end_date:
        df_raw = df_raw[df_raw["ts_event"] <= pd.Timestamp(end_date, tz="US/Central")]

    # ── 4. Select active contract ─────────────────────────────────────────
    if symbol_filter:
        df_active = df_raw[df_raw["symbol"] == symbol_filter].copy()
        if df_active.empty:
            raise ValueError(f"Symbol '{symbol_filter}' not found in data.")
        logger.info("Using fixed symbol: %s (%d bars)", symbol_filter, len(df_active))
    else:
        df_active = _build_continuous(df_raw)

    # ── 5. Set index, sort, deduplicate ───────────────────────────────────
    df_active = df_active.set_index("ts_event").sort_index()
    df_active = df_active[~df_active.index.duplicated(keep="last")]
    df_active = df_active[["open", "high", "low", "close", "volume"]]

    # ── 6. Type validation ────────────────────────────────────────────────
    _validate_dtypes(df_active)

    # ── 7. Gap detection (RTH only) ───────────────────────────────────────
    gaps = _find_rth_gaps(df_active)

    # ── 8. Summary log ───────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  File    : %s", path.name)
    logger.info("  Bars    : %d", len(df_active))
    logger.info("  From    : %s", df_active.index.min())
    logger.info("  To      : %s", df_active.index.max())
    logger.info("  RTH gaps: %d (> %d min during %s-%s CT)",
                len(gaps), MAX_RTH_GAP_MINUTES, RTH_START, RTH_END)
    if gaps:
        for g in gaps[:5]:
            logger.warning("  GAP: %s → %s (%d min)", g["start"], g["end"], g["minutes"])
        if len(gaps) > 5:
            logger.warning("  ... and %d more gaps", len(gaps) - 5)
    logger.info("=" * 60)

    return df_active


def load_sp500_daily(tickers: list[str], period: str = "5y") -> dict[str, pd.DataFrame]:
    """
    Download daily OHLCV for a list of S&P 500 tickers via yfinance.

    Parameters
    ----------
    tickers : list of str   e.g. ['AAPL', 'MSFT', 'NVDA']
    period  : str           yfinance period string, default '5y'

    Returns
    -------
    dict mapping ticker → DataFrame with columns: open, high, low, close, volume
    DatetimeIndex, sorted ascending.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance not installed. Run: pip install yfinance") from exc

    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        logger.info("Downloading %s ...", ticker)
        raw = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
        if raw.empty:
            logger.warning("No data returned for %s", ticker)
            continue
        raw.columns = [c.lower() for c in raw.columns]
        raw = raw[["open", "high", "low", "close", "volume"]].sort_index()
        result[ticker] = raw
    logger.info("Downloaded %d/%d tickers", len(result), len(tickers))
    return result


# ─── Private helpers ─────────────────────────────────────────────────────────

def _build_continuous(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Build a continuous front-month series.

    Logic: for each 1-min timestamp, keep the row belonging to the contract
    that had the highest cumulative volume over the trailing calendar day.
    This naturally mirrors the market's roll: volume migrates to the next
    contract ~1 week before expiration.
    """
    # Compute rolling daily volume per contract (trailing 390 bars ≈ 1 trading day)
    # Group by symbol, then compute expanding daily vol
    df_raw = df_raw.sort_values("ts_event")

    # Deduplicate (same timestamp + same symbol) keeping last row
    df_raw = df_raw.drop_duplicates(subset=["ts_event", "symbol"], keep="last")

    # Daily volume per symbol per date
    df_raw["date"] = df_raw["ts_event"].dt.date
    daily_vol = (
        df_raw.groupby(["date", "symbol"])["volume"]
        .sum()
        .rename("daily_vol")
        .reset_index()
    )

    # Merge back
    df = df_raw.merge(daily_vol, on=["date", "symbol"], how="left")

    # At each timestamp, keep only the symbol with max daily_vol
    # Use last=True so ties resolve to the last (most recent) row
    idx = df.groupby("ts_event")["daily_vol"].transform("max") == df["daily_vol"]
    df_deduped = df[idx].drop_duplicates(subset=["ts_event"], keep="last")
    df_continuous = df_deduped.copy()

    # Log roll dates
    roll_dates = df_continuous[df_continuous["symbol"] != df_continuous["symbol"].shift(1)]
    logger.info("Contract rolls detected: %d", len(roll_dates) - 1)
    for _, row in roll_dates.iloc[1:].iterrows():
        logger.info("  Roll at %s → %s", row["ts_event"], row["symbol"])

    return df_continuous[["ts_event", "open", "high", "low", "close", "volume"]]


def _validate_dtypes(df: pd.DataFrame) -> None:
    """Raise if any price/volume column has wrong dtype."""
    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        if not pd.api.types.is_float_dtype(df[col]):
            raise TypeError(f"Column '{col}' expected float, got {df[col].dtype}")
    if not pd.api.types.is_integer_dtype(df["volume"]):
        raise TypeError(f"Column 'volume' expected int, got {df['volume'].dtype}")


def _find_rth_gaps(df: pd.DataFrame) -> list[dict]:
    """
    Return list of gaps > MAX_RTH_GAP_MINUTES that occur during RTH.
    Overnight and weekend gaps are excluded.
    """
    gaps = []
    rth_mask = (
        (df.index.time >= pd.Timestamp(RTH_START).time())
        & (df.index.time <= pd.Timestamp(RTH_END).time())
        & (df.index.weekday < 5)  # Mon-Fri only
    )
    rth_bars = df[rth_mask]

    if len(rth_bars) < 2:
        return gaps

    diffs = rth_bars.index.to_series().diff().dt.total_seconds() / 60
    large_gaps = diffs[diffs > MAX_RTH_GAP_MINUTES]

    for ts, minutes in large_gaps.items():
        prev_idx = rth_bars.index.get_loc(ts) - 1
        prev_ts = rth_bars.index[prev_idx]
        # Only flag gaps within the SAME trading day — overnight/weekend expected
        if prev_ts.date() == ts.date():
            gaps.append({"start": prev_ts, "end": ts, "minutes": int(minutes)})

    return gaps
