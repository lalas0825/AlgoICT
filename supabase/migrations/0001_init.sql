-- ==========================================================================
-- AlgoICT — Initial Schema Migration (0001_init.sql)
-- ==========================================================================
-- Creates 8 tables + indexes + RLS policies + Realtime publication.
--
-- Design rules:
--   * Every table has Row Level Security enabled.
--   * anon role (dashboard) gets SELECT-only on everything.
--   * service_role (engine) bypasses RLS entirely — no policy needed.
--   * Realtime is enabled on tables the dashboard subscribes to live.
--
-- Safe to re-run: all CREATE statements use IF NOT EXISTS.
-- Apply via Supabase Dashboard → SQL Editor → paste → Run.
-- ==========================================================================

-- ─── Extensions ─────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()


-- ==========================================================================
-- 1. bot_state — singleton row with live engine state
-- ==========================================================================
CREATE TABLE IF NOT EXISTS public.bot_state (
    id                   TEXT PRIMARY KEY DEFAULT 'bot_1',
    is_running           BOOLEAN NOT NULL DEFAULT FALSE,
    last_heartbeat       TIMESTAMPTZ,

    -- VPIN / Toxicity Shield
    vpin                 NUMERIC(10, 6) NOT NULL DEFAULT 0,
    toxicity_level       TEXT NOT NULL DEFAULT 'calm'
                         CHECK (toxicity_level IN ('calm','normal','elevated','high','extreme')),
    shield_active        BOOLEAN NOT NULL DEFAULT FALSE,

    -- Daily P&L
    trades_today         INTEGER NOT NULL DEFAULT 0,
    pnl_today            NUMERIC(12, 2) NOT NULL DEFAULT 0,
    daily_high_pnl       NUMERIC(12, 2) NOT NULL DEFAULT 0,
    max_loss_threshold   NUMERIC(12, 2) NOT NULL DEFAULT -1000,
    profit_cap           NUMERIC(12, 2) NOT NULL DEFAULT 1500,
    position_count       INTEGER NOT NULL DEFAULT 0,
    wins_today           INTEGER NOT NULL DEFAULT 0,
    losses_today         INTEGER NOT NULL DEFAULT 0,

    -- SWC (Sentiment-Weighted Confluence)
    swc_mood             TEXT NOT NULL DEFAULT 'choppy'
                         CHECK (swc_mood IN ('risk_on','risk_off','event_driven','choppy')),
    swc_confidence       NUMERIC(4, 3) NOT NULL DEFAULT 0,
    swc_summary          TEXT DEFAULT '',

    -- GEX (Gamma Exposure)
    gex_regime           TEXT NOT NULL DEFAULT 'unknown'
                         CHECK (gex_regime IN ('positive','negative','flip','unknown')),
    gex_call_wall        NUMERIC(12, 2),
    gex_put_wall         NUMERIC(12, 2),
    gex_flip_point       NUMERIC(12, 2),

    last_signal          TEXT,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.bot_state IS 'Singleton row (id=bot_1) with live engine state. Heartbeat older than 15s = offline; 30s = auto-flatten.';


-- ==========================================================================
-- 2. trades — completed and open trades
-- ==========================================================================
CREATE TABLE IF NOT EXISTS public.trades (
    id                TEXT PRIMARY KEY,
    symbol            TEXT NOT NULL,
    strategy          TEXT NOT NULL,
    direction         TEXT NOT NULL CHECK (direction IN ('long','short')),
    status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','closed','cancelled')),

    entry_time        TIMESTAMPTZ NOT NULL,
    exit_time         TIMESTAMPTZ,
    entry_price       NUMERIC(12, 4) NOT NULL,
    exit_price        NUMERIC(12, 4),
    stop_loss         NUMERIC(12, 4) NOT NULL,
    take_profit       NUMERIC(12, 4) NOT NULL,

    contracts         INTEGER NOT NULL,
    pnl               NUMERIC(12, 2),
    reason            TEXT,  -- 'target' | 'stop' | 'hard_close' | 'manual'
    confluence_score  INTEGER NOT NULL,
    kill_zone         TEXT,
    duration_bars     INTEGER,

    -- Edge context at entry
    vpin              NUMERIC(10, 6),
    toxicity          TEXT,
    gex_regime        TEXT,
    swc_mood          TEXT,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_entry_time
    ON public.trades (entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status
    ON public.trades (status);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_entry_time
    ON public.trades (symbol, entry_time DESC);

COMMENT ON TABLE public.trades IS 'Completed and open trades. id format: {symbol}_{entry_time} or UUID.';


-- ==========================================================================
-- 3. signals — every signal the strategy generates (whether taken or not)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS public.signals (
    id                TEXT PRIMARY KEY,
    timestamp         TIMESTAMPTZ NOT NULL,
    symbol            TEXT NOT NULL,
    strategy          TEXT,
    direction         TEXT NOT NULL CHECK (direction IN ('long','short')),
    level             TEXT,  -- level that triggered (e.g. '5min OB')
    price             NUMERIC(12, 4) NOT NULL,
    confluence_score  INTEGER NOT NULL,

    -- ICT concept flags (individual booleans + aggregated array for the UI)
    ict_concepts      TEXT[] DEFAULT '{}',
    liquidity_grab    BOOLEAN DEFAULT FALSE,
    fair_value_gap    BOOLEAN DEFAULT FALSE,
    order_block       BOOLEAN DEFAULT FALSE,
    market_structure  BOOLEAN DEFAULT FALSE,

    -- Edge context
    vpin              NUMERIC(10, 6),
    gex_regime        TEXT,
    kill_zone         TEXT,
    active            BOOLEAN NOT NULL DEFAULT TRUE,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signals_timestamp
    ON public.signals (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_timestamp
    ON public.signals (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_signals_active
    ON public.signals (active) WHERE active = TRUE;

COMMENT ON TABLE public.signals IS 'Every 20-point confluence signal detected by the strategy.';


-- ==========================================================================
-- 4. daily_performance — per-day P&L roll-up
-- ==========================================================================
CREATE TABLE IF NOT EXISTS public.daily_performance (
    id               TEXT PRIMARY KEY,  -- YYYY-MM-DD
    date             DATE NOT NULL UNIQUE,
    trades_count     INTEGER NOT NULL DEFAULT 0,
    wins             INTEGER NOT NULL DEFAULT 0,
    losses           INTEGER NOT NULL DEFAULT 0,
    total_pnl        NUMERIC(12, 2) NOT NULL DEFAULT 0,
    max_drawdown     NUMERIC(8, 4),
    sharpe           NUMERIC(8, 4),
    best_trade       NUMERIC(12, 2),
    worst_trade      NUMERIC(12, 2),
    violations       INTEGER NOT NULL DEFAULT 0,  -- Topstep rule violations
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_daily_perf_date
    ON public.daily_performance (date DESC);

COMMENT ON TABLE public.daily_performance IS 'Per-day P&L summary. Written at session close.';


-- ==========================================================================
-- 5. post_mortems — AI loss analysis
-- ==========================================================================
CREATE TABLE IF NOT EXISTS public.post_mortems (
    id               TEXT PRIMARY KEY,
    timestamp        TIMESTAMPTZ NOT NULL,
    trade_id         TEXT NOT NULL REFERENCES public.trades(id) ON DELETE CASCADE,
    pnl              NUMERIC(12, 2) NOT NULL,

    reason_category  TEXT NOT NULL CHECK (reason_category IN (
        'htf_misread','premature_entry','stop_too_tight','stop_too_wide',
        'news_event','false_signal','overtrading','htf_resistance','other'
    )),
    severity         TEXT NOT NULL DEFAULT 'medium'
                     CHECK (severity IN ('low','medium','high')),

    analysis         TEXT NOT NULL,
    lesson           TEXT NOT NULL,
    related_trades   TEXT[] DEFAULT '{}',

    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_post_mortems_timestamp
    ON public.post_mortems (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_post_mortems_trade_id
    ON public.post_mortems (trade_id);
CREATE INDEX IF NOT EXISTS idx_post_mortems_category
    ON public.post_mortems (reason_category);

COMMENT ON TABLE public.post_mortems IS 'AI-generated loss analysis. Each row maps to one losing trade.';


-- ==========================================================================
-- 6. market_levels — ICT + GEX overlays for the candlestick chart
-- ==========================================================================
CREATE TABLE IF NOT EXISTS public.market_levels (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol            TEXT NOT NULL,
    type              TEXT NOT NULL CHECK (type IN (
        'FVG','OB','liquidity','BSL','SSL','PDH','PDL','EQH','EQL',
        'call_wall','put_wall','gamma_flip'
    )),
    direction         TEXT CHECK (direction IN ('bullish','bearish') OR direction IS NULL),
    timeframe         TEXT,  -- '1min' | '5min' | '15min' | '1H' | '4H' | 'D'

    price_low         NUMERIC(12, 4) NOT NULL,
    price_high        NUMERIC(12, 4),  -- NULL for line-type levels

    active            BOOLEAN NOT NULL DEFAULT TRUE,
    detected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mitigated_at      TIMESTAMPTZ,

    metadata          JSONB DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_levels_symbol_active
    ON public.market_levels (symbol, active, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_levels_symbol_type
    ON public.market_levels (symbol, type);

COMMENT ON TABLE public.market_levels IS 'ICT zones (FVG, OB, liquidity) and GEX levels (walls, flip). Chart overlays.';


-- ==========================================================================
-- 7. backtest_results — history of backtest runs
-- ==========================================================================
CREATE TABLE IF NOT EXISTS public.backtest_results (
    id                TEXT PRIMARY KEY,
    strategy          TEXT NOT NULL,
    start_date        DATE NOT NULL,
    end_date          DATE NOT NULL,

    total_trades      INTEGER NOT NULL DEFAULT 0,
    winning_trades    INTEGER NOT NULL DEFAULT 0,
    losing_trades     INTEGER NOT NULL DEFAULT 0,
    win_rate          NUMERIC(6, 3) NOT NULL DEFAULT 0,
    profit_factor     NUMERIC(8, 4) NOT NULL DEFAULT 0,
    max_drawdown      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    net_profit        NUMERIC(12, 2) NOT NULL DEFAULT 0,
    sharpe_ratio      NUMERIC(8, 4) NOT NULL DEFAULT 0,

    status            TEXT NOT NULL DEFAULT 'completed'
                      CHECK (status IN ('running','completed','failed')),

    config            JSONB DEFAULT '{}'::jsonb,  -- min_confluence, risk, etc.
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_created_at
    ON public.backtest_results (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_strategy
    ON public.backtest_results (strategy);

COMMENT ON TABLE public.backtest_results IS 'Historical backtest runs with metrics and config.';


-- ==========================================================================
-- 8. strategy_candidates — Strategy Lab output (9-gate pipeline)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS public.strategy_candidates (
    id                   TEXT PRIMARY KEY,  -- e.g. 'H-001'
    hypothesis           TEXT NOT NULL,
    strategy_name        TEXT NOT NULL,

    status               TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','running','passed','failed','approved','rejected')),

    gates_passed         INTEGER NOT NULL DEFAULT 0,
    gates_total          INTEGER NOT NULL DEFAULT 9,
    score                INTEGER NOT NULL DEFAULT 0,  -- 0-100 composite
    gate_results         JSONB DEFAULT '{}'::jsonb,

    sharpe_improvement   NUMERIC(8, 4),
    net_profit_delta     NUMERIC(12, 2),

    session_id           TEXT NOT NULL,
    mode                 TEXT DEFAULT 'generate'
                         CHECK (mode IN ('generate','overnight','custom')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at          TIMESTAMPTZ,
    approved_by          TEXT,
    notes                TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidates_created_at
    ON public.strategy_candidates (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_session_id
    ON public.strategy_candidates (session_id);
CREATE INDEX IF NOT EXISTS idx_candidates_status
    ON public.strategy_candidates (status);
CREATE INDEX IF NOT EXISTS idx_candidates_score
    ON public.strategy_candidates (score DESC);

COMMENT ON TABLE public.strategy_candidates IS 'Strategy Lab hypotheses with 9-gate results. approved=ready for Test Set.';


-- ==========================================================================
-- Row Level Security — anon gets read-only, service_role bypasses everything
-- ==========================================================================

ALTER TABLE public.bot_state            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trades               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.signals              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_performance    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_mortems         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.market_levels        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.backtest_results     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.strategy_candidates  ENABLE ROW LEVEL SECURITY;

-- Drop existing policies first (idempotency)
DROP POLICY IF EXISTS "anon read bot_state"           ON public.bot_state;
DROP POLICY IF EXISTS "anon read trades"              ON public.trades;
DROP POLICY IF EXISTS "anon read signals"             ON public.signals;
DROP POLICY IF EXISTS "anon read daily_performance"   ON public.daily_performance;
DROP POLICY IF EXISTS "anon read post_mortems"        ON public.post_mortems;
DROP POLICY IF EXISTS "anon read market_levels"       ON public.market_levels;
DROP POLICY IF EXISTS "anon read backtest_results"    ON public.backtest_results;
DROP POLICY IF EXISTS "anon read strategy_candidates" ON public.strategy_candidates;

-- Anon (dashboard) = read-only on every table
CREATE POLICY "anon read bot_state"
    ON public.bot_state FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon read trades"
    ON public.trades FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon read signals"
    ON public.signals FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon read daily_performance"
    ON public.daily_performance FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon read post_mortems"
    ON public.post_mortems FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon read market_levels"
    ON public.market_levels FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon read backtest_results"
    ON public.backtest_results FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon read strategy_candidates"
    ON public.strategy_candidates FOR SELECT TO anon USING (TRUE);

-- service_role (engine) automatically bypasses RLS — no policies needed.


-- ==========================================================================
-- Realtime — enable on tables the dashboard subscribes to
-- ==========================================================================
-- These are the tables where the dashboard uses .channel().on('postgres_changes'):
--   * bot_state           (live heartbeat, VPIN, shield)
--   * trades              (new trades appear, status updates)
--   * signals             (new signals appear)
--   * strategy_candidates (lab sessions write progress live)

-- ALTER PUBLICATION can fail if the publication exists with different
-- membership. We use a DO block to add tables one at a time, ignoring
-- "already exists" errors so the migration stays idempotent.
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY[
        'bot_state', 'trades', 'signals', 'strategy_candidates'
    ])
    LOOP
        BEGIN
            EXECUTE format(
                'ALTER PUBLICATION supabase_realtime ADD TABLE public.%I',
                tbl
            );
        EXCEPTION
            WHEN duplicate_object THEN
                RAISE NOTICE 'Table %.% already in supabase_realtime publication', 'public', tbl;
        END;
    END LOOP;
END $$;


-- ==========================================================================
-- Seed: singleton bot_state row so the dashboard renders something on first load
-- ==========================================================================
INSERT INTO public.bot_state (id, is_running, last_heartbeat, swc_summary)
VALUES ('bot_1', FALSE, NOW(), 'Engine not connected yet.')
ON CONFLICT (id) DO NOTHING;


-- ==========================================================================
-- Done. Verify with:
--   SELECT table_name FROM information_schema.tables
--   WHERE table_schema = 'public' ORDER BY table_name;
-- Expected: 8 tables.
-- ==========================================================================
