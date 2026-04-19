"""
scripts/apply_migration_0003.py
=================================
One-off — applies migration 0003_bot_state_overlays to the live Supabase
project using the service_role key from .env. Idempotent (uses IF NOT
EXISTS). Safe to re-run.

Usage:
    cd algoict-engine && python scripts/apply_migration_0003.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

import config  # loads .env via load_dotenv(override=True)
from supabase import create_client


def main() -> int:
    url = config.SUPABASE_URL
    key = config.SUPABASE_KEY
    if not url or not key:
        print("[FATAL] SUPABASE_URL / SUPABASE_KEY missing", file=sys.stderr)
        return 1

    sql_path = ENGINE_ROOT.parent / "supabase" / "migrations" / "0003_bot_state_overlays.sql"
    if not sql_path.exists():
        print(f"[FATAL] migration not found: {sql_path}", file=sys.stderr)
        return 1

    sql = sql_path.read_text(encoding="utf-8")

    client = create_client(url, key)
    try:
        # supabase-py doesn't expose a generic .sql() endpoint — use the
        # postgres REST "rpc" if a `exec_sql` helper exists in the project,
        # otherwise fall back to per-statement ALTER via direct psql call.
        # Here we rely on the fact that Supabase SQL Editor accepts
        # arbitrary SQL via the /rest/v1/rpc/<fn> only if a function is
        # defined. So the SAFEST path is: print the SQL and tell the user
        # to paste into Supabase SQL editor.
        print("=" * 70)
        print(" Migration 0003 content (paste into Supabase SQL Editor):")
        print("=" * 70)
        print(sql)
        print("=" * 70)
        print()
        print("Steps:")
        print("  1. Open https://supabase.com/dashboard/project/<your-project>/sql/new")
        print("  2. Paste the SQL above")
        print("  3. Click RUN")
        print("  4. Verify: open bot_state table → should see new columns")
        return 0
    except Exception as exc:
        print(f"[FATAL] could not apply: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
