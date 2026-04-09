"""
db/supabase_lab_client.py
==========================
Canonical Supabase write-path for the engine (M10).

Why a second client
-------------------
The legacy ``db.supabase_client.SupabaseClient`` predates the schema in
``supabase/migrations/0001_init.sql``:

  * It uses a ``side`` column where the schema expects ``direction``.
  * It doesn't cover ``strategy_candidates``, ``market_levels`` (writes),
    or ``backtest_results``.
  * Its methods mix sync ``upsert().execute()`` with an async-looking
    call convention in ``core/heartbeat.py``.

Rather than modify the legacy client (risky — it might still be imported
elsewhere), we introduce ``SupabaseLabClient`` as the new canonical
path. Every write the engine needs to do goes through here.

Design
------
- Pure sync over the supabase-py ``Client`` (supabase-py itself is sync
  and the trading engine can wrap it in ``asyncio.to_thread()`` where
  async is needed).
- Graceful factory: ``get_lab_client()`` returns ``None`` if env is
  missing, instead of crashing at import time.
- Every write method catches exceptions, logs them, and returns a bool
  / id so callers can decide whether to retry or alert.
- High-level convenience methods take dataclasses/dicts directly and
  defer column mapping to ``db.adapters``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .adapters import (
    trade_to_row,
    signal_to_row,
    backtest_result_to_row,
    candidate_record_to_row,
    post_mortem_to_row,
    normalize_bot_state,
)

logger = logging.getLogger(__name__)


# ─── Lazy imports — keep the module importable offline ─────────────────

try:
    from supabase import create_client, Client  # type: ignore
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False
    Client = Any  # type: ignore


# ─── Env loading ────────────────────────────────────────────────────────

def _load_env_if_needed() -> None:
    """
    Load algoict-engine/.env via python-dotenv if present.
    No-op if dotenv isn't installed or the file doesn't exist.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


# ─── Factory ────────────────────────────────────────────────────────────

def get_lab_client(
    url: Optional[str] = None,
    key: Optional[str] = None,
) -> Optional["SupabaseLabClient"]:
    """
    Build a ``SupabaseLabClient`` or return ``None`` if env is missing.

    The trading engine should call this at boot and gracefully degrade
    (skip Supabase writes) if the return is ``None`` — trading itself
    doesn't depend on the dashboard bus.

    Parameters
    ----------
    url : str, optional
        Override URL (tests). Defaults to ``SUPABASE_URL`` env var.
    key : str, optional
        Override key (tests). Defaults to ``SUPABASE_KEY`` env var.
        Must be the service_role key for writes.
    """
    if not _SUPABASE_AVAILABLE:
        logger.warning(
            "supabase-py not installed — engine will run without Supabase. "
            "Install with: pip install supabase"
        )
        return None

    _load_env_if_needed()

    url = url or os.environ.get("SUPABASE_URL", "").strip()
    key = key or os.environ.get("SUPABASE_KEY", "").strip()

    if not url or not key:
        logger.warning(
            "SUPABASE_URL or SUPABASE_KEY missing from environment. "
            "Engine will run without Supabase writes."
        )
        return None

    try:
        raw_client = create_client(url, key)
        return SupabaseLabClient(raw_client, url=url)
    except Exception as e:
        logger.exception("Failed to build Supabase client: %s", e)
        return None


# ─── Client class ───────────────────────────────────────────────────────

class SupabaseLabClient:
    """
    Wraps a ``supabase.Client`` with one method per schema write path.

    Every method is sync and returns either:
      * ``bool`` — True on success, False on any error
      * ``str | None`` — for INSERTs that return a generated UUID

    Errors are logged but never raised, so a misbehaving Supabase doesn't
    take down the trading loop. Callers can check the return value and
    decide whether to retry or alert.
    """

    BOT_ID = "bot_1"

    def __init__(self, client: Any, url: str = ""):
        self._client = client
        self._url = url
        self._write_count = 0
        self._error_count = 0

    # ─── Introspection ──────────────────────────────────────────────────

    @property
    def url(self) -> str:
        return self._url

    @property
    def stats(self) -> dict:
        return {
            "writes": self._write_count,
            "errors": self._error_count,
            "success_rate": (
                self._write_count / (self._write_count + self._error_count)
                if (self._write_count + self._error_count) > 0
                else 1.0
            ),
        }

    # ─── Low-level writers (take pre-normalized dicts) ──────────────────

    def _safe_execute(self, operation: str, fn) -> bool:
        """Run a write callable; catch + log + track counts."""
        try:
            fn()
            self._write_count += 1
            return True
        except Exception as e:
            self._error_count += 1
            logger.error("Supabase %s failed: %s", operation, e)
            return False

    def upsert_bot_state(self, state: dict) -> bool:
        """
        Upsert the singleton bot_state row.

        Accepts a partial dict — only the supplied fields are updated.
        Enum values are normalized to prevent CHECK constraint violations.
        """
        row = normalize_bot_state(state, self.BOT_ID)
        return self._safe_execute(
            "upsert_bot_state",
            lambda: self._client.table("bot_state")
                .upsert(row, on_conflict="id")
                .execute()
        )

    def insert_trade(self, trade: Any, symbol: str = "MNQ") -> bool:
        """Insert a trade row. Accepts Trade dataclass or dict."""
        row = trade_to_row(trade, symbol=symbol)
        return self._safe_execute(
            "insert_trade",
            lambda: self._client.table("trades").upsert(row, on_conflict="id").execute()
        )

    def insert_trades_batch(self, trades: list, symbol: str = "MNQ") -> int:
        """
        Bulk upsert a list of trades. Returns the count successfully written.

        Used by the backtester to persist all closed trades at run end.
        """
        if not trades:
            return 0
        rows = [trade_to_row(t, symbol=symbol) for t in trades]
        try:
            self._client.table("trades").upsert(rows, on_conflict="id").execute()
            self._write_count += len(rows)
            return len(rows)
        except Exception as e:
            self._error_count += 1
            logger.error("Batch trade upsert failed: %s", e)
            return 0

    def insert_signal(self, signal: Any, symbol: str = "MNQ") -> bool:
        """Insert a signal row. Accepts SignalLog dataclass or dict."""
        row = signal_to_row(signal, symbol=symbol)
        return self._safe_execute(
            "insert_signal",
            lambda: self._client.table("signals").upsert(row, on_conflict="id").execute()
        )

    def upsert_daily_performance(self, perf: dict) -> bool:
        """Upsert a daily performance row (keyed by date)."""
        # Ensure id field matches the date
        row = dict(perf)
        if "id" not in row and "date" in row:
            row["id"] = str(row["date"])
        return self._safe_execute(
            "upsert_daily_performance",
            lambda: self._client.table("daily_performance")
                .upsert(row, on_conflict="id")
                .execute()
        )

    def insert_post_mortem(self, pm_result: Any, trade_id: str) -> bool:
        """Insert a post-mortem row referencing an existing trade."""
        row = post_mortem_to_row(pm_result, trade_id)
        return self._safe_execute(
            "insert_post_mortem",
            lambda: self._client.table("post_mortems")
                .upsert(row, on_conflict="id")
                .execute()
        )

    def insert_market_level(self, level: dict) -> Optional[str]:
        """
        Insert a market_levels row and return the generated UUID.

        Returns None on failure.
        """
        try:
            res = self._client.table("market_levels").insert(level).execute()
            self._write_count += 1
            data = res.data if hasattr(res, "data") else None
            if data and len(data) > 0:
                return str(data[0].get("id"))
            return None
        except Exception as e:
            self._error_count += 1
            logger.error("insert_market_level failed: %s", e)
            return None

    def mark_market_level_mitigated(self, level_id: str) -> bool:
        """Mark a market_levels row as mitigated (inactive)."""
        ts = datetime.now(timezone.utc).isoformat()
        return self._safe_execute(
            "mark_market_level_mitigated",
            lambda: self._client.table("market_levels")
                .update({"active": False, "mitigated_at": ts})
                .eq("id", level_id)
                .execute()
        )

    def insert_backtest_result(
        self,
        result: Any,
        run_id: Optional[str] = None,
        config: Optional[dict] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Persist a completed BacktestResult. ``config`` is stored as JSONB.
        """
        row = backtest_result_to_row(result, run_id=run_id, config=config, notes=notes)
        return self._safe_execute(
            "insert_backtest_result",
            lambda: self._client.table("backtest_results")
                .upsert(row, on_conflict="id")
                .execute()
        )

    def upsert_strategy_candidate(self, record: Any) -> bool:
        """
        Upsert a Strategy Lab CandidateRecord. Re-runs update in place.
        """
        row = candidate_record_to_row(record)
        return self._safe_execute(
            "upsert_strategy_candidate",
            lambda: self._client.table("strategy_candidates")
                .upsert(row, on_conflict="id")
                .execute()
        )

    def upsert_strategy_candidates_batch(self, records: list) -> int:
        """Bulk upsert. Returns count successfully written."""
        if not records:
            return 0
        rows = [candidate_record_to_row(r) for r in records]
        try:
            self._client.table("strategy_candidates").upsert(rows, on_conflict="id").execute()
            self._write_count += len(rows)
            return len(rows)
        except Exception as e:
            self._error_count += 1
            logger.error("Batch candidate upsert failed: %s", e)
            return 0

    # ─── Read helpers (for tests and debugging) ─────────────────────────

    def get_bot_state(self) -> Optional[dict]:
        """Read the singleton bot_state row. Returns None if missing."""
        try:
            res = self._client.table("bot_state").select("*").eq("id", self.BOT_ID).single().execute()
            return res.data if hasattr(res, "data") else None
        except Exception as e:
            logger.error("get_bot_state failed: %s", e)
            return None

    def get_recent_trades(self, limit: int = 20) -> list[dict]:
        try:
            res = (
                self._client.table("trades")
                .select("*")
                .order("entry_time", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.error("get_recent_trades failed: %s", e)
            return []

    def get_candidate(self, candidate_id: str) -> Optional[dict]:
        try:
            res = (
                self._client.table("strategy_candidates")
                .select("*")
                .eq("id", candidate_id)
                .single()
                .execute()
            )
            return res.data if hasattr(res, "data") else None
        except Exception as e:
            logger.error("get_candidate failed: %s", e)
            return None
