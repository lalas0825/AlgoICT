"""Bias snapshot per day at NY AM start — compare with live log values."""
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

# Times to check (Mon-Fri at NY AM open + NY PM)
SNAPSHOTS = [
    ("Mon 5/18 08:00 CT", "2026-05-18 13:00:00+00:00"),
    ("Tue 5/19 08:00 CT", "2026-05-19 13:00:00+00:00"),
    ("Wed 5/20 08:00 CT", "2026-05-20 13:00:00+00:00"),
    ("Thu 5/21 08:00 CT", "2026-05-21 13:00:00+00:00"),
    ("Thu 5/21 12:11 CT (trade #1 fire)", "2026-05-21 17:11:00+00:00"),
    ("Thu 5/21 13:41 CT (trade #2 fire)", "2026-05-21 18:41:00+00:00"),
    ("Fri 5/22 08:00 CT", "2026-05-22 13:00:00+00:00"),
]


def main():
    df = load_data_csv(CSV)
    tf = TimeframeManager()
    detector = HTFBiasDetector()
    print(f"Loaded {len(df):,} bars")
    print()
    print(f"{'Moment':<42} {'daily_bias':<10} {'weekly_bias':<11} {'direction':<10} {'#daily':<7} {'#weekly':<8}")
    print("-" * 100)

    for label, ts_str in SNAPSHOTS:
        ts = pd.Timestamp(ts_str)
        # Mimic live: only bars up to current ts, capped at 21 days lookback
        cutoff_start = ts - pd.Timedelta(days=21)
        bars = df[(df.index >= cutoff_start) & (df.index <= ts)]
        if len(bars) < 50:
            print(f"{label:<42} INSUFFICIENT BARS ({len(bars)})")
            continue
        df_daily = tf.aggregate(bars, "D")
        df_weekly = tf.aggregate(bars, "W")
        last_close = float(bars.iloc[-1]["close"])
        bias = detector.determine_bias(df_daily, df_weekly, last_close)
        print(f"{label:<42} {bias.daily_bias:<10} {bias.weekly_bias:<11} "
              f"{bias.direction:<10} {len(df_daily):<7} {len(df_weekly):<8}")


if __name__ == "__main__":
    main()
