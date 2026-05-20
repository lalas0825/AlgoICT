"""
agents/chart_renderer.py
=========================
Matplotlib chart generation for vision-overlay AI validator.

Renders 2 charts when a SB signal fires:
  1. 1-min chart (last ~90 bars): candles + bot's detected swings, FVGs,
     sweep levels, struct events + proposed entry/stop/target lines
  2. 5-min chart (last ~60 bars): HTF context (struct events, key levels,
     daily/weekly bias annotation)

Output: base64-encoded PNG strings, suitable for Claude vision API.

The point: Claude SEES the bot's interpretation overlaid on raw candles,
so it can validate the bot's claims (FVG real? sweep clean? MSS confirmed?)
against the actual price action.

If detector and chart disagree → Claude can detect and reflect in vote.
"""

import base64
import io
import logging
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")  # headless backend — no display required
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_candles(ax, bars, candle_width=0.6, alpha=0.95):
    """Render OHLC candles on the given axis. `bars` is iterable of dicts
    with 'O','H','L','C' or a DataFrame slice with corresponding cols."""
    if isinstance(bars, pd.DataFrame):
        rows = [
            {
                "O": float(r.get("open", 0)),
                "H": float(r.get("high", 0)),
                "L": float(r.get("low", 0)),
                "C": float(r.get("close", 0)),
            }
            for _, r in bars.iterrows()
        ]
    else:
        rows = list(bars)

    for k, b in enumerate(rows):
        color = "#22c55e" if b["C"] >= b["O"] else "#ef4444"
        ax.plot([k, k], [b["L"], b["H"]],
                color=color, linewidth=1.0, alpha=alpha, zorder=2)
        body_h = abs(b["C"] - b["O"])
        body_y = min(b["O"], b["C"])
        ax.add_patch(Rectangle(
            (k - candle_width/2, body_y),
            candle_width,
            max(body_h, 0.2),
            facecolor=color, edgecolor=color,
            alpha=alpha, zorder=3,
        ))


def _ts_to_idx_map(df: pd.DataFrame) -> dict:
    """Map timestamps in df.index → integer column index, for annotation."""
    return {ts: i for i, ts in enumerate(df.index)}


def _safe_fig_to_base64(fig) -> str:
    """Save matplotlib figure to base64-encoded PNG, close fig to free mem."""
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("utf-8")
        return b64
    finally:
        plt.close(fig)
        buf.close()


# ---------------------------------------------------------------------------
# 1-min signal chart (the main one)
# ---------------------------------------------------------------------------

def render_1min_signal_chart(
    bars_1min: pd.DataFrame,
    components: Any,
    state: Any,
    signal: Any,
    bars_back: int = 90,
) -> Optional[str]:
    """Render 1-min chart with bot annotations + proposed trade levels.

    Returns base64-encoded PNG, or None on failure (caller falls back).
    """
    try:
        if bars_1min is None or bars_1min.empty:
            return None
        # Slice last N bars
        df = bars_1min.tail(bars_back).copy()
        if df.empty:
            return None
        n = len(df)
        ts_idx = _ts_to_idx_map(df)

        fig, ax = plt.subplots(figsize=(14, 7))
        fig.patch.set_facecolor("#0a0a0a")
        ax.set_facecolor("#0a0a0a")

        _render_candles(ax, df, candle_width=0.6)

        # ── Bot's detected swing points ──────────────────────────────
        try:
            swing_det = components.detectors.get("swing_1min") or components.detectors.get("swing")
            if swing_det is not None:
                shs = getattr(swing_det, "swing_highs", None) or []
                sls = getattr(swing_det, "swing_lows", None) or []
                for s in shs[-20:]:
                    s_ts = getattr(s, "timestamp", None)
                    if s_ts in ts_idx:
                        k = ts_idx[s_ts]
                        ax.plot(k, getattr(s, "price", 0) + 1.5,
                                marker="v", color="#fbbf24",
                                markersize=10, zorder=6,
                                markeredgecolor="white", markeredgewidth=0.7)
                for s in sls[-20:]:
                    s_ts = getattr(s, "timestamp", None)
                    if s_ts in ts_idx:
                        k = ts_idx[s_ts]
                        ax.plot(k, getattr(s, "price", 0) - 1.5,
                                marker="^", color="#60a5fa",
                                markersize=10, zorder=6,
                                markeredgecolor="white", markeredgewidth=0.7)
        except Exception as exc:
            logger.debug("swing render skip: %s", exc)

        # ── Bot's detected FVGs (1-min) ──────────────────────────────
        try:
            fvg_det = components.detectors.get("fvg")
            if fvg_det is not None:
                fvgs = getattr(fvg_det, "fvgs", None) or []
                # Filter to recent unmitigated 1-min FVGs (top by recency)
                recent_fvgs = [f for f in fvgs
                               if getattr(f, "timeframe", "1min") == "1min"
                               and not getattr(f, "mitigated", False)][-10:]
                for fvg in recent_fvgs:
                    f_ts = getattr(fvg, "timestamp", None)
                    if f_ts not in ts_idx:
                        continue
                    k = ts_idx[f_ts]
                    direction = getattr(fvg, "direction", "bull")
                    color = "#10b981" if direction == "bull" else "#dc2626"
                    low = float(getattr(fvg, "low", 0))
                    high = float(getattr(fvg, "high", 0))
                    if high <= low:
                        continue
                    ax.add_patch(Rectangle(
                        (k - 0.45, low),
                        n - k + 0.5,  # extend to right edge
                        high - low,
                        facecolor=color, edgecolor=color,
                        alpha=0.22, linewidth=0.8, zorder=1,
                    ))
        except Exception as exc:
            logger.debug("fvg render skip: %s", exc)

        # ── Bot's tracked levels (active + swept) ────────────────────
        try:
            levels = components.detectors.get("tracked_levels") or []
            y_text_offsets = {}
            for lvl in levels[-15:]:
                price = float(getattr(lvl, "price", 0))
                if price <= 0:
                    continue
                swept = bool(getattr(lvl, "swept", False))
                lvl_type = str(getattr(lvl, "type", "?"))
                color = "#6b7280" if swept else "#a78bfa"
                style = ":" if swept else "--"
                ax.axhline(price, color=color, linestyle=style,
                           linewidth=0.7, alpha=0.55, zorder=1)
                ax.annotate(
                    f"{lvl_type}{'(SWEPT)' if swept else ''} {price:.2f}",
                    (n - 1, price),
                    color=color, fontsize=7, ha="right",
                    va="bottom" if y_text_offsets.get(int(price), 0) % 2 == 0 else "top",
                )
                y_text_offsets[int(price)] = y_text_offsets.get(int(price), 0) + 1
        except Exception as exc:
            logger.debug("levels render skip: %s", exc)

        # ── Proposed trade lines (entry/stop/target) ─────────────────
        try:
            entry = float(getattr(signal, "entry_price", 0))
            stop = float(getattr(signal, "stop_price", 0))
            target = float(getattr(signal, "target_price", 0))
            direction = str(getattr(signal, "direction", "long"))
            marker_color = "#fbbf24"
            if entry > 0:
                ax.axhline(entry, color=marker_color, linestyle="-",
                           linewidth=1.5, alpha=0.85, zorder=4)
                ax.annotate(f"ENTRY {direction.upper()} @ {entry:.2f}",
                            (0, entry), color=marker_color, fontsize=9,
                            fontweight="bold", ha="left", va="bottom",
                            bbox=dict(facecolor="#0a0a0a", edgecolor=marker_color,
                                      boxstyle="round,pad=0.3", alpha=0.95))
            if stop > 0:
                ax.axhline(stop, color="#ef4444", linestyle="--",
                           linewidth=1.2, alpha=0.7, zorder=4)
                ax.annotate(f"STOP {stop:.2f}", (n - 1, stop),
                            color="#ef4444", fontsize=8, ha="right", va="top")
            if target > 0:
                ax.axhline(target, color="#10b981", linestyle="--",
                           linewidth=1.2, alpha=0.7, zorder=4)
                ax.annotate(f"TARGET {target:.2f}", (n - 1, target),
                            color="#10b981", fontsize=8, ha="right", va="bottom")
        except Exception as exc:
            logger.debug("trade lines render skip: %s", exc)

        # ── Axes formatting ──────────────────────────────────────────
        labels = []
        for i, ts in enumerate(df.index):
            if i % 10 == 0:
                try:
                    labels.append(ts.strftime("%H:%M"))
                except Exception:
                    labels.append("")
            else:
                labels.append("")
        ax.set_xticks(list(range(n)))
        ax.set_xticklabels(labels, color="#a1a1aa", fontsize=7, rotation=45)
        ax.tick_params(axis="y", colors="#a1a1aa", labelsize=8)
        ax.grid(True, color="#27272a", alpha=0.3, zorder=0)
        ax.set_xlim(-1, n)
        kz = str(getattr(signal, "kill_zone", ""))
        sig_dir = str(getattr(signal, "direction", "?")).upper()
        ax.set_title(
            f"1-MIN — Bot's claimed setup ({sig_dir} {kz}) — validate annotations vs raw candles",
            color="white", fontsize=11, pad=10,
        )
        for spine in ax.spines.values():
            spine.set_color("#3f3f46")

        plt.tight_layout()
        return _safe_fig_to_base64(fig)

    except Exception as exc:
        logger.warning("render_1min_signal_chart failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 5-min HTF context chart
# ---------------------------------------------------------------------------

def render_5min_htf_chart(
    components: Any,
    state: Any,
    signal: Any,
    bars_back: int = 60,
) -> Optional[str]:
    """Render 5-min chart for HTF context. Returns base64 or None.

    Pulls completed 5-min bars from components.tf_manager.
    """
    try:
        df_5m = components.tf_manager.get_completed_bars("5min")
        if df_5m is None or df_5m.empty:
            return None
        df = df_5m.tail(bars_back).copy()
        if df.empty:
            return None
        n = len(df)

        fig, ax = plt.subplots(figsize=(14, 6))
        fig.patch.set_facecolor("#0a0a0a")
        ax.set_facecolor("#0a0a0a")

        _render_candles(ax, df, candle_width=0.7)

        # ── Tracked levels (HTF visible) ─────────────────────────────
        try:
            levels = components.detectors.get("tracked_levels") or []
            for lvl in levels[-20:]:
                price = float(getattr(lvl, "price", 0))
                if price <= 0:
                    continue
                swept = bool(getattr(lvl, "swept", False))
                lvl_type = str(getattr(lvl, "type", "?"))
                # Show all HTF levels (PDH/PDL/PWH/PWL) prominently
                is_htf = lvl_type in ("PDH", "PDL", "PWH", "PWL")
                color = "#fbbf24" if is_htf and not swept else ("#6b7280" if swept else "#a78bfa")
                lw = 1.0 if is_htf else 0.6
                ax.axhline(price, color=color, linestyle="--",
                           linewidth=lw, alpha=0.65, zorder=1)
                if is_htf:
                    ax.annotate(
                        f"{lvl_type}{'(SWEPT)' if swept else ''} {price:.2f}",
                        (n - 1, price), color=color, fontsize=8,
                        ha="right", fontweight="bold",
                    )
        except Exception as exc:
            logger.debug("htf levels render skip: %s", exc)

        # ── Entry/stop/target lines (for context vs HTF) ─────────────
        try:
            entry = float(getattr(signal, "entry_price", 0))
            stop = float(getattr(signal, "stop_price", 0))
            target = float(getattr(signal, "target_price", 0))
            if entry > 0:
                ax.axhline(entry, color="#fbbf24", linestyle="-",
                           linewidth=1.2, alpha=0.7, zorder=4)
                ax.annotate(f"ENTRY {entry:.2f}", (0, entry),
                            color="#fbbf24", fontsize=8, fontweight="bold",
                            ha="left", va="bottom")
            if target > 0:
                ax.axhline(target, color="#10b981", linestyle=":",
                           linewidth=1.0, alpha=0.6)
        except Exception as exc:
            logger.debug("5min trade lines skip: %s", exc)

        # ── X-axis labels ────────────────────────────────────────────
        labels = []
        for i, ts in enumerate(df.index):
            if i % 6 == 0:
                try:
                    labels.append(ts.strftime("%H:%M"))
                except Exception:
                    labels.append("")
            else:
                labels.append("")
        ax.set_xticks(list(range(n)))
        ax.set_xticklabels(labels, color="#a1a1aa", fontsize=8, rotation=45)
        ax.tick_params(axis="y", colors="#a1a1aa", labelsize=8)
        ax.grid(True, color="#27272a", alpha=0.3)
        ax.set_xlim(-1, n)

        # HTF bias annotation
        try:
            bias = components.ny_am_strategy.htf_bias_fn(
                float(state.bars_1min.iloc[-1]["close"])
            )
            d_bias = getattr(bias, "daily_bias", "n/a") or "n/a"
            w_bias = getattr(bias, "weekly_bias", "n/a") or "n/a"
            ax.set_title(
                f"5-MIN HTF context — D1={d_bias} W1={w_bias} — validate trend/range/chop visually",
                color="white", fontsize=11, pad=10,
            )
        except Exception:
            ax.set_title(
                "5-MIN HTF context — validate trend/range/chop visually",
                color="white", fontsize=11, pad=10,
            )

        for spine in ax.spines.values():
            spine.set_color("#3f3f46")

        plt.tight_layout()
        return _safe_fig_to_base64(fig)

    except Exception as exc:
        logger.warning("render_5min_htf_chart failed: %s", exc)
        return None
