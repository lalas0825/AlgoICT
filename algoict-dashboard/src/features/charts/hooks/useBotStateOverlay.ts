'use client';

/**
 * useBotStateOverlay
 * ==================
 * Subscribes to the `bot_state` singleton row (migration 0003 columns) and
 * projects its JSONB / scalar fields into the typed chart overlay shapes
 * the candlestick view consumes.
 *
 * The engine writes these every ~5 seconds from _make_state_snapshot /
 * _populate_detector_overlay in main.py. Supabase Realtime broadcasts the
 * UPDATE so the chart re-renders without re-polling.
 */

import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';
import type {
  FVGZone,
  OBZone,
  TrackedLevel,
  StructureEvent,
  Displacement,
  ZoneDirection,
  StructureEventType,
} from '../types';

export interface BotStateOverlay {
  /** Regular (non-IFVG) FVGs — top 3 nearest the last close on 5-min TF. */
  fvgTop3: FVGZone[];
  /** Inverted FVGs — top 3 nearest the last close on 5-min TF. */
  ifvgTop3: FVGZone[];
  /** Order Blocks — top 3 nearest the last close on 5-min TF. */
  obTop3: OBZone[];
  /** PDH/PDL/PWH/PWL + equal highs/lows + BSL/SSL. Includes swept flag. */
  trackedLevels: TrackedLevel[];
  /** Last 3 structure events on 15-min TF (most recent first). */
  structureEvents: StructureEvent[];
  /** Most recent 5-min displacement or null. */
  displacement: Displacement | null;
  /** Live session metadata for the info panel. */
  meta: BotStateMeta;
}

export interface BotStateMeta {
  biasDirection: 'bullish' | 'bearish' | 'neutral';
  biasZone: 'premium' | 'discount' | 'equilibrium' | '';
  dailyBias: 'bullish' | 'bearish' | 'neutral';
  weeklyBias: 'bullish' | 'bearish' | 'neutral';
  activeKz: string;              // '' when outside all KZ
  mllZone: 'normal' | 'warning' | 'caution' | 'stop';
  minConfluence: number;
  botStatus: 'running' | 'halted' | 'error' | 'stopped';
}

const EMPTY_META: BotStateMeta = {
  biasDirection: 'neutral',
  biasZone: '',
  dailyBias: 'neutral',
  weeklyBias: 'neutral',
  activeKz: '',
  mllZone: 'normal',
  minConfluence: 7,
  botStatus: 'running',
};

const EMPTY: BotStateOverlay = {
  fvgTop3: [],
  ifvgTop3: [],
  obTop3: [],
  trackedLevels: [],
  structureEvents: [],
  displacement: null,
  meta: EMPTY_META,
};

// ────────────────────────────────────────────────────────────────────────
// Row shape (what the JSONB columns hold — engine writes these in
// main._populate_detector_overlay). Defensive: everything optional so a
// partial row during rolling migrations doesn't explode the hook.
// ────────────────────────────────────────────────────────────────────────
interface FvgPayload {
  price_low: number;
  price_high: number;
  direction: ZoneDirection;
  tf: string;
  is_ifvg?: boolean;
  midpoint?: number;
  ts?: string;
}
interface ObPayload {
  price_low: number;
  price_high: number;
  direction: ZoneDirection;
  tf: string;
  ts?: string;
}
interface LevelPayload {
  price: number;
  type: string;
  swept: boolean;
  ts?: string;
}
interface StructPayload {
  type: string;
  direction: string;
  price: number;
  ts?: string;
}
interface DisplacementPayload {
  direction: 'bullish' | 'bearish';
  points: number;
  ts?: string;
}
interface BotStateRow {
  fvg_top3?: FvgPayload[] | null;
  ifvg_top3?: FvgPayload[] | null;
  ob_top3?: ObPayload[] | null;
  tracked_levels?: LevelPayload[] | null;
  struct_last3?: StructPayload[] | null;
  last_displacement?: DisplacementPayload | null;
  bias_direction?: string | null;
  bias_zone?: string | null;
  daily_bias?: string | null;
  weekly_bias?: string | null;
  active_kz?: string | null;
  mll_zone?: string | null;
  min_confluence?: number | null;
  bot_status?: string | null;
}

// ────────────────────────────────────────────────────────────────────────

function _tsToMs(ts: string | undefined): number {
  if (!ts) return Date.now();
  const parsed = Date.parse(ts);
  return Number.isNaN(parsed) ? Date.now() : parsed;
}

function _mapRow(row: BotStateRow): BotStateOverlay {
  const fvgTop3: FVGZone[] = (row.fvg_top3 ?? []).map((f, i) => ({
    id: `fvg_${i}_${f.ts ?? ''}`,
    time_start: _tsToMs(f.ts),
    // We don't have an explicit end ts from the engine — zones extend
    // to "now" until mitigation. The chart clamps to the visible range.
    time_end: Date.now() + 60 * 60 * 1000,
    price_low: f.price_low,
    price_high: f.price_high,
    direction: f.direction,
    mitigated: false,
  }));

  const ifvgTop3: FVGZone[] = (row.ifvg_top3 ?? []).map((f, i) => ({
    id: `ifvg_${i}_${f.ts ?? ''}`,
    time_start: _tsToMs(f.ts),
    time_end: Date.now() + 60 * 60 * 1000,
    price_low: f.price_low,
    price_high: f.price_high,
    direction: f.direction,
    mitigated: false,
  }));

  const obTop3: OBZone[] = (row.ob_top3 ?? []).map((o, i) => ({
    id: `ob_${i}_${o.ts ?? ''}`,
    time_start: _tsToMs(o.ts),
    time_end: Date.now() + 60 * 60 * 1000,
    price_low: o.price_low,
    price_high: o.price_high,
    direction: o.direction,
  }));

  const trackedLevels: TrackedLevel[] = (row.tracked_levels ?? []).map((l) => ({
    type: l.type,
    price: l.price,
    swept: !!l.swept,
  }));

  const structureEvents: StructureEvent[] = (row.struct_last3 ?? []).map((s) => {
    // Engine writes event_type e.g. "BOS", "MSS", "CHoCH". Direction as
    // "bullish" / "bearish". Tolerate casing drift.
    const type = (s.type || '').toUpperCase() as StructureEventType;
    const dir = (s.direction || '').toLowerCase();
    return {
      type: (['MSS', 'BOS', 'CHoCH'].includes(type) ? type : 'BOS') as StructureEventType,
      direction: dir === 'bearish' ? 'bearish' : 'bullish',
      time: _tsToMs(s.ts),
      price: s.price,
    };
  });

  const displacement: Displacement | null = row.last_displacement
    ? {
        direction:
          (row.last_displacement.direction === 'bearish' ? 'bearish' : 'bullish') as
          'bullish' | 'bearish',
        points: row.last_displacement.points,
        time: _tsToMs(row.last_displacement.ts),
      }
    : null;

  const meta: BotStateMeta = {
    biasDirection: (row.bias_direction ?? 'neutral') as BotStateMeta['biasDirection'],
    biasZone: (row.bias_zone ?? '') as BotStateMeta['biasZone'],
    dailyBias: (row.daily_bias ?? 'neutral') as BotStateMeta['dailyBias'],
    weeklyBias: (row.weekly_bias ?? 'neutral') as BotStateMeta['weeklyBias'],
    activeKz: row.active_kz ?? '',
    mllZone: (row.mll_zone ?? 'normal') as BotStateMeta['mllZone'],
    minConfluence: row.min_confluence ?? 7,
    botStatus: (row.bot_status ?? 'running') as BotStateMeta['botStatus'],
  };

  return { fvgTop3, ifvgTop3, obTop3, trackedLevels, structureEvents, displacement, meta };
}

export function useBotStateOverlay(): BotStateOverlay {
  const [overlay, setOverlay] = useState<BotStateOverlay>(EMPTY);

  useEffect(() => {
    let cancelled = false;

    // Initial fetch
    supabase
      .from('bot_state')
      .select(
        'fvg_top3, ifvg_top3, ob_top3, tracked_levels, struct_last3, ' +
        'last_displacement, bias_direction, bias_zone, daily_bias, ' +
        'weekly_bias, active_kz, mll_zone, min_confluence, bot_status',
      )
      .limit(1)
      .maybeSingle()
      .then(({ data }) => {
        if (cancelled || !data) return;
        setOverlay(_mapRow(data as unknown as BotStateRow));
      });

    // Realtime — any UPDATE to bot_state broadcasts the full new row.
    const channel = supabase
      .channel('chart-bot-state-overlay')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'bot_state' },
        (payload) => {
          if (!payload.new) return;
          setOverlay(_mapRow(payload.new as unknown as BotStateRow));
        },
      )
      .subscribe();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, []);

  return overlay;
}
