-- 2026-05-20 — Camino C4: Vision-overlay decisions
-- Bot sends chart images (1-min + 5-min) to Claude vision API at each
-- signal fire. Claude votes fire/skip/half based on visual validation
-- of bot's annotations against raw candles. Each row = one call.
--
-- Image data NOT stored here (too large). Charts are regenerable from
-- the timestamp + bars in market_data table if needed for audit.

CREATE TABLE IF NOT EXISTS vision_overlay_decisions (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kz TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('fire', 'skip', 'half')),
    size_multiplier REAL NOT NULL DEFAULT 1.0,
    confidence REAL NOT NULL DEFAULT 0.5,
    rationale TEXT,
    model TEXT,
    response_ms INTEGER,
    images_used INTEGER NOT NULL DEFAULT 0,    -- 0/1/2
    context JSONB,                              -- signal details + day state (image_b64 stripped)
    error TEXT,
    -- counterfactual fields filled by analysis script:
    actual_signal_pnl REAL,                    -- P&L of the signal-driven trade
    obeyed BOOLEAN,                             -- did bot follow Claude's vote
    counterfactual_pnl REAL,                   -- what P&L if obeyed
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_vision_overlay_decisions_ts ON vision_overlay_decisions(ts DESC);
CREATE INDEX IF NOT EXISTS idx_vision_overlay_decisions_kz ON vision_overlay_decisions(kz);
CREATE INDEX IF NOT EXISTS idx_vision_overlay_decisions_decision ON vision_overlay_decisions(decision);

ALTER TABLE vision_overlay_decisions DISABLE ROW LEVEL SECURITY;
