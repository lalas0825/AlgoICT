"""
backtest/data_loader.py
========================
Load OHLCV data from CSV.
"""

import pandas as pd
from pathlib import Path


def load_data_csv(path) -> pd.DataFrame:
    """
    Load OHLCV CSV file.

    Expected columns: timestamp, open, high, low, close, volume (or similar)
    Returns: DataFrame with DatetimeIndex (UTC, converted to America/Chicago)
    """
    path = Path(path)
    df = pd.read_csv(path)

    # Expect at least: timestamp (or date/time), o, h, l, c, v
    # Rename to standard columns if needed
    col_map = {
        "time": "timestamp",
        "datetime": "timestamp",
        "date": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
    }
    df.rename(columns=col_map, inplace=True)

    # Ensure we have the 5 required columns
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV must contain columns: {required}")

    # Parse timestamp
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Set as index and convert to America/Chicago timezone
    df.set_index("timestamp", inplace=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/Chicago")

    # Ensure all OHLCV columns are float
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "volume" not in df.columns:
        df["volume"] = 0

    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    return df.sort_index()
