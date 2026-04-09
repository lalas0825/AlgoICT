'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';

interface BotState {
  id: string;
  is_running: boolean;
  last_heartbeat: string;
  vpin: number;
  toxicity_level: string;
  shield_active: boolean;
  trades_today: number;
  pnl_today: number;
  position_count: number;
  last_signal: string;
}

export default function ControlsPage() {
  const [botState, setBotState] = useState<BotState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchBotState = async () => {
      try {
        const { data, error: err } = await supabase
          .from('bot_state')
          .select('*')
          .single();

        if (err && err.code !== 'PGRST116') {
          setError(err.message);
        } else if (data) {
          setBotState(data);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchBotState();

    // Poll for updates every 5 seconds
    const interval = setInterval(fetchBotState, 5000);
    return () => clearInterval(interval);
  }, []);

  const isHealthy =
    botState &&
    new Date(botState.last_heartbeat).getTime() > Date.now() - 15000;
  const isVPINExtreme = botState && botState.vpin > 0.7;

  if (loading) return <div className="p-6">Loading bot controls...</div>;

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold mb-6">Bot Controls & Status</h1>

      {error && <div className="p-4 bg-red-100 text-red-800 rounded mb-6">{error}</div>}

      {/* Status Badges */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
        {/* Bot Status */}
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-2">Bot Status</div>
          <div className="flex items-center gap-2">
            <div
              className={`w-4 h-4 rounded-full ${
                botState?.is_running ? 'bg-green-500 animate-pulse' : 'bg-gray-400'
              }`}
            />
            <span className="font-semibold">
              {botState?.is_running ? 'RUNNING' : 'STOPPED'}
            </span>
          </div>
        </div>

        {/* Heartbeat */}
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-2">Heartbeat</div>
          <div className="flex items-center gap-2">
            <div
              className={`w-4 h-4 rounded-full ${
                isHealthy ? 'bg-green-500 animate-pulse' : 'bg-red-500'
              }`}
            />
            <span className="font-semibold">
              {isHealthy ? 'HEALTHY' : 'OFFLINE'}
            </span>
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {botState?.last_heartbeat
              ? new Date(botState.last_heartbeat).toLocaleTimeString()
              : 'N/A'}
          </div>
        </div>

        {/* VPIN & Shield */}
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-2">VPIN Toxicity</div>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-2xl font-bold">
                {botState?.vpin.toFixed(3) || '—'}
              </div>
              <div className="text-xs text-gray-500">{botState?.toxicity_level}</div>
            </div>
            <div
              className={`w-12 h-12 rounded-full flex items-center justify-center text-xs font-bold ${
                isVPINExtreme
                  ? 'bg-red-100 text-red-600 animate-pulse'
                  : 'bg-green-100 text-green-600'
              }`}
            >
              {isVPINExtreme ? '⚠' : '✓'}
            </div>
          </div>
        </div>

        {/* Trades Today */}
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-2">Trades Today</div>
          <div className="text-3xl font-bold">{botState?.trades_today || 0}</div>
        </div>

        {/* P&L Today */}
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-2">P&L Today</div>
          <div
            className={`text-3xl font-bold ${
              (botState?.pnl_today || 0) >= 0
                ? 'text-green-600'
                : 'text-red-600'
            }`}
          >
            ${botState?.pnl_today.toFixed(0) || '0'}
          </div>
        </div>

        {/* Open Positions */}
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-2">Open Positions</div>
          <div className="text-3xl font-bold">{botState?.position_count || 0}</div>
        </div>
      </div>

      {/* Last Signal */}
      {botState?.last_signal && (
        <div className="border rounded-lg p-4 mb-8 bg-blue-50">
          <div className="text-sm font-semibold text-gray-700 mb-2">
            Last Signal
          </div>
          <p className="text-sm">{botState.last_signal}</p>
        </div>
      )}

      {/* Control Buttons */}
      <div className="border rounded-lg p-6 bg-gray-50">
        <h2 className="text-lg font-semibold mb-4">Actions</h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <button
            disabled={botState?.is_running}
            className={`px-4 py-3 rounded font-medium transition ${
              botState?.is_running
                ? 'bg-gray-300 text-gray-600 cursor-not-allowed'
                : 'bg-green-600 text-white hover:bg-green-700'
            }`}
          >
            Start Bot
          </button>

          <button
            disabled={!botState?.is_running}
            className={`px-4 py-3 rounded font-medium transition ${
              !botState?.is_running
                ? 'bg-gray-300 text-gray-600 cursor-not-allowed'
                : 'bg-red-600 text-white hover:bg-red-700'
            }`}
          >
            Stop Bot
          </button>

          <button
            disabled={!botState?.is_running || !botState?.position_count}
            className={`px-4 py-3 rounded font-medium transition ${
              !botState?.is_running || !botState?.position_count
                ? 'bg-gray-300 text-gray-600 cursor-not-allowed'
                : 'bg-orange-600 text-white hover:bg-orange-700'
            }`}
          >
            Emergency Flatten
          </button>

          <button className="px-4 py-3 rounded font-medium bg-blue-600 text-white hover:bg-blue-700 transition">
            Reset Daily Stats
          </button>
        </div>

        <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-800">
          ⚠️ <strong>Emergency Flatten:</strong> Closes ALL open positions
          immediately. Use only in extreme conditions.
        </div>
      </div>

      {/* Shield Status */}
      {botState?.shield_active && (
        <div className="mt-8 border-2 border-red-500 rounded-lg p-6 bg-red-50">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-6 h-6 bg-red-500 rounded-full animate-pulse" />
            <h2 className="text-2xl font-bold text-red-600">
              🛡️ VPIN SHIELD ACTIVE
            </h2>
          </div>
          <p className="text-red-700 font-semibold">
            Trading halted due to extreme market toxicity (VPIN &gt; 0.70)
          </p>
          <p className="text-sm text-red-600 mt-2">
            The bot will resume trading when VPIN falls below 0.55.
          </p>
        </div>
      )}
    </div>
  );
}
