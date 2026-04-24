"""
core/health.py
==============
Periodic health-check JSON writer. Dumps a snapshot of bot state to a
well-known file every N seconds so external monitors (systemd, crontab,
a shell script, a dashboard) can check whether the engine is **alive
and trading correctly** — not just whether the process is running.

Previous incidents that would have been caught by a health monitor:

* **Bug J/K (2026-04-24)** — User Hub dead + get_positions returning 404
  for days. The process was alive and logging, but `broker_user_hub_alive`
  was False and every `get_positions` returned 0 → a monitor checking
  `health["broker"]["user_hub_alive"]` would have flagged it.

* **Phantom positions (multiple days)** — local state had positions the
  broker didn't know about. A monitor checking
  `abs(health["positions"]["local_count"] - health["positions"]["broker_count"])`
  would have alerted on divergence.

Usage:

    from core.health import HealthWriter
    writer = HealthWriter(state, components)
    asyncio.create_task(writer.run_forever())

Writes to ``algoict-engine/.health.json`` atomically (tmp + rename).

Example JSON:
    {
      "ts": "2026-04-24T22:15:00+00:00",
      "pid": 59532,
      "uptime_s": 3432.1,
      "mode": "paper",
      "alive": true,
      "bars_1min_count": 10432,
      "last_bar_ts": "2026-04-24T22:14:00+00:00",
      "last_bar_age_s": 12.3,
      "broker": {
        "user_hub_alive": true,
        "market_hub_alive": true,
        "last_order_submitted_ts": "2026-04-24T15:09:01+00:00"
      },
      "positions": {"local_count": 0, "broker_count": 0},
      "risk": {
        "kill_switch_active": false,
        "daily_pnl": 0.0,
        "mll_zone": "normal",
        "trades_today": 0
      },
      "vpin": {"value": 0.43, "shield": "calm"},
      "errors_last_60s": 0
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("algoict.health")

HEALTH_FILE = Path(__file__).resolve().parent.parent / ".health.json"
DEFAULT_INTERVAL_S = 10.0


class HealthWriter:
    """Periodically snapshot engine health to a JSON file."""

    def __init__(self, state, components, interval_s: float = DEFAULT_INTERVAL_S):
        self._state = state
        self._components = components
        self._interval_s = interval_s
        self._started_at = time.monotonic()
        self._running = True

    def stop(self) -> None:
        self._running = False

    async def run_forever(self) -> None:
        """Main loop — call `stop()` to break out."""
        while self._running:
            try:
                self._write_snapshot()
            except Exception as exc:
                # Never kill the bot because health-check failed.
                logger.warning("HealthWriter: snapshot failed: %s", exc)
            await asyncio.sleep(self._interval_s)

    def _write_snapshot(self) -> None:
        snap = self._build_snapshot()
        tmp = HEALTH_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
        # Atomic replace on POSIX; on Windows os.replace works too.
        os.replace(tmp, HEALTH_FILE)

    def _build_snapshot(self) -> dict:
        state = self._state
        components = self._components
        now = datetime.now(timezone.utc)

        bars = getattr(state, "bars_1min", None)
        bar_count = 0
        last_bar_ts = None
        last_bar_age_s = None
        if bars is not None and not bars.empty:
            bar_count = len(bars)
            last_bar_ts = bars.index[-1]
            try:
                last_bar_age_s = (now - last_bar_ts.tz_convert("UTC")).total_seconds()
            except Exception:
                last_bar_age_s = None

        broker = getattr(components, "broker", None)
        user_hub_alive = bool(getattr(broker, "user_hub_alive", False)) if broker else False

        positions_local = len(getattr(state, "open_positions", {}) or {})

        risk = getattr(components, "risk", None)
        risk_snap: dict = {}
        if risk is not None:
            risk_snap = {
                "kill_switch_active": bool(getattr(risk, "kill_switch_active", False)),
                "profit_cap_active": bool(getattr(risk, "profit_cap_active", False)),
                "daily_pnl": float(getattr(risk, "daily_pnl", 0.0)),
                "trades_today": int(getattr(risk, "trades_today", 0)),
                "consecutive_losses": int(getattr(risk, "consecutive_losses", 0)),
                "mll_zone": str(getattr(risk, "_mll_zone", "normal")),
            }

        vpin_snap: dict = {}
        vs = getattr(state, "vpin_status", None)
        if vs is not None:
            vpin_snap = {
                "value": float(vs.vpin) if vs.vpin is not None else None,
                "shield": str(getattr(vs, "toxicity_level", "unknown")),
            }

        return {
            "ts": now.isoformat(),
            "pid": os.getpid(),
            "uptime_s": round(time.monotonic() - self._started_at, 1),
            "mode": getattr(state, "mode", "unknown"),
            "alive": True,
            "bars_1min_count": bar_count,
            "last_bar_ts": str(last_bar_ts) if last_bar_ts is not None else None,
            "last_bar_age_s": round(last_bar_age_s, 1) if last_bar_age_s is not None else None,
            "broker": {
                "user_hub_alive": user_hub_alive,
                "account_id": str(getattr(broker, "_account_id", "")) if broker else "",
            },
            "positions": {
                "local_count": positions_local,
                # broker_count requires an async API call — filled in by
                # run_forever() next loop if the reconciler cached it.
                "broker_count_cached": int(getattr(state, "last_broker_position_count", -1)),
            },
            "risk": risk_snap,
            "vpin": vpin_snap,
        }


def read_health() -> dict | None:
    """Utility: read the last health snapshot from disk (returns None if absent)."""
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
