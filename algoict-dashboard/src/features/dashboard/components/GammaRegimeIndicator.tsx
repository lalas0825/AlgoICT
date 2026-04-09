'use client';

import type { GEXRegime } from '../types';

interface GammaRegimeIndicatorProps {
  regime: GEXRegime;
  callWall: number | null;
  putWall: number | null;
  flipPoint: number | null;
}

const REGIME_CONFIG: Record<GEXRegime, { label: string; color: string; bg: string; desc: string }> = {
  positive: {
    label: 'Positive GEX',
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10 border-emerald-500/30',
    desc: 'Dealers short gamma → mean-reverting, range-bound',
  },
  negative: {
    label: 'Negative GEX',
    color: 'text-red-400',
    bg: 'bg-red-500/10 border-red-500/30',
    desc: 'Dealers long gamma → amplifying, trending moves',
  },
  flip: {
    label: 'Gamma Flip',
    color: 'text-amber-400',
    bg: 'bg-amber-500/10 border-amber-500/30',
    desc: 'Near zero GEX → regime transition, elevated vol',
  },
  unknown: {
    label: 'Unavailable',
    color: 'text-zinc-500',
    bg: 'bg-zinc-800/50 border-zinc-700/30',
    desc: 'GEX data not available',
  },
};

export function GammaRegimeIndicator({ regime, callWall, putWall, flipPoint }: GammaRegimeIndicatorProps) {
  const config = REGIME_CONFIG[regime] ?? REGIME_CONFIG.unknown;

  const formatLevel = (val: number | null) =>
    val != null ? val.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '—';

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <div className="text-xs text-zinc-500 uppercase tracking-wider font-medium mb-3">
        GEX — Gamma Regime
      </div>

      <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border ${config.bg} mb-3`}>
        <span className={`font-semibold text-sm ${config.color}`}>{config.label}</span>
      </div>

      <p className="text-xs text-zinc-500 mb-3 leading-relaxed">{config.desc}</p>

      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">Call Wall</span>
          <span className="text-xs font-mono text-emerald-400 font-medium">
            {formatLevel(callWall)}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">Put Wall</span>
          <span className="text-xs font-mono text-red-400 font-medium">
            {formatLevel(putWall)}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">Gamma Flip</span>
          <span className="text-xs font-mono text-amber-400 font-medium">
            {formatLevel(flipPoint)}
          </span>
        </div>
      </div>
    </div>
  );
}
