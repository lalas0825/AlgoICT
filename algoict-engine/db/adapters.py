"""
db/adapters.py
===============
Pure converter functions: internal dataclasses → Supabase row dicts.

Why separated from the client
-----------------------------
Adapters are pure functions — same input → same output, no I/O. That
makes them trivial to unit test and means the Supabase client can stay
focused on network/auth concerns. Every conversion has a single place
where the schema-to-Python mapping lives.

Schema references
-----------------
Column names and types come from supabase/migrations/0001_init.sql.
If you change the schema, update the matching adapter and the tests
will catch any fields you forgot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


# ─── Helpers ─────────────────────────────────────────────────────────────

def _iso(ts: Any) -> Optional[str]:
    """Convert a timestamp-ish value to ISO 8601 string or None."""
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _date_str(d: Any) -> Optional[str]:
    """Convert a date-ish value to YYYY-MM-DD string or None."""
    if d is None:
        return None
    if isinstance(d, str):
        # Already a date string? Pass through if it parses.
        return d[:10]
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _num(v: Any, default: float = 0.0) -> float:
    """Coerce to float with a default on None/errors."""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    """Coerce to int with a default on None/errors."""
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ─── Trade → trades row ─────────────────────────────────────────────────

def trade_to_row(trade: Any, symbol: str = "MNQ") -> dict:
    """
    Convert a backtest Trade dataclass (or dict-like) to a `trades` row.

    Accepts either the ``backtest.backtester.Trade`` dataclass or any
    object exposing the same attribute names. Also accepts a dict with
    matching keys.

    Schema
    ------
    Matches columns defined in 0001_init.sql::trades. The legacy
    ``side`` column is NOT used — we use ``direction`` everywhere.
    """
    getv = _make_getter(trade)

    entry_time = _iso(getv("entry_time"))
    exit_time = _iso(getv("exit_time"))

    # ID strategy: prefer explicit id, else compose from symbol + entry_time
    trade_id = getv("id") or f"{symbol}_{entry_time}"

    return {
        "id": str(trade_id),
        "symbol": getv("symbol", symbol),
        "strategy": getv("strategy", ""),
        "direction": getv("direction", ""),
        "status": getv("status", "closed" if exit_time else "open"),
        "entry_time": entry_time,
        "exit_time": exit_time,
        "entry_price": _num(getv("entry_price")),
        "exit_price": _num(getv("exit_price"), default=None) if getv("exit_price") is not None else None,
        "stop_loss": _num(getv("stop_price") or getv("stop_loss")),
        "take_profit": _num(getv("target_price") or getv("take_profit")),
        "contracts": _int(getv("contracts")),
        "pnl": _num(getv("pnl"), default=None) if getv("pnl") is not None else None,
        "reason": getv("reason"),
        "confluence_score": _int(getv("confluence_score")),
        "kill_zone": getv("kill_zone"),
        "duration_bars": _int(getv("duration_bars"), default=None) if getv("duration_bars") is not None else None,
        "vpin": _num(getv("vpin"), default=None) if getv("vpin") is not None else None,
        "toxicity": getv("toxicity"),
        "gex_regime": getv("gex_regime"),
        "swc_mood": getv("swc_mood"),
    }


# ─── Signal → signals row ────────────────────────────────────────────────

def signal_to_row(signal: Any, symbol: str = "MNQ") -> dict:
    """
    Convert a SignalLog or compatible object to a `signals` row.

    ICT concepts can be supplied as either individual boolean flags
    (liquidity_grab, fair_value_gap, order_block, market_structure) or
    as a pre-built ``ict_concepts`` list of strings. If only the flags
    are present, the list is derived automatically.
    """
    getv = _make_getter(signal)

    ict_list = getv("ict_concepts")
    if not ict_list:
        ict_list = []
        if getv("liquidity_grab"):
            ict_list.append("liquidity_grab")
        if getv("fair_value_gap"):
            ict_list.append("fair_value_gap")
        if getv("order_block"):
            ict_list.append("order_block")
        if getv("market_structure"):
            ict_list.append("market_structure")

    timestamp = _iso(getv("timestamp"))
    signal_id = getv("id") or f"{symbol}_{timestamp}_{getv('direction', '')}"

    return {
        "id": str(signal_id),
        "timestamp": timestamp,
        "symbol": getv("symbol", symbol),
        "strategy": getv("strategy"),
        "direction": getv("direction", ""),
        "level": getv("level"),
        "price": _num(getv("price") or getv("entry_price")),
        "confluence_score": _int(getv("confluence_score")),
        "ict_concepts": list(ict_list),
        "liquidity_grab": bool(getv("liquidity_grab", False)),
        "fair_value_gap": bool(getv("fair_value_gap", False)),
        "order_block": bool(getv("order_block", False)),
        "market_structure": bool(getv("market_structure", False)),
        "vpin": _num(getv("vpin"), default=None) if getv("vpin") is not None else None,
        "gex_regime": getv("gex_regime"),
        "kill_zone": getv("kill_zone"),
        "active": bool(getv("active", True)),
    }


# ─── BacktestResult → backtest_results row ──────────────────────────────

def backtest_result_to_row(
    result: Any,
    run_id: Optional[str] = None,
    config: Optional[dict] = None,
    notes: Optional[str] = None,
) -> dict:
    """
    Convert a ``backtest.backtester.BacktestResult`` (or dict) to a
    `backtest_results` row.

    Parameters
    ----------
    result : BacktestResult
        Must expose: strategy, trades, total_pnl, total_trades, wins,
        losses, win_rate, start_date, end_date.
    run_id : str, optional
        Explicit row id. If None, we compose one from strategy + timestamp.
    config : dict, optional
        Runtime config (min_confluence, risk_per_trade, etc.) stored as
        JSONB in the row. Safe to pass None.
    notes : str, optional
        Free-form notes field.
    """
    getv = _make_getter(result)

    trades = getv("trades") or []
    total_trades = _int(getv("total_trades", len(trades)))
    wins = _int(getv("wins"))
    losses = _int(getv("losses"))

    # Win rate stored as fraction 0-1 (matches dashboard expectations)
    win_rate = _num(getv("win_rate"))

    # Profit factor: gross wins / gross losses
    gross_win = sum(_num(t.pnl) for t in trades if _num(getattr(t, "pnl", 0)) > 0)
    gross_loss = abs(sum(_num(t.pnl) for t in trades if _num(getattr(t, "pnl", 0)) < 0))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else 0.0

    # Max drawdown: running min of equity curve
    daily_pnl = getv("daily_pnl") or {}
    max_dd = _compute_max_drawdown(daily_pnl) if daily_pnl else 0.0

    # Sharpe: simple daily-returns Sharpe (annualized 252). Safe guard against empty.
    sharpe = _compute_sharpe(daily_pnl) if daily_pnl else 0.0

    strategy_name = getv("strategy", "unknown")
    start_date = _date_str(getv("start_date"))
    end_date = _date_str(getv("end_date"))

    if run_id is None:
        now_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_id = f"{strategy_name}_{now_stamp}"

    return {
        "id": str(run_id),
        "strategy": strategy_name,
        "start_date": start_date or "1970-01-01",
        "end_date": end_date or start_date or "1970-01-01",
        "total_trades": total_trades,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown": round(max_dd, 4),
        "net_profit": round(_num(getv("total_pnl")), 2),
        "sharpe_ratio": round(sharpe, 4),
        "status": "completed",
        "config": config or {},
        "notes": notes,
    }


def _compute_max_drawdown(daily_pnl: dict) -> float:
    """Max drawdown as a fraction from the rolling equity curve."""
    if not daily_pnl:
        return 0.0
    sorted_days = sorted(daily_pnl.keys())
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for d in sorted_days:
        equity += _num(daily_pnl[d])
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _compute_sharpe(daily_pnl: dict, periods_per_year: int = 252) -> float:
    """Annualized Sharpe on daily P&L series (risk-free rate = 0)."""
    if not daily_pnl or len(daily_pnl) < 2:
        return 0.0
    returns = [_num(v) for v in daily_pnl.values()]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if variance <= 0:
        return 0.0
    std = variance ** 0.5
    return (mean / std) * (periods_per_year ** 0.5)


# ─── CandidateRecord → strategy_candidates row ──────────────────────────

def candidate_record_to_row(record: Any) -> dict:
    """
    Convert a Strategy Lab ``CandidateRecord`` to a `strategy_candidates`
    row. The CandidateRecord format already matches the dashboard's
    GateResultsData shape (built in M8 candidate_manager.py), so this
    is mostly a passthrough with type coercion.
    """
    getv = _make_getter(record)

    hypothesis = getv("hypothesis") or {}
    if not isinstance(hypothesis, dict):
        hypothesis = hypothesis if isinstance(hypothesis, str) else str(hypothesis)

    return {
        "id": str(getv("id")),
        "hypothesis": (
            hypothesis.get("ict_reasoning", "")
            if isinstance(hypothesis, dict)
            else str(hypothesis)
        ),
        "strategy_name": getv("strategy_name", ""),
        "status": getv("status", "pending"),
        "gates_passed": _int(getv("gates_passed")),
        "gates_total": _int(getv("gates_total"), default=9),
        "score": _int(getv("score")),
        "gate_results": getv("gate_results") or {},
        "sharpe_improvement": (
            _num(getv("sharpe_improvement"))
            if getv("sharpe_improvement") is not None
            else None
        ),
        "net_profit_delta": (
            _num(getv("net_profit_delta"))
            if getv("net_profit_delta") is not None
            else None
        ),
        "session_id": getv("session_id", ""),
        "mode": getv("mode", "generate"),
        "approved_at": _iso(getv("approved_at")),
        "approved_by": getv("approved_by"),
        "notes": getv("notes"),
    }


# ─── Post-mortem result → post_mortems row ──────────────────────────────

VALID_PM_CATEGORIES = {
    "htf_misread", "premature_entry", "stop_too_tight", "stop_too_wide",
    "news_event", "false_signal", "overtrading", "htf_resistance", "other",
}

VALID_PM_SEVERITIES = {"low", "medium", "high"}


def post_mortem_to_row(pm_result: Any, trade_id: str) -> dict:
    """
    Convert a PostMortemResult (from agents/post_mortem.py) to a
    `post_mortems` row.

    Unknown categories map to 'other'; unknown severities to 'medium'.
    The trade_id is required because the post_mortems table has a
    foreign key to trades(id).
    """
    getv = _make_getter(pm_result)

    category = str(getv("category", "other"))
    if category not in VALID_PM_CATEGORIES:
        category = "other"

    severity = str(getv("severity", "medium"))
    if severity not in VALID_PM_SEVERITIES:
        severity = "medium"

    timestamp = _iso(getv("timestamp")) or datetime.now(timezone.utc).isoformat()
    pm_id = getv("id") or f"{trade_id}_{timestamp}"

    return {
        "id": str(pm_id),
        "timestamp": timestamp,
        "trade_id": trade_id,
        "pnl": _num(getv("pnl")),
        "reason_category": category,
        "severity": severity,
        "analysis": str(getv("analysis") or getv("reason") or ""),
        "lesson": str(getv("lesson") or getv("recommendation") or ""),
        "related_trades": list(getv("related_trades") or []),
    }


# ─── bot_state normalization ────────────────────────────────────────────

def normalize_bot_state(state: dict, bot_id: str = "bot_1") -> dict:
    """
    Validate + normalize a bot_state update payload.

    Ensures id is set, timestamps are ISO strings, and enum columns
    never contain invalid values (which would trip CHECK constraints).
    Unknown enum values fall back to the schema default.
    """
    if not isinstance(state, dict):
        raise TypeError("bot_state update must be a dict")

    out: dict[str, Any] = {"id": bot_id}

    # Pass-through numeric + boolean fields
    for key in (
        "is_running", "vpin", "shield_active", "trades_today", "pnl_today",
        "daily_high_pnl", "max_loss_threshold", "profit_cap", "position_count",
        "wins_today", "losses_today", "swc_confidence", "swc_summary",
        "gex_call_wall", "gex_put_wall", "gex_flip_point", "last_signal",
    ):
        if key in state:
            out[key] = state[key]

    # Enum columns with fallback
    if "toxicity_level" in state:
        v = str(state["toxicity_level"])
        out["toxicity_level"] = v if v in {"calm", "normal", "elevated", "high", "extreme"} else "calm"

    if "swc_mood" in state:
        v = str(state["swc_mood"])
        out["swc_mood"] = v if v in {"risk_on", "risk_off", "event_driven", "choppy"} else "choppy"

    if "gex_regime" in state:
        v = str(state["gex_regime"])
        out["gex_regime"] = v if v in {"positive", "negative", "flip", "unknown"} else "unknown"

    # Timestamps
    if "last_heartbeat" in state:
        out["last_heartbeat"] = _iso(state["last_heartbeat"])

    out["updated_at"] = _iso(state.get("updated_at") or datetime.now(timezone.utc))

    return out


# ─── Internal: universal attribute/key getter ────────────────────────────

def _make_getter(obj: Any):
    """
    Return a callable that reads ``obj`` by attribute OR key.

    Lets every adapter accept either a dataclass or a plain dict without
    a branch per field.
    """
    if isinstance(obj, dict):
        def _g(key: str, default: Any = None) -> Any:
            return obj.get(key, default)
    else:
        def _g(key: str, default: Any = None) -> Any:
            return getattr(obj, key, default)
    return _g
