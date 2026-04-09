'use client';

import { useMemo } from 'react';
import { useChartAnnotations } from '../hooks/useChartAnnotations';
import type {
  Candle,
  Timeframe,
  VPINLevel,
  FVGZone,
  OBZone,
  LiquidityLevel,
  GEXLevel,
  TradeMarker,
  ChartAnnotations,
} from '../types';

interface CandlestickChartProps {
  symbol: string;
  candles: Candle[];
  timeframe: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;
  height?: number;
  /** Override auto-fetched annotations (e.g., for tests/storybook). */
  annotationsOverride?: ChartAnnotations;
}

const TIMEFRAMES: Timeframe[] = ['1m', '5m', '15m', '1H', '4H', 'D'];

// VPIN → candle body color (overrides bull/bear when not calm/normal)
const VPIN_COLORS: Record<VPINLevel, string | null> = {
  calm: null,
  normal: null,
  elevated: '#facc15', // yellow-400
  high: '#fb923c', // orange-400
  extreme: '#b91c1c', // red-700
};

const BULL_COLOR = '#10b981'; // emerald-500
const BEAR_COLOR = '#ef4444'; // red-500

function getCandleColor(candle: Candle): string {
  if (candle.vpin_level) {
    const override = VPIN_COLORS[candle.vpin_level];
    if (override) return override;
  }
  return candle.close >= candle.open ? BULL_COLOR : BEAR_COLOR;
}

export function CandlestickChart({
  symbol,
  candles,
  timeframe,
  onTimeframeChange,
  height = 520,
  annotationsOverride,
}: CandlestickChartProps) {
  const windowStart = candles.length > 0 ? candles[0].time : 0;
  const windowEnd = candles.length > 0 ? candles[candles.length - 1].time : 0;

  const { annotations: fetched, loading: annotLoading } = useChartAnnotations(
    symbol,
    timeframe,
    windowStart,
    windowEnd
  );
  const annotations = annotationsOverride ?? fetched;

  // Calculate viewport + scales (stable when candles change)
  const view = useMemo(() => {
    const viewW = 1400;
    const viewH = height;
    const margin = { top: 16, right: 72, bottom: 40, left: 16 };
    const innerW = viewW - margin.left - margin.right;
    const innerH = viewH - margin.top - margin.bottom;

    if (candles.length === 0) {
      return {
        viewW,
        viewH,
        margin,
        innerW,
        innerH,
        xScale: () => 0,
        yScale: () => 0,
        candleWidth: 0,
        yMin: 0,
        yMax: 1,
        priceTicks: [] as number[],
        timeTicks: [] as { x: number; label: string }[],
      };
    }

    // Price bounds — include annotation prices so overlays stay in view
    const prices: number[] = [];
    for (const c of candles) {
      prices.push(c.high, c.low);
    }
    for (const g of annotations.gexLevels) prices.push(g.price);
    for (const l of annotations.liquidity) prices.push(l.price);
    for (const z of annotations.fvgZones) prices.push(z.price_high, z.price_low);
    for (const z of annotations.obZones) prices.push(z.price_high, z.price_low);

    const rawMin = Math.min(...prices);
    const rawMax = Math.max(...prices);
    const pad = (rawMax - rawMin) * 0.05 || 1;
    const yMin = rawMin - pad;
    const yMax = rawMax + pad;

    // Time bounds — use candle indices (evenly spaced, hides gaps)
    const n = candles.length;
    const xStep = innerW / n;

    const timeToIndex = (t: number) => {
      if (t <= candles[0].time) return 0;
      if (t >= candles[n - 1].time) return n - 1;
      // Binary search
      let lo = 0;
      let hi = n - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (candles[mid].time < t) lo = mid + 1;
        else hi = mid;
      }
      return lo;
    };

    const xScale = (t: number) => {
      const idx = timeToIndex(t);
      return margin.left + idx * xStep + xStep / 2;
    };

    const yScale = (p: number) =>
      margin.top + innerH - ((p - yMin) / (yMax - yMin)) * innerH;

    const candleWidth = Math.max(1.5, xStep * 0.68);

    // Y-axis ticks (6 levels)
    const priceTicks: number[] = [];
    for (let i = 0; i <= 5; i++) {
      priceTicks.push(yMin + ((yMax - yMin) * i) / 5);
    }

    // X-axis ticks (~8 labels)
    const tickCount = Math.min(8, n);
    const timeTicks: { x: number; label: string }[] = [];
    const fmt = (t: number) => {
      const d = new Date(t);
      if (timeframe === 'D') {
        return `${d.getMonth() + 1}/${d.getDate()}`;
      }
      return `${d.getHours().toString().padStart(2, '0')}:${d
        .getMinutes()
        .toString()
        .padStart(2, '0')}`;
    };
    for (let i = 0; i < tickCount; i++) {
      const idx = Math.floor((i * (n - 1)) / (tickCount - 1));
      const c = candles[idx];
      timeTicks.push({ x: xScale(c.time), label: fmt(c.time) });
    }

    return {
      viewW,
      viewH,
      margin,
      innerW,
      innerH,
      xScale,
      yScale,
      candleWidth,
      yMin,
      yMax,
      priceTicks,
      timeTicks,
    };
  }, [candles, annotations, height, timeframe]);

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
      {/* Header: symbol + TF switcher */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-zinc-50">{symbol}</span>
          <span className="text-xs font-mono text-zinc-500 uppercase">
            {timeframe}
          </span>
          {annotLoading && (
            <span className="text-xs text-zinc-600 font-mono animate-pulse">
              loading levels…
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 bg-zinc-950 rounded-lg p-1 border border-zinc-800">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => onTimeframeChange(tf)}
              className={`px-2.5 py-1 text-xs font-mono rounded transition ${
                tf === timeframe
                  ? 'bg-zinc-800 text-zinc-50 font-semibold'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3 px-4 py-2 border-b border-zinc-800 text-xs">
        <LegendItem color="#3b82f6" label="FVG" shape="rect" />
        <LegendItem color="#a855f7" label="Order Block" shape="rect" />
        <LegendItem color="#f59e0b" label="Liquidity" shape="line" />
        <LegendItem color="#ef4444" label="Call Wall" shape="dash" />
        <LegendItem color="#10b981" label="Put Wall" shape="dash" />
        <LegendItem color="#eab308" label="Gamma Flip" shape="dash" />
        <LegendItem color="#facc15" label="VPIN high" shape="square" />
      </div>

      {/* Chart SVG */}
      <div className="w-full bg-zinc-950">
        {candles.length === 0 ? (
          <div
            className="flex items-center justify-center text-zinc-600 text-sm"
            style={{ height }}
          >
            No candle data
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${view.viewW} ${view.viewH}`}
            className="w-full h-auto"
            preserveAspectRatio="xMidYMid meet"
          >
            {/* Grid: horizontal price lines */}
            {view.priceTicks.map((p, i) => {
              const y = view.yScale(p);
              return (
                <line
                  key={`grid-${i}`}
                  x1={view.margin.left}
                  y1={y}
                  x2={view.viewW - view.margin.right}
                  y2={y}
                  stroke="#27272a"
                  strokeWidth="0.5"
                  strokeDasharray="2 4"
                />
              );
            })}

            {/* FVG Zones — blue translucent */}
            <g>
              {annotations.fvgZones.map((z) => (
                <FVGRect key={z.id} zone={z} view={view} />
              ))}
            </g>

            {/* OB Zones — purple translucent */}
            <g>
              {annotations.obZones.map((z) => (
                <OBRect key={z.id} zone={z} view={view} />
              ))}
            </g>

            {/* Liquidity levels — amber horizontal lines */}
            <g>
              {annotations.liquidity.map((l) => (
                <LiquidityLine key={l.id} level={l} view={view} />
              ))}
            </g>

            {/* GEX levels — dashed horizontal lines with labels */}
            <g>
              {annotations.gexLevels.map((g, i) => (
                <GEXLine key={`gex-${g.type}-${i}`} level={g} view={view} />
              ))}
            </g>

            {/* Candles */}
            <g>
              {candles.map((c, i) => {
                const x = view.xScale(c.time);
                const color = getCandleColor(c);
                const bodyTop = view.yScale(Math.max(c.open, c.close));
                const bodyBottom = view.yScale(Math.min(c.open, c.close));
                const bodyHeight = Math.max(1, bodyBottom - bodyTop);
                return (
                  <g key={`candle-${i}`}>
                    <line
                      x1={x}
                      y1={view.yScale(c.high)}
                      x2={x}
                      y2={view.yScale(c.low)}
                      stroke={color}
                      strokeWidth="1"
                    />
                    <rect
                      x={x - view.candleWidth / 2}
                      y={bodyTop}
                      width={view.candleWidth}
                      height={bodyHeight}
                      fill={color}
                      opacity={c.close >= c.open ? 0.9 : 1}
                    />
                  </g>
                );
              })}
            </g>

            {/* Trade markers on top */}
            <g>
              {annotations.trades.map((t) => (
                <TradeMarkerGlyph key={t.id} marker={t} view={view} />
              ))}
            </g>

            {/* Y-axis price labels (right side) */}
            <g>
              {view.priceTicks.map((p, i) => (
                <text
                  key={`price-${i}`}
                  x={view.viewW - view.margin.right + 6}
                  y={view.yScale(p)}
                  fill="#71717a"
                  fontSize="10"
                  fontFamily="monospace"
                  dominantBaseline="middle"
                >
                  {p.toFixed(1)}
                </text>
              ))}
            </g>

            {/* X-axis time labels (bottom) */}
            <g>
              {view.timeTicks.map((t, i) => (
                <text
                  key={`time-${i}`}
                  x={t.x}
                  y={view.viewH - view.margin.bottom + 18}
                  fill="#71717a"
                  fontSize="10"
                  fontFamily="monospace"
                  textAnchor="middle"
                >
                  {t.label}
                </text>
              ))}
            </g>
          </svg>
        )}
      </div>
    </div>
  );
}

// ---- Sub-components ----

type ViewCtx = ReturnType<typeof computeViewForSubComponents>;

// Type helper so sub-component prop types stay in sync with main view.
// We use a type alias derived from the main `view` computation.
function computeViewForSubComponents() {
  // This function exists only as a type source; it is never called.
  return {
    viewW: 0,
    viewH: 0,
    margin: { top: 0, right: 0, bottom: 0, left: 0 },
    innerW: 0,
    innerH: 0,
    xScale: (_t: number) => 0,
    yScale: (_p: number) => 0,
    candleWidth: 0,
    yMin: 0,
    yMax: 0,
    priceTicks: [] as number[],
    timeTicks: [] as { x: number; label: string }[],
  };
}

function LegendItem({
  color,
  label,
  shape,
}: {
  color: string;
  label: string;
  shape: 'rect' | 'line' | 'dash' | 'square';
}) {
  return (
    <div className="flex items-center gap-1.5">
      {shape === 'rect' && (
        <div
          className="w-4 h-3 rounded-sm border"
          style={{
            backgroundColor: `${color}26`,
            borderColor: `${color}80`,
          }}
        />
      )}
      {shape === 'square' && (
        <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: color }} />
      )}
      {shape === 'line' && (
        <div className="w-4 h-0.5" style={{ backgroundColor: color }} />
      )}
      {shape === 'dash' && (
        <svg width="16" height="4">
          <line
            x1="0"
            y1="2"
            x2="16"
            y2="2"
            stroke={color}
            strokeWidth="1.5"
            strokeDasharray="3 2"
          />
        </svg>
      )}
      <span className="text-zinc-500">{label}</span>
    </div>
  );
}

function FVGRect({ zone, view }: { zone: FVGZone; view: ViewCtx }) {
  const x1 = view.xScale(zone.time_start);
  const x2 = view.xScale(zone.time_end);
  const y1 = view.yScale(zone.price_high);
  const y2 = view.yScale(zone.price_low);
  const opacity = zone.mitigated ? 0.08 : 0.18;
  return (
    <rect
      x={x1}
      y={y1}
      width={Math.max(2, x2 - x1)}
      height={Math.max(2, y2 - y1)}
      fill={`rgba(59, 130, 246, ${opacity})`}
      stroke="rgba(59, 130, 246, 0.55)"
      strokeWidth="0.75"
      strokeDasharray={zone.mitigated ? '3 3' : undefined}
    />
  );
}

function OBRect({ zone, view }: { zone: OBZone; view: ViewCtx }) {
  const x1 = view.xScale(zone.time_start);
  const x2 = view.xScale(zone.time_end);
  const y1 = view.yScale(zone.price_high);
  const y2 = view.yScale(zone.price_low);
  return (
    <rect
      x={x1}
      y={y1}
      width={Math.max(2, x2 - x1)}
      height={Math.max(2, y2 - y1)}
      fill="rgba(168, 85, 247, 0.18)"
      stroke="rgba(168, 85, 247, 0.6)"
      strokeWidth="0.75"
    />
  );
}

function LiquidityLine({
  level,
  view,
}: {
  level: LiquidityLevel;
  view: ViewCtx;
}) {
  const y = view.yScale(level.price);
  const x1 = view.xScale(level.time_detected);
  const x2 = view.viewW - view.margin.right;
  const color = level.swept ? 'rgba(245, 158, 11, 0.35)' : 'rgba(245, 158, 11, 0.85)';
  return (
    <g>
      <line
        x1={x1}
        y1={y}
        x2={x2}
        y2={y}
        stroke={color}
        strokeWidth="1"
        strokeDasharray={level.swept ? '2 4' : undefined}
      />
      <text
        x={x2 - 4}
        y={y - 3}
        fill="#f59e0b"
        fontSize="9"
        fontFamily="monospace"
        textAnchor="end"
      >
        {level.type}
        {level.swept ? ' ×' : ''}
      </text>
    </g>
  );
}

function GEXLine({ level, view }: { level: GEXLevel; view: ViewCtx }) {
  const y = view.yScale(level.price);
  const x1 = view.margin.left;
  const x2 = view.viewW - view.margin.right;

  const config = {
    call_wall: { color: '#ef4444', label: 'Call Wall' },
    put_wall: { color: '#10b981', label: 'Put Wall' },
    gamma_flip: { color: '#eab308', label: 'γ Flip' },
  }[level.type];

  return (
    <g>
      <line
        x1={x1}
        y1={y}
        x2={x2}
        y2={y}
        stroke={config.color}
        strokeWidth="1.25"
        strokeDasharray="4 3"
      />
      <rect
        x={x1 + 4}
        y={y - 8}
        width={60}
        height={14}
        fill="#0a0a0a"
        stroke={config.color}
        strokeWidth="0.5"
        rx="2"
      />
      <text
        x={x1 + 8}
        y={y + 2}
        fill={config.color}
        fontSize="9"
        fontFamily="monospace"
        fontWeight="600"
      >
        {config.label} {level.price.toFixed(0)}
      </text>
    </g>
  );
}

function TradeMarkerGlyph({
  marker,
  view,
}: {
  marker: TradeMarker;
  view: ViewCtx;
}) {
  const x = view.xScale(marker.time);
  const y = view.yScale(marker.price);
  const isLong = marker.direction === 'long';
  const isEntry = marker.type === 'entry';

  // Entry: filled triangle pointing into trade direction
  // Exit: hollow diamond colored by pnl
  if (isEntry) {
    const color = isLong ? '#10b981' : '#ef4444';
    const points = isLong
      ? `${x},${y + 4} ${x - 6},${y + 14} ${x + 6},${y + 14}` // pointing up (long entry below)
      : `${x},${y - 4} ${x - 6},${y - 14} ${x + 6},${y - 14}`; // pointing down
    return (
      <g>
        <polygon points={points} fill={color} stroke="#0a0a0a" strokeWidth="1" />
        <circle cx={x} cy={y} r="2" fill={color} />
      </g>
    );
  }

  // Exit
  const pnlPositive = (marker.pnl ?? 0) >= 0;
  const color = pnlPositive ? '#10b981' : '#ef4444';
  return (
    <g>
      <polygon
        points={`${x},${y - 6} ${x + 6},${y} ${x},${y + 6} ${x - 6},${y}`}
        fill="#0a0a0a"
        stroke={color}
        strokeWidth="1.5"
      />
      <circle cx={x} cy={y} r="1.5" fill={color} />
    </g>
  );
}
