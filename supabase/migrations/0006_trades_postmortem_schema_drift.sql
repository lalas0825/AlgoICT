-- ==========================================================================
-- 0006 — reconcile `trades` + `post_mortems` with the live engine's writes
-- ==========================================================================
-- 2026-05-29 forensic: every closed-trade insert 400'd (PGRST204) because the
-- engine's trade_dict (main.py _on_trade_closed) + write_trade()/
-- write_post_mortem() emit columns the 0001 schema never created, and `trades`
-- required stop_loss/take_profit (NOT NULL) that the trailing-mode engine no
-- longer sends. Net effect: trades + post-mortems silently never persisted.
--
-- Fix: add the engine's columns and relax the obsolete NOT NULL pair. The
-- engine expresses risk as stop_points + trailing exit, so a fixed
-- stop_loss / take_profit price is now optional.
-- ==========================================================================

ALTER TABLE public.trades
    ADD COLUMN IF NOT EXISTS ict_concepts        TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS stop_points         NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS signal_stop_points  NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS stop_was_trailed    BOOLEAN;

ALTER TABLE public.trades ALTER COLUMN stop_loss   DROP NOT NULL;
ALTER TABLE public.trades ALTER COLUMN take_profit DROP NOT NULL;

ALTER TABLE public.post_mortems
    ADD COLUMN IF NOT EXISTS entry_analysis TEXT;

COMMENT ON COLUMN public.trades.ict_concepts IS 'ICT structures at entry (sweep/FVG/OB/MSS). Added 0006 2026-05-29.';
COMMENT ON COLUMN public.trades.stop_points IS 'Realized stop distance (pts) at close. Added 0006.';
COMMENT ON COLUMN public.trades.signal_stop_points IS 'Stop distance (pts) at signal fire. Added 0006.';
COMMENT ON COLUMN public.trades.stop_was_trailed IS 'Trailing stop moved before exit. Added 0006.';
COMMENT ON COLUMN public.post_mortems.entry_analysis IS 'AI post-mortem entry analysis. Added 0006.';
