'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import { supabase } from '@/shared/lib/supabase';

// MNQ round-trip commission per contract (matches engine config.MNQ_ROUND_TRIP_FEE).
// Engine writes GROSS pnl to the trades table; net = gross - fee*contracts.
const FEE_PER_CONTRACT = 1.24;
const CONFLUENCE_MAX = 19; // engine-wide max (SB sub-score is /10)
const CT_TZ = 'America/Chicago'; // bot trades in CT; render in CT regardless of viewer TZ

interface Trade {
  id: string;
  strategy: string | null;
  direction: string | null;
  entry_price: number | null;
  exit_price: number | null;
  entry_time: string;
  exit_time: string | null;
  pnl: number | null;
  contracts: number | null;
  confluence_score: number | null;
  kill_zone: string | null;
  status: string | null;
  reason: string | null;
}

// ---- CT time helpers (DST-aware via Intl) ----
function ctParts(iso: string): Record<string, string> {
  const f = new Intl.DateTimeFormat('en-US', {
    timeZone: CT_TZ, year: 'numeric', month: '2-digit', day: '2-digit',
    weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  });
  return Object.fromEntries(f.formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
}
const ctDate = (iso: string) => { const p = ctParts(iso); return `${p.year}-${p.month}-${p.day}`; };
const ctDayLabel = (iso: string) => { const p = ctParts(iso); return `${p.weekday} ${p.month}/${p.day}`; };
const ctTime = (iso: string) => { const p = ctParts(iso); return `${p.hour}:${p.minute}`; };
// Monday-of-week key (YYYY-MM-DD) from a CT calendar date
function weekKey(iso: string): string {
  const [y, m, d] = ctDate(iso).split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  const dow = (dt.getUTCDay() + 6) % 7; // Mon=0 .. Sun=6
  dt.setUTCDate(dt.getUTCDate() - dow);
  return dt.toISOString().slice(0, 10);
}

const netOf = (t: Trade) => (t.pnl ?? 0) - FEE_PER_CONTRACT * (t.contracts ?? 0);

interface Agg { n: number; w: number; l: number; gross: number; fees: number; net: number; }
function aggregate(ts: Trade[]): Agg {
  const a: Agg = { n: 0, w: 0, l: 0, gross: 0, fees: 0, net: 0 };
  for (const t of ts) {
    const nt = netOf(t);
    a.n++; a.gross += t.pnl ?? 0; a.fees += FEE_PER_CONTRACT * (t.contracts ?? 0); a.net += nt;
    if (nt > 0) a.w++; else a.l++;
  }
  return a;
}
const wrOf = (a: Agg) => (a.n ? (a.w / a.n) * 100 : 0);
function pfOf(ts: Trade[]): number {
  let gw = 0, gl = 0;
  for (const t of ts) { const n = netOf(t); if (n > 0) gw += n; else gl += -n; }
  return gl > 0 ? gw / gl : gw > 0 ? Infinity : 0;
}
const money = (v: number) => `${v >= 0 ? '+' : '-'}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
const pfLabel = (v: number) => (v === Infinity ? '∞' : v.toFixed(2));

function groupBy(ts: Trade[], keyFn: (t: Trade) => string): [string, Trade[]][] {
  const m = new Map<string, Trade[]>();
  for (const t of ts) { const k = keyFn(t); (m.get(k) ?? m.set(k, []).get(k)!).push(t); }
  return [...m.entries()];
}

export default function TradesPage() {
  const [all, setAll] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = useCallback(async () => {
    const { data, error: err } = await supabase
      .from('trades')
      .select('*')
      .order('entry_time', { ascending: false })
      .limit(500);
    if (err) setError(err.message);
    else setAll((data ?? []) as Trade[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    // Initial load. fetchTrades() only setStates AFTER an awaited network round-trip,
    // so it is not a synchronous setState cascade (false positive for this rule here).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchTrades();
    const channel = supabase
      .channel('journal-realtime')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'trades' }, () => fetchTrades())
      .subscribe();
    const onFocus = () => fetchTrades();
    window.addEventListener('focus', onFocus);
    return () => { window.removeEventListener('focus', onFocus); supabase.removeChannel(channel); };
  }, [fetchTrades]);

  // closed = has an exit + realized pnl (status column is unreliable: engine leaves it "open")
  const closed = useMemo(() => all.filter((t) => t.exit_time != null && t.pnl != null), [all]);
  const openCount = all.length - closed.length;

  const overall = useMemo(() => aggregate(closed), [closed]);
  const overallPf = useMemo(() => pfOf(closed), [closed]);

  const byWeek = useMemo(() =>
    groupBy(closed, (t) => weekKey(t.entry_time)).sort((a, b) => (a[0] < b[0] ? 1 : -1)), [closed]);
  const byDay = useMemo(() =>
    groupBy(closed, (t) => ctDate(t.entry_time)).sort((a, b) => (a[0] < b[0] ? 1 : -1)).slice(0, 12), [closed]);
  const byKz = useMemo(() =>
    groupBy(closed, (t) => t.kill_zone ?? '—').sort((a, b) => aggregate(b[1]).net - aggregate(a[1]).net), [closed]);

  if (loading) return <div className="p-6 text-zinc-400">Loading journal…</div>;
  if (error) return <div className="p-6 text-red-400">Error: {error}</div>;

  const kpi = (label: string, value: string, tone: 'pos' | 'neg' | 'neutral' = 'neutral', sub?: string) => (
    <div className="border border-zinc-800 rounded-lg p-4 bg-zinc-900">
      <div className="text-xs text-zinc-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold font-mono ${tone === 'pos' ? 'text-green-400' : tone === 'neg' ? 'text-red-400' : 'text-zinc-100'}`}>{value}</div>
      {sub && <div className="text-xs text-zinc-500 mt-1">{sub}</div>}
    </div>
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl font-bold">Trade Journal</h1>
        <div className="text-xs text-zinc-500 font-mono">
          {closed.length} closed{openCount > 0 ? ` · ${openCount} open/pending` : ''} · net of fees · times CT
        </div>
      </div>

      {/* KPI row — over all loaded closed trades */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {kpi('Net P&L', money(overall.net), overall.net > 0 ? 'pos' : overall.net < 0 ? 'neg' : 'neutral', `gross ${money(overall.gross)} − $${overall.fees.toFixed(0)} fees`)}
        {kpi('Win Rate', `${wrOf(overall).toFixed(1)}%`, wrOf(overall) >= 60 ? 'pos' : wrOf(overall) < 40 ? 'neg' : 'neutral', `${overall.w}W / ${overall.l}L`)}
        {kpi('Profit Factor', pfLabel(overallPf), overallPf >= 1.5 ? 'pos' : overallPf < 1 ? 'neg' : 'neutral')}
        {kpi('Trades', `${overall.n}`, 'neutral', `${byDay.length} days shown`)}
        {kpi('Avg Win', overall.w ? money(closed.filter((t) => netOf(t) > 0).reduce((s, t) => s + netOf(t), 0) / overall.w) : '—', 'pos')}
        {kpi('Avg Loss', overall.l ? money(closed.filter((t) => netOf(t) <= 0).reduce((s, t) => s + netOf(t), 0) / overall.l) : '—', 'neg')}
      </div>

      {/* By week */}
      <section>
        <h2 className="text-sm font-semibold text-zinc-300 mb-2">By Week (Mon-start)</h2>
        <div className="border border-zinc-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-zinc-900 text-zinc-400">
              <tr><th className="px-3 py-2 text-left">Week of</th><th className="px-3 py-2 text-right">Trades</th><th className="px-3 py-2 text-right">W/L</th><th className="px-3 py-2 text-right">WR</th><th className="px-3 py-2 text-right">Net</th></tr>
            </thead>
            <tbody>
              {byWeek.map(([wk, ts]) => { const a = aggregate(ts); return (
                <tr key={wk} className="border-t border-zinc-800">
                  <td className="px-3 py-2 text-zinc-300 font-mono">{wk}</td>
                  <td className="px-3 py-2 text-right text-zinc-400">{a.n}</td>
                  <td className="px-3 py-2 text-right text-zinc-400">{a.w}/{a.l}</td>
                  <td className="px-3 py-2 text-right text-zinc-400">{wrOf(a).toFixed(0)}%</td>
                  <td className={`px-3 py-2 text-right font-semibold font-mono ${a.net >= 0 ? 'text-green-400' : 'text-red-400'}`}>{money(a.net)}</td>
                </tr>); })}
            </tbody>
          </table>
        </div>
      </section>

      {/* By day + By KZ side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section>
          <h2 className="text-sm font-semibold text-zinc-300 mb-2">By Day (last 12)</h2>
          <div className="border border-zinc-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-zinc-900 text-zinc-400"><tr><th className="px-3 py-2 text-left">Day</th><th className="px-3 py-2 text-right">T</th><th className="px-3 py-2 text-right">W/L</th><th className="px-3 py-2 text-right">WR</th><th className="px-3 py-2 text-right">Net</th></tr></thead>
              <tbody>
                {byDay.map(([d, ts]) => { const a = aggregate(ts); return (
                  <tr key={d} className="border-t border-zinc-800">
                    <td className="px-3 py-2 text-zinc-300">{ctDayLabel(ts[0].entry_time)}</td>
                    <td className="px-3 py-2 text-right text-zinc-400">{a.n}</td>
                    <td className="px-3 py-2 text-right text-zinc-400">{a.w}/{a.l}</td>
                    <td className="px-3 py-2 text-right text-zinc-400">{wrOf(a).toFixed(0)}%</td>
                    <td className={`px-3 py-2 text-right font-semibold font-mono ${a.net >= 0 ? 'text-green-400' : 'text-red-400'}`}>{money(a.net)}</td>
                  </tr>); })}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-zinc-300 mb-2">By Kill Zone</h2>
          <div className="border border-zinc-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-zinc-900 text-zinc-400"><tr><th className="px-3 py-2 text-left">Kill Zone</th><th className="px-3 py-2 text-right">T</th><th className="px-3 py-2 text-right">W/L</th><th className="px-3 py-2 text-right">WR</th><th className="px-3 py-2 text-right">Net</th></tr></thead>
              <tbody>
                {byKz.map(([kz, ts]) => { const a = aggregate(ts); return (
                  <tr key={kz} className="border-t border-zinc-800">
                    <td className="px-3 py-2 text-zinc-300">{kz}</td>
                    <td className="px-3 py-2 text-right text-zinc-400">{a.n}</td>
                    <td className="px-3 py-2 text-right text-zinc-400">{a.w}/{a.l}</td>
                    <td className="px-3 py-2 text-right text-zinc-400">{wrOf(a).toFixed(0)}%</td>
                    <td className={`px-3 py-2 text-right font-semibold font-mono ${a.net >= 0 ? 'text-green-400' : 'text-red-400'}`}>{money(a.net)}</td>
                  </tr>); })}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* Detailed ledger */}
      <section>
        <h2 className="text-sm font-semibold text-zinc-300 mb-2">Trades (most recent 60)</h2>
        <div className="overflow-x-auto border border-zinc-800 rounded-lg">
          <table className="w-full text-sm">
            <thead className="bg-zinc-900 text-zinc-400">
              <tr>
                <th className="px-3 py-2 text-left">Date</th><th className="px-3 py-2 text-left">Time</th>
                <th className="px-3 py-2 text-left">Dir</th><th className="px-3 py-2 text-left">KZ</th>
                <th className="px-3 py-2 text-right">Entry</th><th className="px-3 py-2 text-right">Exit</th>
                <th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Net</th>
                <th className="px-3 py-2 text-right">Conf</th><th className="px-3 py-2 text-left">Reason</th>
              </tr>
            </thead>
            <tbody>
              {closed.slice(0, 60).map((t) => { const n = netOf(t); return (
                <tr key={t.id} className="border-t border-zinc-800 hover:bg-zinc-900/50">
                  <td className="px-3 py-2 text-zinc-400">{ctDayLabel(t.entry_time)}</td>
                  <td className="px-3 py-2 text-zinc-400 font-mono">{ctTime(t.entry_time)}</td>
                  <td className={`px-3 py-2 font-medium ${t.direction === 'long' ? 'text-green-400' : 'text-red-400'}`}>{(t.direction ?? '?').toUpperCase()}</td>
                  <td className="px-3 py-2 text-zinc-400">{t.kill_zone ?? '—'}</td>
                  <td className="px-3 py-2 text-right text-zinc-400 font-mono">{t.entry_price?.toFixed(1) ?? '—'}</td>
                  <td className="px-3 py-2 text-right text-zinc-400 font-mono">{t.exit_price?.toFixed(1) ?? '—'}</td>
                  <td className="px-3 py-2 text-right text-zinc-400">{t.contracts ?? '—'}</td>
                  <td className={`px-3 py-2 text-right font-semibold font-mono ${n >= 0 ? 'text-green-400' : 'text-red-400'}`}>{money(n)}</td>
                  <td className="px-3 py-2 text-right text-zinc-500">{t.confluence_score ?? 0}/{CONFLUENCE_MAX}</td>
                  <td className="px-3 py-2 text-zinc-500">{t.reason ?? ''}</td>
                </tr>); })}
            </tbody>
          </table>
        </div>
      </section>

      {closed.length === 0 && (
        <div className="text-center py-12 text-zinc-500">No closed trades yet. The journal fills as the bot trades.</div>
      )}
    </div>
  );
}
