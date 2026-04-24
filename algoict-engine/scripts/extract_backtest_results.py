"""
scripts/extract_backtest_results.py
====================================
Parse one or more bt_*.log files (UTF-16 LE encoded by PowerShell Tee)
and print a single markdown table with the key stats.

Usage
-----
    python scripts/extract_backtest_results.py bt_v5_*.log
    python scripts/extract_backtest_results.py bt_v5_*.log bt_v6_*.log
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path
from typing import Optional


# Regex patterns for the lines the backtester prints (see backtest/report.py).
_PATTERNS = {
    "trades":    re.compile(r"Total trades\s*:\s*([\d,]+)"),
    "signals":   re.compile(r"Total signals\s*:\s*([\d,]+)"),
    "win_rate":  re.compile(r"Win rate\s*:\s*([\d.]+)%"),
    # $+10,411.00 or $-41,194.00 — both signs optional and either may appear.
    "pnl":       re.compile(r"Total P&L\s*:\s*\$?([+\-]?[\d,.]+)"),
    "pf":        re.compile(r"Profit factor\s*:\s*([\d.]+)"),
    "avg_pnl":   re.compile(r"Avg P&L/trade\s*:\s*\$?([+\-]?[\d,.]+)"),
    "avg_win":   re.compile(r"Avg win\s*:\s*\$?([+\-]?[\d,.]+)"),
    "avg_loss":  re.compile(r"Avg loss\s*:\s*\$?([+\-]?[\d,.]+)"),
    "duration":  re.compile(r"Backtest Complete \(([\d.]+)s\)"),
    "period":    re.compile(r"Period\s*:\s*([\d-]+\s+[\d:+\-]+)\s*→\s*([\d-]+\s+[\d:+\-]+)"),
    "strategy":  re.compile(r"(\w+)Strategy\s*—\s*Backtest Complete"),
}


def _read_utf16(path: Path) -> str:
    """Read a PowerShell-Tee UTF-16 LE log, with BOM tolerance."""
    data = path.read_bytes()
    # Strip UTF-16 LE BOM if present.
    if data[:2] == b"\xff\xfe":
        data = data[2:]
    try:
        return data.decode("utf-16-le", errors="replace")
    except Exception:
        return data.decode("utf-8", errors="replace")


def _num(text: str) -> float:
    # Accept +/- leading sign explicitly (re captures it as part of match).
    t = text.replace(",", "").strip()
    # A bare "+" is not a valid float — strip it. Keep "-".
    if t.startswith("+"):
        t = t[1:]
    return float(t)


def parse_log(path: Path) -> Optional[dict]:
    """Return a dict of stats, or None if log didn't complete."""
    content = _read_utf16(path)
    if "Backtest Complete" not in content:
        return None
    out: dict = {"file": path.name}
    for key, pat in _PATTERNS.items():
        m = pat.search(content)
        if not m:
            continue
        if key in ("trades", "signals"):
            out[key] = int(_num(m.group(1)))
        elif key in ("win_rate", "pf", "duration"):
            out[key] = float(m.group(1))
        elif key in ("pnl", "avg_pnl", "avg_win", "avg_loss"):
            # The captured group includes the sign, so we don't multiply.
            out[key] = _num(m.group(1))
        elif key == "period":
            out["period_start"] = m.group(1)
            out["period_end"] = m.group(2)
        elif key == "strategy":
            out[key] = m.group(1)
    return out


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No completed backtests found.")
        return
    print(
        f"| {'File':<30} | {'Strategy':<18} | {'Trades':>7} | "
        f"{'WR%':>5} | {'PF':>5} | {'P&L':>12} | "
        f"{'Avg Win':>9} | {'Avg Loss':>9} | {'Runtime':>8} |"
    )
    print("|" + "-" * 32 + "|" + "-" * 20 + "|" + "-" * 9 + "|"
          + "-" * 7 + "|" + "-" * 7 + "|" + "-" * 14 + "|"
          + "-" * 11 + "|" + "-" * 11 + "|" + "-" * 10 + "|")
    for r in rows:
        pnl = r.get("pnl", 0)
        pnl_str = f"${pnl:+,.0f}"
        aw = r.get("avg_win", 0)
        al = r.get("avg_loss", 0)
        dur = r.get("duration", 0)
        dur_str = f"{dur/60:.1f}min" if dur > 60 else f"{dur:.0f}s"
        print(
            f"| {r['file']:<30} | {r.get('strategy', ''):<18} | "
            f"{r.get('trades', 0):>7} | {r.get('win_rate', 0):>5.1f} | "
            f"{r.get('pf', 0):>5.2f} | {pnl_str:>12} | "
            f"${aw:>+8,.0f} | ${al:>+8,.0f} | {dur_str:>8} |"
        )

    # Aggregate row (sum P&L, total trades, avg PF)
    total_trades = sum(r.get("trades", 0) for r in rows)
    total_pnl = sum(r.get("pnl", 0) for r in rows)
    # Weighted PF by trades (approximation)
    pfs = [r.get("pf", 0) for r in rows if r.get("pf", 0) > 0]
    avg_pf = sum(pfs) / len(pfs) if pfs else 0
    print("|" + "-" * 32 + "|" + "-" * 20 + "|" + "-" * 9 + "|"
          + "-" * 7 + "|" + "-" * 7 + "|" + "-" * 14 + "|"
          + "-" * 11 + "|" + "-" * 11 + "|" + "-" * 10 + "|")
    print(
        f"| {'AGGREGATE':<30} | {'':<18} | "
        f"{total_trades:>7} | {'':>5} | "
        f"{avg_pf:>5.2f} | ${total_pnl:+,.0f}       | "
        f"{'':>9} | {'':>9} | {'':>8} |"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("patterns", nargs="+",
                    help="Log file paths or glob patterns (e.g. bt_v5_*.log)")
    ap.add_argument("--cwd", default=".",
                    help="Base directory for relative globs (default: .)")
    args = ap.parse_args()

    base = Path(args.cwd).resolve()
    files: list[Path] = []
    for pattern in args.patterns:
        matches = list(base.glob(pattern))
        if matches:
            files.extend(matches)
        else:
            # Treat as literal path
            p = (base / pattern).resolve()
            if p.exists():
                files.append(p)
    files = sorted(set(files))
    if not files:
        print(f"No files match: {args.patterns}")
        return 1

    # Filter out sidecar files that never contain backtest results.
    def _is_result_log(p: Path) -> bool:
        name = p.name
        if "_err." in name:
            return False
        if name.endswith("_status.log"):
            return False
        return True
    files = [f for f in files if _is_result_log(f)]

    rows = []
    skipped = []
    for f in files:
        res = parse_log(f)
        if res is None:
            skipped.append(f.name)
        else:
            rows.append(res)

    print_table(rows)

    if skipped:
        print()
        print(f"Incomplete / running ({len(skipped)}):")
        for name in skipped:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
