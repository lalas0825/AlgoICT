'use client';

import { useState } from 'react';
import { GateResults, type GateResultsData } from './GateResults';

export type CandidateStatus =
  | 'pending'
  | 'running'
  | 'passed'
  | 'failed'
  | 'approved'
  | 'rejected';

export interface Candidate {
  id: string; // e.g. "H-001"
  hypothesis: string;
  strategy_name: string;
  status: CandidateStatus;
  gates_passed: number;
  gates_total: number;
  score: number; // 0–100
  gate_results: GateResultsData | null;
  session_id: string;
  created_at: string;
  approved_at: string | null;
  approved_by: string | null;
  sharpe_improvement?: number | null;
  net_profit_delta?: number | null;
  notes?: string | null;
}

const STATUS_CONFIG: Record<
  CandidateStatus,
  { label: string; color: string; bg: string }
> = {
  pending: { label: 'Pending', color: 'text-zinc-400', bg: 'bg-zinc-700/40 border-zinc-700' },
  running: { label: 'Running…', color: 'text-sky-400', bg: 'bg-sky-500/10 border-sky-500/30' },
  passed: { label: 'Passed', color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30' },
  failed: { label: 'Failed', color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30' },
  approved: { label: 'Approved ✓', color: 'text-emerald-300', bg: 'bg-emerald-500/15 border-emerald-500/50' },
  rejected: { label: 'Rejected', color: 'text-zinc-500', bg: 'bg-zinc-800/50 border-zinc-700' },
};

interface CandidateCardProps {
  candidate: Candidate;
}

export function CandidateCard({ candidate: c }: CandidateCardProps) {
  const [expanded, setExpanded] = useState(false);
  const status = STATUS_CONFIG[c.status] ?? STATUS_CONFIG.pending;
  const allGatesPassed = c.gates_passed === c.gates_total;

  const scoreColor =
    c.score >= 80
      ? 'text-emerald-400'
      : c.score >= 60
      ? 'text-sky-400'
      : c.score >= 40
      ? 'text-amber-400'
      : 'text-red-400';

  return (
    <div
      className={`bg-zinc-900 rounded-xl border overflow-hidden transition-all ${
        c.status === 'approved'
          ? 'border-emerald-500/40'
          : c.status === 'running'
          ? 'border-sky-500/40'
          : 'border-zinc-800'
      }`}
    >
      {/* Header row */}
      <button
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-zinc-800/40 transition"
        onClick={() => setExpanded((v) => !v)}
      >
        {/* ID badge */}
        <span className="flex-shrink-0 text-xs font-mono font-bold text-zinc-400 bg-zinc-800 px-2 py-1 rounded">
          {c.id}
        </span>

        {/* Strategy + hypothesis */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-sm font-semibold text-zinc-100 truncate">
              {c.strategy_name}
            </span>
            {c.status === 'running' && (
              <div className="w-2 h-2 rounded-full bg-sky-400 animate-pulse flex-shrink-0" />
            )}
          </div>
          <p className="text-xs text-zinc-500 truncate">{c.hypothesis}</p>
        </div>

        {/* Score */}
        <div className="flex-shrink-0 text-center">
          <div className={`text-xl font-mono font-bold ${scoreColor}`}>
            {c.score}
          </div>
          <div className="text-xs text-zinc-600">score</div>
        </div>

        {/* Status badge */}
        <span
          className={`flex-shrink-0 text-xs font-semibold px-2.5 py-1 rounded-lg border ${status.bg} ${status.color}`}
        >
          {status.label}
        </span>

        {/* Gates compact dots */}
        <div className="flex-shrink-0 hidden md:block">
          {c.gate_results ? (
            <GateResults gates={c.gate_results} compact />
          ) : (
            <span className="text-xs font-mono text-zinc-600">
              {c.gates_passed}/{c.gates_total}
            </span>
          )}
        </div>

        {/* Expand chevron */}
        <span className="flex-shrink-0 text-zinc-600 text-xs">
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-zinc-800 px-4 py-4 space-y-4">
          {/* Hypothesis full text */}
          <div>
            <div className="text-xs text-zinc-500 uppercase tracking-wider mb-1">
              Hypothesis
            </div>
            <p className="text-sm text-zinc-300 leading-relaxed">{c.hypothesis}</p>
          </div>

          {/* Key metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <MetricTile
              label="Gates Passed"
              value={`${c.gates_passed}/${c.gates_total}`}
              positive={allGatesPassed}
              negative={c.gates_passed < 7}
            />
            <MetricTile
              label="Score"
              value={String(c.score)}
              positive={c.score >= 80}
              negative={c.score < 50}
            />
            {c.sharpe_improvement != null && (
              <MetricTile
                label="Sharpe Δ"
                value={`${c.sharpe_improvement >= 0 ? '+' : ''}${c.sharpe_improvement.toFixed(2)}`}
                positive={c.sharpe_improvement >= 0.1}
                negative={c.sharpe_improvement < 0}
              />
            )}
            {c.net_profit_delta != null && (
              <MetricTile
                label="Net Profit Δ"
                value={`${c.net_profit_delta >= 0 ? '+' : ''}$${c.net_profit_delta.toFixed(0)}`}
                positive={c.net_profit_delta > 0}
                negative={c.net_profit_delta < 0}
              />
            )}
          </div>

          {/* Full gate results */}
          {c.gate_results && <GateResults gates={c.gate_results} />}

          {/* Notes + approval info */}
          {c.notes && (
            <div className="bg-zinc-950 rounded-lg p-3 border border-zinc-800">
              <div className="text-xs text-zinc-500 mb-1">Notes</div>
              <p className="text-xs text-zinc-400">{c.notes}</p>
            </div>
          )}

          {c.approved_at && (
            <div className="flex items-center gap-2 text-xs text-zinc-500">
              <span className="text-emerald-500">✓ Approved</span>
              <span>{new Date(c.approved_at).toLocaleString()}</span>
              {c.approved_by && <span>by {c.approved_by}</span>}
            </div>
          )}

          <div className="text-xs text-zinc-700 font-mono">
            session: {c.session_id} · created {new Date(c.created_at).toLocaleString()}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricTile({
  label,
  value,
  positive,
  negative,
}: {
  label: string;
  value: string;
  positive?: boolean;
  negative?: boolean;
}) {
  const color = positive
    ? 'text-emerald-400'
    : negative
    ? 'text-red-400'
    : 'text-zinc-300';
  return (
    <div className="bg-zinc-950 rounded-lg p-2.5 border border-zinc-800">
      <div className="text-xs text-zinc-500 mb-1">{label}</div>
      <div className={`text-sm font-mono font-bold ${color}`}>{value}</div>
    </div>
  );
}
