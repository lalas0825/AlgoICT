"""Verify the include_partial=True fix produces correct bias.

Run end-to-end: fetch daily + weekly via broker (with new partial flag),
convert via _bars_to_df, call HTFBiasDetector.determine_bias, print result.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from dotenv import load_dotenv
load_dotenv(ENGINE_ROOT / ".env")

import pandas as pd
from brokers.topstepx import TopstepXClient
from timeframes.htf_bias import HTFBiasDetector
from main import _bars_to_df


async def main():
    client = TopstepXClient(
        username=os.environ["TOPSTEPX_USERNAME"],
        api_key=os.environ["TOPSTEPX_API_KEY"],
    )
    await client.connect()
    contract = await client.lookup_contract("MNQ", live=False)
    end = datetime.now(timezone.utc)

    # Fetch with the new include_partial=True
    daily_raw = await client.get_historical_bars(
        contract_id=contract["id"],
        start=end - timedelta(days=90), end=end,
        unit=4, unit_number=1, limit=100,
        include_partial=True,
    )
    weekly_raw = await client.get_historical_bars(
        contract_id=contract["id"],
        start=end - timedelta(days=180), end=end,
        unit=5, unit_number=1, limit=30,
        include_partial=True,
    )

    daily_df = _bars_to_df(daily_raw)
    weekly_df = _bars_to_df(weekly_raw)

    print(f"DAILY df ({len(daily_df)} bars, last 5):")
    for ts, row in daily_df.tail(5).iterrows():
        print(f"  {ts}  O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f}")
    print(f"\nWEEKLY df ({len(weekly_df)} bars, last 5):")
    for ts, row in weekly_df.tail(5).iterrows():
        print(f"  {ts}  O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f}")

    # Bias compute
    detector = HTFBiasDetector()
    last_price = float(daily_df.iloc[-1]["close"])
    bias = detector.determine_bias(daily_df, weekly_df, last_price)
    print(f"\n--- BIAS (price={last_price:.2f}) ---")
    print(f"  direction:    {bias.direction}")
    print(f"  daily_bias:   {bias.daily_bias}")
    print(f"  weekly_bias:  {bias.weekly_bias}")
    print(f"  premium/disc: {bias.premium_discount}")
    print(f"  confidence:   {bias.confidence}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
