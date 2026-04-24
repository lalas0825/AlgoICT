"""
Verify the 2026-04-23 PWH/PDH forming-bar fix with a synthetic scenario
that reproduces the bug:

Given:
  Mon Apr 13 - Fri Apr 17 (previous week) = high 26,883, low 24,915
  Mon Apr 20 - Thu Apr 23 partial (current forming week) = contains
    overnight spike to 27,138 on Apr 22 Tuesday afternoon

Expected behavior:
  WITHOUT as_of_ts: bot returns PWH = 27,138 (OLD BUG — forming week)
  WITH as_of_ts    : bot returns PWH = 26,883 (FIXED — previous week)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from detectors.liquidity import LiquidityDetector


def _make_weekly(frames):
    """Build a weekly aggregated DataFrame from tuples:
    (monday_date_str, open, high, low, close, volume)
    """
    rows = []
    idx = []
    for monday, o, h, lo, c, v in frames:
        idx.append(pd.Timestamp(monday, tz="America/Chicago"))
        rows.append({"open": o, "high": h, "low": lo, "close": c, "volume": v})
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="ts_event"))
    return df


def _make_daily(frames):
    rows = []
    idx = []
    for date, o, h, lo, c, v in frames:
        idx.append(pd.Timestamp(date, tz="America/Chicago"))
        rows.append({"open": o, "high": h, "low": lo, "close": c, "volume": v})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="ts_event"))


def main():
    # Weekly bars: prev (Apr 13) completed + current (Apr 20) forming
    df_weekly = _make_weekly([
        # Previous completed week: Mon Apr 13 - Fri Apr 17 closing 26,842
        ("2026-04-13", 25004.25, 26883.00, 24914.50, 26842.00, 2000000),
        # Current forming week: Mon Apr 20 - (partial, only through Thu Apr 23)
        # Contains the outlier spike to 27,138 that polluted PWH
        ("2026-04-20", 26855.00, 27138.00, 26556.00, 26967.00,  900000),
    ])

    # Daily bars: several days leading up to today
    df_daily = _make_daily([
        ("2026-04-17", 26400.00, 26883.00, 26100.00, 26842.00, 500000),   # prev Fri
        ("2026-04-20", 26855.00, 26900.00, 26600.00, 26700.00, 400000),   # Mon
        ("2026-04-21", 26700.00, 26950.00, 26670.00, 26920.00, 450000),   # Tue
        ("2026-04-22", 26920.00, 27138.00, 26870.00, 26967.00, 500000),   # Wed (includes spike)
        ("2026-04-23", 26967.00, 27010.00, 26850.00, 26980.00, 200000),   # Thu (forming)
    ])

    det = LiquidityDetector()

    # Current clock: Thursday 2026-04-23 04:30 CT (inside current forming
    # day + week)
    as_of = pd.Timestamp("2026-04-23 04:30:00", tz="America/Chicago")

    print("=" * 72)
    print("TEST 1: Weekly — expect previous week high (26,883), NOT current (27,138)")
    print("=" * 72)
    pwh_buggy, pwl_buggy = det.get_pwh_pwl(df_weekly)  # old behavior
    pwh_fixed, pwl_fixed = det.get_pwh_pwl(df_weekly, as_of_ts=as_of)
    print(f"  Buggy (no as_of_ts):  PWH=${pwh_buggy:,.2f} PWL=${pwl_buggy:,.2f}  <-- forming week")
    print(f"  Fixed (as_of_ts=NOW): PWH=${pwh_fixed:,.2f} PWL=${pwl_fixed:,.2f}  <-- previous week")
    assert abs(pwh_buggy - 27138.00) < 0.01, "buggy PWH should be 27,138"
    assert abs(pwh_fixed - 26883.00) < 0.01, f"fixed PWH should be 26,883, got {pwh_fixed}"
    assert abs(pwl_fixed - 24914.50) < 0.01, f"fixed PWL should be 24,914.50, got {pwl_fixed}"
    print("  [OK] Weekly fix correct")
    print()

    print("=" * 72)
    print("TEST 2: Daily — expect yesterday's session high (27,138), NOT today's")
    print("=" * 72)
    pdh_buggy, pdl_buggy = det.get_pdh_pdl(df_daily)
    pdh_fixed, pdl_fixed = det.get_pdh_pdl(df_daily, as_of_ts=as_of)
    print(f"  Buggy (no as_of_ts):  PDH=${pdh_buggy:,.2f} PDL=${pdl_buggy:,.2f}  <-- today's forming high")
    print(f"  Fixed (as_of_ts=NOW): PDH=${pdh_fixed:,.2f} PDL=${pdl_fixed:,.2f}  <-- yesterday")
    # Note: in the mock data "today's session" as bot computes = today + 6h shift
    # = 2026-04-23 04:30 + 6h = 2026-04-23 10:30 -> date 2026-04-23
    # Expect fixed PDH to be 2026-04-22's high = 27,138 (spike day)
    assert abs(pdh_fixed - 27138.00) < 0.01, f"fixed PDH should be 27,138 (Apr 22's H), got {pdh_fixed}"
    print("  [OK] Daily fix correct")
    print()

    print("=" * 72)
    print("TEST 3: build_key_levels end-to-end with both daily + weekly")
    print("=" * 72)
    levels = det.build_key_levels(
        df_daily=df_daily, df_weekly=df_weekly, as_of_ts=as_of,
    )
    for lvl in levels:
        print(f"  {lvl.type}: ${lvl.price:,.2f}")

    pdh_l = next(l for l in levels if l.type == "PDH")
    pwh_l = next(l for l in levels if l.type == "PWH")
    assert abs(pdh_l.price - 27138.00) < 0.01
    assert abs(pwh_l.price - 26883.00) < 0.01
    print("  [OK] All key levels correct after fix")
    print()

    print("=" * 72)
    print("TEST 4: Backward compat — no as_of_ts reproduces legacy behavior")
    print("=" * 72)
    legacy = det.build_key_levels(df_daily=df_daily, df_weekly=df_weekly)
    pwh_legacy = next(l for l in legacy if l.type == "PWH")
    assert abs(pwh_legacy.price - 27138.00) < 0.01
    print(f"  PWH without as_of_ts = ${pwh_legacy.price:,.2f} (legacy, forming bar)")
    print("  [OK] Backtester backward-compat maintained")
    print()

    print("All fix tests passed. Safe to redeploy.")


if __name__ == "__main__":
    main()
