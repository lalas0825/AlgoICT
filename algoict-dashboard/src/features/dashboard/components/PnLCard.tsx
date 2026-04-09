'use client';

interface PnLCardProps {
  title: string;
  value: string;
  subtext?: string;
  positive?: boolean;
  negative?: boolean;
  neutral?: boolean;
  mono?: boolean;
}

export function PnLCard({
  title,
  value,
  subtext,
  positive,
  negative,
  neutral,
  mono,
}: PnLCardProps) {
  let valueColor = 'text-zinc-50';
  if (positive) valueColor = 'text-emerald-400';
  if (negative) valueColor = 'text-red-400';
  if (neutral) valueColor = 'text-zinc-400';

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col gap-1.5">
      <div className="text-xs text-zinc-500 uppercase tracking-wider font-medium">
        {title}
      </div>
      <div
        className={`text-2xl font-bold ${valueColor} ${mono ? 'font-mono' : ''} leading-none`}
      >
        {value}
      </div>
      {subtext && (
        <div className="text-xs text-zinc-600 font-mono">{subtext}</div>
      )}
    </div>
  );
}
