"""
scripts/run_backtest.py
========================
M11 — First real end-to-end backtest driver.

What this script does
---------------------
1. Loads OHLCV data (synthetic or from a CSV you provide)
2. Instantiates the full backtester stack (8 detectors + risk + tf +
   session + strategy)
3. Runs the backtest
4. Prints a formatted terminal report (metrics + top trades + equity)
5. Writes the BacktestResult and every Trade to Supabase via the
   canonical SupabaseLabClient built in M10

After this script runs, open the dashboard at http://localhost:3000:
  * /backtest  → your first real backtest result row
  * /trades    → every trade from that run
  * /          → live bot_state (if you kept wire_demo's state loaded)

Usage
-----
    # Synthetic 3-month run (zero setup)
    python scripts/run_backtest.py --strategy ny_am_reversal --synthetic

    # Longer run, specific dates
    python scripts/run_backtest.py --strategy silver_bullet --synthetic \\
        --start 2024-01-01 --end 2024-06-30

    # Real CSV data
    python scripts/run_backtest.py --strategy ny_am_reversal \\
        --csv data/mnq_1min.csv --start 2024-01-01 --end 2024-03-31

    # Local only, skip Supabase write
    python scripts/run_backtest.py --strategy ny_am_reversal --synthetic \\
        --no-supabase

Why this is the "M11 moment"
----------------------------
Everything we built from M1 → M10 meets here:
  * ICT detectors (swing, structure, FVG, OB, liquidity, displacement)
  * Confluence scorer
  * Risk manager (position sizing, kill switch, profit cap)
  * Session + TF managers
  * NY AM Reversal / Silver Bullet strategies
  * Backtester's candle-by-candle hot loop
  * SupabaseLabClient write path (M10)
  * Dashboard read path (M7)

If this produces a non-empty BacktestResult and the row lands in
Supabase visible in /backtest — the full stack works.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Windows cp1252 → UTF-8 so Unicode (▶ ✓ █ 🟢 etc.) prints correctly
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass  # Older Python or non-standard streams — best-effort only

import pandas as pd

# Make sibling modules importable when run as a script
ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from backtest.backtester import Backtester, BacktestResult  # noqa: E402
from backtest.data_loader import load_data_csv  # noqa: E402
from backtest.synthetic_data import generate_synthetic_data  # noqa: E402

# Detectors
from detectors.swing_points import SwingPointDetector  # noqa: E402
from detectors.market_structure import MarketStructureDetector  # noqa: E402
from detectors.fair_value_gap import FairValueGapDetector  # noqa: E402
from detectors.order_block import OrderBlockDetector  # noqa: E402
from detectors.liquidity import LiquidityDetector  # noqa: E402
from detectors.displacement import DisplacementDetector  # noqa: E402
from detectors.confluence import ConfluenceScorer  # noqa: E402

# Risk + time management
from risk.risk_manager import RiskManager  # noqa: E402
from timeframes.tf_manager import TimeframeManager  # noqa: E402
from timeframes.session_manager import SessionManager  # noqa: E402

# Strategies
from strategies.ny_am_reversal import NYAMReversalStrategy  # noqa: E402
from strategies.silver_bullet import SilverBulletStrategy  # noqa: E402

# Supabase write path (M10)
from db.supabase_lab_client import get_lab_client  # noqa: E402


logger = logging.getLogger("run_backtest")


# ─── Data loading ───────────────────────────────────────────────────────

DEFAULT_SYNTHETIC_PATH = ENGINE_ROOT.parent / "data" / "synthetic_m11.csv"
DEFAULT_SYNTHETIC_START = "2024-01-01"
DEFAULT_SYNTHETIC_END = "2024-03-31"


def load_or_generate_data(
    synthetic: bool,
    csv_path: Optional[str],
    start: Optional[str],
    end: Optional[str],
) -> pd.DataFrame:
    """Either generate synthetic data or load an existing CSV."""
    if synthetic:
        synth_start = start or DEFAULT_SYNTHETIC_START
        synth_end = end or DEFAULT_SYNTHETIC_END
        print(f"▶ Generating synthetic data: {synth_start} → {synth_end}")
        DEFAULT_SYNTHETIC_PATH.parent.mkdir(parents=True, exist_ok=True)
        generate_synthetic_data(
            str(DEFAULT_SYNTHETIC_PATH),
            start_date=synth_start,
            end_date=synth_end,
        )
        # Round-trip through load_data_csv so the shape matches production
        df = load_data_csv(DEFAULT_SYNTHETIC_PATH)
    else:
        if not csv_path:
            raise ValueError("--csv is required when --synthetic is not set")
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {path}")
        print(f"▶ Loading data from {path}")
        df = load_data_csv(path)

    print(f"  → {len(df):,} bars ({df.index[0]} → {df.index[-1]})")
    return df


# ─── Collaborator factory ───────────────────────────────────────────────

def build_backtester(strategy_name: str) -> tuple[Backtester, dict]:
    """
    Wire up every collaborator the backtester needs. Returns a ready-to-run
    Backtester + the config dict that will be stored alongside the result
    in Supabase for reproducibility.
    """
    print("▶ Building detectors...")
    # Note: SwingPointDetector takes an optional lookbacks DICT, not a TF string.
    # cli.py passes "1min" as a positional arg which is actually a bug there —
    # the default (config.SWING_LOOKBACK) is what we want here.
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

    # Stub HTF bias — cli.py uses the same pattern. A real driver would
    # compute bias from weekly/daily frames. For synthetic data it's fine
    # to force bullish since the random walk has no real HTF structure.
    def htf_bias_fn(*_args, **_kwargs):
        # Stub bias: forced bullish with high confidence so synthetic random-walk
        # data can still produce signals. A real driver would compute this from
        # actual weekly/daily bars via timeframes.htf_bias.
        from timeframes.htf_bias import BiasResult
        return BiasResult(
            direction="bullish",
            premium_discount="discount",
            htf_levels={},
            confidence="high",
            weekly_bias="bullish",
            daily_bias="bullish",
        )

    print(f"▶ Building strategy: {strategy_name}")
    strategy_name_lc = strategy_name.lower()
    if strategy_name_lc == "ny_am_reversal":
        strategy = NYAMReversalStrategy(
            detectors, risk_mgr, session_mgr, htf_bias_fn
        )
    elif strategy_name_lc == "silver_bullet":
        strategy = SilverBulletStrategy(
            detectors, risk_mgr, session_mgr, htf_bias_fn
        )
    else:
        raise ValueError(
            f"Unknown strategy '{strategy_name}'. "
            f"Valid: ny_am_reversal, silver_bullet"
        )

    backtester = Backtester(strategy, detectors, risk_mgr, tf_mgr, session_mgr)

    config = {
        "strategy": strategy_name_lc,
        "entry_tf": getattr(strategy, "ENTRY_TF", "5min"),
        "context_tf": getattr(strategy, "CONTEXT_TF", "15min"),
        "htf_bias": "bullish (stub)",
        "min_confluence": 7,
        "risk_per_trade": 250,
        "kill_switch_losses": 3,
        "daily_profit_cap": 1500,
    }
    return backtester, config


# ─── Reporting ──────────────────────────────────────────────────────────

def print_report(result: BacktestResult, elapsed_s: float) -> None:
    """Formatted terminal report."""
    print()
    print("=" * 70)
    print(f"  {result.strategy}  —  Backtest Complete ({elapsed_s:.1f}s)")
    print("=" * 70)

    print()
    print(f"  Period          : {result.start_date} → {result.end_date}")
    print(f"  Total signals   : {result.total_signals}")
    print(f"  Total trades    : {result.total_trades}")
    print(f"  Wins / Losses   : {result.wins} / {result.losses}")
    print(f"  Win rate        : {result.win_rate:.1%}")
    print(f"  Total P&L       : ${result.total_pnl:+,.2f}")

    if result.total_trades > 0:
        avg_pnl = result.total_pnl / result.total_trades
        wins_pnl = sum(t.pnl for t in result.trades if t.pnl > 0)
        losses_pnl = sum(t.pnl for t in result.trades if t.pnl <= 0)
        avg_win = wins_pnl / result.wins if result.wins > 0 else 0
        avg_loss = losses_pnl / result.losses if result.losses > 0 else 0
        pf = abs(wins_pnl / losses_pnl) if losses_pnl != 0 else 0.0

        print(f"  Profit factor   : {pf:.2f}")
        print(f"  Avg P&L/trade   : ${avg_pnl:+.2f}")
        print(f"  Avg win         : ${avg_win:+.2f}")
        print(f"  Avg loss        : ${avg_loss:+.2f}")

    # ─── Equity curve (simple ASCII) ────────────────────────────────
    if result.daily_pnl:
        print()
        print("  Daily P&L (first 15 sessions):")
        for i, (d, pnl) in enumerate(sorted(result.daily_pnl.items())[:15]):
            bar_width = int(abs(pnl) / 20)  # 1 char ≈ $20
            bar_char = "█" if pnl >= 0 else "▓"
            bar = bar_char * max(1, min(bar_width, 40))
            color_mark = "+" if pnl >= 0 else "-"
            print(f"    {d}  {color_mark}${abs(pnl):>7.2f}  {bar}")

    # ─── Top trades ─────────────────────────────────────────────────
    if result.trades:
        print()
        print(f"  Top 5 trades by P&L:")
        top = sorted(result.trades, key=lambda t: -t.pnl)[:5]
        for i, t in enumerate(top, 1):
            print(
                f"    {i}. {t.direction:<5} {t.entry_price:>8.2f} → "
                f"{t.exit_price:>8.2f}  pnl=${t.pnl:+.2f}  "
                f"conf={t.confluence_score}  [{t.reason}]"
            )

        print()
        print(f"  Worst 3 trades:")
        worst = sorted(result.trades, key=lambda t: t.pnl)[:3]
        for i, t in enumerate(worst, 1):
            print(
                f"    {i}. {t.direction:<5} {t.entry_price:>8.2f} → "
                f"{t.exit_price:>8.2f}  pnl=${t.pnl:+.2f}  "
                f"conf={t.confluence_score}  [{t.reason}]"
            )

    print()
    print("=" * 70)


# ─── Supabase write ─────────────────────────────────────────────────────

def write_to_supabase(
    result: BacktestResult,
    config: dict,
    run_id: str,
    notes: str,
    symbol: str,
) -> bool:
    """Persist result + trades to Supabase. Returns True on success."""
    client = get_lab_client()
    if client is None:
        print("⚠ No Supabase client (SUPABASE_URL/KEY missing) — skipping DB write.")
        print("  Pass --no-supabase to silence this warning.")
        return False

    print(f"▶ Writing to Supabase ({client.url})")

    ok = client.insert_backtest_result(
        result, run_id=run_id, config=config, notes=notes
    )
    if not ok:
        print("  ✗ backtest_results insert failed — check logs above")
        return False
    print(f"  ✓ backtest_results  id={run_id}")

    if result.trades:
        n = client.insert_trades_batch(result.trades, symbol=symbol)
        print(f"  ✓ trades batch      {n}/{len(result.trades)} inserted")
    else:
        print(f"  · trades            none to insert (0 trades)")

    stats = client.stats
    print(f"  · client stats      writes={stats['writes']} errors={stats['errors']}")
    return True


# ─── Main ───────────────────────────────────────────────────────────────

def main() -> int:
    args = _parse_args()

    logging.basicConfig(
        level=logging.WARNING,  # Suppress detector noise; just the report
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print()
    print("▶ M11 — AlgoICT First Real Backtest")
    print()

    # Step 1: data
    try:
        df = load_or_generate_data(
            synthetic=args.synthetic,
            csv_path=args.csv,
            start=args.start,
            end=args.end,
        )
    except Exception as e:
        print(f"✗ Data load failed: {e}")
        return 1

    if df.empty:
        print("✗ Data frame is empty — nothing to backtest")
        return 1

    # Step 2: backtester + collaborators
    try:
        backtester, config = build_backtester(args.strategy)
    except Exception as e:
        print(f"✗ Build failed: {e}")
        import traceback; traceback.print_exc()
        return 1

    # Step 3: run
    print(f"▶ Running backtest...")
    t0 = time.perf_counter()
    try:
        result = backtester.run(
            df,
            start_date=args.start,
            end_date=args.end,
        )
    except Exception as e:
        print(f"✗ Backtest crashed: {e}")
        import traceback; traceback.print_exc()
        return 2
    elapsed = time.perf_counter() - t0

    # Step 4: report
    print_report(result, elapsed)

    # Step 5: Supabase write
    if not args.no_supabase:
        run_id = (
            args.run_id
            or f"{args.strategy}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        )
        notes = f"M11 first real backtest — {'synthetic' if args.synthetic else Path(args.csv).name}"
        write_to_supabase(
            result=result,
            config=config,
            run_id=run_id,
            notes=notes,
            symbol=args.symbol,
        )

    # Step 6: success marker
    print()
    if result.total_trades > 0:
        pnl_mark = "🟢" if result.total_pnl > 0 else "🔴"
        print(f"{pnl_mark}  HOLY SHIT IT WORKED.  {result.total_trades} trades, ${result.total_pnl:+.2f}")
    else:
        print("⚪  Backtest ran successfully but produced 0 trades.")
        print("    (Synthetic random-walk data rarely forms ICT patterns —")
        print("    try real MNQ data or adjust strategy thresholds.)")
    print()
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_backtest",
        description="M11 — First real end-to-end backtest + Supabase write",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--strategy",
        required=True,
        choices=("ny_am_reversal", "silver_bullet"),
        help="Strategy to backtest",
    )

    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--synthetic",
        action="store_true",
        help="Generate and use synthetic OHLCV data",
    )
    src.add_argument(
        "--csv",
        help="Path to a 1-min OHLCV CSV file",
    )

    p.add_argument(
        "--start",
        help="Start date YYYY-MM-DD (default: 2024-01-01 for synthetic)",
    )
    p.add_argument(
        "--end",
        help="End date YYYY-MM-DD (default: 2024-03-31 for synthetic)",
    )
    p.add_argument(
        "--symbol",
        default="MNQ",
        help="Symbol for trade rows (default: MNQ)",
    )
    p.add_argument(
        "--run-id",
        help="Explicit run id (default: auto-generated)",
    )
    p.add_argument(
        "--no-supabase",
        action="store_true",
        help="Skip writing to Supabase (local only)",
    )
    return p.parse_args()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
