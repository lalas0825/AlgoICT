'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';

interface Trade {
  id: string;
  strategy: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  entry_time: string;
  exit_time: string;
  pnl: number;
  contracts: number;
  confluence_score: number;
  kill_zone: string;
}

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        const { data, error: err } = await supabase
          .from('trades')
          .select('*')
          .order('entry_time', { ascending: false })
          .limit(50);

        if (err) {
          setError(err.message);
        } else {
          setTrades(data || []);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchTrades();
  }, []);

  if (loading) return <div className="p-6">Loading trades...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold mb-6">Trade Journal</h1>

      <div className="overflow-x-auto border rounded-lg">
        <table className="w-full">
          <thead className="bg-gray-100">
            <tr>
              <th className="px-4 py-2 text-left font-semibold">Trade ID</th>
              <th className="px-4 py-2 text-left font-semibold">Strategy</th>
              <th className="px-4 py-2 text-left font-semibold">Direction</th>
              <th className="px-4 py-2 text-right font-semibold">Entry</th>
              <th className="px-4 py-2 text-right font-semibold">Exit</th>
              <th className="px-4 py-2 text-right font-semibold">P&L</th>
              <th className="px-4 py-2 text-right font-semibold">Confluence</th>
              <th className="px-4 py-2 text-left font-semibold">Kill Zone</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id} className="border-t hover:bg-gray-50">
                <td className="px-4 py-2 text-sm">{trade.id}</td>
                <td className="px-4 py-2 text-sm">{trade.strategy}</td>
                <td className="px-4 py-2 text-sm font-medium">
                  <span
                    className={
                      trade.direction === 'long'
                        ? 'text-green-600'
                        : 'text-red-600'
                    }
                  >
                    {trade.direction.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-2 text-sm text-right">
                  {trade.entry_price.toFixed(1)}
                </td>
                <td className="px-4 py-2 text-sm text-right">
                  {trade.exit_price.toFixed(1)}
                </td>
                <td
                  className={`px-4 py-2 text-sm text-right font-semibold ${
                    trade.pnl >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}
                >
                  ${trade.pnl.toFixed(0)}
                </td>
                <td className="px-4 py-2 text-sm text-right">
                  {trade.confluence_score}/20
                </td>
                <td className="px-4 py-2 text-sm">{trade.kill_zone}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {trades.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          No trades yet. Start trading to see results here.
        </div>
      )}
    </div>
  );
}
