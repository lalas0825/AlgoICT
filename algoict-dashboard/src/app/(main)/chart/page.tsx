'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { UTCTimestamp, CandlestickData } from 'lightweight-charts';

import { LiveCandlestickChart } from '@/features/charts/components/LiveCandlestickChart';
import { useChartAnnotations } from '@/features/charts/hooks/useChartAnnotations';
import type { Timeframe } from '@/features/charts/types';
import { supabase } from '@/shared/lib/supabase';

const TIMEFRAMES: Timeframe[] = ['1m', '5m', '15m', '1H', '4H', 'D'];

interface BarApiCandle {
  time: number;       // unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface BarsResponse {
  symbol: string;
  timeframe: Timeframe;
  count: number;
  source: string;
  bars: BarApiCandle[];
}

// Minimal projection of bot_state fields we display in the sidebar
interface BotStateLite {
  vpin: number | null;
  toxicity_level: string | null;
  gex_regime: string | null;
  gex_call_wall: number | null;
  gex_put_wall: number | null;
  gex_flip_point: number | null;
  last_signal: string | null;
}

const DEFAULT_STATE: BotStateLite = {
  vpin: null,
  toxicity_level: null,
  gex_regime: null,
  gex_call_wall: null,
  gex_put_wall: null,
  gex_flip_point: null,
  last_signal: null,
};

export default function ChartPage() {
  const symbol = 'MNQ';
  const [timeframe, setTimeframe] = useState<Timeframe>('1m');
  const [bars, setBars] = useState<CandlestickData<UTCTimestamp>[]>([]);
  const [loadingBars, setLoadingBars] = useState(true);
  const [barsError, setBarsError] = useState<string | null>(null);
  const [botState, setBotState] = useState<BotStateLite>(DEFAULT_STATE);
  const [lastBar, setLastBar] = useState<CandlestickData<UTCTimestamp> | null>(null);

  // ── Fetch historical bars whenever timeframe changes ──────────────
  useEffect(() => {
    let cancelled = false;
    setLoadingBars(true);
    setBarsError(null);
    fetch(`/api/bars?symbol=${symbol}&timeframe=${timeframe}&limit=500`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as BarsResponse;
      })
      .then((data) => {
        if (cancelled) return;
        const mapped: CandlestickData<UTCTimestamp>[] = data.bars.map((b) => ({
          time: b.time as UTCTimestamp,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }));
        setBars(mapped);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setBarsError(e instanceof Error ? e.message : 'Failed to load bars');
      })
      .finally(() => {
        if (!cancelled) setLoadingBars(false);
      });
    return () => {
      cancelled = true;
    };
  }, [timeframe]);

  // ── Live window for the annotations hook ──────────────────────────
  const { windowStart, windowEnd } = useMemo(() => {
    if (bars.length === 0) {
      const end = Date.now();
      return { windowStart: end - 24 * 60 * 60 * 1000, windowEnd: end };
    }
    return {
      windowStart: (bars[0].time as number) * 1000,
      windowEnd: (bars[bars.length - 1].time as number) * 1000,
    };
  }, [bars]);

  const { annotations } = useChartAnnotations(symbol, timeframe, windowStart, windowEnd);

  // ── Live bot_state subscription for sidebar ───────────────────────
  useEffect(() => {
    let cancelled = false;

    supabase
      .from('bot_state')
      .select('*')
      .limit(1)
      .maybeSingle()
      .then(({ data }) => {
        if (!cancelled && data) setBotState(data as unknown as BotStateLite);
      });

    const channel = supabase
      .channel('chart-bot-state')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'bot_state' },
        (payload) => {
          if (payload.new) setBotState(payload.new as unknown as BotStateLite);
        },
      )
      .subscribe();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, []);

  // ── Realtime: market_data inserts → update last candle ───────────
  useEffect(() => {
    const channel = supabase
      .channel(`chart-market-data-${timeframe}`)
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'market_data',
          filter: `symbol=eq.${symbol}`,
        },
        (payload) => {
          const row = payload.new as {
            timestamp: string;
            open: number;
            high: number;
            low: number;
            close: number;
            volume: number;
            timeframe: string;
          };
          // Only update chart if the incoming bar matches the current timeframe
          if (row.timeframe !== timeframe) return;
          const bar: CandlestickData<UTCTimestamp> = {
            time: Math.floor(new Date(row.timestamp).getTime() / 1000) as UTCTimestamp,
            open: row.open,
            high: row.high,
            low: row.low,
            close: row.close,
          };
          setLastBar(bar);
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [symbol, timeframe]);

  const handleTimeframeChange = useCallback((tf: Timeframe) => {
    setTimeframe(tf);
    setLastBar(null); // clear stale real-time bar when switching timeframe
  }, []);

  // ── Derived header stats ──────────────────────────────────────────
  const lastClose = bars.length > 0 ? bars[bars.length - 1].close : null;
  const firstClose = bars.length > 0 ? bars[0].close : null;
  const change = lastClose != null && firstClose != null ? lastClose - firstClose : null;
  const changePct = change != null && firstClose ? (change / firstClose) * 100 : null;

  const activeFVGs = annotations.fvgZones.filter((f) => !f.mitigated).length;
  const activeOBs = annotations.obZones.length;

  return (
    <div className="px-6 py-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-zinc-50">Chart — {symbol}</h1>
          <div className="mt-1 flex items-center gap-3 text-sm">
            <span className="text-zinc-300 font-mono text-base">
              {lastClose != null ? `$${lastClose.toFixed(2)}` : '—'}
            </span>
            {change != null && (
              <span
                className={`font-mono ${change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}
              >
                {change >= 0 ? '+' : ''}
                {change.toFixed(2)} ({changePct!.toFixed(2)}%)
              </span>
            )}
          </div>
        </div>

        {/* Timeframe switcher */}
        <div className="flex items-center gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => handleTimeframeChange(tf)}
              className={`px-3 py-1 text-xs font-mono rounded transition ${
                tf === timeframe
                  ? 'bg-zinc-700 text-zinc-50'
                  : 'text-zinc-400 hover:text-zinc-100'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-5 gap-4">
        {/* Chart: 4/5 columns */}
        <div className="col-span-4">
          {loadingBars && bars.length === 0 && (
            <div className="h-[640px] flex items-center justify-center text-zinc-500 border border-zinc-800 rounded-xl">
              Loading bars…
            </div>
          )}
          {barsError && (
            <div className="h-[640px] flex items-center justify-center text-red-400 border border-zinc-800 rounded-xl">
              {barsError}
            </div>
          )}
          {!barsError && bars.length > 0 && (
            <LiveCandlestickChart
              candles={bars}
              annotations={annotations}
              lastBar={lastBar}
            />
          )}
        </div>

        {/* Sidebar: 1/5 columns */}
        <aside className="col-span-1 flex flex-col gap-3">
          <SidebarCard title="Price">
            <div className="text-2xl font-mono font-bold text-zinc-50 leading-none">
              {lastClose != null ? `$${lastClose.toFixed(2)}` : '—'}
            </div>
            {change != null && (
              <div
                className={`text-sm font-mono mt-1 ${
                  change >= 0 ? 'text-emerald-400' : 'text-red-400'
                }`}
              >
                {change >= 0 ? '+' : ''}
                {change.toFixed(2)} ({changePct!.toFixed(2)}%)
              </div>
            )}
          </SidebarCard>

          <SidebarCard title="VPIN">
            <VPINGaugeMini
              value={botState.vpin}
              label={botState.toxicity_level ?? 'unknown'}
            />
          </SidebarCard>

          <SidebarCard title="GEX Regime">
            <GEXBadge regime={botState.gex_regime} />
            {botState.gex_call_wall != null && (
              <div className="mt-2 space-y-1 font-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-zinc-500">Call wall</span>
                  <span className="text-red-400">
                    {botState.gex_call_wall.toFixed(0)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">Put wall</span>
                  <span className="text-emerald-400">
                    {botState.gex_put_wall?.toFixed(0) ?? '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">Gamma flip</span>
                  <span className="text-yellow-400">
                    {botState.gex_flip_point?.toFixed(0) ?? '—'}
                  </span>
                </div>
              </div>
            )}
          </SidebarCard>

          <SidebarCard title="ICT Zones">
            <div className="space-y-1 font-mono text-xs">
              <div className="flex justify-between">
                <span className="text-zinc-500">Active FVGs</span>
                <span className="text-blue-400">{activeFVGs}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Active OBs</span>
                <span className="text-purple-400">{activeOBs}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Liquidity</span>
                <span className="text-amber-400">{annotations.liquidity.length}</span>
              </div>
            </div>
          </SidebarCard>

          <SidebarCard title="Last Signal">
            <div className="text-xs text-zinc-300 break-words font-mono">
              {botState.last_signal || 'No signals yet'}
            </div>
          </SidebarCard>
        </aside>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Sidebar sub-components
// ─────────────────────────────────────────────────────────────────────

function SidebarCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium mb-2">
        {title}
      </div>
      {children}
    </div>
  );
}

function VPINGaugeMini({
  value,
  label,
}: {
  value: number | null;
  label: string;
}) {
  if (value == null) {
    return <div className="text-zinc-500 text-sm">no data</div>;
  }
  const pct = Math.min(100, Math.max(0, value * 100));
  const color =
    value >= 0.7
      ? 'bg-red-500'
      : value >= 0.55
        ? 'bg-orange-500'
        : value >= 0.45
          ? 'bg-yellow-500'
          : 'bg-emerald-500';
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <div className="text-xl font-mono font-bold text-zinc-50 leading-none">
          {value.toFixed(3)}
        </div>
        <div className="text-[10px] uppercase tracking-wider text-zinc-400">
          {label}
        </div>
      </div>
      <div className="h-2 bg-zinc-800 rounded overflow-hidden">
        <div
          className={`h-full ${color} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function GEXBadge({ regime }: { regime: string | null }) {
  const label = regime ?? 'unknown';
  const style =
    regime === 'positive'
      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
      : regime === 'negative'
        ? 'bg-red-500/15 text-red-300 border-red-500/30'
        : 'bg-zinc-800 text-zinc-400 border-zinc-700';
  return (
    <span
      className={`inline-block px-2 py-0.5 text-[11px] uppercase tracking-wider border rounded font-mono ${style}`}
    >
      {label}
    </span>
  );
}
