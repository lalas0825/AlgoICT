'use client';

import { useEffect, useState, useCallback } from 'react';
import { supabase } from '@/shared/lib/supabase';
import type { BotState, Trade } from '@/features/dashboard/types';
import { HeartbeatIndicator } from '@/features/dashboard/components/HeartbeatIndicator';
import { PnLCard } from '@/features/dashboard/components/PnLCard';
import { RiskGauge } from '@/features/dashboard/components/RiskGauge';
import { VPINGauge } from '@/features/dashboard/components/VPINGauge';
import { SentimentCard } from '@/features/dashboard/components/SentimentCard';
import { GammaRegimeIndicator } from '@/features/dashboard/components/GammaRegimeIndicator';
import { PositionTable } from '@/features/dashboard/components/PositionTable';

// Safe defaults when bot_state row doesn't exist yet
const DEFAULT_BOT_STATE: BotState = {
  id: 'default',
  is_running: false,
  last_heartbeat: new Date(0).toISOString(),
  vpin: 0,
  toxicity_level: 'calm',
  shield_active: false,
  trades_today: 0,
  pnl_today: 0,
  daily_high_pnl: 0,
  max_loss_threshold: -1000,
  profit_cap: 1500,
  position_count: 0,
  wins_today: 0,
  losses_today: 0,
  swc_mood: 'choppy',
  swc_confidence: 0,
  swc_summary: 'Bot not connected.',
  gex_regime: 'unknown',
  gex_call_wall: null,
  gex_put_wall: null,
  gex_flip_point: null,
  updated_at: new Date(0).toISOString(),
};

export default function DashboardPage() {
  const [botState, setBotState] = useState<BotState>(DEFAULT_BOT_STATE);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(Date.now());

  // Tick every second to keep heartbeat timer fresh
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const fetchInitial = useCallback(async () => {
    const [stateRes, tradesRes] = await Promise.all([
      supabase.from('bot_state').select('*').single(),
      supabase
        .from('trades')
        .select('*')
        .eq('status', 'open')
        .order('entry_time', { ascending: false }),
    ]);

    if (stateRes.data) setBotState(stateRes.data as BotState);
    if (tradesRes.data) setTrades(tradesRes.data as Trade[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchInitial();

    // Realtime subscriptions
    const channel = supabase
      .channel('dashboard-realtime')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'bot_state' },
        (payload) => {
          if (payload.new) setBotState(payload.new as BotState);
        }
      )
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'trades' },
        (payload) => {
          const t = payload.new as Trade;
          if (t.status === 'open') {
            setTrades((prev) => [t, ...prev]);
          }
        }
      )
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'trades' },
        (payload) => {
          const updated = payload.new as Trade;
          setTrades((prev) =>
            updated.status !== 'open'
              ? prev.filter((t) => t.id !== updated.id)
              : prev.map((t) => (t.id === updated.id ? updated : t))
          );
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchInitial]);

  // Derived metrics
  const totalTrades = botState.wins_today + botState.losses_today;
  const winRate = totalTrades > 0 ? Math.round((botState.wins_today / totalTrades) * 100) : 0;
  const pnlPositive = botState.pnl_today >= 0;
  const isHeartbeatOk = now - new Date(botState.last_heartbeat).getTime() < 15_000;

  // Shield alert banner
  const showShieldAlert = botState.shield_active;
  const showOfflineAlert = botState.is_running && !isHeartbeatOk;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex items-center gap-3 text-zinc-500">
          <div className="w-4 h-4 border-2 border-zinc-600 border-t-zinc-300 rounded-full animate-spin" />
          <span className="text-sm font-mono">Connecting to Supabase…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      {/* Shield Alert */}
      {showShieldAlert && (
        <div className="bg-red-500/10 border border-red-500/50 rounded-xl px-4 py-3 flex items-center gap-3 animate-pulse">
          <span className="text-red-400 text-lg">🛡️</span>
          <div>
            <span className="text-red-400 font-bold text-sm">VPIN SHIELD ACTIVE — Trading Halted</span>
            <span className="text-red-500/70 text-xs ml-2">
              VPIN {botState.vpin.toFixed(3)} &gt; 0.70. Resumes when VPIN &lt; 0.55.
            </span>
          </div>
        </div>
      )}

      {/* Offline Alert */}
      {showOfflineAlert && (
        <div className="bg-amber-500/10 border border-amber-500/50 rounded-xl px-4 py-3 flex items-center gap-3">
          <span className="text-amber-400 text-lg">⚠️</span>
          <span className="text-amber-400 font-semibold text-sm">
            Heartbeat missing — engine may be offline. Auto-flatten triggered at 30s.
          </span>
        </div>
      )}

      {/* Top bar: status row */}
      <div className="flex items-center justify-between bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
        <div className="flex items-center gap-6">
          <HeartbeatIndicator
            lastHeartbeat={botState.last_heartbeat}
            isRunning={botState.is_running}
          />
          <div className="h-4 w-px bg-zinc-700" />
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${botState.is_running ? 'bg-emerald-500 animate-pulse' : 'bg-zinc-600'}`} />
            <span className="text-xs font-mono text-zinc-400">
              {botState.is_running ? 'BOT RUNNING' : 'BOT STOPPED'}
            </span>
          </div>
          {botState.shield_active && (
            <>
              <div className="h-4 w-px bg-zinc-700" />
              <span className="text-xs font-mono font-bold text-red-400 animate-pulse">
                🛡 SHIELD ON
              </span>
            </>
          )}
        </div>

        <div className="flex items-center gap-4 text-xs font-mono text-zinc-600">
          <span>VPIN {botState.vpin.toFixed(3)}</span>
          <span>·</span>
          <span>{botState.toxicity_level.toUpperCase()}</span>
          <span>·</span>
          <span>Last update {new Date(botState.updated_at).toLocaleTimeString()}</span>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <PnLCard
          title="P&L Today"
          value={`${pnlPositive ? '+' : ''}$${botState.pnl_today.toLocaleString('en-US', { maximumFractionDigits: 0 })}`}
          subtext={`Max: $${botState.daily_high_pnl.toFixed(0)}`}
          positive={pnlPositive && botState.pnl_today !== 0}
          negative={!pnlPositive}
          neutral={botState.pnl_today === 0}
          mono
        />
        <PnLCard
          title="Win Rate"
          value={`${winRate}%`}
          subtext={`${botState.wins_today}W / ${botState.losses_today}L`}
          positive={winRate >= 60}
          negative={winRate > 0 && winRate < 40}
          neutral={winRate === 0 || (winRate >= 40 && winRate < 60)}
          mono
        />
        <PnLCard
          title="Trades Today"
          value={`${botState.trades_today} / 3`}
          subtext={`${botState.position_count} open position${botState.position_count !== 1 ? 's' : ''}`}
          neutral
          mono
        />
        <PnLCard
          title="GEX Regime"
          value={botState.gex_regime.toUpperCase()}
          subtext={
            botState.gex_call_wall != null
              ? `Call ${botState.gex_call_wall.toFixed(0)} / Put ${botState.gex_put_wall?.toFixed(0) ?? '—'}`
              : 'Data unavailable'
          }
          positive={botState.gex_regime === 'positive'}
          negative={botState.gex_regime === 'negative'}
          neutral={botState.gex_regime === 'flip' || botState.gex_regime === 'unknown'}
        />
      </div>

      {/* Risk Gauge */}
      <RiskGauge
        pnlToday={botState.pnl_today}
        maxLoss={botState.max_loss_threshold}
        profitCap={botState.profit_cap}
      />

      {/* Open Positions */}
      <PositionTable trades={trades} />

      {/* Intelligence Row: SWC | GEX | VPIN */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <SentimentCard
          mood={botState.swc_mood}
          confidence={botState.swc_confidence}
          summary={botState.swc_summary}
        />
        <GammaRegimeIndicator
          regime={botState.gex_regime}
          callWall={botState.gex_call_wall}
          putWall={botState.gex_put_wall}
          flipPoint={botState.gex_flip_point}
        />
        <VPINGauge
          vpin={botState.vpin}
          level={botState.toxicity_level}
          shieldActive={botState.shield_active}
        />
      </div>
    </div>
  );
}
