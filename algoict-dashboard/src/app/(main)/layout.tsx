import Link from 'next/link';

export default function MainLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Navigation */}
      <nav className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link href="/" className="text-2xl font-bold text-blue-600">
            🦉 AlgoICT
          </Link>

          <div className="flex gap-6">
            <Link href="/trades" className="hover:text-blue-600 font-medium">
              Trades
            </Link>
            <Link href="/signals" className="hover:text-blue-600 font-medium">
              Signals
            </Link>
            <Link href="/backtest" className="hover:text-blue-600 font-medium">
              Backtest
            </Link>
            <Link
              href="/post-mortems"
              className="hover:text-blue-600 font-medium"
            >
              Analysis
            </Link>
            <Link href="/controls" className="hover:text-blue-600 font-medium">
              Controls
            </Link>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto">{children}</main>

      {/* Footer */}
      <footer className="bg-gray-100 border-t mt-12">
        <div className="max-w-7xl mx-auto px-6 py-6 text-center text-gray-600 text-sm">
          AlgoICT Dashboard — M7 Scaffold | Python Engine +{' '}
          <span className="font-semibold">Next.js 16</span> | Real-time RLS
        </div>
      </footer>
    </div>
  );
}
