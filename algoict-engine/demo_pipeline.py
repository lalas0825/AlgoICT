"""
demo_pipeline.py — Full backtest audit → combine → report pipeline demo.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from backtest.backtester import Trade
from backtest.risk_audit import audit_trades
from backtest.combine_simulator import simulate_combine
from backtest.report import generate_report
import config

# ─────────────────────────────────────────────────────────────────────────
# Generate synthetic trades that PASS all rules
# ─────────────────────────────────────────────────────────────────────────

def generate_demo_trades():
    """Create 30 synthetic trades across 6 trading days."""
    trades = []
    base_date = pd.Timestamp("2024-01-01", tz="America/Chicago")
    
    # 5 profitable days + 1 breakeven = pass all rules
    trade_configs = [
        # Day 1: 5 wins
        (1, 9, 30, 500.0, "ny_am"),
        (1, 10, 15, 500.0, "ny_am"),
        (1, 10, 45, 250.0, "silver_bullet"),
        (1, 11, 0, 300.0, "ny_am"),
        (1, 11, 30, 400.0, "ny_am"),
        # Day 2: 4 wins, 1 loss (reset consecutive losses)
        (2, 9, 30, 600.0, "ny_am"),
        (2, 10, 0, -250.0, "ny_am"),
        (2, 10, 30, 450.0, "ny_am"),
        (2, 11, 0, 350.0, "silver_bullet"),
        (2, 13, 30, 500.0, "ny_am"),
        # Day 3: 5 wins
        (3, 9, 30, 550.0, "ny_am"),
        (3, 10, 0, 400.0, "silver_bullet"),
        (3, 10, 30, 500.0, "ny_am"),
        (3, 11, 0, 450.0, "ny_am"),
        (3, 13, 30, 600.0, "ny_am"),
        # Day 4: 5 wins
        (4, 9, 30, 500.0, "ny_am"),
        (4, 10, 0, 350.0, "silver_bullet"),
        (4, 10, 30, 480.0, "ny_am"),
        (4, 11, 0, 520.0, "ny_am"),
        (4, 13, 30, 550.0, "ny_am"),
        # Day 5: 5 wins
        (5, 9, 30, 600.0, "ny_am"),
        (5, 10, 0, 400.0, "silver_bullet"),
        (5, 10, 30, 500.0, "ny_am"),
        (5, 11, 0, 450.0, "ny_am"),
        (5, 13, 30, 500.0, "ny_am"),
        # Day 6: 4 wins, 1 small loss
        (6, 9, 30, 550.0, "ny_am"),
        (6, 10, 0, 350.0, "silver_bullet"),
        (6, 10, 30, -100.0, "ny_am"),
        (6, 11, 0, 500.0, "ny_am"),
        (6, 13, 30, 600.0, "ny_am"),
    ]
    
    for day, hour, minute, pnl, kz in trade_configs:
        entry_time = base_date.replace(day=day, hour=hour, minute=minute)
        exit_time = entry_time + pd.Timedelta(minutes=30)
        
        entry_price = 10000.0 if pnl > 0 else 10001.0
        stop_price = 9999.0
        target_price = 10005.0 if pnl > 0 else 9995.0
        
        trade = Trade(
            strategy="ny_am_reversal" if kz == "ny_am" else "silver_bullet",
            symbol="MNQ",
            direction="long",
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            exit_price=entry_price + (pnl / 250),
            contracts=25,
            pnl=pnl,
            reason="target" if pnl > 0 else "stop",
            confluence_score=9,
            duration_bars=30,
        )
        trade.kill_zone = kz
        trades.append(trade)
    
    return trades


if __name__ == "__main__":
    print("=" * 70)
    print("  AlgoICT Backtest Pipeline Demo")
    print("=" * 70)
    
    trades = generate_demo_trades()
    print(f"\n[OK] Generated {len(trades)} synthetic trades")
    
    print("\n" + "-" * 70)
    print("STEP 1: Risk Audit")
    print("-" * 70)
    audit = audit_trades(trades)
    status = "CLEAN [PASS]" if audit.is_clean else f"VIOLATIONS ({audit.violation_count}) [FAIL]"
    print(f"Status: {status}")
    
    print("\n" + "-" * 70)
    print("STEP 2: Topstep $50K Combine Simulation")
    print("-" * 70)
    combine = simulate_combine(trades)
    status = "PASSED [OK]" if combine.passed else f"FAILED: {combine.failure_reason}"
    print(f"Status:          {status}")
    print(f"Start balance:   ${combine.starting_balance:,.2f}")
    print(f"End balance:     ${combine.ending_balance:,.2f}")
    print(f"Total P&L:       ${combine.total_pnl:+,.2f}")
    print(f"Trading days:    {combine.trading_days}")
    print(f"Target:          ${combine.profit_target:,.2f}")
    if combine.best_day_date:
        print(f"Best day:        ${combine.best_day_pnl:+.2f} on {combine.best_day_date}")
    
    print("\n" + "-" * 70)
    print("STEP 3: Performance Report")
    print("-" * 70)
    report = generate_report(trades, combine_result=combine)
    print(report)
    
    print("=" * 70)
    print("  Demo complete!")
    print("=" * 70)
