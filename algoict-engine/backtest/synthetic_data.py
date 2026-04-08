"""
backtest/synthetic_data.py
===========================
Generate synthetic OHLCV data for testing.
"""

import numpy as np
import pandas as pd
from pathlib import Path


def generate_synthetic_data(
    filename: str,
    start_date: str = "2023-01-01",
    end_date: str = "2025-12-31",
    trading_days_per_week: int = 5,
    bars_per_day: int = 390,     # 8:30-15:00 CT @ 1min
    start_price: float = 10000.0,
    volatility: float = 0.015,
) -> pd.DataFrame:
    """
    Generate synthetic OHLCV data suitable for backtest testing.

    Parameters
    ----------
    filename: Path to save CSV
    start_date, end_date: Date range (inclusive)
    trading_days_per_week: 5 for stocks/futures, 6-7 for crypto
    bars_per_day: 390 for equities RTH (08:30-15:00 CT)
    start_price: Starting price
    volatility: Daily volatility (std dev of daily returns)

    Returns
    -------
    DataFrame with: timestamp, open, high, low, close, volume
    """
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    # ── Generate date range (weekdays only) ───────────────────────────────
    date_range = pd.date_range(start_date, end_date, freq="D", tz="America/Chicago")
    weekday_mask = date_range.weekday < trading_days_per_week
    trading_dates = date_range[weekday_mask]

    # ── Generate 1-min timestamps ────────────────────────────────────────
    timestamps = []
    for date in trading_dates:
        # 8:30 AM to 3:00 PM CT (390 bars at 1-min intervals)
        day_times = pd.date_range(
            date.replace(hour=8, minute=30),
            date.replace(hour=15, minute=0),
            freq="1min",
            tz="America/Chicago",
        )
        timestamps.extend(day_times)

    # ── Generate price series (random walk with drift) ─────────────────────
    n = len(timestamps)
    np.random.seed(42)

    # Daily returns
    daily_returns = np.random.normal(0.0005, volatility, n // bars_per_day + 1)
    intraday_vol = volatility / 4  # intraday is noisier

    prices = [start_price]
    for i in range(1, n):
        if i % bars_per_day == 0:
            # New day: jump by daily return
            daily_idx = i // bars_per_day
            ret = daily_returns[daily_idx] if daily_idx < len(daily_returns) else 0.0
            prices.append(prices[-1] * (1 + ret))
        else:
            # Intraday noise
            ret = np.random.normal(0, intraday_vol)
            prices.append(prices[-1] * (1 + ret))

    prices = np.array(prices[:n])

    # ── Generate OHLCV ──────────────────────────────────────────────────
    ohlc_data = []
    for i, ts in enumerate(timestamps):
        close = prices[i]
        # Random intraday range
        open_price = close * (1 + np.random.normal(0, intraday_vol / 2))
        high = max(open_price, close) * (1 + np.random.uniform(0, 0.002))
        low = min(open_price, close) * (1 - np.random.uniform(0, 0.002))
        volume = int(np.random.uniform(100, 5000))

        ohlc_data.append({
            "timestamp": ts,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": volume,
        })

    df = pd.DataFrame(ohlc_data)

    # ── Save to CSV ──────────────────────────────────────────────────────
    df.to_csv(filename, index=False)
    print(f"Generated {len(df)} candles ({len(trading_dates)} trading days)")
    print(f"Saved to: {filename}")
    print(f"Period: {df['timestamp'].min()} to {df['timestamp'].max()}")

    return df


if __name__ == "__main__":
    generate_synthetic_data("../data/nq_1min.csv")
    generate_synthetic_data("../data/mnq_1min.csv")
