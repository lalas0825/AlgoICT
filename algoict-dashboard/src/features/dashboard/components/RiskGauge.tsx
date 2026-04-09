'use client';

interface RiskGaugeProps {
  pnlToday: number;
  maxLoss: number;
  profitCap: number;
}

export function RiskGauge({ pnlToday, maxLoss, profitCap }: RiskGaugeProps) {
  // Range: maxLoss (negative) → 0 → profitCap
  const totalRange = profitCap + Math.abs(maxLoss);
  const offset = Math.abs(maxLoss);
  const position = Math.min(Math.max(pnlToday + offset, 0), totalRange);
  const pct = (position / totalRange) * 100;

  // Color zones: red zone (loss), yellow zone (near limits), green (profit)
  const lossZonePct = (Math.abs(maxLoss) / totalRange) * 100;
  const profitZonePct = (profitCap / totalRange) * 100;

  let trackColor = 'bg-emerald-500';
  if (pnlToday < 0) trackColor = 'bg-red-500';
  if (Math.abs(pnlToday) >= Math.abs(maxLoss) * 0.8) trackColor = 'bg-amber-500';

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <div className="text-xs text-zinc-500 uppercase tracking-wider font-medium mb-3">
        Daily Risk Gauge
      </div>

      <div className="relative h-3 bg-zinc-800 rounded-full overflow-hidden mb-2">
        {/* Loss zone background */}
        <div
          className="absolute left-0 top-0 h-full bg-red-900/40 rounded-l-full"
          style={{ width: `${lossZonePct}%` }}
        />
        {/* Profit zone background */}
        <div
          className="absolute right-0 top-0 h-full bg-emerald-900/40 rounded-r-full"
          style={{ width: `${profitZonePct}%` }}
        />
        {/* Current position indicator */}
        <div
          className="absolute top-0 h-full w-1 -translate-x-0.5 rounded"
          style={{ left: `${pct}%`, background: trackColor === 'bg-emerald-500' ? '#10b981' : trackColor === 'bg-red-500' ? '#ef4444' : '#f59e0b' }}
        />
      </div>

      <div className="flex justify-between text-xs font-mono">
        <span className="text-red-500">${maxLoss.toLocaleString()}</span>
        <span className={`font-semibold ${pnlToday >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          ${pnlToday >= 0 ? '+' : ''}{pnlToday.toLocaleString()}
        </span>
        <span className="text-emerald-500">+${profitCap.toLocaleString()}</span>
      </div>
    </div>
  );
}
