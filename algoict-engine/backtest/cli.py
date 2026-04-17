"""
backtest/cli.py
================
Command-line interface for backtest pipeline.

Usage
-----
# Run backtest
python -m backtest.cli backtest --strategy ny_am_reversal --data data/nq_1min.csv

# Audit trades
python -m backtest.cli audit --trades [json file from backtest]

# Simulate Combine
python -m backtest.cli combine --trades [json file]

# Generate report
python -m backtest.cli report --trades [json file]
"""

import argparse
import json
import sys
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from backtest.backtester import Backtester
from backtest.risk_audit import audit_trades
from backtest.combine_simulator import simulate_combine
from backtest.report import generate_report
from backtest.data_loader import load_data_csv

# Import all detectors and managers (assume they exist)
try:
    from detectors.swing_points import SwingPointDetector
    from detectors.market_structure import MarketStructureDetector
    from detectors.fair_value_gap import FairValueGapDetector
    from detectors.order_block import OrderBlockDetector
    from detectors.liquidity import LiquidityDetector
    from detectors.displacement import DisplacementDetector
    from detectors.confluence import ConfluenceScorer
    from risk.risk_manager import RiskManager
    from timeframes.tf_manager import TimeframeManager
    from timeframes.session_manager import SessionManager
    from strategies.ny_am_reversal import NYAMReversalStrategy
    from strategies.silver_bullet import SilverBulletStrategy
except ImportError as e:
    print(f"Warning: some modules not available: {e}")

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────

def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _serialize_trade(t):
    """Convert Trade to JSON-serializable dict."""
    return {
        "strategy": t.strategy,
        "symbol": t.symbol,
        "direction": t.direction,
        "entry_time": str(t.entry_time),
        "exit_time": str(t.exit_time),
        "entry_price": float(t.entry_price),
        "stop_price": float(t.stop_price),
        "target_price": float(t.target_price),
        "exit_price": float(t.exit_price),
        "contracts": int(t.contracts),
        "pnl": float(t.pnl),
        "reason": t.reason,
        "confluence_score": int(t.confluence_score),
        "duration_bars": int(t.duration_bars),
        "kill_zone": getattr(t, "kill_zone", ""),
    }


def _deserialize_trade(d):
    """Convert JSON dict back to Trade object."""
    from backtest.backtester import Trade
    return Trade(
        strategy=d["strategy"],
        symbol=d["symbol"],
        direction=d["direction"],
        entry_time=pd.Timestamp(d["entry_time"]),
        exit_time=pd.Timestamp(d["exit_time"]),
        entry_price=float(d["entry_price"]),
        stop_price=float(d["stop_price"]),
        target_price=float(d["target_price"]),
        exit_price=float(d["exit_price"]),
        contracts=int(d["contracts"]),
        pnl=float(d["pnl"]),
        reason=d["reason"],
        confluence_score=int(d["confluence_score"]),
        duration_bars=int(d["duration_bars"]),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_backtest(args):
    """Run a backtest and save results."""
    strategy_name = args.strategy.lower()
    data_path = Path(args.data)

    if not data_path.exists():
        print(f"ERROR: Data file not found: {data_path}")
        return 1

    print(f"Loading data from {data_path}...")
    try:
        df = load_data_csv(data_path)
    except Exception as e:
        print(f"ERROR loading data: {e}")
        return 1

    if df.empty:
        print("ERROR: Data frame is empty")
        return 1

    print(f"Loaded {len(df)} candles ({df.index[0]} to {df.index[-1]})")

    # Build detectors and managers
    print("Initializing detectors...")
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

    # Build strategy
    if strategy_name == "ny_am_reversal":
        def htf_bias_fn(price):
            from timeframes.htf_bias import BiasResult
            return BiasResult(direction="bullish", strength=0.5)  # default bias
        strategy = NYAMReversalStrategy(
            detectors, risk_mgr, session_mgr, htf_bias_fn
        )
    elif strategy_name == "silver_bullet":
        def htf_bias_fn(price):
            from timeframes.htf_bias import BiasResult
            return BiasResult(direction="bullish", strength=0.5)
        strategy = SilverBulletStrategy(
            detectors, risk_mgr, session_mgr, htf_bias_fn
        )
    else:
        print(f"ERROR: Unknown strategy '{strategy_name}'")
        return 1

    # Run backtest
    print(f"Running {strategy_name} backtest...")
    backtester = Backtester(strategy, detectors, risk_mgr, tf_mgr, session_mgr)

    try:
        start_date = pd.Timestamp(args.start) if args.start else None
        end_date = pd.Timestamp(args.end) if args.end else None
        result = backtester.run(df, start_date=start_date, end_date=end_date)
    except Exception as e:
        print(f"ERROR running backtest: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "strategy": result.strategy,
        "total_trades": result.total_trades,
        "total_signals": result.total_signals,
        "wins": result.wins,
        "losses": result.losses,
        "win_rate": float(result.win_rate),
        "total_pnl": float(result.total_pnl),
        "start_date": str(result.start_date),
        "end_date": str(result.end_date),
        "trades": [_serialize_trade(t) for t in result.trades],
        "daily_pnl": {str(k): float(v) for k, v in result.daily_pnl.items()},
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\n=== Backtest Results ===")
    print(f"Strategy      : {result.strategy}")
    print(f"Total Trades  : {result.total_trades}")
    print(f"Win Rate      : {result.win_rate:.1%}")
    print(f"Total P&L     : ${result.total_pnl:+.2f}")
    print(f"Period        : {result.start_date} to {result.end_date}")
    print(f"Results saved : {output_path}")
    return 0


def cmd_audit(args):
    """Run risk audit on trades."""
    input_path = Path(args.trades)
    if not input_path.exists():
        print(f"ERROR: Trades file not found: {input_path}")
        return 1

    with open(input_path) as f:
        data = json.load(f)

    trades = [_deserialize_trade(t) for t in data["trades"]]
    result = audit_trades(trades)

    print(f"\n=== Risk Audit ===")
    print(f"Status        : {'CLEAN' if result.is_clean else 'VIOLATIONS'}")
    print(f"Violation Count: {result.violation_count}")
    if not result.is_clean:
        for msg in result.violations[:10]:  # show first 10
            print(f"  - {msg}")
        if len(result.violations) > 10:
            print(f"  ... and {len(result.violations) - 10} more")

    return 0 if result.is_clean else 1


def cmd_combine(args):
    """Simulate Topstep $50K Combine."""
    input_path = Path(args.trades)
    if not input_path.exists():
        print(f"ERROR: Trades file not found: {input_path}")
        return 1

    with open(input_path) as f:
        data = json.load(f)

    trades = [_deserialize_trade(t) for t in data["trades"]]
    result = simulate_combine(trades)

    print(f"\n=== Combine Simulation ===")
    print(f"Status        : {'PASSED' if result.passed else 'FAILED'}")
    if not result.passed:
        print(f"Failure       : {result.failure_reason}")
    print(f"Starting Bal  : ${result.starting_balance:,.2f}")
    print(f"Ending Bal    : ${result.ending_balance:,.2f}")
    print(f"Total P&L     : ${result.total_pnl:+,.2f}")
    print(f"Trading Days  : {result.trading_days}")
    print(f"Best Day      : ${result.best_day_pnl:+.2f} on {result.best_day_date}")

    return 0 if result.passed else 1


def cmd_report(args):
    """Generate performance report."""
    input_path = Path(args.trades)
    if not input_path.exists():
        print(f"ERROR: Trades file not found: {input_path}")
        return 1

    with open(input_path) as f:
        data = json.load(f)

    trades = [_deserialize_trade(t) for t in data["trades"]]

    # Load combine result if available
    combine_result = None
    if args.combine:
        combine_result = simulate_combine(trades)

    report = generate_report(
        trades,
        combine_result=combine_result,
        equity_csv=args.equity_csv,
    )

    print(report)

    # Optionally save report
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)
        print(f"\nReport saved to {output_path}")

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    setup_logging()

    parser = argparse.ArgumentParser(
        description="AlgoICT Backtest Pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backtest.cli backtest --strategy ny_am_reversal --data data/nq_1min.csv
  python -m backtest.cli audit --trades backtest_result.json
  python -m backtest.cli combine --trades backtest_result.json
  python -m backtest.cli report --trades backtest_result.json --combine
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Backtest command
    bt = subparsers.add_parser("backtest", help="Run backtest")
    bt.add_argument("--strategy", required=True, help="Strategy name (ny_am_reversal, silver_bullet)")
    bt.add_argument("--data", required=True, help="Path to OHLCV CSV")
    bt.add_argument("--start", help="Start date (YYYY-MM-DD)")
    bt.add_argument("--end", help="End date (YYYY-MM-DD)")
    bt.add_argument("--output", default="backtest_result.json", help="Output JSON file")
    bt.set_defaults(func=cmd_backtest)

    # Audit command
    au = subparsers.add_parser("audit", help="Run risk audit")
    au.add_argument("--trades", required=True, help="Trades JSON file")
    au.set_defaults(func=cmd_audit)

    # Combine command
    cb = subparsers.add_parser("combine", help="Simulate Topstep Combine")
    cb.add_argument("--trades", required=True, help="Trades JSON file")
    cb.set_defaults(func=cmd_combine)

    # Report command
    rp = subparsers.add_parser("report", help="Generate report")
    rp.add_argument("--trades", required=True, help="Trades JSON file")
    rp.add_argument("--combine", action="store_true", help="Include Combine simulation")
    rp.add_argument("--equity-csv", help="Save equity curve to CSV")
    rp.add_argument("--output", help="Save report to file")
    rp.set_defaults(func=cmd_report)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
