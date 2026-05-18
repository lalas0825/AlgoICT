"""One-shot broker cleanup: list + cancel open orders, flatten positions.

Run this AFTER killing the bot to clean any orphan/zombie state at broker
without launching the full engine.
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from brokers.topstepx import TopstepXClient


async def main():
    client = TopstepXClient(
        username=os.environ["TOPSTEPX_USERNAME"],
        api_key=os.environ["TOPSTEPX_API_KEY"],
        api_url=os.environ["TOPSTEPX_API_URL"],
        ws_url=os.environ.get("TOPSTEPX_WS_URL", ""),
    )
    await client.connect()

    # List open orders
    open_orders = await client.get_open_orders()
    print(f"\nOpen orders at broker: {len(open_orders)}")
    for o in open_orders:
        print(f"  order_id={o.get('id')} symbol={o.get('symbolId')} side={o.get('side')} "
              f"size={o.get('size')} type={o.get('type')} status={o.get('status')} "
              f"limitPrice={o.get('limitPrice')} stopPrice={o.get('stopPrice')}")

    # Cancel them all
    cancelled = []
    failed = []
    for o in open_orders:
        oid = o.get('id')
        try:
            ok = await client.cancel_order(str(oid))
            if ok:
                cancelled.append(oid)
                print(f"  -> CANCELLED {oid}")
            else:
                failed.append(oid)
                print(f"  -> FAILED {oid}")
        except Exception as exc:
            failed.append(oid)
            print(f"  -> ERROR {oid}: {exc}")

    # List positions (will use POST /Position/searchOpen)
    positions = await client.get_positions()
    print(f"\nOpen positions at broker: {len(positions)}")
    for p in positions:
        print(f"  {p}")

    if positions:
        print("\nFlattening...")
        await client.flatten_all()
        print("  done.")

    print(f"\nSummary:")
    print(f"  Orders cancelled: {len(cancelled)} {cancelled}")
    print(f"  Orders failed:    {len(failed)} {failed}")
    print(f"  Positions:        {len(positions)} (flattened if any)")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
