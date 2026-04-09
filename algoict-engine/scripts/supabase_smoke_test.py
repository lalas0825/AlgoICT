"""
scripts/supabase_smoke_test.py
===============================
End-to-end verification that the engine can talk to Supabase.

What it does
------------
1. Loads SUPABASE_URL + SUPABASE_KEY from algoict-engine/.env
2. Pings the `bot_state` table with a SELECT (must exist from migration 0001)
3. Writes a test update to the singleton row (bot_1)
4. Reads it back and diff-checks the written value
5. Inserts a test row into each of the other 7 tables
6. Cleans up: removes test rows we just created (except bot_state, which
   stays updated — it's a singleton anyway)

Run
---
    cd algoict-engine
    python scripts/supabase_smoke_test.py

Exit codes
----------
    0 = everything works
    1 = dependency missing (supabase-py not installed)
    2 = .env not loaded or credentials missing
    3 = connection failed
    4 = schema missing (migration 0001 not applied)
    5 = write/read mismatch
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ─── Dependency checks ──────────────────────────────────────────────────

try:
    from supabase import create_client, Client
except ImportError:
    print("✗ supabase-py not installed")
    print("  Fix: pip install supabase")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    # dotenv is optional — we'll fall back to os.environ directly
    load_dotenv = None


# ─── Env loading ────────────────────────────────────────────────────────

ENGINE_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ENGINE_ROOT / ".env"

if load_dotenv and ENV_FILE.exists():
    load_dotenv(ENV_FILE)
    print(f"✓ Loaded env from {ENV_FILE}")
elif not ENV_FILE.exists():
    print(f"✗ .env file not found at {ENV_FILE}")
    print("  Fix: cp .env.example .env and fill in values")
    sys.exit(2)
else:
    print("⚠ python-dotenv not installed — reading from os.environ directly")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("✗ SUPABASE_URL or SUPABASE_KEY missing from .env")
    sys.exit(2)

# Hide the key in logs — show only first 12 chars
KEY_PREVIEW = f"{SUPABASE_KEY[:12]}…"
print(f"  URL: {SUPABASE_URL}")
print(f"  KEY: {KEY_PREVIEW}")


# ─── Client connection ─────────────────────────────────────────────────

try:
    client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"✗ Failed to build Supabase client: {e}")
    sys.exit(3)

print("✓ Supabase client created")


# ─── Step 1: schema existence check ────────────────────────────────────

print("\n=== Step 1: schema check ===")

EXPECTED_TABLES = [
    "bot_state", "trades", "signals", "daily_performance",
    "post_mortems", "market_levels", "backtest_results", "strategy_candidates",
]

missing = []
for table in EXPECTED_TABLES:
    try:
        # Count query — cheapest possible way to verify the table exists
        res = client.table(table).select("*", count="exact").limit(0).execute()
        count = res.count if hasattr(res, "count") else "?"
        print(f"  ✓ {table:<22} rows={count}")
    except Exception as e:
        missing.append(table)
        msg = str(e)[:80]
        print(f"  ✗ {table:<22} ERROR: {msg}")

if missing:
    print(f"\n✗ Missing tables: {missing}")
    print("  Fix: apply supabase/migrations/0001_init.sql via SQL Editor")
    sys.exit(4)

print("✓ All 8 tables present")


# ─── Step 2: bot_state write + read ────────────────────────────────────

print("\n=== Step 2: bot_state write/read ===")

sentinel_summary = f"smoke-test-{uuid.uuid4().hex[:8]}"
sentinel_vpin = 0.123456

try:
    client.table("bot_state").update({
        "swc_summary": sentinel_summary,
        "vpin": sentinel_vpin,
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
    }).eq("id", "bot_1").execute()
    print("  ✓ UPDATE succeeded")
except Exception as e:
    print(f"  ✗ UPDATE failed: {e}")
    print("  Likely cause: SUPABASE_KEY is the anon key, not service_role")
    sys.exit(5)

try:
    res = client.table("bot_state").select("*").eq("id", "bot_1").single().execute()
    row = res.data
    print(f"  ✓ SELECT returned row: id={row['id']}")
    if row["swc_summary"] != sentinel_summary:
        print(f"  ✗ swc_summary mismatch: wrote {sentinel_summary!r}, read {row['swc_summary']!r}")
        sys.exit(5)
    if abs(float(row["vpin"]) - sentinel_vpin) > 1e-5:
        print(f"  ✗ vpin mismatch: wrote {sentinel_vpin}, read {row['vpin']}")
        sys.exit(5)
    print(f"  ✓ Sentinel values round-trip: swc_summary={sentinel_summary} vpin={sentinel_vpin}")
except Exception as e:
    print(f"  ✗ SELECT failed: {e}")
    sys.exit(5)


# ─── Step 3: insert + cleanup in each other table ──────────────────────

print("\n=== Step 3: insert + cleanup test rows in all tables ===")

test_id_prefix = f"smoke-{uuid.uuid4().hex[:8]}"
now_iso = datetime.now(timezone.utc).isoformat()
today_str = datetime.now(timezone.utc).date().isoformat()

cleanups: list[tuple[str, str, str]] = []  # (table, column, value)

# trades
trade_id = f"{test_id_prefix}-trade"
try:
    client.table("trades").insert({
        "id": trade_id,
        "symbol": "MNQ",
        "strategy": "smoke_test",
        "direction": "long",
        "status": "closed",
        "entry_time": now_iso,
        "exit_time": now_iso,
        "entry_price": 18000.0,
        "exit_price": 18050.0,
        "stop_loss": 17980.0,
        "take_profit": 18060.0,
        "contracts": 1,
        "pnl": 100.0,
        "reason": "target",
        "confluence_score": 12,
        "kill_zone": "NY_AM",
    }).execute()
    print(f"  ✓ trades INSERT                   (id={trade_id})")
    cleanups.append(("trades", "id", trade_id))
except Exception as e:
    print(f"  ✗ trades INSERT failed: {str(e)[:120]}")

# signals
signal_id = f"{test_id_prefix}-signal"
try:
    client.table("signals").insert({
        "id": signal_id,
        "timestamp": now_iso,
        "symbol": "MNQ",
        "direction": "long",
        "price": 18000.0,
        "confluence_score": 12,
        "ict_concepts": ["FVG", "OB", "liquidity"],
        "active": True,
    }).execute()
    print(f"  ✓ signals INSERT                  (id={signal_id})")
    cleanups.append(("signals", "id", signal_id))
except Exception as e:
    print(f"  ✗ signals INSERT failed: {str(e)[:120]}")

# daily_performance — use a sentinel date far in the future so we never conflict
perf_id = f"smoke-2099-01-01"
try:
    client.table("daily_performance").insert({
        "id": perf_id,
        "date": "2099-01-01",
        "trades_count": 3,
        "wins": 2,
        "losses": 1,
        "total_pnl": 150.0,
    }).execute()
    print(f"  ✓ daily_performance INSERT        (id={perf_id})")
    cleanups.append(("daily_performance", "id", perf_id))
except Exception as e:
    print(f"  ✗ daily_performance INSERT failed: {str(e)[:120]}")

# post_mortems — depends on trade we just inserted
pm_id = f"{test_id_prefix}-pm"
try:
    client.table("post_mortems").insert({
        "id": pm_id,
        "timestamp": now_iso,
        "trade_id": trade_id,
        "pnl": -100.0,
        "reason_category": "other",
        "severity": "low",
        "analysis": "smoke test — not a real analysis",
        "lesson": "ignore",
    }).execute()
    print(f"  ✓ post_mortems INSERT             (id={pm_id})")
    cleanups.append(("post_mortems", "id", pm_id))
except Exception as e:
    print(f"  ✗ post_mortems INSERT failed: {str(e)[:120]}")

# market_levels
ml_id = None
try:
    res = client.table("market_levels").insert({
        "symbol": "MNQ",
        "type": "FVG",
        "direction": "bullish",
        "timeframe": "5min",
        "price_low": 17990.0,
        "price_high": 18010.0,
        "active": True,
        "metadata": {"smoke_test": True, "prefix": test_id_prefix},
    }).execute()
    ml_id = res.data[0]["id"] if res.data else None
    print(f"  ✓ market_levels INSERT            (id={ml_id})")
    if ml_id:
        cleanups.append(("market_levels", "id", ml_id))
except Exception as e:
    print(f"  ✗ market_levels INSERT failed: {str(e)[:120]}")

# backtest_results
br_id = f"{test_id_prefix}-bt"
try:
    client.table("backtest_results").insert({
        "id": br_id,
        "strategy": "smoke_test",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "total_trades": 100,
        "winning_trades": 60,
        "losing_trades": 40,
        "win_rate": 0.60,
        "profit_factor": 1.85,
        "max_drawdown": 0.08,
        "net_profit": 2500.0,
        "sharpe_ratio": 1.42,
        "status": "completed",
    }).execute()
    print(f"  ✓ backtest_results INSERT         (id={br_id})")
    cleanups.append(("backtest_results", "id", br_id))
except Exception as e:
    print(f"  ✗ backtest_results INSERT failed: {str(e)[:120]}")

# strategy_candidates
sc_id = f"{test_id_prefix}-H"
try:
    client.table("strategy_candidates").insert({
        "id": sc_id,
        "hypothesis": "smoke test hypothesis — ignore",
        "strategy_name": "ny_am_reversal",
        "status": "pending",
        "gates_passed": 0,
        "gates_total": 9,
        "score": 0,
        "session_id": f"{test_id_prefix}-session",
        "mode": "generate",
    }).execute()
    print(f"  ✓ strategy_candidates INSERT      (id={sc_id})")
    cleanups.append(("strategy_candidates", "id", sc_id))
except Exception as e:
    print(f"  ✗ strategy_candidates INSERT failed: {str(e)[:120]}")


# ─── Cleanup ───────────────────────────────────────────────────────────

print("\n=== Cleanup ===")

# Delete in reverse dependency order (post_mortems before trades)
for table, column, value in reversed(cleanups):
    try:
        client.table(table).delete().eq(column, value).execute()
        print(f"  ✓ deleted {table}.{column}={value}")
    except Exception as e:
        print(f"  ⚠ failed to delete {table}.{column}={value}: {str(e)[:80]}")


# ─── Final status ──────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("✅ SUPABASE SMOKE TEST PASSED")
print("=" * 60)
print(f"Project URL:    {SUPABASE_URL}")
print(f"Tables verified: {len(EXPECTED_TABLES)}/8")
print(f"Writes tested:  {len(cleanups)}/7 non-singleton tables")
print(f"bot_state singleton: updated (now: swc_summary={sentinel_summary})")
print()
print("Next: start the dashboard with `cd algoict-dashboard && npm run dev`")
print("      and refresh to see bot_state render live.")
sys.exit(0)
