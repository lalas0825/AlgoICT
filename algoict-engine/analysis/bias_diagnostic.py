"""Bias diagnostic — recreate live vs backtest HTF bias divergence.

Hypothesis: live and backtest call same determine_bias() but feed it
different df_daily / df_weekly. Compute what each would produce at the
end of Thu 5/21 and compare.
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

import pandas as pd
from backtest.data_loader import load_data_csv
from timeframes.tf_manager import TimeframeManager
from timeframes.htf_bias import HTFBiasDetector


CSV = ENGINE_ROOT / "analysis" / "paridad_replay" / "live_bars_apr16_to_may22.csv"


def main():
    print("BIAS DIAGNOSTIC — reconstruct live vs backtest at Thu 5/21 end\n")
    df = load_data_csv(CSV)
    print(f"Loaded {len(df):,} bars, range {df.index[0]} -> {df.index[-1]}")

    tf = TimeframeManager()
    detector = HTFBiasDetector()

    # Reconstruct what live would see at end of Thu 5/21 (assuming
    # warmup = 21 days lookback = bars going back to ~April 30).
    # The bot's bars_1min cache at that moment contains ~21 days of bars
    # leading up to current time.
    thu_end = pd.Timestamp("2026-05-21 23:59:59", tz="UTC")
    live_lookback_start = thu_end - pd.Timedelta(days=21)
    live_bars = df[(df.index >= live_lookback_start) & (df.index <= thu_end)]
    print(f"\nLIVE simulation: bars[{live_bars.index[0]} -> {live_bars.index[-1]}] ({len(live_bars):,})")

    live_daily = tf.aggregate(live_bars, "D")
    live_weekly = tf.aggregate(live_bars, "W")
    print(f"  live df_daily ({len(live_daily)} bars):")
    for ts, row in live_daily.iterrows():
        print(f"    {ts}: O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f}")
    print(f"  live df_weekly ({len(live_weekly)} bars):")
    for ts, row in live_weekly.iterrows():
        print(f"    {ts}: O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f}")

    last_close = float(live_bars.iloc[-1]["close"])
    live_bias = detector.determine_bias(live_daily, live_weekly, last_close)
    print(f"\n  -> LIVE bias: {live_bias}")

    # Backtest: uses entire CSV (5 weeks of warmup loaded by --csv)
    print(f"\nBACKTEST simulation: bars[{df.index[0]} -> {thu_end}] ({len(df[df.index <= thu_end]):,})")
    bt_bars = df[df.index <= thu_end]
    bt_daily = tf.aggregate(bt_bars, "D")
    bt_weekly = tf.aggregate(bt_bars, "W")
    print(f"  backtest df_daily ({len(bt_daily)} bars):")
    for ts, row in bt_daily.iterrows():
        print(f"    {ts}: O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f}")
    print(f"  backtest df_weekly ({len(bt_weekly)} bars):")
    for ts, row in bt_weekly.iterrows():
        print(f"    {ts}: O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f}")

    bt_bias = detector.determine_bias(bt_daily, bt_weekly, last_close)
    print(f"\n  -> BACKTEST bias: {bt_bias}")

    print("\n" + "="*70)
    print("DIVERGENCE ANALYSIS")
    print("="*70)
    print(f"Live    daily_bias: {live_bias.daily_bias}    weekly_bias: {live_bias.weekly_bias}    -> direction: {live_bias.direction}")
    print(f"Backtest daily_bias: {bt_bias.daily_bias}    weekly_bias: {bt_bias.weekly_bias}    -> direction: {bt_bias.direction}")

    if live_bias.direction != bt_bias.direction:
        print("\n!!! DIVERGENCE CONFIRMED !!!")
        print(f"Daily bar count: live={len(live_daily)} vs backtest={len(bt_daily)}")
        print(f"Weekly bar count: live={len(live_weekly)} vs backtest={len(bt_weekly)}")
    else:
        print("\nNo divergence in this snapshot.")


if __name__ == "__main__":
    main()
