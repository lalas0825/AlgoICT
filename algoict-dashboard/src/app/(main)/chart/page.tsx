'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { UTCTimestamp, CandlestickData, HistogramData } from 'lightweight-charts';

import {
  LiveCandlestickChart,
  type OverlayToggles,
} from '@/features/charts/components/LiveCandlestickChart';
import { useChartAnnotations } from '@/features/charts/hooks/useChartAnnotations';
import { useBotStateOverlay } from '@/features/charts/hooks/useBotStateOverlay';
import { useSignalsLive } from '@/features/charts/hooks/useSignalsLive';
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
  const [volumes, setVolumes] = useState<HistogramData<UTCTimestamp>[]>([]);
  const [loadingBars, setLoadingBars] = useState(true);
  const [barsError, setBarsError] = useState<string | null>(null);
  const [botState, setBotState] = useState<BotStateLite>(DEFAULT_STATE);
  const [lastBar, setLastBar] = useState<CandlestickData<UTCTimestamp> | null>(null);
  const [overlays, setOverlays] = useState<OverlayToggles>({
    volume: true,
    killZones: true,
    fvgZones: true,
    obZones: true,
    levels: true,
    trades: true,
  });

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
        const vol: HistogramData<UTCTimestamp>[] = data.bars
          .filter((b) => b.volume > 0)
          .map((b) => ({
            time: b.time as UTCTimestamp,
            value: b.volume,
            color: b.close >= b.open
              ? 'rgba(16, 185, 129, 0.55)'
              : 'rgba(239, 68, 68, 0.55)',
          }));
        setBars(mapped);
        setVolumes(vol);
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

  const { annotations: marketAnnotations } = useChartAnnotations(
    symbol, timeframe, windowStart, windowEnd,
  );
  const overlay = useBotStateOverlay();
  const signals = useSignalsLive(symbol);

  // Compose market_levels (FVGs / OBs / GEX / trades) with the live
  // bot_state overlay (IFVGs / tracked_levels / structure events /
  // displacement) plus the signals stream from the signals table.
  // Memoized so the chart effect doesn't re-fire on every other setState.
  const annotations = useMemo(() => ({
    ...marketAnnotations,
    // Phase 2 additions from bot_state:
    ifvgZones: overlay.ifvgTop3,
    trackedLevels: overlay.trackedLevels,
    structureEvents: overlay.structureEvents,
    displacement: overlay.displacement,
    // Phase 3: signal fires live-streamed from the signals table.
    signals,
    // bot_state always has fresher top-3 FVGs than a detached market_levels
    // table — prefer it when populated, fall back to market_levels queries.
    fvgZones: overlay.fvgTop3.length > 0 ? overlay.fvgTop3 : marketAnnotations.fvgZones,
    obZones:  overlay.obTop3.length  > 0 ? overlay.obTop3  : marketAnnotations.obZones,
  }), [marketAnnotations, overlay, signals]);

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
  //
  // The engine writes ONLY 1-min bars. For higher timeframes the chart
  // needs to aggregate the incoming 1-min tick into the active bucket:
  //   - If the 1-min bar's bucket timestamp equals the chart's last bar
  //     → mutate in place (high=max, low=min, close=incoming, keep open)
  //   - If it's a new bucket (the prior bucket fully closed)
  //     → append a fresh candle with the 1-min bar's OHLC as seed
  // 1m mode still passes through directly.
  useEffect(() => {
    const tfSeconds =
      timeframe === '1m'  ? 60 :
      timeframe === '5m'  ? 5 * 60 :
      timeframe === '15m' ? 15 * 60 :
      timeframe === '1H'  ? 60 * 60 :
      timeframe === '4H'  ? 4 * 60 * 60 :
      /* D */              24 * 60 * 60;

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
          // Engine only emits 1m rows — ignore anything else defensively.
          if (row.timeframe !== '1m') return;

          const rowSec = Math.floor(new Date(row.timestamp).getTime() / 1000);
          const bucketSec = Math.floor(rowSec / tfSeconds) * tfSeconds;

          setLastBar((prev) => {
            if (prev && (prev.time as number) === bucketSec) {
              // Same bucket — aggregate into existing candle
              return {
                time: bucketSec as UTCTimestamp,
                open: prev.open,
                high: Math.max(prev.high, row.high),
                low: Math.min(prev.low, row.low),
                close: row.close,
              };
            }
            // New bucket — seed a fresh candle with this 1-min bar's OHLC
            return {
              time: bucketSec as UTCTimestamp,
              open: row.open,
              high: row.high,
              low: row.low,
              close: row.close,
            };
          });
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
  // Prefer the live `lastBar` (pushed via Supabase Realtime on each 1-min tick)
  // over the static `bars` array, so the header price updates live instead of
  // only on timeframe changes.
  const lastClose =
    lastBar?.close ?? (bars.length > 0 ? bars[bars.length - 1].close : null);
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
            <>
              <OverlayToggleBar overlays={overlays} setOverlays={setOverlays} />
              <LiveCandlestickChart
                candles={bars}
                volumes={volumes}
                annotations={annotations}
                lastBar={lastBar}
                overlays={overlays}
              />
            </>
          )}
        </div>

        {/* Sidebar: 1/5 columns */}
        <aside className="col-span-1 flex flex-col gap-3">
          {/* Phase 4: Live bot info panel — reads bot_state overlay fields */}
          <BotInfoPanel
            overlay={overlay}
            pnlToday={/* pnl_today is on the bigger bot_state row */
              (botState as unknown as { pnl_today?: number }).pnl_today ?? null}
            tradesToday={(botState as unknown as { trades_today?: number }).trades_today ?? null}
            winsToday={(botState as unknown as { wins_today?: number }).wins_today ?? null}
            lossesToday={(botState as unknown as { losses_today?: number }).losses_today ?? null}
            swcMood={(botState as unknown as { swc_mood?: string }).swc_mood ?? null}
            vpin={botState.vpin}
            toxicity={botState.toxicity_level}
          />

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

function BotInfoPanel({
  overlay,
  pnlToday,
  tradesToday,
  winsToday,
  lossesToday,
  swcMood,
  vpin,
  toxicity,
}: {
  overlay: ReturnType<typeof useBotStateOverlay>;
  pnlToday: number | null;
  tradesToday: number | null;
  winsToday: number | null;
  lossesToday: number | null;
  swcMood: string | null;
  vpin: number | null;
  toxicity: string | null;
}) {
  const m = overlay.meta;
  const pnlColor =
    pnlToday == null ? 'text-zinc-400' :
    pnlToday > 0 ? 'text-emerald-400' :
    pnlToday < 0 ? 'text-red-400' : 'text-zinc-300';
  const mllColor =
    m.mllZone === 'stop' ? 'bg-red-500/20 text-red-300 border-red-500/40' :
    m.mllZone === 'caution' ? 'bg-orange-500/15 text-orange-300 border-orange-500/30' :
    m.mllZone === 'warning' ? 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30' :
    'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
  const statusColor =
    m.botStatus === 'running' ? 'text-emerald-400' :
    m.botStatus === 'halted' ? 'text-orange-400' :
    m.botStatus === 'error' ? 'text-red-400' :
    'text-zinc-400';
  const vpinColor =
    vpin == null ? 'text-zinc-400' :
    vpin >= 0.70 ? 'text-red-400' :
    vpin >= 0.55 ? 'text-orange-400' :
    vpin >= 0.45 ? 'text-yellow-400' :
    'text-emerald-400';

  const kzLabel = m.activeKz ? m.activeKz.replace(/_/g, ' ') : 'none';
  const kzColor =
    m.activeKz === 'london' ? 'text-blue-300' :
    m.activeKz === 'ny_am' ? 'text-emerald-300' :
    m.activeKz === 'silver_bullet' || m.activeKz === 'london_silver_bullet' ? 'text-amber-300' :
    m.activeKz === 'ny_pm' ? 'text-orange-300' :
    'text-zinc-500';

  return (
    <SidebarCard title="Live Bot">
      <div className="space-y-2 text-xs font-mono">
        <div className="flex items-baseline justify-between">
          <span className="text-zinc-500">Status</span>
          <span className={`uppercase tracking-wider font-semibold ${statusColor}`}>
            {m.botStatus}
          </span>
        </div>

        <div className="flex items-baseline justify-between">
          <span className="text-zinc-500">Active KZ</span>
          <span className={kzColor}>{kzLabel}</span>
        </div>

        <hr className="border-zinc-800 my-1.5" />

        <div className="flex items-baseline justify-between">
          <span className="text-zinc-500">Bias</span>
          <span className={
            m.biasDirection === 'bullish' ? 'text-emerald-400' :
            m.biasDirection === 'bearish' ? 'text-red-400' :
            'text-zinc-400'
          }>
            {m.biasDirection}
            {m.biasZone ? <span className="text-zinc-500"> ({m.biasZone})</span> : null}
          </span>
        </div>
        <div className="flex items-baseline justify-between text-[10px] text-zinc-500">
          <span>d={m.dailyBias}</span>
          <span>w={m.weeklyBias}</span>
        </div>

        <hr className="border-zinc-800 my-1.5" />

        <div className="flex items-baseline justify-between">
          <span className="text-zinc-500">VPIN</span>
          <span className={vpinColor}>
            {vpin != null ? vpin.toFixed(3) : '—'}
            {toxicity ? <span className="text-zinc-500 text-[10px] ml-1">({toxicity})</span> : null}
          </span>
        </div>

        <div className="flex items-baseline justify-between">
          <span className="text-zinc-500">SWC mood</span>
          <span className="text-zinc-300">{swcMood ?? '—'}</span>
        </div>

        <hr className="border-zinc-800 my-1.5" />

        <div className="flex items-baseline justify-between">
          <span className="text-zinc-500">MLL zone</span>
          <span className={`px-1.5 py-0.5 text-[10px] uppercase tracking-wider border rounded ${mllColor}`}>
            {m.mllZone}
          </span>
        </div>

        <div className="flex items-baseline justify-between">
          <span className="text-zinc-500">Min conf</span>
          <span className="text-zinc-300">{m.minConfluence}/19</span>
        </div>

        <hr className="border-zinc-800 my-1.5" />

        <div className="flex items-baseline justify-between">
          <span className="text-zinc-500">P&amp;L today</span>
          <span className={`${pnlColor} font-bold`}>
            {pnlToday != null ?
              `${pnlToday >= 0 ? '+' : ''}$${pnlToday.toFixed(0)}` :
              '—'}
          </span>
        </div>

        <div className="flex items-baseline justify-between">
          <span className="text-zinc-500">Trades</span>
          <span className="text-zinc-300">
            {tradesToday ?? 0}
            {winsToday != null && lossesToday != null && (
              <span className="text-zinc-500 ml-1">
                ({winsToday}W {lossesToday}L)
              </span>
            )}
          </span>
        </div>

        {overlay.displacement && (
          <>
            <hr className="border-zinc-800 my-1.5" />
            <div className="flex items-baseline justify-between">
              <span className="text-zinc-500">Last disp</span>
              <span className={
                overlay.displacement.direction === 'bullish' ? 'text-emerald-400' : 'text-red-400'
              }>
                {overlay.displacement.direction === 'bullish' ? '↑' : '↓'}
                {' '}
                {overlay.displacement.points.toFixed(1)} pts
              </span>
            </div>
          </>
        )}
      </div>
    </SidebarCard>
  );
}

function OverlayToggleBar({
  overlays,
  setOverlays,
}: {
  overlays: OverlayToggles;
  setOverlays: React.Dispatch<React.SetStateAction<OverlayToggles>>;
}) {
  const items: Array<{ key: keyof OverlayToggles; label: string }> = [
    { key: 'volume',    label: 'Volume' },
    { key: 'killZones', label: 'Kill Zones' },
    { key: 'fvgZones',  label: 'FVG' },
    { key: 'obZones',   label: 'OB' },
    { key: 'levels',    label: 'Levels' },
    { key: 'trades',    label: 'Trades' },
  ];
  const toggle = (k: keyof OverlayToggles) =>
    setOverlays((o) => ({ ...o, [k]: !o[k] }));
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1">
      <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium px-2">
        Overlays
      </span>
      {items.map((it) => {
        const on = overlays[it.key] ?? true;
        return (
          <button
            key={it.key}
            onClick={() => toggle(it.key)}
            className={`px-2.5 py-1 text-xs font-mono rounded transition ${
              on
                ? 'bg-zinc-700 text-zinc-50'
                : 'text-zinc-500 hover:text-zinc-200'
            }`}
            title={`Toggle ${it.label}`}
          >
            {on ? '● ' : '○ '}
            {it.label}
          </button>
        );
      })}
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
