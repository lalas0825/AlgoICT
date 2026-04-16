'use client';

import { useEffect, useRef, memo } from 'react';
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  type CandlestickData,
  type SeriesMarker,
  type Time,
  LineStyle,
  CrosshairMode,
  createSeriesMarkers,
} from 'lightweight-charts';
import type { ChartAnnotations } from '../types';

interface LiveCandlestickChartProps {
  candles: CandlestickData<UTCTimestamp>[];
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
};

export function LiveCandlestickChart({
  candles,
  annotations,
  lastBar,
  height = 640,
}: LiveCandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
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

    chartRef.current = chart;
    seriesRef.current = candleSeries;
    markersRef.current = createSeriesMarkers<Time>(candleSeries, []);

    return () => {
      markersRef.current = null;
      gexSeriesRef.current = [];
      liquiditySeriesRef.current = [];
      zoneSeriesRef.current = [];
      seriesRef.current = null;
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

  // ── Real-time: update the last candle without re-rendering all ────
  useEffect(() => {
    if (!lastBar || !seriesRef.current) return;
    seriesRef.current.update(lastBar);
  }, [lastBar]);

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
    for (const gex of annotations.gexLevels) {
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
    for (const lvl of annotations.liquidity) {
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
    ) => {
      const ts = Math.max(timeStart, firstTime as number) as UTCTimestamp;
      const te = Math.min(timeEnd, lastTime as number) as UTCTimestamp;
      if (te <= ts) return;
      const top = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      top.setData([
        { time: ts, value: priceHigh },
        { time: te, value: priceHigh },
      ]);
      const bottom = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      bottom.setData([
        { time: ts, value: priceLow },
        { time: te, value: priceLow },
      ]);
      zoneSeriesRef.current.push(top, bottom);
    };

    for (const fvg of annotations.fvgZones) {
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
    for (const ob of annotations.obZones) {
      const color = ob.direction === 'bullish' ? CHART_THEME.obBull : CHART_THEME.obBear;
      pushZone(
        Math.floor(ob.time_start / 1000),
        Math.floor(ob.time_end / 1000),
        ob.price_low,
        ob.price_high,
        color,
      );
    }

    // ── Trade markers on the candle series ─────────────────────────
    const markers: SeriesMarker<Time>[] = [];
    for (const tr of annotations.trades) {
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
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    markersRef.current?.setMarkers(markers);
  }, [annotations, candles]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded-xl border border-zinc-800 bg-zinc-950 overflow-hidden"
      style={{ height }}
    />
  );
}
