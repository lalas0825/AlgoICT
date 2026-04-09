'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';

interface PostMortem {
  id: string;
  trade_id: string;
  timestamp: string;
  reason_category: string;
  analysis: string;
  lesson: string;
  severity: string;
  pnl: number;
}

const categoryColors: Record<string, string> = {
  htf_misread: 'bg-red-100 text-red-800',
  premature_entry: 'bg-orange-100 text-orange-800',
  stop_too_tight: 'bg-yellow-100 text-yellow-800',
  stop_too_wide: 'bg-yellow-100 text-yellow-800',
  news_event: 'bg-blue-100 text-blue-800',
  false_signal: 'bg-purple-100 text-purple-800',
  overtrading: 'bg-pink-100 text-pink-800',
  htf_resistance: 'bg-red-100 text-red-800',
  other: 'bg-gray-100 text-gray-800',
};

const severityColors: Record<string, string> = {
  low: 'bg-green-100 text-green-800',
  medium: 'bg-yellow-100 text-yellow-800',
  high: 'bg-red-100 text-red-800',
};

export default function PostMortemsPage() {
  const [postMortems, setPostMortems] = useState<PostMortem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchPostMortems = async () => {
      try {
        const { data, error: err } = await supabase
          .from('post_mortems')
          .select('*')
          .order('timestamp', { ascending: false })
          .limit(50);

        if (err) {
          setError(err.message);
        } else {
          setPostMortems(data || []);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchPostMortems();
  }, []);

  if (loading) return <div className="p-6">Loading post-mortems...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold mb-6">Loss Analysis & Lessons</h1>

      <div className="space-y-4">
        {postMortems.map((pm) => (
          <div
            key={pm.id}
            className="border rounded-lg p-4 hover:shadow-md transition"
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className="text-sm text-gray-600 mb-1">Trade: {pm.trade_id}</div>
                <div className="flex gap-2 items-center">
                  <span
                    className={`px-3 py-1 rounded text-sm font-medium ${
                      categoryColors[pm.reason_category] ||
                      categoryColors.other
                    }`}
                  >
                    {pm.reason_category.replace(/_/g, ' ')}
                  </span>
                  <span
                    className={`px-3 py-1 rounded text-sm font-medium ${
                      severityColors[pm.severity] || severityColors.medium
                    }`}
                  >
                    {pm.severity.toUpperCase()}
                  </span>
                </div>
              </div>
              <div className="text-right">
                <div
                  className={`text-xl font-bold ${
                    pm.pnl >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}
                >
                  ${pm.pnl.toFixed(0)}
                </div>
                <div className="text-xs text-gray-500">
                  {new Date(pm.timestamp).toLocaleDateString()}
                </div>
              </div>
            </div>

            <div className="border-t pt-3">
              <div className="mb-3">
                <div className="text-sm font-semibold text-gray-700 mb-1">
                  Analysis
                </div>
                <p className="text-sm text-gray-600">{pm.analysis}</p>
              </div>

              <div>
                <div className="text-sm font-semibold text-gray-700 mb-1">
                  Lesson
                </div>
                <p className="text-sm text-gray-600 italic bg-blue-50 p-2 rounded">
                  {pm.lesson}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {postMortems.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          No post-mortems yet. Losses will be analyzed here.
        </div>
      )}
    </div>
  );
}
