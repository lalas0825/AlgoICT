"""
Audit PWH/PWL/PDH/PDL computation against raw NQ CSV data.

Bot reported at 2026-04-23 01:00 CT:
  PDH = 27,100
  PDL = 26,848
  PWH = 27,138  <-- SUSPECT (user says should be ~26,883)
  PWL = 26,551.75

Load raw 1-min data, replicate tf_manager's aggregation, print last weeks/days
to verify.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.databento_loader import load_databento_ohlcv_1m
from timeframes.tf_manager import TimeframeManager

import pandas as pd


def main():
    print("Loading NQ 1-min data (last 2 months)...")
    df = load_databento_ohlcv_1m(
        Path("C:/AI Projects/AlgoICT/data/nq_1minute.csv"),
        start_date="2026-03-01",
        end_date="2026-04-23",
        symbol_prefix="NQ",
    )
    print(f"  {len(df):,} bars loaded")
    print(f"  Range: {df.index[0]} -> {df.index[-1]}")
    print(f"  Index tz: {df.index.tz}")
    print()

    tf = TimeframeManager()
    df_daily = tf.aggregate(df, "D")
    df_weekly = tf.aggregate(df, "W")

    print("=" * 100)
    print("LAST 10 DAILY BARS (as aggregated by bot's tf_manager):")
    print("=" * 100)
    print(df_daily.tail(10))
    print()

    print("=" * 100)
    print("LAST 5 WEEKLY BARS (as aggregated by bot):")
    print("=" * 100)
    print(df_weekly.tail(5))
    print()

    print("=" * 100)
    print("Bot's .iloc[-1] picks LAST ROW = this is what PWH/PWL reads from:")
    print("=" * 100)
    last_weekly = df_weekly.iloc[-1]
    print(f"  Timestamp: {df_weekly.index[-1]}")
    print(f"  Open:  {last_weekly['open']:.2f}")
    print(f"  High:  {last_weekly['high']:.2f}  <-- this is what bot uses as PWH")
    print(f"  Low:   {last_weekly['low']:.2f}   <-- this is what bot uses as PWL")
    print(f"  Close: {last_weekly['close']:.2f}")
    print(f"  Volume:{last_weekly['volume']:,}")
    print()

    last_daily = df_daily.iloc[-1]
    print(f"Bot's daily .iloc[-1]:")
    print(f"  Timestamp: {df_daily.index[-1]}")
    print(f"  High:  {last_daily['high']:.2f}  <-- used as PDH")
    print(f"  Low:   {last_daily['low']:.2f}   <-- used as PDL")
    print()

    # What was the ACTUAL previous completed week?
    print("=" * 100)
    print("WHAT THE BOT SHOULD USE (previous week excluding current forming one):")
    print("=" * 100)
    # Find the current week start: today is Thursday 2026-04-23, week of Apr 20-24
    today = pd.Timestamp("2026-04-23", tz="America/Chicago")
    # Monday of current week = Apr 20
    days_since_monday = today.dayofweek
    current_monday = today.normalize() - pd.Timedelta(days=days_since_monday)
    print(f"  Current Monday: {current_monday}")
    # Previous week Monday
    prev_monday = current_monday - pd.Timedelta(days=7)
    print(f"  Previous week Monday: {prev_monday}")

    # Filter weekly bars: last COMPLETED one should be labelled prev_monday
    for ts, row in df_weekly.tail(6).iterrows():
        status = "CURRENT (forming)" if ts >= current_monday else "completed"
        print(f"  {ts}  H={row['high']:>9.2f}  L={row['low']:>9.2f}  C={row['close']:>9.2f}  [{status}]")
    print()

    print("=" * 100)
    print("WHEN did high of 27,138 happen? Finding all 1-min bars with high >= 27,100:")
    print("=" * 100)
    spikes = df[df["high"] >= 27100].tail(30)
    for ts, row in spikes.iterrows():
        print(f"  {ts}  O={row['open']:.2f}  H={row['high']:.2f}  L={row['low']:.2f}  C={row['close']:.2f}  V={row['volume']}")


if __name__ == "__main__":
    main()
