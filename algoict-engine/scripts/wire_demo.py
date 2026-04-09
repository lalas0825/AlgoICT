"""
scripts/wire_demo.py
=====================
End-to-end demonstration of the M10 engine wiring.

What this script does
---------------------
1. Builds a SupabaseLabClient from .env
2. Inserts 3 synthetic trades
3. Inserts a synthetic backtest_results row
4. Inserts 2 synthetic market_levels (FVG + Call Wall)
5. Inserts a synthetic strategy_candidate with gate results
6. Inserts a synthetic post_mortem referencing one of the trades
7. Spins up a BotStateSync loop for ~12 seconds, writing live state
   changes every 2 seconds (so you can watch the dashboard update)
8. Cleans up all test data at the end (except bot_state, which is
   left in its final "demo finished" state)

Run
---
    cd algoict-engine
    python scripts/wire_demo.py

Make sure the dashboard is open at http://localhost:3000 in another
window so you can WATCH the state changes happen in real time.

This is not a test suite — it's a manual integration smoke test. Use
``tests/test_supabase_lab_client.py`` + ``tests/test_state_sync.py``
for automated coverage.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Make sibling modules importable when run as a script
ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from db.supabase_lab_client import get_lab_client  # noqa: E402
from core.state_sync import BotStateSync  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("wire_demo")


DEMO_PREFIX = f"demo-{uuid.uuid4().hex[:8]}"


# ─── Synthetic data builders ─────────────────────────────────────────────

def make_trade(idx: int, pnl: float, direction: str = "long") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"{DEMO_PREFIX}-trade-{idx}",
        "symbol": "MNQ",
        "strategy": "ny_am_reversal",
        "direction": direction,
        "status": "closed",
        "entry_time": now,
        "exit_time": now,
        "entry_price": 18000.0 + idx,
        "stop_price": 17980.0,
        "target_price": 18060.0,
        "exit_price": 18000.0 + idx + (pnl / 2.0),
        "contracts": 1,
        "pnl": pnl,
        "reason": "target" if pnl > 0 else "stop",
        "confluence_score": 11 + idx,
        "kill_zone": "NY_AM",
        "duration_bars": 15 + idx,
        "vpin": 0.35,
        "toxicity": "normal",
        "gex_regime": "positive",
        "swc_mood": "risk_on",
    }


def make_backtest_result() -> dict:
    # Simulate a BacktestResult-like dict
    return {
        "strategy": "ny_am_reversal",
        "trades": [
            type("T", (), {"pnl": 120})(),
            type("T", (), {"pnl": 180})(),
            type("T", (), {"pnl": -80})(),
            type("T", (), {"pnl": 150})(),
        ],
        "daily_pnl": {
            "2025-03-10": 120,
            "2025-03-11": 180,
            "2025-03-12": -80,
            "2025-03-13": 150,
        },
        "total_pnl": 370,
        "total_trades": 4,
        "wins": 3,
        "losses": 1,
        "win_rate": 0.75,
        "start_date": "2025-03-10",
        "end_date": "2025-03-13",
    }


def make_market_level_fvg() -> dict:
    return {
        "symbol": "MNQ",
        "type": "FVG",
        "direction": "bullish",
        "timeframe": "5min",
        "price_low": 17990.0,
        "price_high": 18010.0,
        "active": True,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"demo": True, "prefix": DEMO_PREFIX},
    }


def make_market_level_call_wall() -> dict:
    return {
        "symbol": "MNQ",
        "type": "call_wall",
        "timeframe": "D",
        "price_low": 18500.0,
        "price_high": None,
        "active": True,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"demo": True, "prefix": DEMO_PREFIX, "label": "Call Wall"},
    }


def make_candidate() -> dict:
    return {
        "id": f"{DEMO_PREFIX}-H001",
        "hypothesis": {
            "name": "FVG-inside-OB filter",
            "ict_reasoning": (
                "ICT teaches that OBs represent institutional order zones. "
                "A FVG formed within an active OB inherits that institutional "
                "backing and should produce higher hold rates than isolated FVGs."
            ),
            "condition": "entry_fvg.overlaps(active_ob)",
            "parameters_added": 0,
        },
        "strategy_name": "ny_am_reversal",
        "status": "passed",
        "gates_passed": 9,
        "gates_total": 9,
        "score": 82,
        "gate_results": {
            "sharpe_improvement": {"passed": True, "value": 0.18, "threshold": 0.10, "reason": "Δ=+0.18"},
            "win_rate_delta": {"passed": True, "value": 0.02, "threshold": -0.02, "reason": "Δ=+2%"},
            "drawdown_delta": {"passed": True, "value": 0.03, "threshold": 0.10, "reason": "Δ=+3%"},
            "walk_forward_pct": {"passed": True, "value": 0.78, "threshold": 0.70, "reason": "78% positive"},
            "cross_instrument_count": {"passed": True, "value": 2, "threshold": 2, "reason": "2/3"},
            "noise_resilience_pct": {"passed": True, "value": 0.12, "threshold": 0.30, "reason": "12% max degradation"},
            "inversion_loses": {"passed": True, "value": 1, "threshold": 1, "reason": "Inverted strategy loses"},
            "occam_params": {"passed": True, "value": 0, "threshold": 2, "reason": "0 new params"},
            "validation_improves": {"passed": True, "value": 0.12, "threshold": 0.05, "reason": "Δ=+0.12"},
        },
        "sharpe_improvement": 0.18,
        "net_profit_delta": 450.0,
        "session_id": f"{DEMO_PREFIX}-session",
        "mode": "generate",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def make_post_mortem(trade_id: str) -> dict:
    return {
        "category": "htf_misread",
        "severity": "medium",
        "reason": "Entered against weekly bias — daily was clean but weekly showed distribution.",
        "recommendation": "Require weekly bias alignment before taking daily-framed entries.",
        "pnl": -80.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── State provider for the live sync demo ──────────────────────────────

class DemoStateProvider:
    """
    Generates a sequence of synthetic states that exercises every
    dashboard widget. Each call advances one step in the sequence.
    """

    STATES = [
        # Phase 1: Bot comes online, calm
        {
            "is_running": True,
            "vpin": 0.28,
            "toxicity_level": "calm",
            "shield_active": False,
            "pnl_today": 120,
            "daily_high_pnl": 120,
            "wins_today": 1,
            "losses_today": 0,
            "trades_today": 1,
            "position_count": 0,
            "swc_mood": "risk_on",
            "swc_confidence": 0.72,
            "swc_summary": "M10 demo — phase 1: bot online, first win",
            "gex_regime": "positive",
            "gex_call_wall": 18500,
            "gex_put_wall": 17800,
            "gex_flip_point": 18100,
        },
        # Phase 2: Second trade opens, VPIN rising
        {
            "is_running": True,
            "vpin": 0.42,
            "toxicity_level": "elevated",
            "shield_active": False,
            "pnl_today": 200,
            "daily_high_pnl": 200,
            "wins_today": 2,
            "losses_today": 0,
            "trades_today": 2,
            "position_count": 1,
            "swc_mood": "risk_on",
            "swc_confidence": 0.72,
            "swc_summary": "M10 demo — phase 2: second position open, VPIN rising",
            "gex_regime": "positive",
            "gex_call_wall": 18500,
            "gex_put_wall": 17800,
            "gex_flip_point": 18100,
        },
        # Phase 3: Loss, VPIN spikes
        {
            "is_running": True,
            "vpin": 0.58,
            "toxicity_level": "high",
            "shield_active": False,
            "pnl_today": -30,
            "daily_high_pnl": 200,
            "wins_today": 2,
            "losses_today": 1,
            "trades_today": 3,
            "position_count": 0,
            "swc_mood": "event_driven",
            "swc_confidence": 0.55,
            "swc_summary": "M10 demo — phase 3: loss, VPIN spiked to HIGH, tightening",
            "gex_regime": "flip",
            "gex_call_wall": 18500,
            "gex_put_wall": 17800,
            "gex_flip_point": 18100,
        },
        # Phase 4: VPIN extreme → SHIELD ACTIVE
        {
            "is_running": True,
            "vpin": 0.78,
            "toxicity_level": "extreme",
            "shield_active": True,
            "pnl_today": -30,
            "daily_high_pnl": 200,
            "wins_today": 2,
            "losses_today": 1,
            "trades_today": 3,
            "position_count": 0,
            "swc_mood": "risk_off",
            "swc_confidence": 0.88,
            "swc_summary": "M10 demo — phase 4: 🛡 SHIELD TRIGGERED, trading halted",
            "gex_regime": "negative",
            "gex_call_wall": 18500,
            "gex_put_wall": 17800,
            "gex_flip_point": 18100,
        },
        # Phase 5: Recovery
        {
            "is_running": True,
            "vpin": 0.38,
            "toxicity_level": "normal",
            "shield_active": False,
            "pnl_today": 250,
            "daily_high_pnl": 300,
            "wins_today": 3,
            "losses_today": 1,
            "trades_today": 4,
            "position_count": 0,
            "swc_mood": "risk_on",
            "swc_confidence": 0.68,
            "swc_summary": "M10 demo — phase 5: shield cleared, recovery trade closed",
            "gex_regime": "positive",
            "gex_call_wall": 18500,
            "gex_put_wall": 17800,
            "gex_flip_point": 18100,
        },
        # Phase 6: Final state — engine going offline cleanly
        {
            "is_running": False,
            "vpin": 0.22,
            "toxicity_level": "calm",
            "shield_active": False,
            "pnl_today": 250,
            "daily_high_pnl": 300,
            "wins_today": 3,
            "losses_today": 1,
            "trades_today": 4,
            "position_count": 0,
            "swc_mood": "choppy",
            "swc_confidence": 0.50,
            "swc_summary": "M10 demo — done. Bot stopped cleanly.",
            "gex_regime": "unknown",
        },
    ]

    def __init__(self):
        self._idx = 0

    def __call__(self) -> dict:
        state = dict(self.STATES[self._idx % len(self.STATES)])
        self._idx += 1
        return state


# ─── Main ───────────────────────────────────────────────────────────────

async def main() -> int:
    client = get_lab_client()
    if client is None:
        print("✗ Could not build Supabase client. Check your .env")
        return 1

    print(f"✓ Connected to {client.url}")
    print(f"  Demo prefix: {DEMO_PREFIX}")
    print()

    # Step 1: Trades
    print("=== Step 1: inserting 3 synthetic trades ===")
    trades = [
        make_trade(1, pnl=120, direction="long"),
        make_trade(2, pnl=80, direction="long"),
        make_trade(3, pnl=-80, direction="short"),
    ]
    inserted = client.insert_trades_batch(trades)
    print(f"  → inserted {inserted}/3 trades")

    # Step 2: backtest_results
    print("\n=== Step 2: inserting backtest_results ===")
    bt_result = make_backtest_result()
    ok = client.insert_backtest_result(
        bt_result,
        run_id=f"{DEMO_PREFIX}-backtest",
        config={"min_confluence": 7, "risk_per_trade": 250},
        notes=f"M10 wire demo run {DEMO_PREFIX}",
    )
    print(f"  → {'✓' if ok else '✗'} backtest_results")

    # Step 3: market_levels
    print("\n=== Step 3: inserting 2 market_levels ===")
    fvg_id = client.insert_market_level(make_market_level_fvg())
    wall_id = client.insert_market_level(make_market_level_call_wall())
    print(f"  → FVG id:       {fvg_id}")
    print(f"  → Call Wall id: {wall_id}")

    # Step 4: strategy_candidate
    print("\n=== Step 4: inserting strategy_candidate ===")
    ok = client.upsert_strategy_candidate(make_candidate())
    print(f"  → {'✓' if ok else '✗'} strategy_candidates")

    # Step 5: post_mortem
    print("\n=== Step 5: inserting post_mortem ===")
    ok = client.insert_post_mortem(
        make_post_mortem(trades[2]["id"]),
        trade_id=trades[2]["id"],
    )
    print(f"  → {'✓' if ok else '✗'} post_mortems")

    # Step 6: Live state sync loop
    print("\n=== Step 6: starting BotStateSync for 12 seconds ===")
    print("  Watch the dashboard at http://localhost:3000 now!")
    print("  The VPIN gauge, P&L, SWC mood, and GEX regime will change")
    print("  every 2 seconds through 6 phases.")
    print()

    sync = BotStateSync(
        client,
        DemoStateProvider(),
        interval_s=2.0,
    )

    task = asyncio.create_task(sync.start())
    await asyncio.sleep(13.0)  # Enough for all 6 phases + final stamp
    await sync.stop()
    await asyncio.wait_for(task, timeout=2.0)

    print(f"  → state_sync wrote {sync.stats['total_writes']} updates")
    print(f"     failures: {sync.stats['total_failures']}")

    # Step 7: Cleanup (trades need to be deleted after post_mortems due to FK)
    print("\n=== Step 7: cleanup ===")

    cleanups = [
        ("post_mortems", "trade_id", trades[2]["id"]),
        ("market_levels", "id", fvg_id),
        ("market_levels", "id", wall_id),
        ("strategy_candidates", "id", f"{DEMO_PREFIX}-H001"),
        ("backtest_results", "id", f"{DEMO_PREFIX}-backtest"),
        ("trades", "id", trades[0]["id"]),
        ("trades", "id", trades[1]["id"]),
        ("trades", "id", trades[2]["id"]),
    ]

    for table, col, val in cleanups:
        if val is None:
            continue
        try:
            client._client.table(table).delete().eq(col, val).execute()
            print(f"  ✓ deleted {table}.{col}={val}")
        except Exception as e:
            print(f"  ⚠ failed to delete {table}.{col}={val}: {str(e)[:80]}")

    # Final status
    print()
    print("=" * 60)
    print("✅ M10 WIRE DEMO COMPLETE")
    print("=" * 60)
    print(f"Client stats: {client.stats}")
    print()
    print("The singleton bot_state row was left in the final 'demo done'")
    print("state — the dashboard should show 'Bot stopped cleanly' in the")
    print("SWC summary card.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
