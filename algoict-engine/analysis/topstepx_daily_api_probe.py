"""Probe TopstepX historical bars API for daily bars freshness.

Tests multiple parameter combinations to find one that returns the most
recent daily bar (currently stuck at 5/21, missing 5/22 Friday).
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

from brokers.topstepx import TopstepXClient


async def probe():
    client = TopstepXClient(
        username=os.environ["TOPSTEPX_USERNAME"],
        api_key=os.environ["TOPSTEPX_API_KEY"],
    )
    # Authenticate
    await client.connect()
    print(f"Authenticated\n")

    # Resolve contract
    contract = await client.lookup_contract("MNQ", live=False)
    print(f"Contract: {contract['id']}")
    print(f"Contract details: name={contract.get('name')} desc={contract.get('description','')[:60]}")
    print()

    end_now = datetime.now(timezone.utc)
    start_90 = end_now - timedelta(days=90)

    tests = [
        # Default (current bot behavior)
        ("DEFAULT include_partial=False", dict(unit=4, unit_number=1, limit=100, include_partial=False)),
        # Try include_partial=True
        ("include_partial=True", dict(unit=4, unit_number=1, limit=100, include_partial=True)),
        # Try larger limit
        ("limit=500 partial=True", dict(unit=4, unit_number=1, limit=500, include_partial=True)),
        # End slightly in the future to "force" current bar
        ("end+1d partial=True", dict(unit=4, unit_number=1, limit=100, include_partial=True), end_now + timedelta(days=1)),
        # Test with end set far in the future
        ("end+7d partial=True", dict(unit=4, unit_number=1, limit=100, include_partial=True), end_now + timedelta(days=7)),
        # Hourly comparison — should give us more recent data
        ("HOURLY unit=3 limit=72 partial=True", dict(unit=3, unit_number=1, limit=72, include_partial=True)),
    ]

    for label, params, *opt_end in tests:
        end = opt_end[0] if opt_end else end_now
        start = end - timedelta(days=90)
        try:
            bars = await client.get_historical_bars(
                contract_id=contract["id"],
                start=start, end=end,
                **params,
            )
            if not bars:
                print(f"[{label}] -> 0 bars returned")
                continue
            first_ts = bars[0]["timestamp"]
            last_ts = bars[-1]["timestamp"]
            last_close = bars[-1].get("close")
            print(f"[{label}]")
            print(f"  bars: {len(bars)}")
            print(f"  first: {first_ts}  last: {last_ts}  last_close: {last_close}")
            # Show last 5 bar timestamps
            print(f"  last 5 bar timestamps:")
            for b in bars[-5:]:
                ts = b["timestamp"]
                print(f"    {ts}  O={b.get('open'):.2f} H={b.get('high'):.2f} L={b.get('low'):.2f} C={b.get('close'):.2f} V={b.get('volume')}")
            print()
        except Exception as exc:
            print(f"[{label}] -> EXCEPTION: {exc}")
            print()

    # Also test with explicit "live" flag toggled. The bot hardcodes live=False
    # in payload. Let's try injecting live=True via monkey patch.
    print("=" * 70)
    print(" PROBE: payload-level live=True (override)")
    print("=" * 70)
    end = end_now
    start = end - timedelta(days=90)
    payload_override = {
        "contractId": contract["id"],
        "live": True,                    # << override
        "startTime": start.isoformat(),
        "endTime": end.isoformat(),
        "unit": 4, "unitNumber": 1,
        "limit": 100, "includePartialBar": True,
    }
    try:
        data = await client._post("/History/retrieveBars", payload_override)
        raw_bars = data.get("bars") or []
        print(f"  bars: {len(raw_bars)}")
        if raw_bars:
            # raw API returns newest-first
            print(f"  newest 5 (raw API order, may need parse):")
            for b in raw_bars[:5]:
                print(f"    {b}")
    except Exception as exc:
        print(f"  EXCEPTION: {exc}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(probe())
