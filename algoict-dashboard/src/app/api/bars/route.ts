/**
 * GET /api/bars?symbol=MNQ&timeframe=1m&limit=500
 *
 * Returns historical OHLCV bars for the chart.
 * Reads from the market_data Supabase table written by the engine.
 * Falls back to a synthetic random walk when the table is empty
 * (e.g. engine not yet running) so the chart always has something to render.
 */

import type { NextRequest } from 'next/server';
import { createClient } from '@/shared/lib/supabase-server';

type Timeframe = '1m' | '5m' | '15m' | '1H' | '4H' | 'D';

function isTimeframe(v: string | null): v is Timeframe {
  return v !== null && ['1m', '5m', '15m', '1H', '4H', 'D'].includes(v);
}

interface Candle {
  time: number;      // Unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── Supabase query ────────────────────────────────────────────────────────

async function fetchRealBars(
  symbol: string,
  timeframe: string,
  limit: number,
): Promise<Candle[] | null> {
  try {
    const supabase = await createClient();

    const { data, error } = await supabase
      .from('market_data')
      .select('timestamp, open, high, low, close, volume')
      .eq('symbol', symbol)
      .eq('timeframe', timeframe)
      .order('timestamp', { ascending: false })
      .limit(limit);

    if (error) {
      console.error('[api/bars] Supabase error:', error.message);
      return null;
    }
    if (!data || data.length === 0) return null;

    // Reverse so bars are oldest→newest (chart expects ascending time)
    return data
      .reverse()
      .map((row) => ({
        time: Math.floor(new Date(row.timestamp as string).getTime() / 1000),
        open: row.open as number,
        high: row.high as number,
        low: row.low as number,
        close: row.close as number,
        volume: (row.volume as number) ?? 0,
      }));
  } catch (e) {
    console.error('[api/bars] fetch failed:', e);
    return null;
  }
}

// ── Synthetic fallback ────────────────────────────────────────────────────

const TF_SECONDS: Record<Timeframe, number> = {
  '1m': 60,
  '5m': 5 * 60,
  '15m': 15 * 60,
  '1H': 60 * 60,
  '4H': 4 * 60 * 60,
  D: 24 * 60 * 60,
};

function syntheticBars(symbol: string, tf: Timeframe, limit: number): Candle[] {
  const step = TF_SECONDS[tf];
  const now = Math.floor(Date.now() / 1000);
  const endAligned = now - (now % step);

  let seed = 0;
  for (const ch of symbol) seed = (seed * 31 + ch.charCodeAt(0)) >>> 0;
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 0x100000000;
  };

  const bars: Candle[] = [];
  let price = 25000;
  for (let i = limit - 1; i >= 0; i--) {
    const t = endAligned - i * step;
    const drift = (rnd() - 0.5) * 8;
    const trend = Math.sin(i / 30) * 1.5;
    const open = price;
    const close = open + drift + trend;
    const high = Math.max(open, close) + rnd() * 3;
    const low = Math.min(open, close) - rnd() * 3;
    const volume = Math.floor(200 + rnd() * 1800);
    bars.push({
      time: t,
      open: Math.round(open * 100) / 100,
      high: Math.round(high * 100) / 100,
      low: Math.round(low * 100) / 100,
      close: Math.round(close * 100) / 100,
      volume,
    });
    price = close;
  }
  return bars;
}

// ── Handler ───────────────────────────────────────────────────────────────

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const symbol = (searchParams.get('symbol') ?? 'MNQ').toUpperCase();
  const tfRaw = searchParams.get('timeframe') ?? '1m';
  const limitRaw = parseInt(searchParams.get('limit') ?? '500', 10);

  if (!isTimeframe(tfRaw)) {
    return Response.json({ error: `invalid timeframe: ${tfRaw}` }, { status: 400 });
  }
  const limit = Math.max(50, Math.min(5000, isFinite(limitRaw) ? limitRaw : 500));

  // Try exact timeframe first
  const real = await fetchRealBars(symbol, tfRaw, limit);
  if (real && real.length > 0) {
    return Response.json({ symbol, timeframe: tfRaw, count: real.length, source: 'market_data', bars: real });
  }

  // Engine only writes 1m bars — if a higher TF was requested, try 1m
  if (tfRaw !== '1m') {
    const real1m = await fetchRealBars(symbol, '1m', limit);
    if (real1m && real1m.length > 0) {
      return Response.json({ symbol, timeframe: '1m', count: real1m.length, source: 'market_data_1m', bars: real1m });
    }
  }

  // Last resort: synthetic so the chart always renders
  const bars = syntheticBars(symbol, tfRaw, limit);
  return Response.json({ symbol, timeframe: tfRaw, count: bars.length, source: 'synthetic', bars });
}
