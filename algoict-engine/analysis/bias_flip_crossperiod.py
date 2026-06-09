"""A/B: Tier 1.5 bias-flip auto-cancel (opposite 5min CHoCH/MSS) ON vs OFF.
Cross-period 2023/24/25, current shipped config (carry ON, late-cutoff ON).

Motivated by live 6/9: the cancel fired on a fakeout CHoCH-bear wick (price
then rallied +66pts). It's the ONE cancel that still kills limits under
KZ-carry — does removing it net positive cross-period?
"""
import json, subprocess, sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
RUNNER = ENGINE / "scripts" / "run_backtest.py"
DATA = ENGINE.parent / "data" / "mnq_1min.csv"
OUT = Path(__file__).parent / "bias_flip_crossperiod"
OUT.mkdir(parents=True, exist_ok=True)
YEARS = [("2023", "2023-01-01", "2023-12-31"),
         ("2024", "2024-01-01", "2024-12-31"),
         ("2025", "2025-01-01", "2025-12-31")]

def run(year, start, end, cancel_off):
    out = OUT / f"{year}_{'off' if cancel_off else 'on'}.json"
    cmd = [sys.executable, str(RUNNER), "--strategy", "silver_bullet",
           "--csv", str(DATA), "--start", start, "--end", end,
           "--dynamic-bias", "--wide-kz", "--trade-management", "trailing",
           "--no-supabase", "--export-json", str(out)]
    if cancel_off:
        cmd += ["--config-override", "SB_BIAS_FLIP_CANCEL=False"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        print(f"  FAIL {year} off={cancel_off}\n{p.stderr[-900:]}", flush=True)
        return None
    return json.load(open(out, encoding="utf-8"))

print(f"{'BIAS-FLIP CANCEL (Tier 1.5) A/B — ON (current) vs OFF':^72}")
print("=" * 72, flush=True)
a_on = a_off = 0.0
for year, s, e in YEARS:
    on = run(year, s, e, False)
    off = run(year, s, e, True)
    if not on or not off:
        continue
    op, fp = on["total_pnl"], off["total_pnl"]
    a_on += op; a_off += fp
    print(f"  {year}: ON ${op:>10,.0f} ({on['total_trades']} tr) | OFF ${fp:>10,.0f} "
          f"({off['total_trades']} tr) | delta ${fp-op:>+9,.0f} ({100*(fp-op)/op:+.1f}%)", flush=True)
d = a_off - a_on
print("=" * 72)
print(f"AGG: ON ${a_on:,.0f} | OFF ${a_off:,.0f} | delta ${d:+,.0f} ({100*d/a_on:+.1f}%)")
print(f">>> {'DISABLE the bias-flip cancel — OFF wins cross-period' if d > 0 else 'KEEP it — cancel ON is correct'}")
