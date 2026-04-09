# Supabase Setup — AlgoICT

This directory holds the SQL migration that creates the 8-table schema the
engine writes to and the dashboard reads from.

## Tables created

| Table | Writer | Reader |
|-------|--------|--------|
| `bot_state` | engine (heartbeat loop) | dashboard (home, controls, live) |
| `trades` | engine (on close) | dashboard (home, /trades) |
| `signals` | engine (on detect) | dashboard (/signals) |
| `daily_performance` | engine (session close) | — |
| `post_mortems` | engine (loss analysis) | dashboard (/post-mortems) |
| `market_levels` | engine (ICT + GEX detection) | dashboard (candlestick chart overlays) |
| `backtest_results` | backtest CLI | dashboard (/backtest) |
| `strategy_candidates` | Strategy Lab | dashboard (/strategy-lab) |

## How to apply the migration

**Option A — SQL Editor (simplest, works for any project):**

1. Open your Supabase project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** (left sidebar)
3. Click **New query**
4. Open `migrations/0001_init.sql` and copy the entire file contents
5. Paste into the SQL Editor
6. Click **Run** (bottom right, or press `Ctrl/Cmd + Enter`)

Expected result:
```
Success. No rows returned
```

**Option B — Supabase CLI (requires `supabase` CLI installed):**

```bash
supabase link --project-ref <your-project-ref>
supabase db push
```

The CLI will detect `supabase/migrations/0001_init.sql` and push it.

## Verify the migration worked

Run this query in the SQL Editor:

```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

Expected: **8 tables** in this order:
```
backtest_results
bot_state
daily_performance
market_levels
post_mortems
signals
strategy_candidates
trades
```

Then verify the singleton seed row:
```sql
SELECT id, is_running, swc_summary FROM public.bot_state;
```

Expected:
```
  id   | is_running |      swc_summary
-------+------------+--------------------------
 bot_1 | false      | Engine not connected yet.
```

## Verify Realtime is enabled

```sql
SELECT schemaname, tablename FROM pg_publication_tables
WHERE pubname = 'supabase_realtime'
ORDER BY tablename;
```

Expected: at least `bot_state`, `trades`, `signals`, `strategy_candidates`
in the list.

## Verify RLS policies

```sql
SELECT schemaname, tablename, policyname, roles
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename;
```

Expected: **8 SELECT policies** for the `anon` role — one per table.

## Smoke test end-to-end

1. Run the Python smoke test (verifies engine → Supabase writes work):

    ```bash
    cd algoict-engine
    python scripts/supabase_smoke_test.py
    ```

   This script:
   - Reads `SUPABASE_URL` + `SUPABASE_KEY` from `.env`
   - Writes a fake `bot_state` update
   - Reads it back
   - Exits 0 on success, non-zero on any error

2. Start the dashboard and check it shows the seed row:

    ```bash
    cd algoict-dashboard
    npm run dev
    ```

   Open http://localhost:3000 — the main dashboard should render with
   `BOT STOPPED`, `Engine not connected yet.`, VPIN 0.000, CALM.
   **If you see `Connecting to Supabase…` forever**, your dashboard
   `.env.local` is wrong or the anon key doesn't have read access.

3. Update `bot_state` from the SQL Editor and watch the dashboard update live:

    ```sql
    UPDATE public.bot_state
    SET is_running = TRUE, last_heartbeat = NOW()
    WHERE id = 'bot_1';
    ```

   The dashboard should flip to `BOT RUNNING` within ~1 second via
   Realtime subscription. If it doesn't, Realtime isn't enabled on
   `bot_state`.

## Rolling it back

No automated rollback yet. Manual:

```sql
DROP TABLE IF EXISTS public.post_mortems CASCADE;
DROP TABLE IF EXISTS public.strategy_candidates CASCADE;
DROP TABLE IF EXISTS public.backtest_results CASCADE;
DROP TABLE IF EXISTS public.market_levels CASCADE;
DROP TABLE IF EXISTS public.daily_performance CASCADE;
DROP TABLE IF EXISTS public.signals CASCADE;
DROP TABLE IF EXISTS public.trades CASCADE;
DROP TABLE IF EXISTS public.bot_state CASCADE;
```

## Known gotchas

- **`CHECK` violations on insert**: the schema enforces enum values for
  `status`, `direction`, `toxicity_level`, `swc_mood`, `gex_regime`,
  `reason_category`, `severity`. If you insert a value not in the list
  you'll get `new row for relation "X" violates check constraint`.
- **RLS blocks everything by default**: Supabase enables RLS on every
  new project. Without the policies in this migration, the `anon` role
  gets zero rows on any query. The engine uses `service_role` which
  bypasses RLS automatically — so if the dashboard sees `[]` but the
  engine sees data, check that the anon SELECT policies were created.
- **Realtime pushes row updates**, not query results. If you issue a
  query with `.order()` or `.limit()`, you'll get those filters on the
  initial read but subsequent Realtime events come as raw INSERT/UPDATE
  payloads — the dashboard's reducer is responsible for merging.
