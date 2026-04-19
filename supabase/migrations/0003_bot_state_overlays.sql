-- ==========================================================================
-- 0003_bot_state_overlays.sql
-- --------------------------------------------------------------------------
-- Extends `bot_state` so the dashboard chart can render the detector overlay
-- the engine already computes every bar (main.py:_log_bar_snapshot). Prior
-- to this migration the chart had to re-derive FVGs / OBs / tracked levels
-- from raw candles — the engine's own view was invisible.
--
-- Design: one JSONB column per collection (cheap to upsert every 5s, flexible
-- shape) plus a few scalar helpers the sidebar hits on every render.
--
-- Collections (all JSONB, default '[]'::jsonb unless noted):
--   fvg_top3          — [{price_low, price_high, direction, tf, is_ifvg,
--                         midpoint, ts}]     (top 3 nearest close)
--   ifvg_top3         — same shape as fvg_top3 but is_ifvg=true
--   ob_top3           — [{price_low, price_high, direction, tf, ts}]
--   tracked_levels    — [{price, type, swept, ts}]  where type in
--                         {"PDH","PDL","PWH","PWL","EQH","EQL","BSL","SSL"}
--   struct_last3      — [{type, direction, price, ts}]  type in
--                         {"MSS","BOS","CHoCH"}
--   last_displacement — nullable object {direction, points, ts}
--
-- Scalars (cheap to project in React):
--   bias_direction     TEXT  — 'bullish' | 'bearish' | 'neutral'
--   bias_zone          TEXT  — 'premium' | 'discount' | 'equilibrium'
--   daily_bias         TEXT  — per HTFBiasDetector last-completed-daily
--   weekly_bias        TEXT  — per HTFBiasDetector last-completed-weekly
--   active_kz          TEXT  — 'london' | 'ny_am' | 'silver_bullet' |
--                              'london_silver_bullet' | 'ny_pm' | ''
--   mll_zone           TEXT  — 'normal' | 'warning' | 'caution' | 'stop'
--   min_confluence     INT   — current effective_min_confluence from risk_mgr
--   bot_status         TEXT  — 'running' | 'halted' | 'error'
-- ==========================================================================

ALTER TABLE public.bot_state
    ADD COLUMN IF NOT EXISTS fvg_top3          JSONB   NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS ifvg_top3         JSONB   NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS ob_top3           JSONB   NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS tracked_levels    JSONB   NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS struct_last3      JSONB   NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS last_displacement JSONB,
    ADD COLUMN IF NOT EXISTS bias_direction    TEXT    NOT NULL DEFAULT 'neutral'
                             CHECK (bias_direction IN ('bullish','bearish','neutral')),
    ADD COLUMN IF NOT EXISTS bias_zone         TEXT    NOT NULL DEFAULT 'equilibrium'
                             CHECK (bias_zone IN ('premium','discount','equilibrium','')),
    ADD COLUMN IF NOT EXISTS daily_bias        TEXT    NOT NULL DEFAULT 'neutral'
                             CHECK (daily_bias IN ('bullish','bearish','neutral')),
    ADD COLUMN IF NOT EXISTS weekly_bias       TEXT    NOT NULL DEFAULT 'neutral'
                             CHECK (weekly_bias IN ('bullish','bearish','neutral')),
    ADD COLUMN IF NOT EXISTS active_kz         TEXT    NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS mll_zone          TEXT    NOT NULL DEFAULT 'normal'
                             CHECK (mll_zone IN ('normal','warning','caution','stop')),
    ADD COLUMN IF NOT EXISTS min_confluence    INTEGER NOT NULL DEFAULT 7
                             CHECK (min_confluence BETWEEN 0 AND 30),
    ADD COLUMN IF NOT EXISTS bot_status        TEXT    NOT NULL DEFAULT 'running'
                             CHECK (bot_status IN ('running','halted','error','stopped'));

-- Touch the updated_at trigger target so Realtime broadcasts the new shape.
COMMENT ON COLUMN public.bot_state.fvg_top3 IS
    'Top-3 nearest non-mitigated regular FVGs on the 5-min TF, JSONB array.';
COMMENT ON COLUMN public.bot_state.ifvg_top3 IS
    'Top-3 nearest active IFVGs on the 5-min TF (inverted FVGs).';
COMMENT ON COLUMN public.bot_state.ob_top3 IS
    'Top-3 nearest active Order Blocks on the 5-min TF.';
COMMENT ON COLUMN public.bot_state.tracked_levels IS
    'PDH/PDL/PWH/PWL + equal_highs/lows + BSL/SSL — swept flag flips via engine.';
COMMENT ON COLUMN public.bot_state.struct_last3 IS
    'Last 3 15-min structure events (MSS / BOS / CHoCH) most recent first.';
COMMENT ON COLUMN public.bot_state.last_displacement IS
    'Most recent 5-min displacement or NULL if none within the look-back window.';
