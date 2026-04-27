"""Broker audit: query TopstepX API for today's actual trade history."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

USERNAME = os.environ["TOPSTEPX_USERNAME"]
API_KEY = os.environ["TOPSTEPX_API_KEY"]
API_URL = os.environ.get("TOPSTEPX_API_URL", "https://api.topstepx.com/api")


async def main() -> int:
    async with aiohttp.ClientSession() as session:
        # Auth
        async with session.post(
            f"{API_URL}/Auth/loginKey",
            json={"userName": USERNAME, "apiKey": API_KEY},
        ) as resp:
            if resp.status != 200:
                print("Auth failed:", resp.status, await resp.text())
                return 1
            data = await resp.json()
        token = data.get("token") or data.get("accessToken") or data.get("jwt")
        H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Account
        async with session.post(
            f"{API_URL}/Account/search", json={"onlyActiveAccounts": True}, headers=H,
        ) as resp:
            accs = (await resp.json()).get("accounts", [])
        acc = next((a for a in accs if "PRAC" in (a.get("name") or "").upper()), accs[0])
        print(f"=== ACCOUNT id={acc['id']} name={acc.get('name')} balance=${acc.get('balance'):.2f} ===")

        # Time range: previous 24h to capture full session
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=24)

        # ----- Trades -----
        print(f"\n=== TRADES {start.isoformat()} -> {end.isoformat()} ===")
        async with session.post(
            f"{API_URL}/Trade/search",
            json={"accountId": acc["id"], "startTimestamp": start.isoformat(), "endTimestamp": end.isoformat()},
            headers=H,
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                print(f"  FAILED {resp.status}: {text}")
                trades = []
            else:
                trades = json.loads(text).get("trades", [])
                total_pnl = 0.0
                total_fees = 0.0
                print(f"  {len(trades)} trades")
                for t in trades:
                    ts = t.get("creationTimestamp", t.get("timestamp", "?"))
                    side = "SELL" if t.get("side") == 1 else "BUY"
                    sz = t.get("size", 0)
                    px = t.get("price", 0) or 0
                    pnl = float(t.get("profitAndLoss") or t.get("pnl") or 0)
                    fees = float(t.get("fees") or 0)
                    total_pnl += pnl
                    total_fees += fees
                    print(f"  {ts}  {side:4s} {sz:>3d} @ {px:>10.2f}  pnl={pnl:+10.2f}  fees={fees:.2f}  oid={t.get('orderId','?')}")
                print(f"  ---")
                print(f"  TOTAL realized P&L: {total_pnl:+.2f}")
                print(f"  TOTAL fees:         {total_fees:.2f}")
                print(f"  NET P&L:            {total_pnl - total_fees:+.2f}")

        # ----- Open positions -----
        print(f"\n=== OPEN POSITIONS ===")
        async with session.post(
            f"{API_URL}/Position/searchOpen",
            json={"accountId": acc["id"]}, headers=H,
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                print(f"  FAILED {resp.status}: {text}")
            else:
                positions = json.loads(text).get("positions", [])
                if not positions:
                    print("  none")
                for p in positions:
                    sz = p.get("size", 0)
                    side = "LONG" if (p.get("type") == 1 or sz > 0) else "SHORT"
                    avg = p.get("averagePrice", 0)
                    print(f"  {side} {abs(sz)}x {p.get('contractId','?')} avg={avg:.2f}")

        # ----- Orders -----
        print(f"\n=== ORDERS today ===")
        async with session.post(
            f"{API_URL}/Order/search",
            json={"accountId": acc["id"], "startTimestamp": start.isoformat(), "endTimestamp": end.isoformat()},
            headers=H,
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                print(f"  FAILED {resp.status}: {text}")
            else:
                orders = json.loads(text).get("orders", [])
                status_map = {1: "OPEN", 2: "FILLED", 3: "CANCEL", 4: "EXPIRE", 5: "REJECT"}
                type_map = {1: "LIMIT", 2: "MARKET", 3: "STOP", 4: "TRAILSTOP"}
                print(f"  {len(orders)} orders")
                for o in orders:
                    ts = o.get("creationTimestamp", "?")
                    s = status_map.get(o.get("status"), str(o.get("status")))
                    typ = type_map.get(o.get("type"), str(o.get("type")))
                    side = "SELL" if o.get("side") == 1 else "BUY"
                    sz = o.get("size", 0)
                    lp = o.get("limitPrice")
                    sp = o.get("stopPrice")
                    fillPx = o.get("fillPrice") or o.get("averagePrice")
                    fillVol = o.get("filledVolume") or o.get("fillVolume")
                    px = f"{lp:.2f}" if lp else (f"{sp:.2f}" if sp else "")
                    fpx = f"{fillPx:.2f}" if fillPx else ""
                    print(f"  {ts}  oid={o.get('id')}  {s:6s} {typ:8s} {side:4s} {sz:>3d} px={px:>9s} fillPx={fpx:>8s} fillVol={fillVol}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
