'use client';

/**
 * useSignalsLive
 * ==============
 * Streams the most recent `signals` rows for a symbol and keeps the list
 * synced via Supabase Realtime. Used by the chart overlay to render
 * "fire" arrows at the exact bar where the strategy emitted a signal —
 * distinct from the `trades` table which only contains confirmed
 * executions.
 */

import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';
import type { SignalMarker } from '../types';

interface SignalRow {
  id: string;
  timestamp: string;
  symbol: string;
  strategy: string | null;
  direction: 'long' | 'short';
  price: number;
  confluence_score: number;
}

const MAX_SIGNALS = 200;  // cap working set — chart only reads the visible slice anyway

function _rowToMarker(r: SignalRow): SignalMarker {
  return {
    id: r.id,
    time: Date.parse(r.timestamp),
    price: r.price,
    direction: r.direction,
    confluence_score: r.confluence_score,
    strategy: r.strategy ?? '',
  };
}

export function useSignalsLive(symbol: string): SignalMarker[] {
  const [signals, setSignals] = useState<SignalMarker[]>([]);

  useEffect(() => {
    let cancelled = false;

    // Initial pull — most recent N signals for this symbol.
    supabase
      .from('signals')
      .select('id, timestamp, symbol, strategy, direction, price, confluence_score')
      .eq('symbol', symbol)
      .order('timestamp', { ascending: false })
      .limit(MAX_SIGNALS)
      .then(({ data }) => {
        if (cancelled || !data) return;
        const mapped = (data as unknown as SignalRow[]).map(_rowToMarker);
        // Chart wants ascending time.
        mapped.sort((a, b) => a.time - b.time);
        setSignals(mapped);
      });

    // Realtime — any new INSERT appends to the tail. We don't handle
    // DELETEs — the engine doesn't delete signal rows, only inserts.
    const channel = supabase
      .channel(`chart-signals-${symbol}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'signals',
          filter: `symbol=eq.${symbol}`,
        },
        (payload) => {
          const row = payload.new as unknown as SignalRow;
          if (!row) return;
          setSignals((prev) => {
            const next = [...prev, _rowToMarker(row)];
            // Keep the list bounded + sorted.
            next.sort((a, b) => a.time - b.time);
            if (next.length > MAX_SIGNALS) next.splice(0, next.length - MAX_SIGNALS);
            return next;
          });
        },
      )
      .subscribe();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, [symbol]);

  return signals;
}
