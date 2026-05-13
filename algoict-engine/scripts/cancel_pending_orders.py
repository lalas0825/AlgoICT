"""One-shot: cancel known pending TopstepX orders before bot restart.

Usage:
    python scripts/cancel_pending_orders.py <order_id> [order_id ...]
"""
import asyncio
import sys
from pathlib import Path

# Repo root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brokers.topstepx import TopstepXClient
import config


async def main(order_ids: list[str]) -> None:
    broker = TopstepXClient()
    # connect() starts WS too — fine for a one-shot; close() teardown is clean.
    await broker.connect()
    try:
        for oid in order_ids:
            try:
                ok = await broker.cancel_order(str(oid))
                print(f"cancel {oid}: {'OK' if ok else 'FAILED'}")
            except Exception as exc:
                print(f"cancel {oid}: EXCEPTION {exc!r}")
    finally:
        try:
            await broker.close()
        except Exception:
            pass


if __name__ == "__main__":
    ids = sys.argv[1:]
    if not ids:
        print("Usage: python scripts/cancel_pending_orders.py <order_id> [order_id ...]")
        sys.exit(1)
    asyncio.run(main(ids))
