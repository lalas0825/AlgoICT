'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';
import { CandidateCard, type Candidate, type CandidateStatus } from '@/features/strategy-lab/components/CandidateCard';
import { SessionHistory, type LabSession } from '@/features/strategy-lab/components/SessionHistory';
import type { GateResultsData } from '@/features/strategy-lab/components/GateResults';

// Raw row from Supabase strategy_candidates
interface CandidateRow {
  id: string;
  hypothesis: string;
  strategy_name: string;
  status: string;
  gates_passed: number;
  gates_total: number;
  score: number;
  gate_results: Record<string, unknown> | null;
  session_id: string;
  created_at: string;
  approved_at: string | null;
  approved_by: string | null;
  sharpe_improvement: number | null;
  net_profit_delta: number | null;
  notes: string | null;
  mode: string | null;
}

type FilterStatus = 'all' | CandidateStatus;
type SortKey = 'score' | 'created_at' | 'gates_passed';

function rowToCandidate(row: CandidateRow): Candidate {
  return {
    id: row.id,
    hypothesis: row.hypothesis,
    strategy_name: row.strategy_name,
    status: row.status as CandidateStatus,
    gates_passed: row.gates_passed ?? 0,
    gates_total: row.gates_total ?? 9,
    score: row.score ?? 0,
    gate_results: (row.gate_results as GateResultsData | null) ?? null,
    session_id: row.session_id,
    created_at: row.created_at,
    approved_at: row.approved_at,
    approved_by: row.approved_by,
    sharpe_improvement: row.sharpe_improvement,
    net_profit_delta: row.net_profit_delta,
    notes: row.notes,
  };
}

function deriveSessions(rows: CandidateRow[]): LabSession[] {
  const map = new Map<string, LabSession>();

  for (const row of rows) {
    const sid = row.session_id;
    if (!map.has(sid)) {
      map.set(sid, {
        session_id: sid,
        date: row.created_at,
        mode: (row.mode as LabSession['mode']) ?? 'generate',
        hypotheses_generated: 0,
        candidates_found: 0,
        best_score: 0,
        statuses: {
          pending: 0,
          running: 0,
          passed: 0,
          failed: 0,
          approved: 0,
          rejected: 0,
        },
      });
    }
    const s = map.get(sid)!;
    s.hypotheses_generated += 1;
    if (row.gates_passed === row.gates_total && row.gates_total > 0) {
      s.candidates_found += 1;
    }
    if (row.score > s.best_score) s.best_score = row.score;
    const st = (row.status as CandidateStatus) ?? 'pending';
    s.statuses[st] = (s.statuses[st] ?? 0) + 1;
    // Keep earliest created_at as session date
    if (row.created_at < s.date) s.date = row.created_at;
  }

  return Array.from(map.values()).sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
  );
}

export default function StrategyLabPage() {
  const [rows, setRows] = useState<CandidateRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [sortKey, setSortKey] = useState<SortKey>('created_at');
  const [activeSession, setActiveSession] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const { data, error: err } = await supabase
        .from('strategy_candidates')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(200);

      if (err) {
        setError(err.message);
      } else {
        setRows((data ?? []) as CandidateRow[]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();

    const channel = supabase
      .channel('strategy-lab-realtime')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'strategy_candidates' },
        (payload) => {
          setRows((prev) => [payload.new as CandidateRow, ...prev]);
        }
      )
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'strategy_candidates' },
        (payload) => {
          const updated = payload.new as CandidateRow;
          setRows((prev) =>
            prev.map((r) => (r.id === updated.id ? updated : r))
          );
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchData]);

  const sessions = useMemo(() => deriveSessions(rows), [rows]);

  const candidates = useMemo<Candidate[]>(() => {
    let filtered = rows.map(rowToCandidate);

    if (activeSession) {
      filtered = filtered.filter((c) => c.session_id === activeSession);
    }
    if (filterStatus !== 'all') {
      filtered = filtered.filter((c) => c.status === filterStatus);
    }

    filtered.sort((a, b) => {
      if (sortKey === 'score') return b.score - a.score;
      if (sortKey === 'gates_passed') return b.gates_passed - a.gates_passed;
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });

    return filtered;
  }, [rows, activeSession, filterStatus, sortKey]);

  // Summary stats
  const stats = useMemo(() => {
    const total = rows.length;
    const passed = rows.filter((r) => r.gates_passed === r.gates_total && r.gates_total > 0).length;
    const approved = rows.filter((r) => r.status === 'approved').length;
    const running = rows.filter((r) => r.status === 'running').length;
    const avgScore =
      rows.length > 0
        ? Math.round(rows.reduce((s, r) => s + (r.score ?? 0), 0) / rows.length)
        : 0;
    return { total, passed, approved, running, avgScore };
  }, [rows]);

  const FILTER_OPTIONS: { value: FilterStatus; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'approved', label: 'Approved' },
    { value: 'passed', label: 'Passed' },
    { value: 'running', label: 'Running' },
    { value: 'failed', label: 'Failed' },
    { value: 'pending', label: 'Pending' },
    { value: 'rejected', label: 'Rejected' },
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex items-center gap-3 text-zinc-500">
          <div className="w-4 h-4 border-2 border-zinc-600 border-t-zinc-300 rounded-full animate-spin" />
          <span className="text-sm font-mono">Loading strategy candidates…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-50">Strategy Lab</h1>
          <p className="text-sm text-zinc-500 mt-0.5">
            AI-generated hypotheses · 9 anti-overfit gates · Human approval required
          </p>
        </div>
        {stats.running > 0 && (
          <div className="flex items-center gap-2 px-3 py-2 bg-sky-500/10 border border-sky-500/30 rounded-lg">
            <div className="w-2 h-2 bg-sky-400 rounded-full animate-pulse" />
            <span className="text-sm text-sky-400 font-mono">
              {stats.running} running
            </span>
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatTile label="Total Hypotheses" value={String(stats.total)} />
        <StatTile
          label="All Gates Passed"
          value={String(stats.passed)}
          positive={stats.passed > 0}
        />
        <StatTile
          label="Approved"
          value={String(stats.approved)}
          positive={stats.approved > 0}
        />
        <StatTile
          label="Avg Score"
          value={stats.avgScore > 0 ? String(stats.avgScore) : '—'}
          positive={stats.avgScore >= 70}
          negative={stats.avgScore > 0 && stats.avgScore < 50}
        />
        <StatTile
          label="Sessions"
          value={String(sessions.length)}
        />
      </div>

      {/* Validation split reminder */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-zinc-900 border border-zinc-800 rounded-xl text-xs text-zinc-500 font-mono">
        <span className="text-zinc-400 font-semibold">Data split:</span>
        <span>Train 2019–2022</span>
        <span className="text-zinc-700">·</span>
        <span>Validation 2023</span>
        <span className="text-zinc-700">·</span>
        <span className="text-red-400 font-semibold">Test 2024–2025 🔒 LOCKED</span>
      </div>

      {/* Session history */}
      <SessionHistory
        sessions={sessions}
        onSelectSession={(id) =>
          setActiveSession((prev) => (prev === id ? null : id))
        }
        activeSessionId={activeSession ?? undefined}
      />

      {/* Candidate list: filters + sort */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1">
          {FILTER_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setFilterStatus(value)}
              className={`px-2.5 py-1 text-xs font-mono rounded transition ${
                filterStatus === value
                  ? 'bg-zinc-700 text-zinc-50 font-semibold'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-600">Sort:</span>
          {(['score', 'gates_passed', 'created_at'] as SortKey[]).map((k) => (
            <button
              key={k}
              onClick={() => setSortKey(k)}
              className={`text-xs font-mono px-2 py-1 rounded transition ${
                sortKey === k
                  ? 'text-zinc-200 bg-zinc-800'
                  : 'text-zinc-600 hover:text-zinc-400'
              }`}
            >
              {k === 'created_at' ? 'recent' : k.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      {/* Showing X of Y indicator */}
      {activeSession && (
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span>Session filter active:</span>
          <span className="font-mono text-zinc-400">{activeSession}</span>
          <button
            onClick={() => setActiveSession(null)}
            className="text-zinc-600 hover:text-zinc-400 underline"
          >
            clear
          </button>
        </div>
      )}

      {/* Candidates */}
      <div className="space-y-2">
        {candidates.length === 0 ? (
          <div className="text-center py-16 text-zinc-600 text-sm">
            {rows.length === 0
              ? 'No candidates yet. Run the Strategy Lab to generate hypotheses.'
              : 'No candidates match the current filter.'}
          </div>
        ) : (
          candidates.map((c) => <CandidateCard key={c.id} candidate={c} />)
        )}
      </div>

      {candidates.length > 0 && (
        <div className="text-center text-xs text-zinc-700 font-mono pb-4">
          {candidates.length} of {rows.length} candidates
        </div>
      )}
    </div>
  );
}

function StatTile({
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
    : 'text-zinc-200';
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3">
      <div className="text-xs text-zinc-500 mb-1">{label}</div>
      <div className={`text-2xl font-mono font-bold ${color}`}>{value}</div>
    </div>
  );
}
