-- 2026-05-20 — Camino C2: AI Overlay decisions log
-- Each row = one Claude API call at a KZ entry (London/NY AM/NY PM).
-- In SHADOW mode (KZ_VALIDATOR_SHADOW_MODE=True), the bot logs every
-- decision here but does NOT act on it — used for counterfactual P&L
-- analysis after 3 weeks of data.
--
-- Counterfactual workflow:
--   1. Read ai_overlay_decisions for date range
--   2. For each decision, look up actual trades in that KZ from `trades`
--   3. Compute hypothetical P&L if bot had obeyed decision
--   4. Compare counterfactual vs actual to decide ship/kill

CREATE TABLE IF NOT EXISTS ai_overlay_decisions (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kz TEXT NOT NULL,                                  -- 'london' | 'ny_am' | 'ny_pm'
    decision TEXT NOT NULL CHECK (decision IN ('fire', 'skip', 'half')),
    size_multiplier REAL NOT NULL DEFAULT 1.0,         -- 1.0 = fire, 0.5 = half, 0.0 = skip
    confidence REAL NOT NULL DEFAULT 0.5,              -- 0.0 - 1.0
    rationale TEXT,                                    -- Claude's reasoning, ~200-500 chars
    model TEXT,                                        -- Claude model used
    response_ms INTEGER,                               -- API call latency
    context JSONB,                                     -- Full context sent to Claude
    error TEXT,                                        -- Parse/API error if any (nullable)
    -- counterfactual fields filled by analysis script:
    actual_kz_pnl REAL,                                -- Sum of trades' P&L in this KZ
    actual_kz_trades INTEGER,                          -- Count
    counterfactual_pnl REAL,                           -- P&L if bot had obeyed
    notes TEXT                                         -- Manual notes
);

CREATE INDEX IF NOT EXISTS idx_ai_overlay_decisions_ts ON ai_overlay_decisions(ts DESC);
CREATE INDEX IF NOT EXISTS idx_ai_overlay_decisions_kz ON ai_overlay_decisions(kz);
CREATE INDEX IF NOT EXISTS idx_ai_overlay_decisions_decision ON ai_overlay_decisions(decision);

-- RLS off for now (bot writes, manual reads)
ALTER TABLE ai_overlay_decisions DISABLE ROW LEVEL SECURITY;
