-- Migration 0002: market_data table
-- Stores 1-min OHLCV bars written by the AlgoICT engine.
-- The chart page reads from here instead of generating synthetic bars.

create table public.market_data (
  id          text        primary key,          -- '{symbol}_{timeframe}_{unix_ts}'
  timestamp   timestamptz not null,
  symbol      text        not null default 'MNQ',
  timeframe   text        not null default '1m',
  open        float8      not null,
  high        float8      not null,
  low         float8      not null,
  close       float8      not null,
  volume      int8        not null default 0,
  vpin_level  float8,                           -- nullable: set when VPIN is available
  created_at  timestamptz not null default now()
);

-- Index for the dashboard query: latest bars for a given symbol + timeframe
create index market_data_symbol_tf_ts
  on public.market_data (symbol, timeframe, timestamp desc);

-- RLS: read-only for anon (dashboard), write blocked from client
alter table public.market_data enable row level security;

create policy "anon_read" on public.market_data
  for select
  using (true);
