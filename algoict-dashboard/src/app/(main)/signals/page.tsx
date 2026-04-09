'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';

interface Signal {
  id: string;
  timestamp: string;
  level: string;
  confluence_score: number;
  direction: string;
  price: number;
  ict_concepts: string[];
  active: boolean;
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchSignals = async () => {
      try {
        const { data, error: err } = await supabase
          .from('signals')
          .select('*')
          .order('timestamp', { ascending: false })
          .limit(100);

        if (err) {
          setError(err.message);
        } else {
          setSignals(data || []);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchSignals();
  }, []);

  if (loading) return <div className="p-6">Loading signals...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold mb-6">20pt Confluence Signals</h1>

      <div className="overflow-x-auto border rounded-lg">
        <table className="w-full">
          <thead className="bg-gray-100">
            <tr>
              <th className="px-4 py-2 text-left font-semibold">Time</th>
              <th className="px-4 py-2 text-left font-semibold">Level</th>
              <th className="px-4 py-2 text-center font-semibold">
                Confluence
              </th>
              <th className="px-4 py-2 text-left font-semibold">Direction</th>
              <th className="px-4 py-2 text-right font-semibold">Price</th>
              <th className="px-4 py-2 text-left font-semibold">ICT Concepts</th>
              <th className="px-4 py-2 text-center font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((signal) => (
              <tr key={signal.id} className="border-t hover:bg-gray-50">
                <td className="px-4 py-2 text-sm">
                  {new Date(signal.timestamp).toLocaleTimeString()}
                </td>
                <td className="px-4 py-2 text-sm font-medium">{signal.level}</td>
                <td className="px-4 py-2 text-center font-bold">
                  <span
                    className={
                      signal.confluence_score >= 12
                        ? 'text-green-600 bg-green-50 px-2 py-1 rounded'
                        : signal.confluence_score >= 9
                          ? 'text-blue-600 bg-blue-50 px-2 py-1 rounded'
                          : 'text-gray-600 bg-gray-50 px-2 py-1 rounded'
                    }
                  >
                    {signal.confluence_score}/20
                  </span>
                </td>
                <td className="px-4 py-2 text-sm">
                  <span
                    className={
                      signal.direction === 'long'
                        ? 'text-green-600 font-medium'
                        : 'text-red-600 font-medium'
                    }
                  >
                    {signal.direction.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-2 text-sm text-right">
                  {signal.price.toFixed(1)}
                </td>
                <td className="px-4 py-2 text-sm">
                  <div className="flex gap-1 flex-wrap">
                    {signal.ict_concepts?.map((concept) => (
                      <span
                        key={concept}
                        className="px-2 py-1 bg-purple-100 text-purple-700 rounded text-xs font-medium"
                      >
                        {concept}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-2 text-center">
                  <span
                    className={
                      signal.active
                        ? 'text-green-600 font-medium'
                        : 'text-gray-400'
                    }
                  >
                    {signal.active ? '🟢 Active' : '⚫ Closed'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {signals.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          No signals yet. Waiting for confluence detection.
        </div>
      )}
    </div>
  );
}
