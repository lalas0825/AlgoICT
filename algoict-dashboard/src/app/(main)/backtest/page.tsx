'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';

interface BacktestResult {
  id: string;
  strategy: string;
  start_date: string;
  end_date: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  profit_factor: number;
  max_drawdown: number;
  net_profit: number;
  sharpe_ratio: number;
  status: string;
  created_at: string;
}

export default function BacktestPage() {
  const [results, setResults] = useState<BacktestResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchResults = async () => {
      try {
        const { data, error: err } = await supabase
          .from('backtest_results')
          .select('*')
          .order('created_at', { ascending: false })
          .limit(20);

        if (err) {
          setError(err.message);
        } else {
          setResults(data || []);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, []);

  if (loading) return <div className="p-6">Loading backtest results...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold mb-6">Backtest Results</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        <div className="border rounded-lg p-4 bg-blue-50">
          <div className="text-sm text-gray-600">Total Backtests</div>
          <div className="text-3xl font-bold text-blue-600">
            {results.length}
          </div>
        </div>

        {results.length > 0 && (
          <>
            <div className="border rounded-lg p-4 bg-green-50">
              <div className="text-sm text-gray-600">Best Profit Factor</div>
              <div className="text-3xl font-bold text-green-600">
                {Math.max(...results.map((r) => r.profit_factor || 0)).toFixed(
                  2
                )}
              </div>
            </div>

            <div className="border rounded-lg p-4 bg-purple-50">
              <div className="text-sm text-gray-600">Avg Win Rate</div>
              <div className="text-3xl font-bold text-purple-600">
                {(
                  results.reduce((sum, r) => sum + (r.win_rate || 0), 0) /
                  results.length
                ).toFixed(1)}
                %
              </div>
            </div>
          </>
        )}
      </div>

      <div className="border rounded-lg overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-100">
            <tr>
              <th className="px-4 py-2 text-left font-semibold">Strategy</th>
              <th className="px-4 py-2 text-center font-semibold">Trades</th>
              <th className="px-4 py-2 text-center font-semibold">Win Rate</th>
              <th className="px-4 py-2 text-right font-semibold">
                Profit Factor
              </th>
              <th className="px-4 py-2 text-right font-semibold">Max DD</th>
              <th className="px-4 py-2 text-right font-semibold">Net Profit</th>
              <th className="px-4 py-2 text-right font-semibold">Sharpe</th>
              <th className="px-4 py-2 text-center font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {results.map((result) => (
              <tr key={result.id} className="border-t hover:bg-gray-50">
                <td className="px-4 py-2 font-medium">{result.strategy}</td>
                <td className="px-4 py-2 text-center">{result.total_trades}</td>
                <td className="px-4 py-2 text-center font-semibold">
                  <span
                    className={
                      result.win_rate >= 50
                        ? 'text-green-600'
                        : 'text-orange-600'
                    }
                  >
                    {result.win_rate.toFixed(1)}%
                  </span>
                </td>
                <td className="px-4 py-2 text-right">
                  <span
                    className={
                      result.profit_factor >= 2
                        ? 'text-green-600 font-semibold'
                        : 'text-gray-600'
                    }
                  >
                    {result.profit_factor.toFixed(2)}
                  </span>
                </td>
                <td className="px-4 py-2 text-right text-red-600">
                  {(result.max_drawdown * 100).toFixed(1)}%
                </td>
                <td className="px-4 py-2 text-right font-bold">
                  <span
                    className={
                      result.net_profit >= 0
                        ? 'text-green-600'
                        : 'text-red-600'
                    }
                  >
                    ${result.net_profit.toFixed(0)}
                  </span>
                </td>
                <td className="px-4 py-2 text-right text-purple-600">
                  {result.sharpe_ratio.toFixed(2)}
                </td>
                <td className="px-4 py-2 text-center">
                  <span
                    className={
                      result.status === 'completed'
                        ? 'text-green-600 font-medium'
                        : 'text-yellow-600 font-medium'
                    }
                  >
                    {result.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {results.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          No backtest results yet. Run a backtest to see results here.
        </div>
      )}
    </div>
  );
}
