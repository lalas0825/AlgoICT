'use client';

import { useEffect, useRef, memo } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  AreaSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  type CandlestickData,
  type HistogramData,
  type SeriesMarker,
  type Time,
  LineStyle,
  CrosshairMode,
  createSeriesMarkers,
} from 'lightweight-charts';
import type { ChartAnnotations } from '../types';

// Kill zones (US/Central). Each bar is colored by the first KZ it falls
// inside. Times in 24h local CT. Overlaps follow the order below:
//   London (01:00–04:00) → NY AM (08:30–12:00) →
//   Silver Bullet NY (10:00–11:00, overlays NY AM) →
//   NY PM (13:30–15:00)
// Silver Bullet London is inside London and visually merges with it.
export type KillZoneKey = 'london' | 'ny_am' | 'silver_bullet' | 'ny_pm';

const KZ_RANGES: Array<{ key: KillZoneKey; start: [number, number]; end: [number, number]; fill: string; line: string }> = [
  // London KZ — blue
  { key: 'london',        start: [1,  0], end: [4,  0], fill: 'rgba(59, 130, 246, 0.10)', line: 'rgba(59, 130, 246, 0.25)' },
  // NY AM KZ — emerald (extended to 12:00 CT per config.KILL_ZONES.ny_am)
  { key: 'ny_am',         start: [8, 30], end: [12, 0], fill: 'rgba(16, 185, 129, 0.10)', line: 'rgba(16, 185, 129, 0.25)' },
  // Silver Bullet NY — amber (inside NY AM — renders on top)
  { key: 'silver_bullet', start: [10, 0], end: [11, 0], fill: 'rgba(245, 158, 11, 0.14)', line: 'rgba(245, 158, 11, 0.30)' },
  // NY PM KZ — orange
  { key: 'ny_pm',         start: [13, 30], end: [15, 0], fill: 'rgba(249, 115, 22, 0.10)', line: 'rgba(249, 115, 22, 0.25)' },
];

/** Return the KZ active at a given US/Central hour/minute, or null. */
function _activeKz(hour: number, minute: number): KillZoneKey | null {
  const hm = hour * 60 + minute;
  // Iterate REVERSED so Silver Bullet wins over NY AM for the 10-11 overlap.
  for (let i = KZ_RANGES.length - 1; i >= 0; i--) {
    const r = KZ_RANGES[i];
    const startMin = r.start[0] * 60 + r.start[1];
    const endMin = r.end[0] * 60 + r.end[1];
    if (hm >= startMin && hm < endMin) return r.key;
  }
  return null;
}

function _kzFillForBar(t: UTCTimestamp): string | null {
  // UTC timestamp → US/Central (UTC-5 CDT / UTC-6 CST). Use Intl for DST.
  const d = new Date((t as number) * 1000);
  const ct = new Date(d.toLocaleString('en-US', { timeZone: 'America/Chicago' }));
  const kz = _activeKz(ct.getHours(), ct.getMinutes());
  if (!kz) return null;
  return KZ_RANGES.find((r) => r.key === kz)!.fill;
}

export interface OverlayToggles {
  /** Show volume subpanel below the candlesticks (default true). */
  volume?: boolean;
  /** Shade the chart background per active ICT kill zone (default true). */
  killZones?: boolean;
  /** Render FVG rectangles (default true). */
  fvgZones?: boolean;
  /** Render OB rectangles (default true). */
  obZones?: boolean;
  /** Render tracked levels + GEX + liquidity horizontal lines (default true). */
  levels?: boolean;
  /** Render entry / exit markers + trade PnL bubbles (default true). */
  trades?: boolean;
}

interface LiveCandlestickChartProps {
  candles: CandlestickData<UTCTimestamp>[];
  /** Unix seconds → bar volume. Parallel to `candles`. */
  volumes?: HistogramData<UTCTimestamp>[];
  annotations: ChartAnnotations;
  /**
   * When set, calls series.update() to add/update the last candle
   * without re-rendering the full dataset. Set by the Realtime subscription.
   */
  lastBar?: CandlestickData<UTCTimestamp> | null;
  /** Unix seconds — used to auto-fit the visible range when data changes. */
  windowStart?: number;
  windowEnd?: number;
  height?: number;
  /** Toggle individual overlays. Missing = defaults (all true). */
  overlays?: OverlayToggles;
}

// Zinc-950 background, zinc-800 grid, emerald/red wicks
const CHART_THEME = {
  bg: '#09090b',
  gridLine: '#27272a',
  text: '#a1a1aa',
  border: '#3f3f46',
  bull: '#10b981',
  bear: '#ef4444',
  fvgBull: 'rgba(59, 130, 246, 0.20)',   // blue-500 at 20%
  fvgBear: 'rgba(59, 130, 246, 0.14)',
  obBull: 'rgba(168, 85, 247, 0.22)',    // purple-500 at 22%
  obBear: 'rgba(168, 85, 247, 0.16)',
  liquidity: '#f59e0b',                  // amber-500
  callWall: '#ef4444',                   // red-500
  putWall: '#22c55e',                    // green-500
  gammaFlip: '#facc15',                  // yellow-400
  markerLong: '#10b981',
  markerShort: '#ef4444',
  markerExit: '#e4e4e7',
  // Tracked levels — daily levels blue, weekly levels purple. Swept
  // levels render in zinc-500 to fade out of attention.
  pdLevel: '#3b82f6',     // blue-500
  pwLevel: '#a855f7',     // purple-500
  eqLevel: '#f59e0b',     // amber-500
  swept: '#52525b',       // zinc-600
};

function _trackedLevelColor(kind: string, swept: boolean): string {
  if (swept) return CHART_THEME.swept;
  const k = kind.toUpperCase();
  if (k === 'PDH' || k === 'PDL') return CHART_THEME.pdLevel;
  if (k === 'PWH' || k === 'PWL') return CHART_THEME.pwLevel;
  if (k === 'EQH' || k === 'EQL') return CHART_THEME.eqLevel;
  if (k === 'BSL' || k === 'SSL') return CHART_THEME.liquidity;
  return CHART_THEME.liquidity;
}

export function LiveCandlestickChart({
  candles,
  volumes,
  annotations,
  lastBar,
  height = 640,
  overlays,
}: LiveCandlestickChartProps) {
  const showVolume = overlays?.volume ?? true;
  const showKillZones = overlays?.killZones ?? true;
  const showFvg = overlays?.fvgZones ?? true;
  const showOb = overlays?.obZones ?? true;
  const showLevels = overlays?.levels ?? true;
  const showTrades = overlays?.trades ?? true;

  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const kzSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const gexSeriesRef = useRef<ISeriesApi<'Line'>[]>([]);
  const liquiditySeriesRef = useRef<ISeriesApi<'Line'>[]>([]);
  const zoneSeriesRef = useRef<ISeriesApi<'Line'>[]>([]);
  const markersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);

  // ── Create the chart exactly once ─────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { color: CHART_THEME.bg },
        textColor: CHART_THEME.text,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: CHART_THEME.gridLine },
        horzLines: { color: CHART_THEME.gridLine },
      },
      rightPriceScale: { borderColor: CHART_THEME.border },
      timeScale: {
        borderColor: CHART_THEME.border,
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: { mode: CrosshairMode.Normal },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: CHART_THEME.bull,
      downColor: CHART_THEME.bear,
      borderUpColor: CHART_THEME.bull,
      borderDownColor: CHART_THEME.bear,
      wickUpColor: CHART_THEME.bull,
      wickDownColor: CHART_THEME.bear,
    });
    // Reserve the bottom 20% of the price-axis for volume + KZ strip so
    // they don't overlap candles.
    candleSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.02, bottom: 0.22 },
    });

    // Kill-zone shading — one HistogramSeries pinned to the bottom 22% of
    // the pane with a flat value and color-coded per active KZ. Renders
    // AS A BAND BEHIND candles because it's on its own overlay price
    // scale (empty id + scaleMargins 0.95/0). Value is a constant 1 per
    // bar; color encodes the zone. Bars outside any KZ are skipped
    // (rendered as whitespace).
    const kzSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: '',                 // overlay — no shared axis with candles
      priceFormat: { type: 'volume' },
      base: 0,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    kzSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.0, bottom: 0.0 },
    });

    // Volume subpanel — sits just above the KZ strip, below candles.
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
      color: CHART_THEME.bull,
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.80, bottom: 0.08 },
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    kzSeriesRef.current = kzSeries;
    markersRef.current = createSeriesMarkers<Time>(candleSeries, []);

    return () => {
      markersRef.current = null;
      gexSeriesRef.current = [];
      liquiditySeriesRef.current = [];
      zoneSeriesRef.current = [];
      seriesRef.current = null;
      volumeSeriesRef.current = null;
      kzSeriesRef.current = null;
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // ── Push candle data on change ────────────────────────────────────
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData(candles);
    // Fit the data into view each time we swap timeframes
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  // ── Volume subpanel ──────────────────────────────────────────────
  useEffect(() => {
    const vol = volumeSeriesRef.current;
    if (!vol) return;
    if (!showVolume) {
      vol.setData([]);
      return;
    }
    // Derive volume from props or reuse candles if a volumes array wasn't
    // supplied (the chart page fetches ohlcv rows; volume is usually on
    // the same row). Color green when close>=open, red otherwise.
    if (volumes && volumes.length > 0) {
      vol.setData(volumes);
    } else {
      const derived: HistogramData<UTCTimestamp>[] = candles
        .map((c) => ({
          time: c.time,
          value: (c as CandlestickData<UTCTimestamp> & { volume?: number }).volume ?? 0,
          color: c.close >= c.open ? 'rgba(16, 185, 129, 0.55)' : 'rgba(239, 68, 68, 0.55)',
        }))
        .filter((v) => v.value > 0);
      vol.setData(derived);
    }
  }, [candles, volumes, showVolume]);

  // ── Kill-zone shading ────────────────────────────────────────────
  useEffect(() => {
    const kz = kzSeriesRef.current;
    if (!kz) return;
    if (!showKillZones || candles.length === 0) {
      kz.setData([]);
      return;
    }
    // One histogram bar per candle; value = 1 if inside a KZ (any),
    // coloured by which KZ. Bars outside all KZs get skipped entirely.
    const data: HistogramData<UTCTimestamp>[] = [];
    for (const c of candles) {
      const color = _kzFillForBar(c.time);
      if (!color) continue;
      data.push({ time: c.time, value: 1, color });
    }
    kz.setData(data);
  }, [candles, showKillZones]);

  // ── Real-time: update the last candle without re-rendering all ────
  useEffect(() => {
    if (!lastBar || !seriesRef.current) return;
    seriesRef.current.update(lastBar);
    // Incrementally update the volume histogram for the live bar if we
    // have it; colour by bar direction.
    const vol = volumeSeriesRef.current;
    const lastVolume = (lastBar as CandlestickData<UTCTimestamp> & { volume?: number }).volume;
    if (showVolume && vol && lastVolume != null && lastVolume > 0) {
      vol.update({
        time: lastBar.time,
        value: lastVolume,
        color: lastBar.close >= lastBar.open
          ? 'rgba(16, 185, 129, 0.55)'
          : 'rgba(239, 68, 68, 0.55)',
      });
    }
    // Update KZ strip for the incoming bar so the band follows the live
    // candle in real time.
    const kz = kzSeriesRef.current;
    if (showKillZones && kz) {
      const color = _kzFillForBar(lastBar.time);
      if (color) {
        kz.update({ time: lastBar.time, value: 1, color });
      }
    }
  }, [lastBar, showVolume, showKillZones]);

  // ── Render overlays (GEX lines, liquidity, zones, trade markers) ──
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;
    if (candles.length === 0) return;

    // Clean up any previously-added overlay series
    for (const s of gexSeriesRef.current) chart.removeSeries(s);
    for (const s of liquiditySeriesRef.current) chart.removeSeries(s);
    for (const s of zoneSeriesRef.current) chart.removeSeries(s);
    gexSeriesRef.current = [];
    liquiditySeriesRef.current = [];
    zoneSeriesRef.current = [];

    const firstTime = candles[0].time as UTCTimestamp;
    const lastTime = candles[candles.length - 1].time as UTCTimestamp;

    // ── GEX walls (full-width horizontal lines) ────────────────────
    if (showLevels) for (const gex of annotations.gexLevels) {
      const color =
        gex.type === 'call_wall'
          ? CHART_THEME.callWall
          : gex.type === 'put_wall'
            ? CHART_THEME.putWall
            : CHART_THEME.gammaFlip;
      const line = chart.addSeries(LineSeries, {
        color,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: true,
        title: gex.type === 'call_wall'
          ? 'Call Wall'
          : gex.type === 'put_wall'
            ? 'Put Wall'
            : 'Gamma Flip',
      });
      line.setData([
        { time: firstTime, value: gex.price },
        { time: lastTime, value: gex.price },
      ]);
      gexSeriesRef.current.push(line);
    }

    // ── Liquidity levels (dotted amber) ────────────────────────────
    if (showLevels) for (const lvl of annotations.liquidity) {
      const line = chart.addSeries(LineSeries, {
        color: CHART_THEME.liquidity,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
        title: lvl.type,
      });
      line.setData([
        { time: firstTime, value: lvl.price },
        { time: lastTime, value: lvl.price },
      ]);
      liquiditySeriesRef.current.push(line);
    }

    // ── FVG / OB zones (bounded horizontal bands) ──────────────────
    // lightweight-charts doesn't have a native "box" primitive so we
    // approximate each zone with a pair of line series clamped to the
    // zone's time window. Points outside the window are whitespace.
    const pushZone = (
      timeStart: number,
      timeEnd: number,
      priceLow: number,
      priceHigh: number,
      color: string,
      lineStyle: LineStyle = LineStyle.Solid,
      lineWidth: 1 | 2 = 1,
    ) => {
      const ts = Math.max(timeStart, firstTime as number) as UTCTimestamp;
      const te = Math.min(timeEnd, lastTime as number) as UTCTimestamp;
      if (te <= ts) return;
      const top = chart.addSeries(LineSeries, {
        color,
        lineWidth,
        lineStyle,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      top.setData([
        { time: ts, value: priceHigh },
        { time: te, value: priceHigh },
      ]);
      const bottom = chart.addSeries(LineSeries, {
        color,
        lineWidth,
        lineStyle,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      bottom.setData([
        { time: ts, value: priceLow },
        { time: te, value: priceLow },
      ]);
      zoneSeriesRef.current.push(top, bottom);
    };

    if (showFvg) for (const fvg of annotations.fvgZones) {
      if (fvg.mitigated) continue;
      const color = fvg.direction === 'bullish' ? CHART_THEME.fvgBull : CHART_THEME.fvgBear;
      pushZone(
        Math.floor(fvg.time_start / 1000),
        Math.floor(fvg.time_end / 1000),
        fvg.price_low,
        fvg.price_high,
        color,
      );
    }
    if (showOb) for (const ob of annotations.obZones) {
      const color = ob.direction === 'bullish' ? CHART_THEME.obBull : CHART_THEME.obBear;
      pushZone(
        Math.floor(ob.time_start / 1000),
        Math.floor(ob.time_end / 1000),
        ob.price_low,
        ob.price_high,
        color,
        LineStyle.Solid,
        2, // OBs use heavier outline to distinguish from FVGs
      );
    }

    // ── IFVG rectangles (dashed outline — semantically inverted FVG) ─
    if (showFvg) for (const ifvg of annotations.ifvgZones) {
      if (ifvg.mitigated) continue;
      // Use the same bullish/bearish hue as FVG but with DASHED outline
      // so the operator can distinguish a regular FVG from its inverse.
      const color = ifvg.direction === 'bullish'
        ? CHART_THEME.fvgBull
        : CHART_THEME.fvgBear;
      pushZone(
        Math.floor(ifvg.time_start / 1000),
        Math.floor(ifvg.time_end / 1000),
        ifvg.price_low,
        ifvg.price_high,
        color,
        LineStyle.Dashed,
      );
    }

    // ── Tracked levels (PDH/PDL/PWH/PWL/EQH/EQL/BSL/SSL) ──
    //
    // Rendered as priceLines on the candle series so they span the full
    // width and always stay in view. Swept levels render muted and
    // dashed — plus the label gets a strikethrough-style prefix. The
    // chart doesn't support priceLine removal by reference from a single
    // series across re-renders, so we tear them down into the
    // liquiditySeriesRef bag for cleanup (same lifecycle as other
    // overlay series).
    if (showLevels) for (const lvl of annotations.trackedLevels) {
      const color = _trackedLevelColor(lvl.type, lvl.swept);
      const line = chart.addSeries(LineSeries, {
        color,
        lineWidth: lvl.swept ? 1 : 2,
        lineStyle: lvl.swept ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: true,
        title: lvl.swept ? `${lvl.type} ✖` : `${lvl.type} $${lvl.price.toFixed(2)}`,
      });
      line.setData([
        { time: firstTime, value: lvl.price },
        { time: lastTime, value: lvl.price },
      ]);
      liquiditySeriesRef.current.push(line);
    }

    // ── Trade markers on the candle series ─────────────────────────
    const markers: SeriesMarker<Time>[] = [];
    if (showTrades) for (const tr of annotations.trades) {
      const t = Math.floor(tr.time / 1000) as UTCTimestamp;
      if (tr.type === 'entry') {
        markers.push({
          time: t,
          position: tr.direction === 'long' ? 'belowBar' : 'aboveBar',
          color: tr.direction === 'long' ? CHART_THEME.markerLong : CHART_THEME.markerShort,
          shape: tr.direction === 'long' ? 'arrowUp' : 'arrowDown',
          text: tr.direction.toUpperCase(),
        });
      } else {
        markers.push({
          time: t,
          position: 'inBar',
          color: CHART_THEME.markerExit,
          shape: 'circle',
          text: tr.pnl != null ? `${tr.pnl >= 0 ? '+' : ''}${tr.pnl.toFixed(0)}` : 'X',
        });
      }
    }
    // ── Signal markers (fired — separate from executed trades) ──────
    // Phase 3: the `signals` table captures every time a strategy emitted
    // a setup, whether or not the broker filled. Rendered slightly
    // different from executed trades: green/red arrow with "FIRE"
    // prefix + the confluence score.
    if (showTrades) for (const sig of annotations.signals) {
      const t = Math.floor(sig.time / 1000) as UTCTimestamp;
      if (t < firstTime || t > lastTime) continue;
      const isLong = sig.direction === 'long';
      markers.push({
        time: t,
        position: isLong ? 'belowBar' : 'aboveBar',
        color: isLong ? CHART_THEME.markerLong : CHART_THEME.markerShort,
        shape: isLong ? 'arrowUp' : 'arrowDown',
        text: `FIRE ${sig.confluence_score}`,
      });
    }

    // ── Structure events (MSS / BOS / CHoCH) as labeled markers ─────
    if (showLevels) for (const ev of annotations.structureEvents) {
      const t = Math.floor(ev.time / 1000) as UTCTimestamp;
      // Clamp to visible range so off-screen events don't throw.
      if (t < firstTime || t > lastTime) continue;
      const isBull = ev.direction === 'bullish';
      const shape: SeriesMarker<Time>['shape'] =
        ev.type === 'MSS' ? (isBull ? 'arrowUp' : 'arrowDown') :
        ev.type === 'BOS' ? (isBull ? 'arrowUp' : 'arrowDown') :
        (isBull ? 'circle' : 'square'); // CHoCH
      markers.push({
        time: t,
        position: isBull ? 'belowBar' : 'aboveBar',
        color: isBull ? CHART_THEME.bull : CHART_THEME.bear,
        shape,
        text: `${ev.type}${isBull ? '↑' : '↓'}`,
      });
    }

    markers.sort((a, b) => (a.time as number) - (b.time as number));
    markersRef.current?.setMarkers(markers);
  }, [annotations, candles, showFvg, showOb, showLevels, showTrades]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded-xl border border-zinc-800 bg-zinc-950 overflow-hidden"
      style={{ height }}
    />
  );
}
