"""
scripts/backtest_live_data.py
=============================
End-to-end smoke test: fetch live bars from TopstepX REST, convert to the
1-min CT DataFrame the Backtester expects, and run NY AM Reversal against it.

Purpose: prove that the TopstepX data pipeline connects cleanly to the
existing backtest engine, while markets are closed and WS cannot be tested.

Usage:
    python -m scripts.backtest_live_data [--days N]
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brokers import topstepx as tx  # noqa: E402
from brokers.topstepx import TopstepXClient  # noqa: E402

# Disable WS listener — market is closed and we only need REST here
async def _noop_ws(self):  # noqa: ANN001
    return
tx.TopstepXClient._ws_listener_loop = _noop_ws

from backtest.backtester import Backtester  # noqa: E402
from detectors.swing_points import SwingPointDetector  # noqa: E402
from detectors.market_structure import MarketStructureDetector  # noqa: E402
from detectors.fair_value_gap import FairValueGapDetector  # noqa: E402
from detectors.order_block import OrderBlockDetector  # noqa: E402
from detectors.liquidity import LiquidityDetector  # noqa: E402
from detectors.displacement import DisplacementDetector  # noqa: E402
from detectors.confluence import ConfluenceScorer  # noqa: E402
from risk.risk_manager import RiskManager  # noqa: E402
from timeframes.tf_manager import TimeframeManager  # noqa: E402
from timeframes.session_manager import SessionManager  # noqa: E402
from timeframes.htf_bias import BiasResult  # noqa: E402
from strategies.ny_am_reversal import NYAMReversalStrategy  # noqa: E402


async def fetch_bars(days: int, limit: int = 20000) -> pd.DataFrame:
    """Authenticate, resolve MNQ contract, fetch N days of 1-min bars."""
    client = TopstepXClient()
    await client.connect()
    try:
        contract = await client.lookup_contract("MNQ", live=False)
        if contract is None:
            raise RuntimeError("MNQ contract not found")

        # Pull through "yesterday" to guarantee we land inside the last session
        end = datetime.now(timezone.utc) - timedelta(days=1)
        start = end - timedelta(days=days)
        bars = await client.get_historical_bars(
            contract_id=contract["id"],
            start=start,
            end=end,
            unit=2,
            unit_number=1,
            limit=limit,
        )
    finally:
        await client.close()

    if not bars:
        return pd.DataFrame()

    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    # Backtester docstring says CT tz; convert from UTC.
    df.index = df.index.tz_convert("America/Chicago")
    df = df[["open", "high", "low", "close", "volume"]]
    return df


def run_backtest(df: pd.DataFrame):
    detectors = {
        "swing_entry": SwingPointDetector(),
        "swing_context": SwingPointDetector(),
        "structure": MarketStructureDetector(),
        "fvg": FairValueGapDetector(),
        "ob": OrderBlockDetector(),
        "liquidity": LiquidityDetector(),
        "displacement": DisplacementDetector(),
        "confluence": ConfluenceScorer(),
        "tracked_levels": [],
    }

    risk_mgr = RiskManager()
    tf_mgr = TimeframeManager()
    session_mgr = SessionManager()

    def htf_bias_fn(_price):
        return BiasResult(
            direction="bullish",
            premium_discount="equilibrium",
            htf_levels={},
            confidence="medium",
            weekly_bias="bullish",
            daily_bias="bullish",
        )

    strategy = NYAMReversalStrategy(
        detectors, risk_mgr, session_mgr, htf_bias_fn
    )

    backtester = Backtester(
        strategy, detectors, risk_mgr, tf_mgr, session_mgr
    )
    return backtester.run(df)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=5, help="Lookback days")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    print(f"Fetching last {args.days} days of MNQ 1-min bars from TopstepX…")
    df = asyncio.run(fetch_bars(days=args.days))
    if df.empty:
        print("ERROR: no bars returned")
        return 1

    print(f"Loaded {len(df)} bars ({df.index[0]} -> {df.index[-1]})")
    print(f"  First close: ${df['close'].iloc[0]:,.2f}")
    print(f"  Last  close: ${df['close'].iloc[-1]:,.2f}")
    print(f"  Delta      : ${df['close'].iloc[-1] - df['close'].iloc[0]:+,.2f}")
    print()

    print("Running NY AM Reversal backtest…")
    result = run_backtest(df)

    print()
    print("=== Backtest Results ===")
    print(f"Strategy      : {result.strategy}")
    print(f"Period        : {result.start_date} -> {result.end_date}")
    print(f"Total signals : {result.total_signals}")
    print(f"Total trades  : {result.total_trades}")
    print(f"Wins / Losses : {result.wins} / {result.losses}")
    print(f"Win rate      : {result.win_rate:.1%}")
    print(f"Total P&L     : ${float(result.total_pnl):+,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
