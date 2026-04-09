'use client';

import type { ToxicityLevel } from '../types';

interface VPINGaugeProps {
  vpin: number;
  level: ToxicityLevel;
  shieldActive: boolean;
}

const LEVEL_CONFIG: Record<ToxicityLevel, { color: string; stroke: string; label: string; bg: string }> = {
  calm: { color: 'text-emerald-400', stroke: '#10b981', label: 'CALM', bg: 'bg-emerald-400' },
  normal: { color: 'text-sky-400', stroke: '#38bdf8', label: 'NORMAL', bg: 'bg-sky-400' },
  elevated: { color: 'text-yellow-400', stroke: '#facc15', label: 'ELEVATED', bg: 'bg-yellow-400' },
  high: { color: 'text-orange-400', stroke: '#fb923c', label: 'HIGH', bg: 'bg-orange-400' },
  extreme: { color: 'text-red-400', stroke: '#f87171', label: 'EXTREME', bg: 'bg-red-400' },
};

export function VPINGauge({ vpin, level, shieldActive }: VPINGaugeProps) {
  const config = LEVEL_CONFIG[level] ?? LEVEL_CONFIG.calm;
  const safeVpin = Math.min(Math.max(vpin, 0), 1);

  // SVG arc parameters
  const r = 36;
  const cx = 50;
  const cy = 50;
  const startAngle = -210; // degrees
  const endAngle = 30;
  const totalArcDeg = endAngle - startAngle; // 240 deg arc
  const valueDeg = startAngle + totalArcDeg * safeVpin;

  const toRad = (deg: number) => (deg * Math.PI) / 180;

  const arcPath = (start: number, end: number) => {
    const s = toRad(start);
    const e = toRad(end);
    const x1 = cx + r * Math.cos(s);
    const y1 = cy + r * Math.sin(s);
    const x2 = cx + r * Math.cos(e);
    const y2 = cy + r * Math.sin(e);
    const largeArc = end - start > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`;
  };

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-zinc-500 uppercase tracking-wider font-medium">
          VPIN Toxicity
        </div>
        {shieldActive && (
          <span className="text-xs font-mono font-bold text-red-400 animate-pulse">
            🛡 SHIELD ACTIVE
          </span>
        )}
      </div>

      <div className="flex items-center gap-4">
        {/* SVG Gauge */}
        <svg viewBox="0 0 100 70" className="w-28 h-20 flex-shrink-0">
          {/* Background arc */}
          <path
            d={arcPath(startAngle, endAngle)}
            fill="none"
            stroke="#27272a"
            strokeWidth="8"
            strokeLinecap="round"
          />
          {/* Value arc */}
          {safeVpin > 0 && (
            <path
              d={arcPath(startAngle, valueDeg)}
              fill="none"
              stroke={config.stroke}
              strokeWidth="8"
              strokeLinecap="round"
            />
          )}
          {/* Zone markers */}
          {/* 0.45 line */}
          {[0.45, 0.55, 0.70].map((threshold) => {
            const deg = startAngle + totalArcDeg * threshold;
            const rad = toRad(deg);
            return (
              <line
                key={threshold}
                x1={cx + (r - 6) * Math.cos(rad)}
                y1={cy + (r - 6) * Math.sin(rad)}
                x2={cx + (r + 6) * Math.cos(rad)}
                y2={cy + (r + 6) * Math.sin(rad)}
                stroke="#52525b"
                strokeWidth="1.5"
              />
            );
          })}
          {/* Center value text */}
          <text
            x={cx}
            y={cy + 2}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#fafafa"
            fontSize="11"
            fontFamily="monospace"
            fontWeight="600"
          >
            {safeVpin.toFixed(3)}
          </text>
        </svg>

        <div>
          <div className={`text-lg font-bold font-mono ${config.color} leading-none`}>
            {config.label}
          </div>
          <div className="mt-1.5 space-y-0.5">
            {(['calm', 'elevated', 'high', 'extreme'] as ToxicityLevel[]).map((l) => (
              <div key={l} className="flex items-center gap-1.5">
                <div
                  className={`w-1.5 h-1.5 rounded-full ${
                    l === level ? LEVEL_CONFIG[l].bg : 'bg-zinc-700'
                  }`}
                />
                <span
                  className={`text-xs font-mono ${l === level ? LEVEL_CONFIG[l].color : 'text-zinc-600'}`}
                >
                  {l}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
