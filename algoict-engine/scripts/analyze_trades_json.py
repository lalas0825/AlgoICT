"""
scripts/analyze_trades_json.py
===============================
Post-process a trades.json (exported by run_backtest.py --export-json)
into:

  - Per-kill-zone splits (trades, WR, PF, P&L, avg_rr, max_dd)
  - Combine Simulator result (single run) on the full trade sequence
  - Combine Simulator rolling pass-rate (up to 30 attempts)

Usage
-----
    python scripts/analyze_trades_json.py ../ny_am_2024_trades.json
    python scripts/analyze_trades_json.py file1.json file2.json ...   (combines)
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from dataclasses import dataclass
import pandas as pd
from backtest.backtester import Trade
from backtest.combine_simulator import simulate_combine


@dataclass
class _TradeRow:
    """Local analogue of Trade that also carries kill_zone. Compatible with
    combine_simulator.simulate_combine (which only reads entry_time / pnl)."""
    strategy: str
    symbol: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    contracts: int
    pnl: float
    reason: str
    confluence_score: int
    kill_zone: str
    duration_bars: int


# Kill-zone ranges (hour, minute) in US/Central. Mirrors config.KILL_ZONES
# but inlined so this script stays standalone.
_KZ = {
    "london":                ((1, 0),  (4, 0)),
    "london_silver_bullet":  ((2, 0),  (3, 0)),
    "ny_am":                 ((8, 30), (12, 0)),
    "silver_bullet":         ((10, 0), (11, 0)),
    "ny_pm":                 ((13, 30),(15, 0)),
}
_STRATEGY_KZ = {
    "ny_am_reversal": ("london", "ny_am", "ny_pm"),
    "silver_bullet":  ("london_silver_bullet", "silver_bullet"),
}

def _infer_kill_zone(ts: pd.Timestamp, strategy: str) -> str:
    """Infer which kill zone the entry bar fell in. Timestamps are US/Central
    (Databento was converted to CT during load)."""
    candidates = _STRATEGY_KZ.get(strategy, ())
    hm = (ts.hour, ts.minute)
    for kz in candidates:
        start, end = _KZ[kz]
        if start <= hm < end:
            return kz
    return "(unknown)"


def load_trades(paths: list[str]) -> list["_TradeRow"]:
    out: list[_TradeRow] = []
    for p in paths:
        with open(p) as f:
            payload = json.load(f)
        for r in payload["trades"]:
            et = pd.Timestamp(r["entry_time"])
            kz = r.get("kill_zone") or _infer_kill_zone(et, r.get("strategy", ""))
            out.append(_TradeRow(
                strategy=r.get("strategy", ""),
                symbol=r.get("symbol", "MNQ"),
                direction=r["direction"],
                entry_time=et,
                exit_time=pd.Timestamp(r["exit_time"]),
                entry_price=float(r["entry_price"]),
                stop_price=float(r["stop_price"]),
                target_price=float(r["target_price"]),
                exit_price=float(r["exit_price"]),
                contracts=int(r["contracts"]),
                pnl=float(r["pnl"]),
                reason=r.get("reason", ""),
                confluence_score=int(r.get("confluence_score", 0) or 0),
                kill_zone=kz,
                duration_bars=0,
            ))
    return sorted(out, key=lambda t: t.entry_time)


def stats(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    sum_w = sum(t.pnl for t in wins)
    sum_l = -sum(t.pnl for t in losses)  # positive
    pf = (sum_w / sum_l) if sum_l > 0 else float("inf")
    avg_w = sum_w / len(wins) if wins else 0.0
    avg_l = (sum_l / len(losses)) if losses else 0.0
    rr = (avg_w / avg_l) if avg_l > 0 else float("inf")
    # equity / dd
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        eq += t.pnl
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    pnl = sum(t.pnl for t in trades)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / n,
        "pnl": pnl,
        "pf": pf,
        "avg_win": avg_w,
        "avg_loss": avg_l,
        "avg_rr": rr,
        "max_dd": max_dd,
    }


def fmt(s: dict, label: str) -> str:
    if s.get("trades", 0) == 0:
        return f"  {label:<25} (0 trades)"
    return (
        f"  {label:<25} "
        f"trades={s['trades']:>4}  "
        f"WR={s['win_rate']*100:>5.1f}%  "
        f"PF={s['pf']:>5.2f}  "
        f"P&L=${s['pnl']:>+10,.0f}  "
        f"avg_rr={s['avg_rr']:>4.2f}:1  "
        f"maxDD=${s['max_dd']:>7,.0f}"
    )


def rolling_combine_attempts(trades: list, starting_balance: float = 50_000.0,
                              target: float = 3_000.0, max_attempts: int = 30) -> dict:
    """Sequential Combine attempts (mirrors scripts/walk_forward_combine._sequential_combine).

    A pass is detected at the FIRST trade whose cumulative balance >= target;
    the next attempt starts the next day. On fail, cut off at breach day, next
    attempt starts the next day."""
    remaining = sorted(trades, key=lambda t: t.entry_time)
    attempts = []

    while remaining and len(attempts) < max_attempts:
        num = len(attempts) + 1
        res = simulate_combine(remaining, starting_balance=starting_balance)
        first_date = remaining[0].entry_time.date()

        if res.passed:
            balance = starting_balance
            target_bal = starting_balance + target
            pass_date = None
            for t in remaining:
                balance += t.pnl
                if balance >= target_bal:
                    pass_date = t.entry_time.date()
                    break
            if pass_date is None:
                pass_date = remaining[-1].entry_time.date()
            cal_days = (pass_date - first_date).days + 1
            attempts.append({
                "attempt": num, "passed": True, "failure": None,
                "pnl": res.total_pnl,
                "days": cal_days,        # calendar days
                "trading_days": res.trading_days,
                "trades": sum(1 for t in remaining if t.entry_time.date() <= pass_date),
            })
            remaining = [t for t in remaining if t.entry_time.date() > pass_date]
        else:
            # Fail: cut off at last day of day_records, continue next day
            day_list = getattr(res, "days", None) or []
            if day_list:
                fail_date = day_list[-1].date
            else:
                fail_date = remaining[-1].entry_time.date()
            cal_days = (fail_date - first_date).days + 1
            attempts.append({
                "attempt": num, "passed": False, "failure": res.failure_reason,
                "pnl": res.total_pnl,
                "days": cal_days,
                "trading_days": res.trading_days,
                "trades": sum(1 for t in remaining if t.entry_time.date() <= fail_date),
            })
            remaining = [t for t in remaining if t.entry_time.date() > fail_date]

    passes = sum(1 for a in attempts if a["passed"])
    pass_days = [a["days"] for a in attempts if a["passed"]]
    return {
        "attempts": attempts,
        "total_attempts": len(attempts),
        "passes": passes,
        "pass_rate": passes / len(attempts) if attempts else 0.0,
        "avg_days_to_pass": sum(pass_days) / len(pass_days) if pass_days else None,
    }


def main(paths: list[str]) -> int:
    trades = load_trades(paths)
    if not trades:
        print("No trades loaded.")
        return 1

    print("=" * 80)
    print(f"Loaded {len(trades)} trades from {len(paths)} file(s)")
    print(f"Period: {trades[0].entry_time} → {trades[-1].entry_time}")
    print("=" * 80)

    # Overall
    print("\n▶ Overall")
    print(fmt(stats(trades), "ALL trades"))

    # Kill zone splits
    print("\n▶ By kill zone")
    by_kz: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_kz[t.kill_zone or "(none)"].append(t)
    for kz in sorted(by_kz.keys()):
        print(fmt(stats(by_kz[kz]), kz))

    # By strategy
    print("\n▶ By strategy")
    by_s: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_s[t.strategy].append(t)
    for s in sorted(by_s.keys()):
        print(fmt(stats(by_s[s]), s))

    # Single Combine
    print("\n▶ Topstep $50K Combine — single run (sequential through full trade list)")
    res = simulate_combine(trades)
    status = "PASSED" if res.passed else f"FAILED ({res.failure_reason})"
    print(f"  {status}   balance=${res.ending_balance:,.2f}   "
          f"pnl=${res.total_pnl:+,.2f}   days={res.trading_days}   trades={res.total_trades}")

    # Rolling attempts
    print("\n▶ Topstep $50K Combine — rolling attempts (up to 30)")
    roll = rolling_combine_attempts(trades)
    print(f"  Pass rate: {roll['passes']}/{roll['total_attempts']}  "
          f"({roll['pass_rate']*100:.1f}%)")
    if roll["avg_days_to_pass"] is not None:
        print(f"  Avg days to pass: {roll['avg_days_to_pass']:.1f}")
    for a in roll["attempts"]:
        mark = "✓" if a["passed"] else "✗"
        reason = "" if a["passed"] else f"  [{a['failure']}]"
        print(f"    {mark} A{a['attempt']:02d}  trades={a['trades']:>3}  "
              f"days={a['days']:>3}  pnl=${a['pnl']:>+8,.0f}{reason}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_trades_json.py <trades.json> [trades2.json ...]")
        sys.exit(1)
    sys.exit(main(sys.argv[1:]))
