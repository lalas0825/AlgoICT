import Link from 'next/link';
import OwlLogo from '@/shared/components/OwlLogo';
import LogoutButton from '@/shared/components/LogoutButton';

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-zinc-950">
      <nav className="bg-zinc-900 border-b border-zinc-800 sticky top-0 z-50">
        <div className="max-w-[1440px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <Link href="/" className="flex items-center gap-2 text-lg font-bold text-zinc-50 tracking-tight">
              <OwlLogo size="sm" />
              AlgoICT
            </Link>
            <div className="flex gap-1">
              <Link href="/" className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800 rounded transition">
                Dashboard
              </Link>
              <Link href="/chart" className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800 rounded transition">
                Chart
              </Link>
              <Link href="/trades" className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800 rounded transition">
                Trades
              </Link>
              <Link href="/signals" className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800 rounded transition">
                Signals
              </Link>
              <Link href="/backtest" className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800 rounded transition">
                Backtest
              </Link>
              <Link href="/post-mortems" className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800 rounded transition">
                Analysis
              </Link>
              <Link href="/controls" className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800 rounded transition">
                Controls
              </Link>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-xs text-zinc-600 font-mono">READ-ONLY</div>
            <LogoutButton />
          </div>
        </div>
      </nav>
      <main className="max-w-[1440px] mx-auto">{children}</main>
    </div>
  );
}
