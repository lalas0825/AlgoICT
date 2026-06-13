-- Migration 0007: Edge Hunt War Room
-- ===================================================================
-- Backs the dashboard's /edge-hunt page ("Edge Hunt War Room").
-- Python (analysis/publish_edge_hunt.py) WRITES; the dashboard READS.
-- Mirrors the project's READ-ONLY-dashboard rule: anon SELECT only,
-- writes blocked from the client (same policy shape as 0002 market_data).
--
-- The EDGE HUNT funnel (analysis/EDGE_HUNT_PLAN_20260612.md):
--   concept probe -> only the ASYMMETRIC ones become a strategy
--   -> 9 anti-overfit gates -> shadow live.
-- A concept SURVIVES Phase 1 iff in BOTH screening years (2019 AND 2022):
--   median(MFE_R)/median(MAE_R) >= 1.4  AND  P(MFE >= 2R) >= 30%.

-- -------------------------------------------------------------------
-- edge_hunt_runs: one row per (concept, screening year) probe result.
-- -------------------------------------------------------------------
create table if not exists public.edge_hunt_runs (
  id          text        primary key,          -- '{concept}_{year}', e.g. 'ob_retest_2019'
  concept     text        not null,             -- 'ob_retest', 'sweep_reclaim', 'f_disp', ...
  batch       text        not null,             -- 'phase1' | 'ob_retest_r2' | 'round3' | ...
  period_year text        not null,             -- '2019' | '2022' (screening) | '2023'... (validation)
  trades      int8        not null default 0,
  win_rate    float8,                           -- 0.0 - 1.0
  net_pnl     float8,                           -- sum(pnl) - sum(contracts * 1.74 fee)
  med_mfe_r   float8,                           -- median MFE in R
  med_mae_r   float8,                           -- median MAE in R
  ratio       float8,                           -- med_mfe_r / med_mae_r (asymmetry)
  p_mfe_2r    float8,                           -- P(MFE >= 2R), 0.0 - 1.0
  verdict     text,                             -- 'survives' | 'dies' | 'partial'
  created_at  timestamptz not null default now()
);

-- Dashboard groups by batch then concept; filters by batch.
create index if not exists edge_hunt_runs_batch_concept
  on public.edge_hunt_runs (batch, concept);

-- RLS: read-only for anon (dashboard), write blocked from client.
alter table public.edge_hunt_runs enable row level security;

create policy "anon_read" on public.edge_hunt_runs
  for select
  using (true);

-- -------------------------------------------------------------------
-- edge_hunt_state: single-row JSONB blob holding the funnel phases,
-- the closed-chapter SB autopsy cards, and the cycle-2 themes.
-- The publisher upserts id='current'; the dashboard reads that one row.
-- -------------------------------------------------------------------
create table if not exists public.edge_hunt_state (
  id          text        primary key,          -- always 'current'
  payload     jsonb       not null default '{}'::jsonb,
  updated_at  timestamptz not null default now()
);

-- RLS: read-only for anon (dashboard), write blocked from client.
alter table public.edge_hunt_state enable row level security;

create policy "anon_read" on public.edge_hunt_state
  for select
  using (true);
