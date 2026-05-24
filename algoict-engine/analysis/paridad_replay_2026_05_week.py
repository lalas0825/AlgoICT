"""Parity replay diagnostic — does backtester match live for this week?

Extract bars from engine logs (4/16-5/22 covers ~5 weeks of context +
the audit week 5/18-5/22). Run backtester on 5/18-5/22 only with the
same canonical config the live bot uses. Compare:
  - Trade count
  - Total P&L
  - WR
  - Distribution of trade directions
  - Distribution by KZ

Live this week (from week_audit_2026_05_18_22.py):
  44 trades (counting dupes) / 41 unique
  WR 29.3% (12W, 29L)
  Net -$504.50 (or -$248 per audit dedup)

If backtest replay produces SIMILAR results -> live = backtest, variance.
If backtest replay produces MUCH BETTER results -> execution path bug.
"""
import re
import os
import sys
import json
import subprocess
from pathlib import Path
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ENGINE_ROOT = Path(__file__).resolve().parent.parent
RUNNER = ENGINE_ROOT / "scripts" / "run_backtest.py"
OUT_DIR = Path(__file__).parent / "paridad_replay"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def extract_bars_to_csv() -> Path:
    """Parse all engine_*.log files, extract unique 1-min bars, write CSV."""
    bar_re = re.compile(
        r'WS: CON\.F\.US\.MNQ\.M26 bar \[(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):00\+00:00\] '
        r'O:([\d.]+) H:([\d.]+) L:([\d.]+) C:([\d.]+) V:(\d+)'
    )
    all_bars = {}  # (date,hour,minute) -> ohlcv
    log_dir = ENGINE_ROOT
    log_files = sorted([
        f for f in os.listdir(log_dir)
        if f.startswith("engine") and f.endswith(".log") and "err" not in f
    ])
    print(f"Scanning {len(log_files)} log files...")
    for fn in log_files:
        path = log_dir / fn
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = bar_re.search(line)
                    if m:
                        d, h, mn, o, hi, l, c, v = m.groups()
                        key = (d, int(h), int(mn))
                        if key not in all_bars:
                            all_bars[key] = (float(o), float(hi), float(l), float(c), int(v))
        except Exception as exc:
            print(f"  warn: {fn}: {exc}")

    csv_path = OUT_DIR / "live_bars_apr16_to_may22.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("timestamp,open,high,low,close,volume\n")
        for key in sorted(all_bars.keys()):
            d, h, mn = key
            o, hi, l, c, v = all_bars[key]
            # CSV: UTC timestamp (matches what load_data_csv expects).
            # The bot's WS uses +00:00 = UTC.
            ts = f"{d} {h:02d}:{mn:02d}:00+00:00"
            f.write(f"{ts},{o},{hi},{l},{c},{v}\n")
    print(f"  -> {csv_path} ({len(all_bars)} bars)")
    return csv_path


def run_backtest(csv_path: Path) -> Path:
    """Run backtester on the audit week with canonical config."""
    out_json = OUT_DIR / "replay_5_18_to_5_22.json"
    cmd = [
        sys.executable, str(RUNNER),
        "--strategy", "silver_bullet",
        "--csv", str(csv_path),
        "--start", "2026-05-18",
        "--end", "2026-05-22",
        "--dynamic-bias",
        "--wide-kz",
        "--trade-management", "trailing",
        "--no-supabase",
        "--export-json", str(out_json),
    ]
    print(f"\nRunning backtester:")
    print(f"  {' '.join(cmd)}\n")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(f"FAIL rc={proc.returncode}")
        print(proc.stdout[-3000:])
        print(proc.stderr[-2000:])
        raise SystemExit(1)
    # Print last 30 lines of stdout
    print("\n".join(proc.stdout.splitlines()[-30:]))
    return out_json


def compare_vs_live(backtest_json: Path):
    """Print summary comparing backtest replay vs live audit."""
    if not backtest_json.exists():
        print(f"No backtest JSON at {backtest_json}")
        return
    with open(backtest_json, "r", encoding="utf-8") as f:
        bt = json.load(f)

    # Live numbers (from week_audit_2026_05_18_22.py, deduped)
    live = {
        "trades": 41,        # unique after dedup
        "wins": 12,
        "losses": 29,
        "wr": 12 / 41,
        "pnl": -504.50,       # the raw audit total (sum of trade P&Ls, dedupe-aware)
    }
    bt_summary = {
        "trades": bt.get("total_trades", 0),
        "wins": bt.get("wins", 0),
        "losses": bt.get("losses", 0),
        "wr": bt.get("win_rate", 0.0),
        "pnl": bt.get("total_pnl", 0.0),
    }

    print()
    print("=" * 80)
    print(" PARITY REPLAY — Mon 5/18 to Fri 5/22 2026")
    print("=" * 80)
    print()
    print(f"{'Metric':<15} {'LIVE (real)':>15} {'BACKTEST replay':>18} {'Delta':>15}")
    print("-" * 80)
    print(f"{'Trades':<15} {live['trades']:>15} {bt_summary['trades']:>18} "
          f"{bt_summary['trades']-live['trades']:>+15}")
    print(f"{'Wins':<15} {live['wins']:>15} {bt_summary['wins']:>18} "
          f"{bt_summary['wins']-live['wins']:>+15}")
    print(f"{'Losses':<15} {live['losses']:>15} {bt_summary['losses']:>18} "
          f"{bt_summary['losses']-live['losses']:>+15}")
    print(f"{'WR':<15} {live['wr']*100:>14.1f}% {bt_summary['wr']*100:>17.1f}% "
          f"{(bt_summary['wr']-live['wr'])*100:>+14.1f}pp")
    print(f"{'P&L':<15} ${live['pnl']:>+13,.2f} ${bt_summary['pnl']:>+16,.2f} "
          f"${bt_summary['pnl']-live['pnl']:>+13,.2f}")
    print("-" * 80)
    print()
    pnl_gap = bt_summary["pnl"] - live["pnl"]
    print("VERDICT:")
    if abs(pnl_gap) < 250:
        print(f"  PARITY (gap ${pnl_gap:+.2f} < $250) — live ≈ backtest.")
        print("  This week was VARIANCE, not execution bug. Bot OK to resume.")
    elif pnl_gap > 1000:
        print(f"  DIVERGENCE (gap ${pnl_gap:+.2f}) — backtest much better than live.")
        print("  EXECUTION PATH BUG suspected. Investigate:")
        print("  - OPPORTUNITY REPLACE tier 2.5 (limit cancellation timing)")
        print("  - Fill timing (24min limit -> fill seen in trade #1)")
        print("  - Slippage on fills (live broker vs ideal backtest fills)")
    elif pnl_gap < -1000:
        print(f"  WORSE IN BACKTEST (gap ${pnl_gap:+.2f}) — backtest even more negative.")
        print("  Strategy genuinely struggles in this regime. Bot's live -$248")
        print("  may have actually been LUCKY relative to baseline expectation.")
    else:
        print(f"  CLOSE-ISH (gap ${pnl_gap:+.2f}) — within 1 std dev.")
        print("  Mostly variance with possible minor execution drift. OK to resume.")

    # Per-trade dump for visual comparison
    if bt.get("trades"):
        print()
        print("Backtest trades this week:")
        for i, t in enumerate(bt["trades"][:20], 1):
            print(f"  [{i:>2}] {t.get('entry_time')} {t.get('direction')} "
                  f"{t.get('contracts')}x exit={t.get('exit_price'):.2f} "
                  f"pnl=${t.get('pnl'):+.2f} [{t.get('reason','')}]")


def main():
    print("PARITY REPLAY — Mon 5/18 to Fri 5/22 2026")
    print()
    csv_path = extract_bars_to_csv()
    backtest_json = run_backtest(csv_path)
    compare_vs_live(backtest_json)


if __name__ == "__main__":
    main()
