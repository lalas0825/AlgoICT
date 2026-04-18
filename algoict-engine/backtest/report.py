"""
backtest/report.py
==================
Generates a human-readable performance report from backtest trades and
optionally a CombineResult.

Metrics computed
----------------
- Total trades, win rate, avg win, avg loss, expectancy
- Profit factor, Sharpe ratio (daily P&L), max drawdown (cumulative)
- Distribution by kill zone, by weekday, by confluence band (7-8 / 9-11 / 12+)
- Equity curve exported as CSV (optional path parameter)

Usage
-----
    from backtest.report import generate_report
    text = generate_report(result.trades, combine_result=sim)
    print(text)
    # or save equity curve:
    text = generate_report(result.trades, equity_csv="equity.csv")
"""

import csv
import datetime
import math
import logging
from collections import defaultdict
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

logger = logging.getLogger(__name__)

MNQ_POINT_VALUE = config.MNQ_POINT_VALUE
_RISK_FREE_DAILY = 0.0          # assume 0% risk-free for Sharpe


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_report(
    trades,
    combine_result=None,
    equity_csv: Optional[str] = None,
) -> str:
    """
    Generate a text performance report.

    Parameters
    ----------
    trades        : list[Trade]
    combine_result: CombineResult | None  — appended section if provided
    equity_csv    : str | None            — path to write equity curve CSV

    Returns
    -------
    str — multi-line report ready for print() or file.write()
    """
    lines: list[str] = []
    _h = lines.append                   # shorthand

    if not trades:
        return "=== AlgoICT Backtest Report ===\n(no trades)\n"

    # ── Core stats ─────────────────────────────────────────────────────────
    total = len(trades)
    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    n_wins   = len(wins)
    n_losses = len(losses)
    win_rate = n_wins / total if total else 0.0

    total_pnl   = sum(t.pnl for t in trades)
    avg_win     = (sum(t.pnl for t in wins)   / n_wins)   if wins   else 0.0
    avg_loss    = (sum(t.pnl for t in losses) / n_losses) if losses else 0.0
    expectancy  = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    gross_profit = sum(t.pnl for t in wins)
    gross_loss   = abs(sum(t.pnl for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    # ── Exit reason breakdown ───────────────────────────────────────────────
    by_reason: dict[str, int] = defaultdict(int)
    for t in trades:
        by_reason[t.reason] += 1

    # Daily P&L -> Sharpe
    daily_pnl: dict[datetime.date, float] = defaultdict(float)
    for t in trades:
        try:
            d = t.entry_time.date()
        except AttributeError:
            d = t.entry_time.to_pydatetime().date()
        daily_pnl[d] += t.pnl

    daily_values = list(daily_pnl.values())
    sharpe = _sharpe(daily_values)

    # ── Equity curve + max drawdown ─────────────────────────────────────────
    equity_curve = _build_equity_curve(trades)
    max_dd = _max_drawdown(equity_curve)

    if equity_csv and equity_curve:
        _write_equity_csv(equity_curve, equity_csv)

    # ── Kill-zone distribution ──────────────────────────────────────────────
    by_kz: dict[str, list] = defaultdict(list)
    for t in trades:
        kz = getattr(t, "kill_zone", "") or _infer_kz(t)
        by_kz[kz].append(t.pnl)

    # ── Weekday distribution ────────────────────────────────────────────────
    by_dow: dict[str, list] = defaultdict(list)
    _DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for t in trades:
        try:
            dow = t.entry_time.weekday()
        except AttributeError:
            dow = t.entry_time.to_pydatetime().weekday()
        by_dow[_DAYS[dow]].append(t.pnl)

    # Confluence bands
    bands = {"7-8": [], "9-11": [], "12+": []}
    for t in trades:
        s = t.confluence_score
        if s <= 8:
            bands["7-8"].append(t.pnl)
        elif s <= 11:
            bands["9-11"].append(t.pnl)
        else:
            bands["12+"].append(t.pnl)

    # Duration stats
    durations = [t.duration_bars for t in trades]
    avg_dur = sum(durations) / len(durations) if durations else 0
    max_dur = max(durations) if durations else 0

    # Build report text
    _h("=" * 60)
    _h("  AlgoICT Backtest Report")
    _h("=" * 60)

    if trades:
        try:
            first_d = min(t.entry_time for t in trades)
            last_d  = max(t.entry_time for t in trades)
            _h(f"  Period : {first_d.date()} to {last_d.date()}")
        except Exception:
            pass

    strategy_names = list({t.strategy for t in trades})
    _h(f"  Strategy: {', '.join(strategy_names)}")
    _h("")

    # Core metrics
    _h("-- Overview -------------------------------------------")
    _h(f"  Total Trades   : {total}")
    _h(f"  Wins / Losses  : {n_wins} / {n_losses}")
    _h(f"  Win Rate       : {win_rate:.1%}")
    _h(f"  Total P&L      : ${total_pnl:+.2f}")
    _h("")
    _h(f"  Avg Win        : ${avg_win:+.2f}")
    _h(f"  Avg Loss       : ${avg_loss:+.2f} ")
    _h(f"  Expectancy     : ${expectancy:+.2f} / trade")
    _h(f"  Profit Factor  : {profit_factor:.2f}")
    _h(f"  Sharpe (daily) : {sharpe:.2f}")
    _h(f"  Max Drawdown   : ${max_dd:.2f}")
    _h("")

    _h("── Exit Reasons ──────────────────────────────────────────")
    for reason, cnt in sorted(by_reason.items()):
        _h(f"  {reason:<14} : {cnt}")
    _h("")

    _h("── Duration ──────────────────────────────────────────────")
    _h(f"  Avg Hold (bars): {avg_dur:.1f}  |  Max: {max_dur}")
    _h("")

    _h("── Kill Zone Distribution ────────────────────────────────")
    for kz, pnls in sorted(by_kz.items()):
        wr = sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0
        _h(f"  {kz or 'unknown':<18}: {len(pnls):>3} trades  wr={wr:.0%}  sum=${sum(pnls):+.2f}")
    _h("")

    _h("── Day-of-Week Distribution ──────────────────────────────")
    for dow in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        pnls = by_dow.get(dow, [])
        if not pnls:
            continue
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        _h(f"  {dow}: {len(pnls):>3} trades  wr={wr:.0%}  sum=${sum(pnls):+.2f}")
    _h("")

    _h("── Confluence Band Distribution ──────────────────────────")
    for band, pnls in bands.items():
        if not pnls:
            _h(f"  {band}: (no trades)")
            continue
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        _h(f"  {band:<5}: {len(pnls):>3} trades  wr={wr:.0%}  sum=${sum(pnls):+.2f}")
    _h("")

    # ── Combine section ─────────────────────────────────────────────────────
    if combine_result is not None:
        _h("── Topstep $50K Combine Simulation ──────────────────────")
        status = "PASSED" if combine_result.passed else "FAILED"
        _h(f"  Status         : {status}")
        if combine_result.failure_reason:
            _h(f"  Failure        : {combine_result.failure_reason}")
        _h(f"  Starting Bal   : ${combine_result.starting_balance:,.2f}")
        _h(f"  Ending Bal     : ${combine_result.ending_balance:,.2f}")
        _h(f"  Peak Bal       : ${combine_result.peak_balance:,.2f}")
        _h(f"  Total P&L      : ${combine_result.total_pnl:+,.2f}")
        _h(f"  Profit Target  : ${combine_result.profit_target:,.2f}")
        _h(f"  Trading Days   : {combine_result.trading_days}")
        if combine_result.best_day_date:
            _h(
                f"  Best Day       : ${combine_result.best_day_pnl:+.2f}"
                f" on {combine_result.best_day_date}"
            )
        if combine_result.consistency_ok is not None:
            flag = "OK" if combine_result.consistency_ok else "VIOLATED"
            _h(f"  Consistency    : {flag}")
        _h("")

    if equity_csv:
        _h(f"  Equity CSV     : {equity_csv}")
        _h("")

    _h("=" * 60)

    report = "\n".join(lines)
    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_equity_curve(trades):
    """
    Returns list of (timestamp, cumulative_pnl) sorted by entry_time.
    """
    sorted_t = sorted(trades, key=lambda t: t.entry_time)
    curve = []
    running = 0.0
    for t in sorted_t:
        running += t.pnl
        curve.append((t.exit_time, running))
    return curve


def _max_drawdown(equity_curve) -> float:
    """Maximum peak-to-trough drawdown in dollars."""
    if not equity_curve:
        return 0.0
    peak = 0.0
    max_dd = 0.0
    for _, val in equity_curve:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _sharpe(daily_values) -> float:
    """Annualised Sharpe from list of daily P&L values."""
    n = len(daily_values)
    if n < 2:
        return 0.0
    mean = sum(daily_values) / n
    variance = sum((x - mean) ** 2 for x in daily_values) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    daily_sharpe = (mean - _RISK_FREE_DAILY) / std
    return daily_sharpe * math.sqrt(252)            # annualise


def _write_equity_csv(equity_curve, path: str) -> None:
    """Write (timestamp, cumulative_pnl) pairs to CSV."""
    try:
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "cumulative_pnl"])
            for ts, val in equity_curve:
                writer.writerow([ts, f"{val:.2f}"])
        logger.info("Equity curve saved to %s (%d rows)", path, len(equity_curve))
    except Exception as exc:
        logger.error("Failed to write equity CSV: %s", exc)


def _infer_kz(trade) -> str:
    """Fallback: guess kill zone from entry hour (CT)."""
    try:
        h = trade.entry_time.hour
    except AttributeError:
        h = trade.entry_time.to_pydatetime().hour
    if 8 <= h < 11:
        return "ny_am"
    if 10 <= h < 11:
        return "silver_bullet"
    return ""
