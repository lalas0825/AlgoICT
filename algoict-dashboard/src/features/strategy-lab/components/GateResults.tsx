'use client';

export interface GateResult {
  passed: boolean;
  value: number | boolean | string;
  display?: string; // pre-formatted value string
}

export interface GateResultsData {
  sharpe_improvement: GateResult;
  win_rate_delta: GateResult;
  drawdown_delta: GateResult;
  walk_forward_pct: GateResult;
  cross_instrument_count: GateResult;
  noise_resilience_pct: GateResult;
  inversion_loses: GateResult;
  occam_params: GateResult;
  validation_improves: GateResult;
}

interface GateSpec {
  key: keyof GateResultsData;
  label: string;
  threshold: string;
  formatValue: (r: GateResult) => string;
}

const GATES: GateSpec[] = [
  {
    key: 'sharpe_improvement',
    label: 'Sharpe Improvement',
    threshold: '≥ +0.10',
    formatValue: (r) =>
      r.display ?? (typeof r.value === 'number' ? `+${r.value.toFixed(2)}` : String(r.value)),
  },
  {
    key: 'win_rate_delta',
    label: 'Win Rate',
    threshold: 'Δ < −2%',
    formatValue: (r) =>
      r.display ??
      (typeof r.value === 'number'
        ? `${r.value >= 0 ? '+' : ''}${r.value.toFixed(1)}%`
        : String(r.value)),
  },
  {
    key: 'drawdown_delta',
    label: 'Max Drawdown',
    threshold: 'Δ < +10%',
    formatValue: (r) =>
      r.display ??
      (typeof r.value === 'number'
        ? `${r.value >= 0 ? '+' : ''}${r.value.toFixed(1)}%`
        : String(r.value)),
  },
  {
    key: 'walk_forward_pct',
    label: 'Walk-Forward',
    threshold: '≥ 70% windows',
    formatValue: (r) =>
      r.display ??
      (typeof r.value === 'number' ? `${r.value.toFixed(0)}%` : String(r.value)),
  },
  {
    key: 'cross_instrument_count',
    label: 'Cross-Instrument',
    threshold: '≥ 2/3 (NQ+ES+YM)',
    formatValue: (r) =>
      r.display ??
      (typeof r.value === 'number' ? `${r.value}/3` : String(r.value)),
  },
  {
    key: 'noise_resilience_pct',
    label: 'Noise Resilience',
    threshold: 'Δ < 30% degradation',
    formatValue: (r) =>
      r.display ??
      (typeof r.value === 'number' ? `${r.value.toFixed(0)}%` : String(r.value)),
  },
  {
    key: 'inversion_loses',
    label: 'Inversion Test',
    threshold: 'Inverse must lose',
    formatValue: (r) =>
      r.display ?? (r.value === true || r.value === 'true' ? 'LOSES ✓' : 'PROFITS ✗'),
  },
  {
    key: 'occam_params',
    label: "Occam's Razor",
    threshold: '≤ 2 new params',
    formatValue: (r) =>
      r.display ??
      (typeof r.value === 'number' ? `${r.value} param${r.value !== 1 ? 's' : ''}` : String(r.value)),
  },
  {
    key: 'validation_improves',
    label: 'Validation 2023',
    threshold: 'Must improve vs base',
    formatValue: (r) =>
      r.display ?? (r.value === true || r.value === 'true' ? 'IMPROVED ✓' : 'NO CHANGE ✗'),
  },
];

interface GateResultsProps {
  gates: GateResultsData;
  compact?: boolean;
}

export function GateResults({ gates, compact = false }: GateResultsProps) {
  const passed = GATES.filter((g) => gates[g.key]?.passed).length;

  if (compact) {
    // Compact row of 9 dots for use inside CandidateCard
    return (
      <div className="flex items-center gap-1">
        {GATES.map((g) => {
          const result = gates[g.key];
          return (
            <div
              key={g.key}
              title={`${g.label}: ${g.formatValue(result)} (${g.threshold})`}
              className={`w-4 h-4 rounded-sm flex items-center justify-center text-[8px] font-bold ${
                result?.passed
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-red-500/20 text-red-400'
              }`}
            >
              {result?.passed ? '✓' : '✗'}
            </div>
          );
        })}
        <span className="ml-1 text-xs font-mono text-zinc-500">
          {passed}/9
        </span>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-zinc-500 uppercase tracking-wider font-medium">
          Anti-Overfit Gates
        </span>
        <span
          className={`text-sm font-mono font-bold ${
            passed === 9
              ? 'text-emerald-400'
              : passed >= 7
              ? 'text-sky-400'
              : passed >= 5
              ? 'text-amber-400'
              : 'text-red-400'
          }`}
        >
          {passed}/9 gates passed
        </span>
      </div>

      <div className="grid grid-cols-1 gap-1.5">
        {GATES.map((g) => {
          const result = gates[g.key];
          const ok = result?.passed;
          return (
            <div
              key={g.key}
              className={`flex items-center justify-between px-3 py-2 rounded-lg border ${
                ok
                  ? 'bg-emerald-500/8 border-emerald-500/25'
                  : 'bg-red-500/8 border-red-500/25'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <div
                  className={`w-5 h-5 rounded flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                    ok
                      ? 'bg-emerald-500/25 text-emerald-400'
                      : 'bg-red-500/25 text-red-400'
                  }`}
                >
                  {ok ? '✓' : '✗'}
                </div>
                <div>
                  <div className={`text-xs font-medium ${ok ? 'text-zinc-200' : 'text-zinc-400'}`}>
                    {g.label}
                  </div>
                  <div className="text-xs text-zinc-600">{g.threshold}</div>
                </div>
              </div>
              <span
                className={`text-xs font-mono font-semibold ${
                  ok ? 'text-emerald-400' : 'text-red-400'
                }`}
              >
                {result ? g.formatValue(result) : '—'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
