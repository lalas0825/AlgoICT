"""
db/supabase_client.py
=====================
Supabase client for AlgoICT.

Handles CRUD operations for:
    - trades
    - signals
    - daily_performance
    - bot_state
    - post_mortems

All writes use upsert with error handling + logging.

Usage:
    from db.supabase_client import SupabaseClient

    client = SupabaseClient()
    await client.write_trade({"symbol": "MNQ", "entry_time": ..., "pnl": 250, ...})
    await client.update_bot_state({"last_heartbeat": "2024-01-02T09:30:00Z"})
"""

import logging
from typing import Any, Optional

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)


class SupabaseClient:
    """
    Async-friendly Supabase client wrapper.

    All methods are sync-only (Supabase Python client doesn't have async).
    For async usage, wrap calls in executor or run_in_executor.
    """

    def __init__(self, url: str = SUPABASE_URL, key: str = SUPABASE_KEY):
        if not SUPABASE_AVAILABLE:
            raise ImportError("supabase package not installed. Run: pip install supabase")

        if not url or not key:
            raise ValueError(
                "Supabase credentials missing. "
                "Set SUPABASE_URL and SUPABASE_KEY in .env"
            )

        self._url = url
        self._key = key
        self._client: Client = create_client(url, key)
        logger.info("SupabaseClient initialized (url: %s)", url)

    # ------------------------------------------------------------------ #
    # Trades
    # ------------------------------------------------------------------ #

    def write_trade(self, trade: dict) -> bool:
        """
        Write or update a trade record.

        Expected keys:
            symbol, entry_time, exit_time, side, contracts, entry_price,
            exit_price, pnl, confluence_score, vpin, toxicity, strategy

        Returns True on success, False on error.
        """
        try:
            trade_id = f"{trade.get('symbol')}_{trade.get('entry_time')}"

            self._client.table("trades").upsert(
                {
                    "id": trade_id,
                    "symbol": trade.get("symbol"),
                    "entry_time": trade.get("entry_time"),
                    "exit_time": trade.get("exit_time"),
                    "side": trade.get("side"),
                    "contracts": trade.get("contracts"),
                    "entry_price": trade.get("entry_price"),
                    "exit_price": trade.get("exit_price"),
                    "pnl": trade.get("pnl"),
                    "confluence_score": trade.get("confluence_score"),
                    "vpin": trade.get("vpin"),
                    "toxicity": trade.get("toxicity"),
                    "strategy": trade.get("strategy"),
                    **{k: v for k, v in trade.items()
                       if k not in [
                           "id", "symbol", "entry_time", "exit_time",
                           "side", "contracts", "entry_price", "exit_price",
                           "pnl", "confluence_score", "vpin", "toxicity", "strategy"
                       ]}
                },
                on_conflict="id"
            ).execute()
            logger.debug("Trade written: %s", trade_id)
            return True
        except Exception as exc:
            logger.error("Failed to write trade: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Signals
    # ------------------------------------------------------------------ #

    def write_signal(self, signal: dict) -> bool:
        """
        Write a trading signal.

        Expected keys:
            timestamp, symbol, signal_type, price, confluence_score,
            liquidity_grab, fair_value_gap, order_block, etc.

        Returns True on success.
        """
        try:
            signal_id = f"{signal.get('symbol')}_{signal.get('timestamp')}"

            self._client.table("signals").insert(
                {
                    "id": signal_id,
                    "timestamp": signal.get("timestamp"),
                    "symbol": signal.get("symbol"),
                    "signal_type": signal.get("signal_type"),
                    "price": signal.get("price"),
                    "confluence_score": signal.get("confluence_score"),
                    "liquidity_grab": signal.get("liquidity_grab"),
                    "fair_value_gap": signal.get("fair_value_gap"),
                    "order_block": signal.get("order_block"),
                    "market_structure": signal.get("market_structure"),
                    "vpin": signal.get("vpin"),
                    "gex_regime": signal.get("gex_regime"),
                    **{k: v for k, v in signal.items()
                       if k not in [
                           "id", "timestamp", "symbol", "signal_type",
                           "price", "confluence_score", "liquidity_grab",
                           "fair_value_gap", "order_block", "market_structure",
                           "vpin", "gex_regime"
                       ]}
                }
            ).execute()
            logger.debug("Signal written: %s", signal_id)
            return True
        except Exception as exc:
            logger.error("Failed to write signal: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Bot State
    # ------------------------------------------------------------------ #

    def update_bot_state(self, state: dict) -> bool:
        """
        Update bot state (heartbeat, status, etc.).

        Expected keys (any subset):
            last_heartbeat, status, current_position, daily_pnl, trades_today

        Returns True on success.
        """
        try:
            # Bot state is a singleton (always id='bot_1')
            self._client.table("bot_state").upsert(
                {
                    "id": "bot_1",
                    **state
                },
                on_conflict="id"
            ).execute()
            logger.debug("Bot state updated: %s", state)
            return True
        except Exception as exc:
            logger.error("Failed to update bot state: %s", exc)
            return False

    def get_bot_state(self) -> Optional[dict]:
        """
        Retrieve current bot state.

        Returns the bot_state row or None on error.
        """
        try:
            result = self._client.table("bot_state").select(
                "*"
            ).eq("id", "bot_1").execute()

            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as exc:
            logger.error("Failed to get bot state: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # Daily Performance
    # ------------------------------------------------------------------ #

    def write_daily_performance(self, perf: dict) -> bool:
        """
        Write or update daily performance summary.

        Expected keys:
            date, trades_count, wins, losses, total_pnl, max_drawdown,
            sharpe, best_trade, worst_trade

        Returns True on success.
        """
        try:
            perf_id = perf.get("date")

            self._client.table("daily_performance").upsert(
                {
                    "id": perf_id,
                    "date": perf.get("date"),
                    "trades_count": perf.get("trades_count"),
                    "wins": perf.get("wins"),
                    "losses": perf.get("losses"),
                    "total_pnl": perf.get("total_pnl"),
                    "max_drawdown": perf.get("max_drawdown"),
                    "sharpe": perf.get("sharpe"),
                    "best_trade": perf.get("best_trade"),
                    "worst_trade": perf.get("worst_trade"),
                    **{k: v for k, v in perf.items()
                       if k not in [
                           "id", "date", "trades_count", "wins", "losses",
                           "total_pnl", "max_drawdown", "sharpe",
                           "best_trade", "worst_trade"
                       ]}
                },
                on_conflict="id"
            ).execute()
            logger.debug("Daily performance written: %s", perf_id)
            return True
        except Exception as exc:
            logger.error("Failed to write daily performance: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Post-Mortems
    # ------------------------------------------------------------------ #

    def write_post_mortem(self, postmortem: dict) -> bool:
        """
        Write an AI-generated trade post-mortem analysis.

        Expected keys:
            timestamp, trade_id, reason_category, analysis, lesson, related_trades

        Returns True on success.
        """
        try:
            pm_id = f"{postmortem.get('trade_id')}_{postmortem.get('timestamp')}"

            self._client.table("post_mortems").insert(
                {
                    "id": pm_id,
                    "timestamp": postmortem.get("timestamp"),
                    "trade_id": postmortem.get("trade_id"),
                    "reason_category": postmortem.get("reason_category"),
                    "analysis": postmortem.get("analysis"),
                    "lesson": postmortem.get("lesson"),
                    "related_trades": postmortem.get("related_trades"),
                    **{k: v for k, v in postmortem.items()
                       if k not in [
                           "id", "timestamp", "trade_id",
                           "reason_category", "analysis", "lesson",
                           "related_trades"
                       ]}
                }
            ).execute()
            logger.debug("Post-mortem written: %s", pm_id)
            return True
        except Exception as exc:
            logger.error("Failed to write post-mortem: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Query helpers
    # ------------------------------------------------------------------ #

    def get_trades_today(self, date_str: str) -> list[dict]:
        """
        Retrieve all trades for a given date (YYYY-MM-DD).

        Returns list of trade dicts or empty list on error.
        """
        try:
            result = self._client.table("trades").select("*").gte(
                "entry_time", f"{date_str}T00:00:00"
            ).lt(
                "entry_time", f"{date_str}T23:59:59"
            ).execute()
            return result.data or []
        except Exception as exc:
            logger.error("Failed to get trades for %s: %s", date_str, exc)
            return []

    def get_recent_trades(self, limit: int = 10) -> list[dict]:
        """
        Retrieve the most recent N trades.

        Returns list of trade dicts or empty list on error.
        """
        try:
            result = self._client.table("trades").select("*").order(
                "entry_time", desc=True
            ).limit(limit).execute()
            return result.data or []
        except Exception as exc:
            logger.error("Failed to get recent trades: %s", exc)
            return []

    def get_market_levels(self, symbol: str) -> Optional[dict]:
        """
        Retrieve current market levels (PDH, PDL, OB, FVG, etc.) for a symbol.

        Returns dict or None on error.
        """
        try:
            result = self._client.table("market_levels").select("*").eq(
                "symbol", symbol
            ).order("timestamp", desc=True).limit(1).execute()
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as exc:
            logger.error("Failed to get market levels for %s: %s", symbol, exc)
            return None
