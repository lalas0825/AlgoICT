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
from backtest.databento_loader import load_databento_ohlcv_1m  # noqa: E402
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

# HTF bias detector for dynamic bias mode
from timeframes.htf_bias import HTFBiasDetector, BiasResult  # noqa: E402

# Supabase write path (M10)
from db.supabase_lab_client import get_lab_client  # noqa: E402


# ─── Dynamic HTF bias wrapper ───────────────────────────────────────────

class DynamicBiasStrategy:
    """
    Strategy wrapper that replaces the static ``htf_bias_fn`` with a
    real bias computed from past daily + weekly bars at every evaluate().

    Why this exists
    ---------------
    The base strategies expect a callable ``htf_bias_fn(last_close) -> BiasResult``.
    Our default (cli.py copy) hardcodes bullish, which biases the entire
    backtest to long-only and inflates results during uptrending markets.

    A real bias must be:
      * derived from completed daily + weekly bars
      * recomputed at every minute the strategy evaluates
      * strictly look-ahead-free — only data that existed BEFORE the
        current bar's timestamp is allowed

    Implementation
    --------------
    The wrapper holds pre-computed daily + weekly aggregates of the
    full backtest dataset (built once at construction). On each
    ``evaluate()`` call:

      1. Capture the current bar's timestamp from ``candles_5min.index[-1]``
      2. Inject a closure into the inner strategy as ``htf_bias_fn``
         that, when called by the strategy, slices ``df_daily`` and
         ``df_weekly`` to bars whose label is strictly BEFORE
         ``current_ts.normalize()`` (i.e. excludes today + this week)
      3. Calls ``HTFBiasDetector.determine_bias(past_daily, past_weekly, price)``
      4. Delegates to inner strategy's ``evaluate()``

    All other attributes (ENTRY_TF, CONTEXT_TF, reset_daily, etc.)
    pass through to the inner strategy via ``__getattr__``.
    """

    def __init__(
        self,
        inner: object,
        df_daily: pd.DataFrame,
        df_weekly: pd.DataFrame,
        detector: Optional[HTFBiasDetector] = None,
    ):
        self._inner = inner
        self._df_daily = df_daily
        self._df_weekly = df_weekly
        self._detector = detector or HTFBiasDetector()

        self._current_ts: Optional[pd.Timestamp] = None
        self._neutral_count = 0
        self._bullish_count = 0
        self._bearish_count = 0

        # Wire the closure into the inner strategy
        self._inner.htf_bias_fn = self._dynamic_bias

    # ─── Stats ──────────────────────────────────────────────────────────

    @property
    def bias_stats(self) -> dict:
        total = self._bullish_count + self._bearish_count + self._neutral_count
        return {
            "calls": total,
            "bullish": self._bullish_count,
            "bearish": self._bearish_count,
            "neutral": self._neutral_count,
            "bullish_pct": self._bullish_count / total if total else 0.0,
            "bearish_pct": self._bearish_count / total if total else 0.0,
            "neutral_pct": self._neutral_count / total if total else 0.0,
        }

    # ─── Core: dynamic bias closure ─────────────────────────────────────

    def _dynamic_bias(self, current_price: float, *_args, **_kwargs) -> BiasResult:
        """
        Closure invoked by the inner strategy in place of its htf_bias_fn.
        Reads the captured ``self._current_ts`` to determine which past
        bars to use, then calls the detector.
        """
        if self._current_ts is None:
            # Strategy called bias before evaluate() — defensive neutral
            return self._detector._neutral_result()

        # Cutoff: start of today (Chicago tz). Anything labeled before
        # this is a fully-completed prior bar; today's in-progress bar
        # is excluded.
        cutoff = self._current_ts.normalize()

        past_daily = self._df_daily[self._df_daily.index < cutoff]
        past_weekly = self._df_weekly[self._df_weekly.index < cutoff]

        if past_daily.empty or past_weekly.empty:
            # Not enough HTF history yet — return neutral so the strategy
            # rejects the trade rather than defaulting to bullish
            self._neutral_count += 1
            return self._detector._neutral_result()

        result = self._detector.determine_bias(
            df_daily=past_daily,
            df_weekly=past_weekly,
            current_price=float(current_price),
        )

        if result.direction == "bullish":
            self._bullish_count += 1
        elif result.direction == "bearish":
            self._bearish_count += 1
        else:
            self._neutral_count += 1
        return result

    # ─── Strategy interface delegation ─────────────────────────────────

    def evaluate(self, candles_entry: pd.DataFrame, candles_context: pd.DataFrame):
        if not candles_entry.empty:
            self._current_ts = candles_entry.index[-1]
        return self._inner.evaluate(candles_entry, candles_context)

    def __getattr__(self, name: str):
        # Called only when normal attribute lookup fails — passes through
        # ENTRY_TF, CONTEXT_TF, reset_daily, etc. to the inner strategy.
        return getattr(self._inner, name)


logger = logging.getLogger("run_backtest")


# ─── Data loading ───────────────────────────────────────────────────────

DEFAULT_SYNTHETIC_PATH = ENGINE_ROOT.parent / "data" / "synthetic_m11.csv"
DEFAULT_SYNTHETIC_START = "2024-01-01"
DEFAULT_SYNTHETIC_END = "2024-03-31"


def load_or_generate_data(
    synthetic: bool,
    csv_path: Optional[str],
    databento_path: Optional[str],
    start: Optional[str],
    end: Optional[str],
    symbol_prefix: str = "NQ",
) -> pd.DataFrame:
    """
    Data source dispatcher — one of three modes:
      * synthetic: generate random-walk OHLCV via synthetic_data.py
      * csv:       simple OHLCV CSV via load_data_csv (timestamp column)
      * databento: full Databento OHLCV-1m dump via databento_loader
                   (handles multi-contract files + front-month continuous)
    """
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
        df = load_data_csv(DEFAULT_SYNTHETIC_PATH)
    elif databento_path:
        path = Path(databento_path)
        if not path.exists():
            raise FileNotFoundError(f"Databento CSV not found: {path}")
        print(f"▶ Loading Databento OHLCV-1m: {path.name} ({path.stat().st_size / 1024 / 1024:.0f} MB)")
        print(f"  (filtering front-month continuous, prefix={symbol_prefix!r})")
        df = load_databento_ohlcv_1m(
            path,
            start_date=start,
            end_date=end,
            symbol_prefix=symbol_prefix,
        )
    else:
        if not csv_path:
            raise ValueError("one of --synthetic, --csv, --databento is required")
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {path}")
        print(f"▶ Loading simple OHLCV CSV: {path}")
        df = load_data_csv(path)

    print(f"  → {len(df):,} bars ({df.index[0]} → {df.index[-1]})")
    return df


# ─── Collaborator factory ───────────────────────────────────────────────

def build_backtester(
    strategy_name: str,
    df_1min: Optional[pd.DataFrame] = None,
    dynamic_bias: bool = False,
    topstep_mode: bool = False,
    # MLL defaults aligned with live (main.py + risk_manager.py). Prior
    # 0.80/0.95 here diverged from 0.60/0.85 everywhere else — meta-audit
    # 2026-04-17 flagged it as live-vs-backtest parity break.
    mll_warning_pct: float = 0.40,
    mll_caution_pct: float = 0.60,
    mll_stop_pct: float = 0.85,
    ny_am_only: bool = False,
    ifvg_enabled: bool = True,
    # None → fall back to config.TRADE_MANAGEMENT (default "trailing") so
    # backtest and live agree on exit regime unless caller opts in.
    trade_management: Optional[str] = None,
    kill_zones_override: Optional[tuple] = None,
) -> tuple[Backtester, dict]:
    """
    Wire up every collaborator the backtester needs. Returns a ready-to-run
    Backtester + the config dict that will be stored alongside the result
    in Supabase for reproducibility.

    If ``df_1min`` is supplied, we pre-compute daily PDH/PDL + weekly
    PWH/PWL from the entire dataset and seed the ``tracked_levels`` list.
    This is essential: both strategies require at least one *swept*
    liquidity level to fire, and without pre-seeding, the list stays
    empty for the whole run → zero signals. (See main.py:215 — the
    comment ``populated by engine as PDH/PDL/equals are swept`` describes
    the production engine's behavior; the standalone backtester CLI
    never wired this up, which is why cli.py always returns 0 trades
    on real data.)
    """
    print("▶ Building detectors...")
    # Note: SwingPointDetector takes an optional lookbacks DICT, not a TF string.
    # cli.py passes "1min" as a positional arg which is actually a bug there —
    # the default (config.SWING_LOOKBACK) is what we want here.
    liquidity = LiquidityDetector()
    detectors = {
        "swing_entry": SwingPointDetector(),
        "swing_context": SwingPointDetector(),
        "structure": MarketStructureDetector(),
        "fvg": FairValueGapDetector(),
        "ob": OrderBlockDetector(),
        "liquidity": liquidity,
        "displacement": DisplacementDetector(),
        "confluence": ConfluenceScorer(),
        "tracked_levels": [],
    }

    # Seed tracked_levels with PDH/PDL + PWH/PWL for the whole period.
    # The backtester's _update_sweeps() will mark these as swept as the
    # 1-min bars cross them, and the strategy will see sweeps.
    if df_1min is not None and not df_1min.empty:
        tmp_tf = TimeframeManager()
        try:
            df_daily = tmp_tf.aggregate(df_1min, "D")
        except Exception:
            df_daily = None
        try:
            df_weekly = tmp_tf.aggregate(df_1min, "W")
        except Exception:
            df_weekly = None

        seeded: list = []
        if df_daily is not None and not df_daily.empty:
            # Build PDH/PDL pairs for every day using a 1-day trailing window.
            # Each daily bar produces ONE pair (high/low of that day) which
            # becomes the following day's PDH/PDL. We label them with the
            # daily bar's own timestamp.
            for i in range(len(df_daily)):
                window = df_daily.iloc[i:i + 1]
                pair = liquidity.build_key_levels(df_daily=window)
                seeded.extend(pair)

        if df_weekly is not None and not df_weekly.empty:
            for i in range(len(df_weekly)):
                window = df_weekly.iloc[i:i + 1]
                pair = liquidity.build_key_levels(df_weekly=window)
                seeded.extend(pair)

        detectors["tracked_levels"] = seeded
        print(f"  seeded tracked_levels: {len(seeded)} PDH/PDL/PWH/PWL levels")

    risk_mgr = RiskManager()
    if topstep_mode:
        risk_mgr.enable_topstep_mode(
            warning_pct=mll_warning_pct,
            caution_pct=mll_caution_pct,
            stop_pct=mll_stop_pct,
        )
        mll = risk_mgr._mll_limit
        print(
            f"  Topstep $50K Combine mode ON "
            f"(warn=${mll * mll_warning_pct:.0f} @ {mll_warning_pct:.0%}, "
            f"caution=${mll * mll_caution_pct:.0f} @ {mll_caution_pct:.0%}, "
            f"stop=${mll * mll_stop_pct:.0f} @ {mll_stop_pct:.0%})"
        )
    tf_mgr = TimeframeManager()
    session_mgr = SessionManager()

    # Static stub bias — used unless --dynamic-bias is set. Always returns
    # bullish so the strategy will at least take long setups on synthetic
    # data (which has no real HTF structure). For real data the dynamic
    # branch below should be used.
    def static_bullish_bias(*_args, **_kwargs):
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
            detectors, risk_mgr, session_mgr, static_bullish_bias
        )
    elif strategy_name_lc == "silver_bullet":
        strategy = SilverBulletStrategy(
            detectors, risk_mgr, session_mgr, static_bullish_bias
        )
    else:
        raise ValueError(
            f"Unknown strategy '{strategy_name}'. "
            f"Valid: ny_am_reversal, silver_bullet"
        )

    # Ablation overrides
    if kill_zones_override is not None:
        strategy.KILL_ZONES = kill_zones_override
        strategy._trades_by_zone = {z: 0 for z in kill_zones_override}
        print(f"  KZ OVERRIDE: KILL_ZONES = {kill_zones_override}")
    elif ny_am_only and strategy_name_lc == "ny_am_reversal":
        strategy.KILL_ZONES = ("ny_am",)
        strategy._trades_by_zone = {"ny_am": 0}
        print("  ABLATION: KILL_ZONES restricted to ('ny_am',)")
    if not ifvg_enabled and strategy_name_lc == "ny_am_reversal":
        strategy._ifvg_enabled = False
        print("  ABLATION: IFVG fallback disabled")

    # Optional: wrap with DynamicBiasStrategy if requested + we have data
    bias_label = "bullish (static stub)"
    if dynamic_bias:
        if df_1min is None or df_1min.empty:
            print("  ⚠ --dynamic-bias requested but no df_1min — falling back to static")
        else:
            print("  ▶ Wrapping with DynamicBiasStrategy (computed from W/D bars)")
            tmp_tf = TimeframeManager()
            df_daily_for_bias = tmp_tf.aggregate(df_1min, "D")
            df_weekly_for_bias = tmp_tf.aggregate(df_1min, "W")
            print(
                f"    daily bars:  {len(df_daily_for_bias)}  "
                f"weekly bars: {len(df_weekly_for_bias)}"
            )
            strategy = DynamicBiasStrategy(
                inner=strategy,
                df_daily=df_daily_for_bias,
                df_weekly=df_weekly_for_bias,
            )
            bias_label = "dynamic (HTFBiasDetector W+D)"

    backtester = Backtester(
        strategy, detectors, risk_mgr, tf_mgr, session_mgr,
        trade_management=trade_management,
    )
    if trade_management != "fixed":
        print(f"  Trade management: {trade_management}")

    config = {
        "strategy": strategy_name_lc,
        "entry_tf": getattr(strategy, "ENTRY_TF", "5min"),
        "context_tf": getattr(strategy, "CONTEXT_TF", "15min"),
        "htf_bias": bias_label,
        "topstep_mode": topstep_mode,
        "trade_management": trade_management,
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
            databento_path=args.databento,
            start=args.start,
            end=args.end,
            symbol_prefix=args.symbol_prefix,
        )
    except Exception as e:
        print(f"✗ Data load failed: {e}")
        return 1

    if df.empty:
        print("✗ Data frame is empty — nothing to backtest")
        return 1

    # Step 2: backtester + collaborators (seeds tracked_levels from df)
    try:
        kz_override = None
        if args.kill_zones:
            kz_override = tuple(z.strip() for z in args.kill_zones.split(",") if z.strip())
        backtester, config = build_backtester(
            args.strategy,
            df_1min=df,
            dynamic_bias=args.dynamic_bias,
            topstep_mode=args.topstep,
            mll_warning_pct=args.mll_warning_pct,
            mll_caution_pct=args.mll_caution_pct,
            mll_stop_pct=args.mll_stop_pct,
            ny_am_only=args.ny_am_only,
            ifvg_enabled=not args.no_ifvg,
            trade_management=args.trade_management,
            kill_zones_override=kz_override,
        )
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

    # Optional: dynamic bias stats
    strategy_obj = backtester.strategy
    if isinstance(strategy_obj, DynamicBiasStrategy):
        stats = strategy_obj.bias_stats
        print()
        print(f"  HTF bias distribution ({stats['calls']} calls):")
        print(f"    bullish : {stats['bullish']:>6,}  ({stats['bullish_pct']:>5.1%})")
        print(f"    bearish : {stats['bearish']:>6,}  ({stats['bearish_pct']:>5.1%})")
        print(f"    neutral : {stats['neutral']:>6,}  ({stats['neutral_pct']:>5.1%})")
        print()

    # Optional: Topstep MLL stats
    rm = backtester.risk
    if rm.topstep_mode:
        print()
        print(f"  Topstep Combine stats:")
        print(f"    Final balance   : ${rm.current_balance:>10,.2f}")
        print(f"    Peak EOD balance: ${rm.peak_balance_eod:>10,.2f}")
        print(f"    Current DD      : ${rm.current_drawdown:>10,.2f}")
        print(f"    MLL zone        : {rm.mll_zone}")
        print(f"    Target reached  : {'YES' if rm.target_reached else 'NO'}")
        print()

    # Step 5: Supabase write
    if not args.no_supabase:
        run_id = (
            args.run_id
            or f"{args.strategy}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        )
        if args.synthetic:
            source_label = "synthetic"
        elif args.databento:
            source_label = f"databento:{Path(args.databento).name}"
        else:
            source_label = Path(args.csv).name
        notes = f"M11 run — {source_label}"
        write_to_supabase(
            result=result,
            config=config,
            run_id=run_id,
            notes=notes,
            symbol=args.symbol,
        )

    # Step 5b: JSON export for post-hoc analysis (KZ splits, combine sim, etc.)
    if args.export_json:
        import json as _json
        export_path = Path(args.export_json)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        # Compute equity curve + max drawdown from trade sequence
        trades_sorted = sorted(result.trades, key=lambda t: t.entry_time)
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        equity_curve = []
        for t in trades_sorted:
            equity += float(t.pnl)
            peak = max(peak, equity)
            dd = peak - equity
            max_dd = max(max_dd, dd)
            equity_curve.append({"t": str(t.entry_time), "equity": equity, "peak": peak, "dd": dd})
        payload = {
            "strategy": result.strategy,
            "total_trades": int(result.total_trades),
            "wins": int(result.wins),
            "losses": int(result.losses),
            "win_rate": float(result.win_rate),
            "total_pnl": float(result.total_pnl),
            "max_drawdown_dollars": float(max_dd),
            "peak_equity": float(peak),
            "start_date": str(result.start_date),
            "end_date": str(result.end_date),
            "trades": [
                {
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
                    "reason": getattr(t, "reason", ""),
                    "confluence_score": int(getattr(t, "confluence_score", 0) or 0),
                    "kill_zone": getattr(t, "kill_zone", ""),
                } for t in trades_sorted
            ],
        }
        with open(export_path, "w", encoding="utf-8") as f:
            _json.dump(payload, f, indent=2)
        print(f"  ✓ trades exported to {export_path} (max_dd=${max_dd:,.2f})")

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
        help="Generate and use synthetic OHLCV data (random walk)",
    )
    src.add_argument(
        "--csv",
        help="Path to a simple OHLCV CSV (columns: timestamp,open,high,low,close,volume)",
    )
    src.add_argument(
        "--databento",
        help="Path to a Databento OHLCV-1m CSV dump (multi-contract + spreads)",
    )

    p.add_argument(
        "--symbol-prefix",
        default="NQ",
        help="Contract root filter for Databento files (default: NQ)",
    )
    p.add_argument(
        "--dynamic-bias",
        action="store_true",
        help=(
            "Replace the hardcoded-bullish HTF bias stub with a real bias "
            "computed from completed weekly + daily bars at every "
            "evaluate() call. Look-ahead-free."
        ),
    )
    p.add_argument(
        "--topstep",
        action="store_true",
        help=(
            "Enable Topstep $50K Combine MLL-aware risk protection. "
            "Halves position at 75%% MLL drawdown, stops at 90%%, "
            "enters protective mode after profit target reached."
        ),
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
    p.add_argument(
        "--export-json",
        help="Also dump trades to a JSON file at this path",
    )
    p.add_argument(
        "--mll-warning-pct",
        type=float,
        default=0.40,
        help="MLL warning zone threshold (fraction of MLL). -25%% size when DD >= this. Default 0.40 = $800.",
    )
    p.add_argument(
        "--mll-caution-pct",
        type=float,
        default=0.80,
        help="MLL caution zone threshold. -50%% size when DD >= this. Default 0.80 = $1,600.",
    )
    p.add_argument(
        "--mll-stop-pct",
        type=float,
        default=0.95,
        help="MLL stop zone threshold. No new trades when DD >= this. Default 0.95 = $1,900.",
    )
    p.add_argument(
        "--ny-am-only",
        action="store_true",
        help="Restrict strategy KILL_ZONES to ('ny_am',) only (ablation)",
    )
    p.add_argument(
        "--no-ifvg",
        action="store_true",
        help="Disable IFVG fallback in NY AM Reversal (ablation)",
    )
    p.add_argument(
        "--trade-management",
        default=None,  # None → fall back to config.TRADE_MANAGEMENT at Backtester ctor
        choices=("fixed", "partials_be", "trailing"),
        help=(
            "Exit mode: "
            "fixed=standard SL/TP; "
            "partials_be=close 50%% at 1R + move stop to BE; "
            "trailing=no fixed target, trail last 5min swing. "
            "Default: config.TRADE_MANAGEMENT (currently: trailing) — matches live."
        ),
    )
    p.add_argument(
        "--kill-zones",
        default=None,
        help=(
            "Comma-separated kill zone override, e.g. 'london,ny_am'. "
            "Overrides the strategy's default KILL_ZONES for this run."
        ),
    )
    return p.parse_args()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
