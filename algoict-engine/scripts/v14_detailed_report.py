"""
v14 detailed walk-forward report with full per-year + per-KZ + monthly stats.

Loads `analysis/sb_v14_<year>.json` for all 7 years (2019-2025) and prints:
  1. Per-year deep stats (trades, WR, P&L, PF, avg win/loss, streaks, DD)
  2. Per-KZ breakdown across all years (London/NY AM/NY PM)
  3. Monthly P&L matrix (84 months across 7 years)
  4. Distribution of outcomes (hit rate by month, by day)
  5. Equity curve + drawdown timing per year
  6. v14 vs v8 baseline comparison

Usage:  python scripts/v14_detailed_report.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent

# v8 baseline from CLAUDE.md (2026-04-24 snapshot)
V8_BASELINE = {
    2019: {"trades": 2110, "wr": 0.431, "pnl": 70028, "pf": 1.68, "dd": 3030, "resets": 10},
    2020: {"trades": 2049, "wr": 0.437, "pnl": 92203, "pf": 1.84, "dd": 5813, "resets": 10},
    2021: {"trades": 1916, "wr": 0.407, "pnl": 110598, "pf": 2.06, "dd": 5790, "resets": 12},
    2022: {"trades": 2101, "wr": 0.448, "pnl": 103804, "pf": 2.01, "dd": 3810, "resets": 8},
    2023: {"trades": 1991, "wr": 0.453, "pnl": 91062, "pf": 1.88, "dd": 4261, "resets": 8},
    2024: {"trades": 2067, "wr": 0.441, "pnl": 115547, "pf": 2.05, "dd": 3864, "resets": 7},
    2025: {"trades": 1952, "wr": 0.449, "pnl": 89759, "pf": 1.86, "dd": 3032, "resets": 9},
}


def load_year(year: int) -> dict | None:
    if year == 2025:
        path = ENGINE_ROOT / "analysis" / "sb_v14_2025_full.json"
    else:
        path = ENGINE_ROOT / "analysis" / f"sb_v14_{year}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def deep_metrics(d: dict) -> dict:
    trades = d.get("trades", [])
    if not trades:
        return {}
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    scratches = [t for t in trades if t["pnl"] == 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    # Streaks
    max_win_streak = max_loss_streak = cur_w = cur_l = 0
    for t in trades:
        if t["pnl"] > 0:
            cur_w += 1; cur_l = 0
            max_win_streak = max(max_win_streak, cur_w)
        elif t["pnl"] < 0:
            cur_l += 1; cur_w = 0
            max_loss_streak = max(max_loss_streak, cur_l)
        else:
            cur_w = cur_l = 0

    # Largest individual win/loss
    largest_win = max((t["pnl"] for t in wins), default=0)
    largest_loss = min((t["pnl"] for t in losses), default=0)

    # Daily aggregation
    daily_pnl = defaultdict(float)
    daily_trades = defaultdict(int)
    for t in trades:
        day = t["exit_time"][:10]
        daily_pnl[day] += t["pnl"]
        daily_trades[day] += 1
    pos_days = sum(1 for v in daily_pnl.values() if v > 0)
    neg_days = sum(1 for v in daily_pnl.values() if v < 0)
    flat_days = sum(1 for v in daily_pnl.values() if v == 0)
    total_days = len(daily_pnl)
    daily_hit_rate = pos_days / total_days * 100 if total_days else 0
    best_day = max(daily_pnl.values(), default=0)
    worst_day = min(daily_pnl.values(), default=0)

    # Monthly aggregation
    monthly_pnl = defaultdict(float)
    monthly_count = defaultdict(int)
    monthly_wins = defaultdict(int)
    for t in trades:
        m = t["exit_time"][:7]
        monthly_pnl[m] += t["pnl"]
        monthly_count[m] += 1
        if t["pnl"] > 0:
            monthly_wins[m] += 1
    pos_months = sum(1 for v in monthly_pnl.values() if v > 0)
    neg_months = sum(1 for v in monthly_pnl.values() if v < 0)
    monthly_hit_rate = pos_months / len(monthly_pnl) * 100 if monthly_pnl else 0

    # KZ split
    kz_pnl = defaultdict(float)
    kz_count = defaultdict(int)
    kz_wins = defaultdict(int)
    for t in trades:
        kz = t.get("kill_zone", "?")
        kz_pnl[kz] += t["pnl"]
        kz_count[kz] += 1
        if t["pnl"] > 0: kz_wins[kz] += 1

    return {
        "trades": len(trades),
        "wins": len(wins), "losses": len(losses), "scratches": len(scratches),
        "wr": d.get("win_rate", 0),
        "pnl": d.get("total_pnl", 0),
        "pf": pf,
        "dd": d.get("max_drawdown_dollars", 0),
        "resets": d.get("combine_resets", 0),
        "gross_win": gross_win, "gross_loss": gross_loss,
        "avg_win": gross_win / len(wins) if wins else 0,
        "avg_loss": gross_loss / len(losses) if losses else 0,
        "largest_win": largest_win, "largest_loss": largest_loss,
        "max_win_streak": max_win_streak, "max_loss_streak": max_loss_streak,
        "trading_days": total_days,
        "pos_days": pos_days, "neg_days": neg_days, "flat_days": flat_days,
        "daily_hit_rate": daily_hit_rate,
        "best_day": best_day, "worst_day": worst_day,
        "monthly_pnl": dict(monthly_pnl),
        "monthly_count": dict(monthly_count),
        "monthly_wins": dict(monthly_wins),
        "pos_months": pos_months, "neg_months": neg_months,
        "monthly_hit_rate": monthly_hit_rate,
        "kz_pnl": dict(kz_pnl), "kz_count": dict(kz_count), "kz_wins": dict(kz_wins),
        "expectancy": d.get("total_pnl", 0) / len(trades) if trades else 0,
    }


def expected_value_per_trade(m: dict) -> float:
    """E[pnl] = P(win)*avg_win - P(loss)*avg_loss"""
    if m["trades"] == 0:
        return 0
    pw = m["wins"] / m["trades"]
    pl = m["losses"] / m["trades"]
    return pw * m["avg_win"] - pl * m["avg_loss"]


def main() -> int:
    years = sorted(V8_BASELINE.keys())
    yearly = {}
    for year in years:
        d = load_year(year)
        if d is None:
            continue
        yearly[year] = deep_metrics(d)

    if not yearly:
        print("No v14 results found.")
        return 1

    print("=" * 100)
    print("v14 SILVER BULLET - 7-YEAR DETAILED WALK-FORWARD REPORT (2019-2025)")
    print("=" * 100)
    print()

    # ---------- 1. Per-year deep stats ----------
    print("## 1. Per-year stats")
    print()
    print(f"{'Year':<6}{'Trades':>8}{'WR':>8}{'PnL':>14}{'PF':>7}{'AvgW':>8}"
          f"{'AvgL':>8}{'BiggestW':>10}{'BiggestL':>10}{'WStrk':>7}{'LStrk':>7}"
          f"{'MaxDD':>9}{'Resets':>8}")
    for year, m in yearly.items():
        print(
            f"{year:<6}{m['trades']:>8,}{m['wr']*100:>7.1f}%"
            f"${m['pnl']:>+12,.0f}{m['pf']:>7.2f}"
            f"${m['avg_win']:>7.0f}${m['avg_loss']:>7.0f}"
            f"${m['largest_win']:>9,.0f}${m['largest_loss']:>9,.0f}"
            f"{m['max_win_streak']:>7}{m['max_loss_streak']:>7}"
            f"${m['dd']:>7,.0f}{m['resets']:>8}"
        )
    # Aggregate row
    total_trades = sum(m["trades"] for m in yearly.values())
    total_pnl = sum(m["pnl"] for m in yearly.values())
    total_resets = sum(m["resets"] for m in yearly.values())
    mean_wr = sum(m["wr"] for m in yearly.values()) / len(yearly)
    mean_pf = sum(m["pf"] for m in yearly.values()) / len(yearly)
    avg_dd = sum(m["dd"] for m in yearly.values()) / len(yearly)
    print("-" * 100)
    print(
        f"{'AGG':<6}{total_trades:>8,}{mean_wr*100:>7.1f}%"
        f"${total_pnl:>+12,.0f}{mean_pf:>7.2f}"
        f"{'':<8}{'':<8}{'':<10}{'':<10}{'':<7}{'':<7}"
        f"${avg_dd:>7,.0f}{total_resets:>8}"
    )
    print()

    # ---------- 2. Daily/Monthly hit rates ----------
    print("## 2. Consistency metrics")
    print()
    print(f"{'Year':<6}{'TradingDays':>12}{'Pos':>5}{'Neg':>5}{'Flat':>5}"
          f"{'DailyHit%':>11}{'BestDay':>10}{'WorstDay':>10}"
          f"{'PosMo':>7}{'NegMo':>7}{'MoHit%':>8}")
    for year, m in yearly.items():
        print(
            f"{year:<6}{m['trading_days']:>12}"
            f"{m['pos_days']:>5}{m['neg_days']:>5}{m['flat_days']:>5}"
            f"{m['daily_hit_rate']:>10.1f}%"
            f"${m['best_day']:>+9,.0f}${m['worst_day']:>+9,.0f}"
            f"{m['pos_months']:>7}{m['neg_months']:>7}"
            f"{m['monthly_hit_rate']:>7.1f}%"
        )
    print()

    # ---------- 3. KZ split per year ----------
    print("## 3. Per-KZ breakdown by year")
    print()
    print(f"{'Year':<6}{'London':>30}{'NY AM':>30}{'NY PM':>30}")
    print(f"{'':<6}{'(trd / WR / P&L)':>30}{'(trd / WR / P&L)':>30}{'(trd / WR / P&L)':>30}")
    for year, m in yearly.items():
        cells = []
        for kz in ("london", "ny_am", "ny_pm"):
            n = m["kz_count"].get(kz, 0)
            if n == 0:
                cells.append("---")
                continue
            wr = m["kz_wins"].get(kz, 0) / n * 100
            pnl = m["kz_pnl"].get(kz, 0)
            cells.append(f"{n:>4d} / {wr:4.1f}% / ${pnl:>+8,.0f}")
        print(f"{year:<6}{cells[0]:>30}{cells[1]:>30}{cells[2]:>30}")
    # Aggregate KZ
    agg_kz_pnl = defaultdict(float); agg_kz_count = defaultdict(int); agg_kz_wins = defaultdict(int)
    for m in yearly.values():
        for kz in ("london", "ny_am", "ny_pm"):
            agg_kz_pnl[kz] += m["kz_pnl"].get(kz, 0)
            agg_kz_count[kz] += m["kz_count"].get(kz, 0)
            agg_kz_wins[kz] += m["kz_wins"].get(kz, 0)
    cells = []
    for kz in ("london", "ny_am", "ny_pm"):
        n = agg_kz_count[kz]
        wr = agg_kz_wins[kz] / n * 100 if n else 0
        pnl = agg_kz_pnl[kz]
        cells.append(f"{n:>4d} / {wr:4.1f}% / ${pnl:>+9,.0f}")
    print("-" * 96)
    print(f"{'AGG':<6}{cells[0]:>30}{cells[1]:>30}{cells[2]:>30}")
    print()

    # ---------- 4. Monthly P&L matrix ----------
    print("## 4. Monthly P&L matrix ($)")
    print()
    print(f"{'Month':<6}", end="")
    for year in years:
        print(f"{year:>10}", end="")
    print(f"{'AVG':>10}{'#Pos':>6}")
    months_order = [f"{i:02d}" for i in range(1, 13)]
    for mo in months_order:
        row_pnls = []
        for year in years:
            key = f"{year}-{mo}"
            v = yearly.get(year, {}).get("monthly_pnl", {}).get(key, None)
            row_pnls.append(v)
        present = [v for v in row_pnls if v is not None]
        avg = sum(present) / len(present) if present else 0
        n_pos = sum(1 for v in present if v > 0)
        cells = []
        for v in row_pnls:
            if v is None:
                cells.append("---")
            elif v > 0:
                cells.append(f"+{v:>8,.0f}")
            else:
                cells.append(f"{v:>9,.0f}")
        print(f"{mo:<6}", end="")
        for c in cells:
            print(f"{c:>10}", end="")
        avg_str = f"+{avg:,.0f}" if avg > 0 else f"{avg:,.0f}"
        print(f"{avg_str:>10}{n_pos:>3}/{len(present):<2}")
    # Yearly totals row
    print("-" * 100)
    print(f"{'TOT':<6}", end="")
    for year in years:
        v = yearly.get(year, {}).get("pnl", 0)
        sign = "+" if v >= 0 else ""
        print(f"{sign + format(v, ',.0f'):>10}", end="")
    print()
    print()

    # ---------- 5. Expected value + risk metrics ----------
    print("## 5. Expected value + risk profile (per trade)")
    print()
    print(f"{'Year':<6}{'E[$]':>10}{'AvgWin':>10}{'AvgLoss':>10}{'W:L':>8}"
          f"{'GrossW':>14}{'GrossL':>14}{'NetExp':>14}")
    for year, m in yearly.items():
        ev = expected_value_per_trade(m)
        wl_ratio = (m["avg_win"] / m["avg_loss"]) if m["avg_loss"] > 0 else 0
        print(
            f"{year:<6}${ev:>+9,.2f}"
            f"${m['avg_win']:>+9,.2f}${-m['avg_loss']:>+9,.2f}"
            f"{wl_ratio:>7.2f}"
            f"${m['gross_win']:>+12,.0f}${-m['gross_loss']:>+12,.0f}"
            f"${m['expectancy']:>+12,.2f}"
        )
    print()

    # ---------- 6. v14 vs v8 comparison ----------
    print("## 6. v14 vs v8 baseline (CLAUDE.md)")
    print()
    print(f"{'Year':<6}{'v14 P&L':>12}{'v8 P&L':>12}{'D P&L':>10}"
          f"{'v14 WR':>8}{'v8 WR':>8}{'D WR':>8}"
          f"{'v14 DD':>10}{'v8 DD':>10}{'D DD':>10}"
          f"{'v14 Rst':>8}{'v8 Rst':>8}")
    for year, m in yearly.items():
        v8 = V8_BASELINE.get(year, {})
        d_pnl = m["pnl"] - v8.get("pnl", 0)
        d_wr = (m["wr"] - v8.get("wr", 0)) * 100
        d_dd = m["dd"] - v8.get("dd", 0)
        print(
            f"{year:<6}"
            f"${m['pnl']:>+10,.0f}${v8.get('pnl', 0):>+10,.0f}${d_pnl:>+8,.0f}"
            f"{m['wr']*100:>7.1f}%{v8.get('wr', 0)*100:>7.1f}%{d_wr:>+7.1f}"
            f"${m['dd']:>8,.0f}${v8.get('dd', 0):>8,.0f}${d_dd:>+8,.0f}"
            f"{m['resets']:>8}{v8.get('resets', 0):>8}"
        )
    v8_pnl_total = sum(V8_BASELINE[y].get("pnl", 0) for y in yearly)
    v8_resets_total = sum(V8_BASELINE[y].get("resets", 0) for y in yearly)
    v8_dd_avg = sum(V8_BASELINE[y].get("dd", 0) for y in yearly) / len(yearly)
    v8_wr_mean = sum(V8_BASELINE[y].get("wr", 0) for y in yearly) / len(yearly)
    print("-" * 110)
    print(
        f"{'TOT':<6}"
        f"${total_pnl:>+10,.0f}${v8_pnl_total:>+10,.0f}${total_pnl - v8_pnl_total:>+8,.0f}"
        f"{mean_wr*100:>7.1f}%{v8_wr_mean*100:>7.1f}%{(mean_wr - v8_wr_mean)*100:>+7.1f}"
        f"${avg_dd:>8,.0f}${v8_dd_avg:>8,.0f}${avg_dd - v8_dd_avg:>+8,.0f}"
        f"{total_resets:>8}{v8_resets_total:>8}"
    )

    # ---------- 7. Combine survival check ----------
    print()
    print("## 7. Topstep $50K Combine survival analysis")
    print()
    print("Combine rules: Start $50K, target $53K (+$3K), MLL $2K trailing,")
    print("DLL $1K daily, min 5 trading days, consistency rule.")
    print()
    print(f"{'Year':<6}{'Trades':>8}{'TotalP&L':>12}{'MaxDD':>8}{'Resets':>8}"
          f"{'WeeklyAvg':>12}{'DaysToTarget':>14}")
    for year, m in yearly.items():
        weekly_avg = m["pnl"] / 52
        # Approx days to hit $3K target at expectancy
        ev = expected_value_per_trade(m)
        trades_per_day = m["trades"] / m["trading_days"] if m["trading_days"] else 1
        daily_pnl_est = ev * trades_per_day
        days_to_3k = 3000 / daily_pnl_est if daily_pnl_est > 0 else 999
        print(
            f"{year:<6}{m['trades']:>8,}${m['pnl']:>+10,.0f}"
            f"${m['dd']:>6,.0f}{m['resets']:>8}"
            f"${weekly_avg:>10,.0f}{days_to_3k:>12.1f}d"
        )

    print()
    print("=" * 100)
    print("END OF REPORT")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
