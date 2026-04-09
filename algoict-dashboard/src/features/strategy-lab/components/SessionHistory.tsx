'use client';

import type { CandidateStatus } from './CandidateCard';

export interface LabSession {
  session_id: string;
  date: string; // ISO
  mode: 'generate' | 'overnight' | 'custom';
  hypotheses_generated: number;
  candidates_found: number; // gates_passed === gates_total
  best_score: number;
  statuses: Record<CandidateStatus, number>;
}

interface SessionHistoryProps {
  sessions: LabSession[];
  onSelectSession?: (sessionId: string) => void;
  activeSessionId?: string;
}

const MODE_LABEL: Record<string, string> = {
  generate: 'Generate',
  overnight: 'Overnight',
  custom: 'Custom',
};

export function SessionHistory({
  sessions,
  onSelectSession,
  activeSessionId,
}: SessionHistoryProps) {
  if (sessions.length === 0) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
        <div className="text-xs text-zinc-500 uppercase tracking-wider font-medium mb-3">
          Lab Sessions
        </div>
        <div className="text-center py-8 text-zinc-600 text-sm">
          No sessions yet. Run{' '}
          <code className="font-mono text-zinc-500">
            python -m strategy_lab.lab_engine --mode generate
          </code>
        </div>
      </div>
    );
  }

  const totalHypotheses = sessions.reduce((s, r) => s + r.hypotheses_generated, 0);
  const totalCandidates = sessions.reduce((s, r) => s + r.candidates_found, 0);
  const totalApproved = sessions.reduce(
    (s, r) => s + (r.statuses.approved ?? 0),
    0
  );

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
      {/* Header + stats */}
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <span className="text-xs text-zinc-500 uppercase tracking-wider font-medium">
          Lab Sessions
        </span>
        <div className="flex items-center gap-4 text-xs font-mono text-zinc-500">
          <span>{sessions.length} sessions</span>
          <span className="text-zinc-700">·</span>
          <span>{totalHypotheses} hypotheses</span>
          <span className="text-zinc-700">·</span>
          <span className="text-emerald-400">{totalCandidates} candidates</span>
          <span className="text-zinc-700">·</span>
          <span className="text-emerald-300 font-semibold">{totalApproved} approved</span>
        </div>
      </div>

      {/* Session rows */}
      <div className="divide-y divide-zinc-800/50">
        {sessions.map((s) => {
          const isActive = s.session_id === activeSessionId;
          const passRate =
            s.hypotheses_generated > 0
              ? Math.round((s.candidates_found / s.hypotheses_generated) * 100)
              : 0;

          return (
            <button
              key={s.session_id}
              onClick={() => onSelectSession?.(s.session_id)}
              className={`w-full text-left px-4 py-3 flex items-center gap-4 transition ${
                isActive
                  ? 'bg-zinc-800/60 border-l-2 border-l-emerald-500'
                  : 'hover:bg-zinc-800/30'
              }`}
            >
              {/* Date + Mode */}
              <div className="w-40 flex-shrink-0">
                <div className="text-xs font-mono text-zinc-300">
                  {new Date(s.date).toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: '2-digit',
                  })}
                </div>
                <div className="text-xs text-zinc-600 mt-0.5">
                  {new Date(s.date).toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </div>
              </div>

              {/* Mode badge */}
              <span className="flex-shrink-0 text-xs font-mono px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">
                {MODE_LABEL[s.mode] ?? s.mode}
              </span>

              {/* Hypotheses → Candidates funnel */}
              <div className="flex-1 flex items-center gap-2 min-w-0">
                <div className="text-xs font-mono">
                  <span className="text-zinc-300">{s.hypotheses_generated}</span>
                  <span className="text-zinc-600"> hyp</span>
                </div>
                <span className="text-zinc-700 text-xs">→</span>
                <div className="text-xs font-mono">
                  <span
                    className={
                      s.candidates_found > 0 ? 'text-emerald-400' : 'text-zinc-500'
                    }
                  >
                    {s.candidates_found}
                  </span>
                  <span className="text-zinc-600"> found</span>
                </div>

                {/* Mini progress bar */}
                <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden max-w-24">
                  <div
                    className={`h-full rounded-full ${
                      passRate >= 30
                        ? 'bg-emerald-500'
                        : passRate > 0
                        ? 'bg-amber-500'
                        : 'bg-zinc-600'
                    }`}
                    style={{ width: `${passRate}%` }}
                  />
                </div>
                <span className="text-xs font-mono text-zinc-600">{passRate}%</span>
              </div>

              {/* Best score */}
              <div className="flex-shrink-0 text-right w-20">
                <div
                  className={`text-sm font-mono font-bold ${
                    s.best_score >= 80
                      ? 'text-emerald-400'
                      : s.best_score >= 60
                      ? 'text-sky-400'
                      : s.best_score >= 40
                      ? 'text-amber-400'
                      : 'text-zinc-600'
                  }`}
                >
                  {s.best_score > 0 ? s.best_score : '—'}
                </div>
                <div className="text-xs text-zinc-600">best</div>
              </div>

              {/* Status mini badges */}
              <div className="flex-shrink-0 flex items-center gap-1.5">
                {(s.statuses.approved ?? 0) > 0 && (
                  <span className="text-xs font-mono bg-emerald-500/15 text-emerald-400 px-1.5 py-0.5 rounded">
                    ✓ {s.statuses.approved}
                  </span>
                )}
                {(s.statuses.failed ?? 0) > 0 && (
                  <span className="text-xs font-mono bg-zinc-800 text-zinc-500 px-1.5 py-0.5 rounded">
                    ✗ {s.statuses.failed}
                  </span>
                )}
              </div>

              {/* Active indicator */}
              {isActive && (
                <span className="flex-shrink-0 text-xs text-emerald-500">◀</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
