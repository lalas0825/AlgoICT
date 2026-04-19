'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';
import type {
  ChartAnnotations,
  FVGZone,
  OBZone,
  LiquidityLevel,
  GEXLevel,
  TradeMarker,
  LiquidityType,
  ZoneDirection,
  Timeframe,
} from '../types';

interface MarketLevelRow {
  id: string;
  symbol: string;
  type: string; // 'FVG' | 'OB' | 'liquidity' | 'call_wall' | 'put_wall' | 'gamma_flip' | ...
  price_low: number;
  price_high: number | null;
  direction: string | null;
  timeframe: string | null;
  active: boolean;
  detected_at: string;
  mitigated_at: string | null;
  metadata: Record<string, unknown> | null;
}

interface TradeRow {
  id: string;
  symbol: string;
  strategy: string;
  direction: 'long' | 'short';
  entry_price: number;
  entry_time: string;
  exit_price: number | null;
  exit_time: string | null;
  pnl: number | null;
  status: string;
}

const EMPTY: ChartAnnotations = {
  fvgZones: [],
  ifvgZones: [],
  obZones: [],
  liquidity: [],
  gexLevels: [],
  trades: [],
  trackedLevels: [],
  structureEvents: [],
  signals: [],
  displacement: null,
};

export function useChartAnnotations(
  symbol: string,
  timeframe: Timeframe,
  windowStart: number,
  windowEnd: number
) {
  const [annotations, setAnnotations] = useState<ChartAnnotations>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchData = async () => {
      try {
        setLoading(true);

        const [levelsRes, tradesRes] = await Promise.all([
          supabase
            .from('market_levels')
            .select('*')
            .eq('symbol', symbol)
            .eq('active', true)
            .gte('detected_at', new Date(windowStart).toISOString()),
          supabase
            .from('trades')
            .select('*')
            .eq('symbol', symbol)
            .gte('entry_time', new Date(windowStart).toISOString())
            .lte('entry_time', new Date(windowEnd).toISOString()),
        ]);

        if (cancelled) return;

        // Transform market_levels → typed annotations
        const levels = (levelsRes.data ?? []) as MarketLevelRow[];
        const fvgZones: FVGZone[] = [];
        const obZones: OBZone[] = [];
        const liquidity: LiquidityLevel[] = [];
        const gexLevels: GEXLevel[] = [];

        for (const row of levels) {
          const detectedAt = new Date(row.detected_at).getTime();
          const endAt = row.mitigated_at
            ? new Date(row.mitigated_at).getTime()
            : windowEnd;
          const dir = (row.direction ?? 'bullish') as ZoneDirection;

          switch (row.type) {
            case 'FVG':
              if (row.price_high != null) {
                fvgZones.push({
                  id: row.id,
                  time_start: detectedAt,
                  time_end: endAt,
                  price_low: row.price_low,
                  price_high: row.price_high,
                  direction: dir,
                  mitigated: row.mitigated_at != null,
                });
              }
              break;
            case 'OB':
              if (row.price_high != null) {
                obZones.push({
                  id: row.id,
                  time_start: detectedAt,
                  time_end: endAt,
                  price_low: row.price_low,
                  price_high: row.price_high,
                  direction: dir,
                });
              }
              break;
            case 'liquidity':
            case 'BSL':
            case 'SSL':
            case 'PDH':
            case 'PDL':
            case 'EQH':
            case 'EQL':
              liquidity.push({
                id: row.id,
                price: row.price_low,
                type: (row.type === 'liquidity'
                  ? 'BSL'
                  : row.type) as LiquidityType,
                time_detected: detectedAt,
                swept: row.mitigated_at != null,
              });
              break;
            case 'call_wall':
            case 'put_wall':
            case 'gamma_flip':
              gexLevels.push({
                type: row.type,
                price: row.price_low,
                label: String(row.metadata?.label ?? ''),
              });
              break;
          }
        }

        // Transform trades → entry/exit markers
        const tradeRows = (tradesRes.data ?? []) as TradeRow[];
        const trades: TradeMarker[] = [];
        for (const t of tradeRows) {
          trades.push({
            id: `${t.id}-entry`,
            time: new Date(t.entry_time).getTime(),
            price: t.entry_price,
            direction: t.direction,
            type: 'entry',
          });
          if (t.exit_time && t.exit_price != null) {
            trades.push({
              id: `${t.id}-exit`,
              time: new Date(t.exit_time).getTime(),
              price: t.exit_price,
              direction: t.direction,
              type: 'exit',
              pnl: t.pnl,
            });
          }
        }

        // NOTE: ifvgZones / trackedLevels / structureEvents / signals /
        // displacement are sourced separately from the `bot_state` JSONB
        // columns (migration 0003) via `useBotStateOverlay`. Page-level
        // composition merges the two. This hook stays focused on the
        // market_levels + trades tables.
        setAnnotations({
          fvgZones,
          ifvgZones: [],
          obZones,
          liquidity,
          gexLevels,
          trades,
          trackedLevels: [],
          structureEvents: [],
          signals: [],
          displacement: null,
        });
        setError(null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load annotations');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchData();
    return () => {
      cancelled = true;
    };
  }, [symbol, timeframe, windowStart, windowEnd]);

  return { annotations, loading, error };
}
