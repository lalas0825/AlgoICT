'use client';

import { useEffect, useMemo, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';

// ===================================================================== //
// Types — mirror the Supabase schema in 0007_edge_hunt.sql.
// Dashboard is READ-ONLY: it only ever SELECTs + subscribes.
// ===================================================================== //

interface EdgeHuntRun {
  id: string;
  concept: string;
  batch: string;
  period_year: string;
  trades: number;
  win_rate: number | null;
  net_pnl: number | null;
  med_mfe_r: number | null;
  med_mae_r: number | null;
  ratio: number | null;
  p_mfe_2r: number | null;
  verdict: string | null;
  created_at: string;
}

type PhaseStatus = 'done' | 'work' | 'wait';

interface FunnelPhase {
  key: string;
  title: string;
  detail: string;
  status: PhaseStatus;
}

interface SBAutopsyCard {
  period: string;
  pnl: number;
  wr: number;
  note?: string;
}

interface Cycle2Theme {
  key: string;
  title: string;
  detail: string;
  status: string;
}

interface EdgeHuntStatePayload {
  funnel_phases?: FunnelPhase[];
  sb_autopsy?: SBAutopsyCard[];
  cycle2_themes?: Cycle2Theme[];
  criterion?: {
    ratio_min?: number;
    p2r_min?: number;
    years?: string[];
    rule?: string;
  };
  summary?: {
    survivors?: string[];
    partials?: string[];
    concepts_screened?: number;
  };
  last_updated?: string;
}

interface EdgeHuntStateRow {
  id: string;
  payload: EdgeHuntStatePayload | null;
  updated_at: string;
}

// Screening-year columns the asymmetry tables render.
const YEARS = ['2019', '2022'] as const;
const RATIO_THRESHOLD = 1.4;

// Friendlier batch labels for the section headers.
const BATCH_LABELS: Record<string, string> = {
  phase1: 'Phase 1 — 12 minimal triggers',
  ob_retest_r2: 'Round 2 — OB-retest quality filters',
  round3: 'Round 3 — Lab hypotheses',
};

function batchLabel(batch: string): string {
  return BATCH_LABELS[batch] ?? batch;
}

// ===================================================================== //

export default function EdgeHuntPage() {
  const [runs, setRuns] = useState<EdgeHuntRun[]>([]);
  const [state, setState] = useState<EdgeHuntStatePayload | null>(null);
  const [stateUpdatedAt, setStateUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      try {
        const [runsRes, stateRes] = await Promise.all([
          supabase
            .from('edge_hunt_runs')
            .select('*')
            .order('batch', { ascending: true })
            .order('concept', { ascending: true })
            .order('period_year', { ascending: true })
            .limit(500),
          supabase
            .from('edge_hunt_state')
            .select('*')
            .eq('id', 'current')
            .maybeSingle(),
        ]);

        if (cancelled) return;

        if (runsRes.error) {
          setError(runsRes.error.message);
        } else {
          setRuns((runsRes.data ?? []) as EdgeHuntRun[]);
        }

        if (!stateRes.error && stateRes.data) {
          const row = stateRes.data as EdgeHuntStateRow;
          setState(row.payload ?? null);
          setStateUpdatedAt(row.updated_at ?? null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Unknown error');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchAll();

    // Realtime on BOTH tables.
    const channel = supabase
      .channel('edge-hunt-realtime')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'edge_hunt_runs' },
        (payload) => {
          if (payload.eventType === 'DELETE') {
            const oldId = (payload.old as { id?: string })?.id;
            if (oldId) setRuns((prev) => prev.filter((r) => r.id !== oldId));
            return;
          }
          const row = payload.new as EdgeHuntRun;
          setRuns((prev) => {
            const idx = prev.findIndex((r) => r.id === row.id);
            if (idx === -1) return [...prev, row];
            const next = [...prev];
            next[idx] = row;
            return next;
          });
        }
      )
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'edge_hunt_state' },
        (payload) => {
          const row = payload.new as EdgeHuntStateRow;
          if (row?.id === 'current') {
            setState(row.payload ?? null);
            setStateUpdatedAt(row.updated_at ?? null);
          }
        }
      )
      .subscribe();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, []);

  // Group runs by batch, then by concept, indexing stats per year.
  const batches = useMemo(() => groupRuns(runs), [runs]);

  const survivors = state?.summary?.survivors ?? [];
  const partials = state?.summary?.partials ?? [];
  const ratioMin = state?.criterion?.ratio_min ?? RATIO_THRESHOLD;
  const p2rMin = state?.criterion?.p2r_min ?? 0.3;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex items-center gap-3 text-zinc-500">
          <div className="w-4 h-4 border-2 border-zinc-600 border-t-zinc-300 rounded-full animate-spin" />
          <span className="text-sm font-mono">Loading Edge Hunt War Room…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-zinc-50">Edge Hunt War Room</h1>
          <p className="text-sm text-zinc-500 mt-0.5">
            Concept → only the asymmetric ones become a strategy → 9 gates → shadow live
          </p>
        </div>
        <div className="flex items-center gap-3">
          {survivors.length > 0 ? (
            <div className="flex items-center gap-2 px-3 py-2 bg-emerald-500/10 border border-emerald-500/30 rounded-lg">
              <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
              <span className="text-sm text-emerald-400 font-mono">
                {survivors.length} survivor{survivors.length === 1 ? '' : 's'}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg">
              <span className="text-sm text-zinc-500 font-mono">0 survivors yet</span>
            </div>
          )}
          {stateUpdatedAt && (
            <span className="text-xs text-zinc-600 font-mono">
              updated {new Date(stateUpdatedAt).toLocaleString()}
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* (a) Funnel strip */}
      <FunnelStrip phases={state?.funnel_phases ?? []} />

      {/* Pre-registered criterion reminder */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-zinc-900 border border-zinc-800 rounded-xl text-xs text-zinc-500 font-mono flex-wrap">
        <span className="text-zinc-400 font-semibold">Pre-registered criterion:</span>
        <span>
          medMFE/medMAE ≥{' '}
          <span className="text-emerald-400 font-semibold">{ratioMin.toFixed(1)}</span>
        </span>
        <span className="text-zinc-700">·</span>
        <span>
          P(MFE≥2R) ≥{' '}
          <span className="text-emerald-400 font-semibold">{(p2rMin * 100).toFixed(0)}%</span>
        </span>
        <span className="text-zinc-700">·</span>
        <span className="text-zinc-400">survives only if BOTH years qualify</span>
      </div>

      {/* (b) Asymmetry section — one table per batch */}
      <div className="space-y-5">
        <h2 className="text-lg font-semibold text-zinc-200">Asymmetry screening</h2>
        {batches.length === 0 ? (
          <div className="text-center py-12 text-zinc-600 text-sm border border-zinc-800 rounded-xl bg-zinc-900">
            No edge-hunt runs published yet. Run{' '}
            <span className="font-mono text-zinc-400">analysis/publish_edge_hunt.py</span>.
          </div>
        ) : (
          batches.map((b) => (
            <AsymmetryTable
              key={b.batch}
              batch={b.batch}
              concepts={b.concepts}
              ratioMin={ratioMin}
            />
          ))
        )}

        {/* survivors / partials roll-up */}
        {(survivors.length > 0 || partials.length > 0) && (
          <div className="flex flex-wrap gap-3 text-xs">
            {survivors.length > 0 && (
              <div className="flex items-center gap-2 px-3 py-2 bg-emerald-500/10 border border-emerald-500/30 rounded-lg">
                <span className="text-emerald-400 font-semibold">Survivors:</span>
                <span className="font-mono text-emerald-300">{survivors.join(', ')}</span>
              </div>
            )}
            {partials.length > 0 && (
              <div className="flex items-center gap-2 px-3 py-2 bg-amber-500/10 border border-amber-500/30 rounded-lg">
                <span className="text-amber-400 font-semibold">Partial (1/2 years):</span>
                <span className="font-mono text-amber-300">{partials.join(', ')}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* (c) SB closed-chapter cards */}
      <SBAutopsy cards={state?.sb_autopsy ?? []} />

      {/* (d) Cycle-2 themes */}
      <Cycle2Themes themes={state?.cycle2_themes ?? []} />

      <div className="text-center text-xs text-zinc-700 font-mono pb-4">
        READ-ONLY · Python writes via analysis/publish_edge_hunt.py · dashboard reads Supabase
      </div>
    </div>
  );
}

// ===================================================================== //
// Grouping
// ===================================================================== //

interface ConceptRow {
  concept: string;
  verdict: string | null;
  byYear: Record<string, EdgeHuntRun>;
}

interface BatchGroup {
  batch: string;
  concepts: ConceptRow[];
}

function groupRuns(runs: EdgeHuntRun[]): BatchGroup[] {
  const byBatch = new Map<string, Map<string, ConceptRow>>();

  for (const r of runs) {
    if (!byBatch.has(r.batch)) byBatch.set(r.batch, new Map());
    const conceptMap = byBatch.get(r.batch)!;
    if (!conceptMap.has(r.concept)) {
      conceptMap.set(r.concept, {
        concept: r.concept,
        verdict: r.verdict,
        byYear: {},
      });
    }
    const cr = conceptMap.get(r.concept)!;
    cr.byYear[r.period_year] = r;
    // verdict is concept-level (same across years); keep any non-null.
    if (r.verdict) cr.verdict = r.verdict;
  }

  // Phase 1 first, then R2, then round3, then anything else alphabetically.
  const order = ['phase1', 'ob_retest_r2', 'round3'];
  const result: BatchGroup[] = [];
  const batchKeys = Array.from(byBatch.keys()).sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    if (ia !== -1 && ib !== -1) return ia - ib;
    if (ia !== -1) return -1;
    if (ib !== -1) return 1;
    return a.localeCompare(b);
  });

  for (const batch of batchKeys) {
    const concepts = Array.from(byBatch.get(batch)!.values()).sort((a, b) =>
      a.concept.localeCompare(b.concept)
    );
    result.push({ batch, concepts });
  }
  return result;
}

// ===================================================================== //
// (a) Funnel strip
// ===================================================================== //

const PHASE_STYLES: Record<PhaseStatus, { box: string; dot: string; label: string }> = {
  done: {
    box: 'bg-emerald-500/10 border-emerald-500/30',
    dot: 'bg-emerald-400',
    label: 'text-emerald-400',
  },
  work: {
    box: 'bg-sky-500/10 border-sky-500/30',
    dot: 'bg-sky-400 animate-pulse',
    label: 'text-sky-400',
  },
  wait: {
    box: 'bg-zinc-900 border-zinc-800',
    dot: 'bg-zinc-600',
    label: 'text-zinc-500',
  },
};

function FunnelStrip({ phases }: { phases: FunnelPhase[] }) {
  if (phases.length === 0) {
    return (
      <div className="text-sm text-zinc-600 border border-zinc-800 rounded-xl bg-zinc-900 px-4 py-3">
        Funnel state not published yet.
      </div>
    );
  }
  return (
    <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
      {phases.map((p, i) => {
        const s = PHASE_STYLES[p.status] ?? PHASE_STYLES.wait;
        return (
          <div key={p.key} className="flex items-stretch gap-2 shrink-0">
            <div
              className={`min-w-[180px] max-w-[240px] border rounded-xl p-3 ${s.box}`}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <div className={`w-2 h-2 rounded-full ${s.dot}`} />
                <span className={`text-xs font-mono font-semibold uppercase tracking-wide ${s.label}`}>
                  {p.status}
                </span>
              </div>
              <div className="text-sm font-semibold text-zinc-100 leading-tight">
                {p.title}
              </div>
              <div className="text-xs text-zinc-500 mt-1 leading-snug">{p.detail}</div>
            </div>
            {i < phases.length - 1 && (
              <div className="flex items-center text-zinc-700 text-lg">→</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ===================================================================== //
// (b) Asymmetry table (one per batch)
// ===================================================================== //

function AsymmetryTable({
  batch,
  concepts,
  ratioMin,
}: {
  batch: string;
  concepts: ConceptRow[];
  ratioMin: number;
}) {
  return (
    <div className="border border-zinc-800 rounded-xl bg-zinc-900 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-zinc-800">
        <h3 className="text-sm font-semibold text-zinc-200">{batchLabel(batch)}</h3>
        <span className="text-xs text-zinc-600 font-mono">
          ratio ≥ {ratioMin.toFixed(1)} = asymmetric (green)
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-zinc-500 border-b border-zinc-800">
              <th className="text-left font-medium px-4 py-2">concept</th>
              {YEARS.map((y) => (
                <th key={y} className="text-right font-medium px-3 py-2">
                  {y} ratio
                </th>
              ))}
              <th className="text-right font-medium px-3 py-2">P2R</th>
              <th className="text-right font-medium px-3 py-2">net</th>
              <th className="text-right font-medium px-3 py-2">trades</th>
              <th className="text-right font-medium px-4 py-2">verdict</th>
            </tr>
          </thead>
          <tbody>
            {concepts.map((c) => {
              // Use the most recent screening year present for P2R/net/trades.
              const ref = c.byYear[YEARS[YEARS.length - 1]] ?? c.byYear[YEARS[0]];
              return (
                <tr
                  key={c.concept}
                  className="border-b border-zinc-800/60 last:border-0 hover:bg-zinc-800/30 transition"
                >
                  <td className="px-4 py-2 font-mono text-zinc-300">{c.concept}</td>
                  {YEARS.map((y) => (
                    <RatioCell key={y} run={c.byYear[y]} ratioMin={ratioMin} />
                  ))}
                  <td className="px-3 py-2 text-right font-mono text-zinc-400">
                    {fmtPct(ref?.p_mfe_2r)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-mono ${netColor(ref?.net_pnl)}`}
                  >
                    {fmtMoney(ref?.net_pnl)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-zinc-500">
                    {ref?.trades ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <VerdictBadge verdict={c.verdict} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RatioCell({ run, ratioMin }: { run?: EdgeHuntRun; ratioMin: number }) {
  if (!run) {
    return <td className="px-3 py-2 text-right font-mono text-zinc-700">—</td>;
  }
  const ratio = run.ratio;
  const isAsym = ratio != null && ratio >= ratioMin;
  return (
    <td
      className={`px-3 py-2 text-right font-mono ${
        ratio == null
          ? 'text-zinc-700'
          : isAsym
          ? 'text-emerald-400 font-semibold'
          : 'text-zinc-500'
      }`}
    >
      {ratio == null ? '∞' : ratio.toFixed(2)}
    </td>
  );
}

function VerdictBadge({ verdict }: { verdict: string | null }) {
  const v = verdict ?? 'dies';
  const styles: Record<string, string> = {
    survives: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    partial: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    dies: 'bg-zinc-800 text-zinc-500 border-zinc-700',
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-mono border ${
        styles[v] ?? styles.dies
      }`}
    >
      {v}
    </span>
  );
}

// ===================================================================== //
// (c) SB closed-chapter cards
// ===================================================================== //

function SBAutopsy({ cards }: { cards: SBAutopsyCard[] }) {
  if (cards.length === 0) return null;
  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-2">
        <h2 className="text-lg font-semibold text-zinc-200">Silver Bullet — closed chapter</h2>
        <span className="text-xs text-zinc-600">
          honest-fill autopsy · base ≈ breakeven, WR ~36%
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {cards.map((c) => {
          const positive = c.pnl > 0;
          const agg = c.period.toLowerCase() === 'agg';
          return (
            <div
              key={c.period}
              className={`rounded-xl p-3 border ${
                agg
                  ? 'bg-zinc-800/60 border-zinc-700'
                  : 'bg-zinc-900 border-zinc-800'
              }`}
            >
              <div className="text-xs text-zinc-500 mb-1">{c.period}</div>
              <div
                className={`text-xl font-mono font-bold ${
                  positive ? 'text-emerald-400' : 'text-red-400'
                }`}
              >
                {fmtMoney(c.pnl)}
              </div>
              <div className="text-xs text-zinc-600 font-mono mt-0.5">
                WR {(c.wr * 100).toFixed(0)}%
              </div>
              {c.note && (
                <div className="text-[11px] text-zinc-600 mt-1 leading-snug">{c.note}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ===================================================================== //
// (d) Cycle-2 themes
// ===================================================================== //

const THEME_STATUS_STYLES: Record<string, string> = {
  generating: 'text-sky-400 bg-sky-500/10 border-sky-500/30',
  screening: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  survives: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  dead: 'text-zinc-500 bg-zinc-800 border-zinc-700',
};

function Cycle2Themes({ themes }: { themes: Cycle2Theme[] }) {
  if (themes.length === 0) return null;
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-zinc-200">Cycle 2 — next themes</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {themes.map((t) => {
          const badge = THEME_STATUS_STYLES[t.status] ?? THEME_STATUS_STYLES.dead;
          return (
            <div
              key={t.key}
              className="rounded-xl p-4 border border-zinc-800 bg-zinc-900"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm font-semibold text-zinc-100">{t.title}</div>
                <span
                  className={`inline-block px-2 py-0.5 rounded text-[11px] font-mono border ${badge}`}
                >
                  {t.status}
                </span>
              </div>
              <div className="text-xs text-zinc-500 leading-snug">{t.detail}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ===================================================================== //
// Formatters
// ===================================================================== //

function fmtMoney(v: number | null | undefined): string {
  if (v == null) return '—';
  const sign = v < 0 ? '-' : '';
  return `${sign}$${Math.abs(Math.round(v)).toLocaleString()}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${(v * 100).toFixed(0)}%`;
}

function netColor(v: number | null | undefined): string {
  if (v == null) return 'text-zinc-700';
  return v >= 0 ? 'text-emerald-400' : 'text-red-400';
}
