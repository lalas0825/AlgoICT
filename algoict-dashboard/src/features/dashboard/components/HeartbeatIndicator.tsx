'use client';

interface HeartbeatIndicatorProps {
  lastHeartbeat: string | null;
  isRunning: boolean;
}

export function HeartbeatIndicator({ lastHeartbeat, isRunning }: HeartbeatIndicatorProps) {
  const now = Date.now();
  const lastBeat = lastHeartbeat ? new Date(lastHeartbeat).getTime() : 0;
  const diffMs = now - lastBeat;

  let status: 'healthy' | 'warn' | 'dead' = 'dead';
  let label = 'OFFLINE';
  let color = 'bg-zinc-600';
  let textColor = 'text-zinc-500';

  if (isRunning && diffMs < 15_000) {
    status = 'healthy';
    label = 'LIVE';
    color = 'bg-emerald-500';
    textColor = 'text-emerald-400';
  } else if (isRunning && diffMs < 30_000) {
    status = 'warn';
    label = 'SLOW';
    color = 'bg-amber-500';
    textColor = 'text-amber-400';
  }

  const timeAgo = lastHeartbeat
    ? `${Math.floor(diffMs / 1000)}s ago`
    : 'never';

  return (
    <div className="flex items-center gap-2">
      <div className="relative flex items-center justify-center">
        <div
          className={`w-2.5 h-2.5 rounded-full ${color} ${
            status === 'healthy' ? 'animate-pulse' : ''
          }`}
        />
        {status === 'healthy' && (
          <div className={`absolute w-2.5 h-2.5 rounded-full ${color} animate-ping opacity-75`} />
        )}
      </div>
      <div>
        <span className={`text-xs font-mono font-semibold ${textColor} tracking-widest`}>
          {label}
        </span>
        <span className="text-xs text-zinc-600 font-mono ml-1.5">{timeAgo}</span>
      </div>
    </div>
  );
}
