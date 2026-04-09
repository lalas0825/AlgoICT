'use client';

import type { Trade } from '../types';

interface PositionTableProps {
  trades: Trade[];
}

export function PositionTable({ trades }: PositionTableProps) {
  const openTrades = trades.filter((t) => t.status === 'open');

  if (openTrades.length === 0) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
        <div className="text-xs text-zinc-500 uppercase tracking-wider font-medium mb-3">
          Open Positions
        </div>
        <div className="text-center py-8 text-zinc-600 text-sm">
          No open positions
        </div>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500 uppercase tracking-wider font-medium">
            Open Positions
          </span>
          <span className="text-xs font-mono bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded">
            {openTrades.length}
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800">
              <th className="px-4 py-2.5 text-left text-xs text-zinc-500 font-medium uppercase tracking-wider">Strategy</th>
              <th className="px-4 py-2.5 text-left text-xs text-zinc-500 font-medium uppercase tracking-wider">Dir</th>
              <th className="px-4 py-2.5 text-right text-xs text-zinc-500 font-medium uppercase tracking-wider">Entry</th>
              <th className="px-4 py-2.5 text-right text-xs text-zinc-500 font-medium uppercase tracking-wider">SL</th>
              <th className="px-4 py-2.5 text-right text-xs text-zinc-500 font-medium uppercase tracking-wider">TP</th>
              <th className="px-4 py-2.5 text-right text-xs text-zinc-500 font-medium uppercase tracking-wider">Contracts</th>
              <th className="px-4 py-2.5 text-right text-xs text-zinc-500 font-medium uppercase tracking-wider">P&L</th>
              <th className="px-4 py-2.5 text-center text-xs text-zinc-500 font-medium uppercase tracking-wider">Conf</th>
              <th className="px-4 py-2.5 text-left text-xs text-zinc-500 font-medium uppercase tracking-wider">Zone</th>
            </tr>
          </thead>
          <tbody>
            {openTrades.map((trade) => (
              <tr key={trade.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition">
                <td className="px-4 py-3 font-medium text-zinc-300">{trade.strategy}</td>
                <td className="px-4 py-3">
                  <span
                    className={`text-xs font-mono font-bold px-2 py-1 rounded ${
                      trade.direction === 'long'
                        ? 'bg-emerald-500/15 text-emerald-400'
                        : 'bg-red-500/15 text-red-400'
                    }`}
                  >
                    {trade.direction.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-zinc-300">
                  {trade.entry_price.toFixed(1)}
                </td>
                <td className="px-4 py-3 text-right font-mono text-red-400">
                  {trade.stop_loss.toFixed(1)}
                </td>
                <td className="px-4 py-3 text-right font-mono text-emerald-400">
                  {trade.take_profit.toFixed(1)}
                </td>
                <td className="px-4 py-3 text-right font-mono text-zinc-400">
                  {trade.contracts}
                </td>
                <td className="px-4 py-3 text-right font-mono font-semibold">
                  {trade.pnl != null ? (
                    <span className={trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                      {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(0)}
                    </span>
                  ) : (
                    <span className="text-zinc-600">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-center">
                  <span
                    className={`text-xs font-mono font-semibold ${
                      trade.confluence_score >= 12
                        ? 'text-emerald-400'
                        : trade.confluence_score >= 9
                        ? 'text-sky-400'
                        : 'text-zinc-400'
                    }`}
                  >
                    {trade.confluence_score}/20
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-zinc-500">{trade.kill_zone}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
