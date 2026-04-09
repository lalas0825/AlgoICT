import Link from 'next/link';

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center">
      <div className="text-center">
        <div className="text-7xl mb-4">🦉</div>
        <h1 className="text-4xl font-bold text-gray-800 mb-4">AlgoICT</h1>
        <p className="text-lg text-gray-600 mb-8 max-w-md">
          Automated MNQ & S&P 500 trading engine with 6 layers of AI intelligence
        </p>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
          <Link
            href="/trades"
            className="px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition font-medium"
          >
            📊 Trades
          </Link>
          <Link
            href="/signals"
            className="px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 transition font-medium"
          >
            📈 Signals
          </Link>
          <Link
            href="/backtest"
            className="px-4 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition font-medium"
          >
            🔬 Backtest
          </Link>
          <Link
            href="/post-mortems"
            className="px-4 py-3 bg-orange-600 text-white rounded-lg hover:bg-orange-700 transition font-medium"
          >
            📋 Analysis
          </Link>
          <Link
            href="/controls"
            className="px-4 py-3 bg-red-600 text-white rounded-lg hover:bg-red-700 transition font-medium"
          >
            ⚙️ Controls
          </Link>
        </div>

        <div className="bg-white rounded-lg shadow p-6 max-w-md">
          <h2 className="text-lg font-semibold mb-4">System Stack</h2>
          <ul className="text-sm text-gray-600 space-y-2 text-left">
            <li>✓ Python 3.12 engine (Windows local)</li>
            <li>✓ Next.js 16 + React 19 dashboard</li>
            <li>✓ Supabase (PostgreSQL + Realtime)</li>
            <li>✓ 6 AI intelligence layers (ICT+SWC+GEX+VPIN+PostMortem+StrategyLab)</li>
            <li>✓ TopstepX & Alpaca broker integration</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
