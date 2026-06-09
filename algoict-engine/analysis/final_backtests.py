"""Final backtests requested 2026-06-08:
  1. Combine $50K pass rate with current shipped config (--combine-reset-on-breach)
  2. Late-session cutoff A/B (SB_LATE_SESSION_CUTOFF ON=current vs OFF)
All runs use the current config: wide-kz + dynamic-bias + trailing + carry(default).
"""
import json, subprocess, sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
RUNNER = ENGINE / "scripts" / "run_backtest.py"
DATA = ENGINE.parent / "data" / "mnq_1min.csv"
OUT = Path(__file__).parent / "final_backtests"
OUT.mkdir(parents=True, exist_ok=True)
YEARS = [("2023", "2023-01-01", "2023-12-31"),
         ("2024", "2024-01-01", "2024-12-31"),
         ("2025", "2025-01-01", "2025-12-31")]

def run(tag, start, end, extra=None):
    out = OUT / f"{tag}.json"
    cmd = [sys.executable, str(RUNNER), "--strategy", "silver_bullet",
           "--csv", str(DATA), "--start", start, "--end", end,
           "--dynamic-bias", "--wide-kz", "--trade-management", "trailing",
           "--no-supabase", "--export-json", str(out)]
    if extra:
        cmd += extra
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        print(f"  FAIL {tag} rc={p.returncode}\n{p.stderr[-900:]}", flush=True)
        return None
    return json.load(open(out, encoding="utf-8"))

# ===== 1. COMBINE PASS RATE =====
print("="*72)
print("1. COMBINE SIMULATOR — $50K pass rate (current shipped config)")
print("="*72, flush=True)
tot_p = tot_f = 0
for y, s, e in YEARS:
    d = run(f"combine_{y}", s, e, ["--combine-reset-on-breach"])
    if not d:
        continue
    p_, f_ = d.get("combine_passes", 0), d.get("combine_fails", 0)
    pr = d.get("combine_pass_rate", 0); pr = pr*100 if pr <= 1 else pr
    tot_p += p_; tot_f += f_
    print(f"  {y}: passes={p_} fails={f_} pass_rate={pr:.1f}% | pnl=${d['total_pnl']:,.0f}", flush=True)
if tot_p + tot_f:
    print(f"  3-YR: {tot_p} passes / {tot_p+tot_f} attempts = {100*tot_p/(tot_p+tot_f):.1f}% pass rate")

# ===== 2. LATE-CUTOFF A/B =====
print("\n" + "="*72)
print("2. LATE-SESSION CUTOFF A/B — cutoff ON (current) vs OFF")
print("="*72, flush=True)
ab = at = 0.0
for y, s, e in YEARS:
    base = run(f"cut_on_{y}", s, e)                                             # cutoff ON (current)
    treat = run(f"cut_off_{y}", s, e, ["--config-override", "SB_LATE_SESSION_CUTOFF=False"])
    if not base or not treat:
        continue
    bp, tp = base["total_pnl"], treat["total_pnl"]
    ab += bp; at += tp
    print(f"  {y}: ON ${bp:>10,.0f} | OFF ${tp:>10,.0f} | delta ${tp-bp:>+9,.0f} ({100*(tp-bp)/bp:+.1f}%) "
          f"| trades {base['total_trades']}->{treat['total_trades']}", flush=True)
d = at - ab
print(f"  AGG: ON ${ab:,.0f} | OFF ${at:,.0f} | delta ${d:+,.0f} ({100*d/ab:+.1f}%)")
print(f"  >>> {'cutoff COSTS money (OFF better) — reconsider/tune' if d > 100 else 'cutoff ~free or helps — keep the safety'}")
