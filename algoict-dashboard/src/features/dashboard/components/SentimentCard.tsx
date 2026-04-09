'use client';

import type { MarketMood } from '../types';

interface SentimentCardProps {
  mood: MarketMood;
  confidence: number;
  summary: string;
}

const MOOD_CONFIG: Record<MarketMood, { emoji: string; color: string; bg: string; label: string }> = {
  risk_on: { emoji: '🟢', color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', label: 'Risk On' },
  risk_off: { emoji: '🔴', color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30', label: 'Risk Off' },
  event_driven: { emoji: '🟡', color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30', label: 'Event Driven' },
  choppy: { emoji: '⚪', color: 'text-zinc-400', bg: 'bg-zinc-700/20 border-zinc-600/30', label: 'Choppy' },
};

export function SentimentCard({ mood, confidence, summary }: SentimentCardProps) {
  const config = MOOD_CONFIG[mood] ?? MOOD_CONFIG.choppy;
  const confPct = Math.round(confidence * 100);

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <div className="text-xs text-zinc-500 uppercase tracking-wider font-medium mb-3">
        SWC — Market Mood
      </div>

      <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border ${config.bg} mb-3`}>
        <span className="text-base">{config.emoji}</span>
        <span className={`font-semibold text-sm ${config.color}`}>{config.label}</span>
      </div>

      {/* Confidence bar */}
      <div className="mb-3">
        <div className="flex justify-between text-xs text-zinc-600 font-mono mb-1">
          <span>Confidence</span>
          <span className={config.color}>{confPct}%</span>
        </div>
        <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              mood === 'risk_on' ? 'bg-emerald-500' :
              mood === 'risk_off' ? 'bg-red-500' :
              mood === 'event_driven' ? 'bg-amber-500' : 'bg-zinc-500'
            }`}
            style={{ width: `${confPct}%` }}
          />
        </div>
      </div>

      <p className="text-xs text-zinc-400 leading-relaxed line-clamp-3">{summary || 'No summary available.'}</p>
    </div>
  );
}
