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
  htf_misread: 'bg-red-950 text-red-300',
  premature_entry: 'bg-orange-950 text-orange-300',
  stop_too_tight: 'bg-yellow-950 text-yellow-300',
  stop_too_wide: 'bg-yellow-950 text-yellow-300',
  news_event: 'bg-blue-950 text-blue-300',
  false_signal: 'bg-purple-950 text-purple-300',
  overtrading: 'bg-pink-950 text-pink-300',
  htf_resistance: 'bg-red-950 text-red-300',
  other: 'bg-zinc-800 text-zinc-300',
};

const severityColors: Record<string, string> = {
  low: 'bg-green-950 text-green-300',
  medium: 'bg-yellow-950 text-yellow-300',
  high: 'bg-red-950 text-red-300',
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
  if (error) return <div className="p-6 text-red-400">Error: {error}</div>;

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold mb-6">Loss Analysis & Lessons</h1>

      <div className="space-y-4">
        {postMortems.map((pm) => (
          <div
            key={pm.id}
            className="border border-zinc-800 rounded-lg p-4 bg-zinc-900 hover:bg-zinc-900/80 transition"
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className="text-sm text-zinc-500 mb-1">Trade: {pm.trade_id}</div>
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
                    pm.pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  ${pm.pnl.toFixed(0)}
                </div>
                <div className="text-xs text-zinc-500">
                  {new Date(pm.timestamp).toLocaleDateString()}
                </div>
              </div>
            </div>

            <div className="border-t border-zinc-800 pt-3">
              <div className="mb-3">
                <div className="text-sm font-semibold text-zinc-300 mb-1">
                  Analysis
                </div>
                <p className="text-sm text-zinc-400">{pm.analysis}</p>
              </div>

              <div>
                <div className="text-sm font-semibold text-zinc-300 mb-1">
                  Lesson
                </div>
                <p className="text-sm text-zinc-400 italic bg-zinc-800 p-2 rounded">
                  {pm.lesson}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {postMortems.length === 0 && (
        <div className="text-center py-12 text-zinc-500">
          No post-mortems yet. Losses will be analyzed here.
        </div>
      )}
    </div>
  );
}
