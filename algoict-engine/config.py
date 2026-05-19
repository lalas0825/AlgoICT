"""
AlgoICT Configuration — ALL constants, risk rules, kill zones, timeframes.
Sensei Rule: These values are HARDCODED. No dynamic overrides in production.
"""

import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

_log = logging.getLogger("algoict.config")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(BASE_DIR / ".env", override=True)


# ---------------------------------------------------------------------------
# Fail-loud config accessor (2026-04-24 Batch 4 hardening)
# ---------------------------------------------------------------------------
# Silent config defaults have bitten us multiple times: a renamed key
# (TRADE_MANAGEMENT → TRADE_MGMT) or a deleted key silently reverts to
# the hardcoded default at the call site, and the bot looks fine for
# weeks until you audit backtest P&L and realize it's been running on
# stale logic.
#
# `cfg(name, default)` is a drop-in replacement for
# `getattr(config, name, default)` that WARNS the first time a default
# is used for a given name. It deduplicates so the log doesn't spam.
#
# Usage:
#     from config import cfg
#     ttl = cfg("LIMIT_ORDER_TTL_BARS", 10)
#
# Migration path: replace `getattr(config, X, D)` with `config.cfg(X, D)`
# incrementally. Existing getattr calls keep working (cfg is additive).
_missing_cfg_keys_warned: set[str] = set()


def cfg(name: str, default):
    """
    Return config attribute ``name`` if present, else ``default`` + WARN once.

    The warning surfaces the first call stack that hit a missing key so
    ops can see WHICH module silently fell back to a hardcoded default.
    """
    this_module = sys.modules[__name__]
    if hasattr(this_module, name):
        return getattr(this_module, name)
    if name not in _missing_cfg_keys_warned:
        _missing_cfg_keys_warned.add(name)
        _log.warning(
            "config: key %r not defined in config.py — falling back to "
            "default %r. If this is intentional, add %s = %r to config.py "
            "to silence this warning.",
            name, default, name, default,
        )
    return default

# ---------------------------------------------------------------------------
# Broker — TopstepX (MNQ Intraday)
# ---------------------------------------------------------------------------
TOPSTEPX_USERNAME = os.getenv("TOPSTEPX_USERNAME", "")
TOPSTEPX_API_KEY = os.getenv("TOPSTEPX_API_KEY", "")
TOPSTEPX_API_URL = os.getenv("TOPSTEPX_API_URL", "https://api.topstepx.com/api")
TOPSTEPX_WS_URL = os.getenv("TOPSTEPX_WS_URL", "wss://realtime.topstepx.com/api")
TOPSTEPX_ACCOUNT_ID = os.getenv("TOPSTEPX_ACCOUNT_ID", "")

# ---------------------------------------------------------------------------
# Broker — Alpaca (S&P 500 Swing)
# ---------------------------------------------------------------------------
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ---------------------------------------------------------------------------
# AI / APIs
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
MENTHORQ_API_KEY = os.getenv("MENTHORQ_API_KEY", "")

# ---------------------------------------------------------------------------
# AI Model Assignment (token optimization)
# Any caller of the Anthropic API must import from here — never hardcode
# a model id in an agent file. Swap a single constant to re-route a role.
# ---------------------------------------------------------------------------
AI_MODEL_POST_MORTEM = "claude-sonnet-4-6"    # Loss analysis
AI_MODEL_MOOD_SYNTHESIS = "claude-sonnet-4-6"  # SWC daily mood
AI_MODEL_HYPOTHESIS_GEN = "claude-sonnet-4-6"  # Strategy Lab (when wired)

# Haiku reserved for simple tasks (enable when SDK lists it)
# AI_MODEL_SIMPLE = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Telegram Alerts
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Verbosity controls how much bot-internal reasoning gets pushed to Telegram.
#   "quiet"   : only trade entries/exits, kill switch, heartbeat alerts,
#               daily summary, VPIN shield + emergencies.
#   "normal"  : quiet + kill-zone open/close summaries, liquidity sweeps,
#               signal-fired alerts. ~15-25 msgs/day. (default)
#   "verbose" : normal + new FVG forming inside active KZ, "near-miss"
#               rejections (structurally valid but failed one gate),
#               5-min MSS/BOS events. ~40-80 msgs/day.
# Override via env: TELEGRAM_VERBOSITY=verbose in .env
TELEGRAM_VERBOSITY = os.getenv("TELEGRAM_VERBOSITY", "normal").lower().strip()
if TELEGRAM_VERBOSITY not in ("quiet", "normal", "verbose"):
    TELEGRAM_VERBOSITY = "normal"

# Per-alert-type throttle floors (seconds). The TelegramBot enforces these
# across duplicate alert-types with the same bucket-key (e.g. the same
# kill-zone + reject-reason won't re-alert for 5 min). 0 = no throttle.
TELEGRAM_THROTTLE_SEC = {
    "kz_enter":       0,    # once per KZ transition — no throttle needed
    "kz_summary":     0,    # once per KZ close — no throttle needed
    "sweep":          0,    # one per level (swept flag prevents re-alerting)
    "fvg":           60,    # 1/min per (kz, direction) — verbose only
    "near_miss":    300,    # 5 min per (kz, reason) — prevents reject-storm
    "mss":          180,    # 3 min per (tf, direction) — verbose only
    # 2026-04-24 Bug H4: VPIN state chatter — 10 min per level so we
    # don't flood on oscillation around 0.55/0.70. "extreme" +
    # "normalized" bypass this entirely (critical, see send_vpin_alert).
    "vpin":         600,
}

# ---------------------------------------------------------------------------
# Risk Rules (HARDCODED — Sensei Rules)
# ---------------------------------------------------------------------------
RISK_PER_TRADE = 250          # $250 max risk per trade
MNQ_POINT_VALUE = 2.0         # USD per point per contract (4 ticks × $0.50)
MNQ_TICK_VALUE = 0.50         # USD per tick per contract (0.25 pts)
MNQ_TICK_SIZE = 0.25          # minimum price increment (used for order rounding)

# 2026-05-11 — KILL SWITCH SIMPLIFIED TO P&L-ONLY
# Old: 3 consecutive losses OR 3 total daily losses OR $750 daily P&L.
# Count-based gates blocked the bot prematurely on days where 3 small
# losses still left room for profit recovery. User decision Day 6:
# replace count gates with a single $900 P&L drawdown threshold
# (Topstep $50K DLL is $1,000 — $900 leaves a $100 buffer).
#
# 0 disables the count-based gates. Only KILL_SWITCH_AMOUNT remains.
KILL_SWITCH_LOSSES = 0        # 0 = disabled (was: 3 consecutive losses)
KILL_SWITCH_AMOUNT = 900      # $900 max daily P&L drawdown (was: 750)

# 2026-05-05 — DAILY TOTAL LOSSES KILL SWITCH (post-Day-2 audit)
# The existing KILL_SWITCH_LOSSES counts CONSECUTIVE losses — a winner
# resets the counter to 0. The 2024 full-year backtest revealed a hole:
# on 2024-03-11 the bot took 4 trades — 3 losses + 1 small win between
# them. consecutive_losses got reset by the win, but TOTAL losses for
# the day were still 3, daily P&L was -$1,501, and the bot busted MLL.
#
# This new gate trips on TOTAL losses regardless of order. After
# KILL_SWITCH_DAILY_LOSSES (default 3), halt for the rest of the day.
# Tighter than KILL_SWITCH_AMOUNT alone because it triggers BEFORE
# you've lost $750 — 3 small losses ($250 each = $750) gets you to the
# limit, but 3 mid losses ($300 + $400 + $500 = $1,200) blow past it.
KILL_SWITCH_DAILY_LOSSES = 0   # 2026-05-11: disabled — see KILL_SWITCH_AMOUNT above

# 2026-04-29 hardening — same-setup tighter kill-switch + cooldown.
# Caught 2026-04-29 NY PM: bot took 3 SHORTs at IDENTICAL entry/stop
# (27,199.25 / 27,212.75) within 35 min, all stopped out (-$331.50
# total). The 3-consecutive-losses kill_switch eventually halted but
# only AFTER the 3rd loss. These layered tighter guards stop earlier:
#
#   KILL_SWITCH_SAME_SETUP_LOSSES         — 2 losses at same price → halt
#   KILL_SWITCH_SAME_SETUP_PRICE_TOL_PTS  — "same" tolerance window
#   SB_SAME_SETUP_COOLDOWN_MIN            — strategy-side cooldown after
#                                            a stopout at same FVG zone
#   SB_SAME_SETUP_PRICE_TOL_PTS           — strategy "same" tolerance
KILL_SWITCH_SAME_SETUP_LOSSES = 2
KILL_SWITCH_SAME_SETUP_PRICE_TOL_PTS = 5.0
# 2026-05-04 — bumped 30→240 min after live caught same-setup re-fire:
# Trade 1 lost at 08:59 (cooldown ARMED 30min → expired 09:29).
# Trade 2 fired at 09:48 with IDENTICAL entry 27857/stop 27841 (49min later,
# 19min after cooldown expired) → lost same way. Both trades = -$384 net.
# 240min covers a full KZ window so same-setup can't repeat within session.
SB_SAME_SETUP_COOLDOWN_MIN = 240
SB_SAME_SETUP_PRICE_TOL_PTS = 5.0

# 2026-05-05 — MIN STOP FLOOR (post-Day-2 audit)
# Silver Bullet structural sweep should be of MAJOR liquidity (PDH/PDL/PWH/
# PWL/AH/AL or fresh HTF swings). When the sweep is just a small intraday
# pivot (5-8pt poke), the resulting stop is tiny and the position size
# auto-inflates past 10 contracts — turning a marginal setup into a max-
# size loss. Live caught 2026-05-05 London: 7.5pt stop, 12 contracts,
# −$180 in 4 minutes (full risk).
#
# Floor at 15pt — roughly the noise level of a 1-min MNQ bar. ICT-canonical
# sweeps of D1/W1 levels are 20-50pt on MNQ; setups below 15pt are
# overwhelmingly noise-grade pivots, not institutional liquidity grabs.
SB_MIN_STOP_POINTS = 15.0

# 2026-05-05 — MIN TARGET R/R (post-Day-2 audit feedback)
# A target less than 2× the stop distance is mathematically losing for
# most realistic WR. With the new SB_MIN_STOP_POINTS=15, the legacy
# MIN_FRAMEWORK_PTS=10 absolute floor was producing 0.67R targets where
# even 60% WR was barely breakeven.
#
# New rule: framework distance must give ≥ SB_MIN_TARGET_RR × stop_pts.
# Default 2.0 → with 15pt stop, target must be 30pt or more.
# At 2R, expectancy turns positive at WR > 33% — gives the strategy
# real edge headroom against backtest WR ~63%.
#
# Target selection now picks the NEAREST pool that satisfies the RR,
# not the absolute nearest. ICT canonical "next major liquidity pool"
# still holds — but if the next one is too close, skip to the one
# beyond. No valid pool ≥ required_target_pts → reject (framework_lt_2R).
SB_MIN_TARGET_RR = 2.0

# 2026-05-11 — MAX CAPS (Day 6 audit, Trade #5 lesson)
# Trade #5 (NY AM SHORT) had stop 59.5pt and target 19.04R — far outside
# any realistic ICT setup. The real problem was the 19R target (next
# qualifying pool 1,132 pts away), NOT the wide stop. A 50-80pt stop
# with a 2R+ target is mathematically valid (e.g., 80pt stop / 160pt
# target = 1:2 = same math as 15pt stop / 30pt target).
#
# Decision 2026-05-11: keep SB_MAX_TARGET_RR cap, disable
# SB_MAX_STOP_POINTS. Wide stops alone aren't disqualifying — only
# combined with disproportionate targets.
SB_MAX_STOP_POINTS = 0       # 0 = disabled (was: 30, too restrictive)
# 2026-05-12 (post London/NY AM audit): target cap removed. With
# TRADE_MANAGEMENT="trailing" the target order is skipped — bot trails
# until stopped. The "target" is just (a) initial RR math sanity at
# entry, and (b) telemetry. A distant target doesn't actually drag
# the trade out — trail captures whatever the move gives. Today's
# London had ~19 setups rejected by target_too_far where targets
# were 950+pts away (PDL/PWH/PWL all swept pre-session, next pool was
# AL@28245 = 30-60R away). Those would have been valid trail-managed
# trades — bot was MATEMATICALLY impossibilitated from trading the
# 134pt bearish move just because the framework picker couldn't find
# a closer named target. Disable cap; keep MIN_TARGET_RR=2.0 for
# math sanity. Note: Trade #5-style absurd 19R targets are still
# bounded by the stop floor (15pt) — they'd risk 1R = ~$30, trail
# handles the rest.
SB_MAX_TARGET_RR = 0         # 0 = disabled (was: 8.0, blocking valid trail trades)

# 2026-05-11 — STRUCTURE EVENT MAGNITUDE FILTER (Day 6 bug)
# The MarketStructureDetector calls every close-beyond-prior-swing a
# BOS / CHoCH / MSS — including breaks of just 1-2 pts. On chop days
# this produces a stream of noise "structural events" that the strategy
# treats as institutional signals. Day 6 example: 07:20 "CHoCH bear"
# came from a 13pt break of a recent swing low during a normal pullback
# inside a clear uptrend.
#
# Fix: require structural breaks to clear a minimum % of price. At
# NQ 29,300 a 0.05% filter is ~15pt — matches the SB stop floor and
# the realistic threshold for an institutional structural shift on
# 5-min. Tune via STRUCT_MIN_BREAK_PCT.
# 2026-05-11 PM revert: hybrid v20d baseline. Full-year 2025 backtest
# showed this filter (at 0.05) regressed P&L from +$83,740 (v20d biasflip)
# to +$25,054 (-70%). Live diagnosis revealed Day 6 chop was caused by
# cooldown re-fires + 7.5pt-stop bug, NOT structure noise. Real anti-chop
# already deployed via cooldown multi-stopout list (7292cc7), min_stop
# 15pt (ca03e19), bias-flip (bbb3a73), FVG-mitigate-on-any-close
# (d5570eb). Disabling magnitude filter restores v20d trade pace + WR.
STRUCT_MIN_BREAK_PCT = 0       # 0 = disabled (was: 0.05, too restrictive)

# 2026-05-12 — MSS confirmation follow-through magnitude filter.
# London audit 2026-05-12 found a fake "MSS bull @ 05:10 CT" confirmed
# with only +7.25pt of follow-through above the CHoCH bar close. The
# 5-min bar that triggered it closed 29238 vs CHoCH close of 29230.75.
# Price then dropped 117pt to 29121 — the fake MSS had blocked bearish
# setups via bias-flip gate for an hour. The MSS confirmation in the
# market_structure detector previously had NO magnitude filter (unlike
# BOS/CHoCH which can use STRUCT_MIN_BREAK_PCT). Fix: require the
# follow-through close to clear the CHoCH close by this % of price.
# Default 0.05% ≈ 15pt at NQ 29K — matches the BOS/CHoCH magnitude
# semantics. Set to 0 to disable.
STRUCT_MSS_MIN_FOLLOWTHROUGH_PCT = 0.05    # v20g config: MSS filter at 0.05% (catches fake MSS like 2026-05-12 London; zero effect in Q1 2025)

# 2026-05-14 — FIXED R TARGET (v20n experiment).
# Override the liquidity-based target with a fixed R-multiple. Default
# (0 = disabled) keeps "next unswept pool" logic. When > 0, target =
# entry ± (SB_FIXED_TARGET_R × stop_points). Trade-off:
#   PROS: guaranteed full +NR capture on winners that reach target
#   CONS: caps upside on >NR moves (Trade #3 today peak +4.36R would
#         have capped at +3R)
# Validation (≥2R, valid pool in direction) still applies — the fixed
# target only overrides the EXIT level, not the structural check.
# 2026-05-14 — Tested 3R (v20n: -12% P&L) and 2R (v20q: -14% P&L) vs
# v20g baseline ($18,621 Q1). Both fixed targets underperform the
# dynamic liquidity-based target. Trail+ratchet handles upside cap
# naturally; fixed target just removes good winners. Disabled.
SB_FIXED_TARGET_R = 0      # disabled — v20g uses liquidity-based target

# 2026-05-18 — SB CONFLUENCE GATES: TESTED & REJECTED (code removed)
#
# Two A/B experiments ran on 2026-05-18 (4 days of live + 3 years backtest):
#
#  A) SB_REQUIRE_HTF_BIAS = True  — mandatory `htf_bias_aligned` factor
#     Q1 2025 A/B: 86 trades (-53%), WR 62.8%, $8,797 (-63% vs baseline)
#     Killed counter-trend shorts that had OTHER quality factors.
#     Hard fail. Killed in Q1 alone — no need for cross-period.
#
#  B) SB_MIN_LIVE_CONFLUENCE = 1  — reject pure score=0 trades
#     Q1 2025 A/B:  185 trades, WR 67.6%, $29,510 vs baseline $23,911 (+23%) — looked great
#     Full 2025:    570 trades, $76,248 vs baseline $75,436 (+1.1%)         — Q1 fluke
#     2024 A/B:     940 trades, $128,196 vs baseline $143,283 (-10.5%)      — hostile regime
#     2023 A/B:    1110 trades, $152,366 vs baseline $153,981 (-1.0%)       — tie
#     3-year net:  -$15,891 (-4.3%). Cross-period FAIL.
#
# Deeper investigation (analysis/score_investigation/) revealed:
#   * Score=0 has HIGHEST WR (72-80%) AND highest avg P&L ($171-$182)
#     ACROSS ALL 3 YEARS. These are counter-trend mean-reversion shorts.
#   * Structural gates (sweep + FVG + MSS) already filter for quality.
#   * Score is paper-trail only — does NOT discriminate outcome.
#   * Stop-distance buckets: no threshold helps either. Mega-sweeps
#     (stop > 1.5% of entry) generate 54-69% of yearly P&L by themselves.
#
# Decision: canonical SB v4 RTH Mode — NO confluence gate. Live with score=0.
# Today's live losses on score=0 were variance, not pattern.
#
# Gate code REMOVED from strategies/silver_bullet.py (see follow-up commit
# after revert 4fef290). To reopen for future regime-aware research, the
# gate was placed right after `sb_breakdown`/`sb_reasons` are computed:
#     _min = int(config.cfg("SB_MIN_LIVE_CONFLUENCE", 0))
#     if _min > 0 and sb_score < _min: return None
# Plus a sibling factor-specific gate (SB_REQUIRE_HTF_BIAS).

# 2026-05-12 — R-STEP TRAIL (post NY AM audit experiment).
# NY AM trade 2026-05-12 reached +4.58R peak but trail (swing-based)
# exited at +1R = $184/3c. Left ~3.58R = ~$660 on the table.
# Proposed continuous R-step trail: trail = peak_R - buffer.
#   peak +2R → trail at 0R (break-even)
#   peak +3R → +1R
#   peak +4R → +2R
#   peak +NR (N≥2) → trail at (N - buffer)R
# Default buffer = 2R (always 2R away from peak).
# Backtester only for now — live bot's _manage_open_positions
# would need separate mirror update.
# 2026-05-12 — BOS EXHAUSTION GATE (ICT rule of three).
# After a Market Structure Shift (MSS) in the new trend direction, ICT
# canonical only considers the first 2 BOS continuation events as valid
# SB entry zones. Beyond that, the trend is in "exhaustion" territory
# and continuation entries lose statistically (mean reversion or larger
# retrace is more likely). Observed 2026-05-12 NY PM: bot fired SHORT
# 14 BOS bear past the MSS bear @ 09:45 — stop hit. Set to 0 to disable.
# 2026-05-13 — Disabled per full 2025 backtest comparison (v20g winner):
#   v20g (no gate):  451 trades, +$50,006, PF 2.55
#   v20j (gate=2):   364 trades, +$42,376, PF 2.57 (-$7.6K)
#   v20k (gate=3):   381 trades, +$44,148, PF 2.57 (-$5.9K)
# Gate cost more than it saved on full year. ICT "rule of three" doesn't
# materially improve PF (2.55 → 2.57 marginal), only cuts volume by 15-20%.
# Today 2026-05-12 NY PM short was a real exhaustion (14 BOS) but those
# extreme cases are rare; backtest dominance favors no-gate.
SB_MAX_BOS_AFTER_MSS = 0       # 0 = disabled (v20g final config)

# 2026-05-13 — OPPORTUNITY REPLACEMENT (Day 8 audit, post-Trade #3 duplicate).
# Default behavior was: any pending limit order blocks all subsequent
# signal evaluation via "single-position rule" — bot could be locked
# for 3-4 hours on a limit that never fills, missing better setups.
#
# This module enables 4 smart cancel/replace behaviors:
#
#   TIER 1 — Opposite-direction replace: new signal in opposite direction
#     ALWAYS replaces pending limit (bias has structurally flipped).
#
#   TIER 2 — Closer-fill replace: same direction, but new entry is
#     materially closer to current price (≥30% closer AND ≥5pt closer).
#     Higher probability of actually filling.
#
#   TIER 2.5 — Stale aging: after N bars without fill, ANY decent new
#     signal can replace the pending (priority decays).
#
#   TIER 1.5 — Bias-flip auto-cancel: if an opposite 5-min CHoCH/MSS
#     event registers AFTER the limit was placed, cancel proactively
#     (even without a new signal yet). The structural thesis is dead.
#
# Set OPPORTUNITY_REPLACE_ENABLED=False to disable all 4 features.
OPPORTUNITY_REPLACE_ENABLED = True
REPLACE_MIN_PROXIMITY_PCT = 0.70   # new must be ≤70% of pending distance
REPLACE_MIN_PROXIMITY_PTS = 5.0    # AND new must be ≥5pt closer than pending
STALE_LIMIT_BARS = 10              # bars without fill before stale-aging kicks in
AUTOCANCEL_ON_BIAS_FLIP = True     # cancel pending when opposite CHoCH/MSS fires

TRAIL_R_STEP_ENABLED = True     # v20g/v20i config: R-step trail enabled
TRAIL_R_STEP_BUFFER = 2.0
# 2026-05-12 — TRAIL_USE_SWING: when False, the swing-based trail is
# skipped entirely. v20i Q1 test confirmed disabling swing is CATASTROPHIC
# (WR 70%→36%, P&L +$18K → -$814). Swing trail does critical work at
# 0-2R range that R-step + ratchet alone can't replicate. Keep TRUE.
TRAIL_USE_SWING = True

# 2026-05-11 — HTF DISPLACEMENT OVERRIDE (Day 6 bug)
# If a recent 5-min displacement is in the OPPOSITE direction with
# significant magnitude, counter-trend setups become institutional
# fades and consistently lose. Day 6 Trade #5: bot fired SHORT 6 min
# after a +132pt bull spike. Override blocks the trade.
#
# Activation: last displacement on 5-min within
# SB_HTF_DISP_OVERRIDE_WINDOW_MIN AND magnitude >=
# SB_HTF_DISP_OVERRIDE_MIN_PTS → reject opposite-direction setups.
# 2026-05-11 PM revert: disabled per v20d hybrid baseline. The Day 6
# counter-trend short trade (Trade #5) was caused by a 19R target setup,
# already neutralized by SB_MAX_TARGET_RR=8.0 above. v20d biasflip
# backtest 2025 had no such override and scored 72.4% WR / +$83,740 —
# adding this filter cut WR -10pp without reducing DD materially.
SB_HTF_DISP_OVERRIDE_ENABLED = False   # was: True (over-filtered NY AM/PM)
SB_HTF_DISP_OVERRIDE_WINDOW_MIN = 30   # only last N min counts (if re-enabled)
SB_HTF_DISP_OVERRIDE_MIN_PTS = 80      # min magnitude to trigger (if re-enabled)

# 2026-04-30 v19a — DISABLED time-based age caps for sweeps and structure.
# ICT canonical: sweeps and structure events expire by PRICE ACTION, not by
# clock time. The age caps were anti-selective — they preferentially rejected
# the highest-quality late-KZ trades (London +60-+165min buckets had 70-94%
# WR but were systematically blocked).
#
# Investigation evidence (V15_REGRESSION_INVESTIGATION_2026_04_30.md):
#   - 7-yr backtest 2019-2025: v15 (60min cap) cut $425K (-65%) vs no-cap baseline
#   - 3,239 rejected trades >=60min into KZ had 69.4% WR — better than baseline
#   - 2026-04-30 LIVE: 117 NY AM evals + 54 NY PM evals rejected as stale_sweep
#     for ICT-textbook setup (LL@27185 swept → bull FVG @27270-78 → BOS bull
#     @07:20). Trade missed.
#
# Replaced by:
#   - LiquidityDetector.check_post_sweep_invalidation (close-back rule)
#   - SB_INVALIDATOR_OPPOSITE_COUNT (counter-event count for structure)
#
# Backtest validation (single year smoke + Q1 2025 sanity 2026-04-30):
#   - 2019: v19a $74.7K vs v15 $13K (+476%, recovered v14 baseline)
#   - Q1 2025: v19a $25.3K vs v15 $20.6K (+23%, did NOT regress trended)
#   - WR 57.4% (chop) / 60.9% (trend), PF 2.05 / 2.82, MaxDD same or lower
#
# To re-enable: set to 60 (v15) or 90 (v18 middle). 0 = ICT canonical (off).
SB_MAX_SWEEP_AGE_MINUTES = 0           # v19a: rely on close-back invalidation

# 2026-04-29 hardening — Fix #5: max-age + smart invalidator for 5-min struct.
# Caught NY PM 2026-04-29: bot fired 3 SHORTs against fresh BULLISH structure
# (CHoCH bull 13:55, MSS bull 14:00, BOS bull 14:15+) using STALE bear MSS
# from 11:45 CT (1h 46min - 2h 21min stale). Bug G original (single-event
# invalidator) was too aggressive in backtest — Q1 2025 v10 collapsed.
# This SMART version uses two thresholds:
#
#   Gate A — MAX_STRUCT_AGE: aligned event must be < N min old
#   Gate B — INVALIDATOR_COUNT + WINDOW: only invalidate if N+ opposite events
#            in M-min window (filters single-pullback noise from real flips)
#
# v19a (2026-04-30): Gate A DISABLED, Gate B kept. The 04-29 incident is still
# caught by Gate B (3 fresh bull events in 30min ≥ 2 → bear MSS invalidated).
# Gate A was the over-filter — see V15_REGRESSION_INVESTIGATION for evidence.
SB_STRUCT_INVALIDATOR_ENABLED = True
SB_MAX_STRUCT_AGE_MINUTES = 0         # v19a: rely on Gate B + close-back
SB_INVALIDATOR_OPPOSITE_COUNT = 2     # need 2+ opposite events to invalidate
SB_INVALIDATOR_WINDOW_MIN = 30        # within last 30 minutes from current bar

# 2026-04-29 hardening — Fix #6: FVG quality filter.
# Caught NY PM trade #4 2026-04-29: FVG was 3pt wide with 19.25pt stop
# (candle 1 had 11.25pt upper wick = indecision, not displacement). FVG
# entered, mitigated 1 bar later, stopped out for -$115.50.
#
# 2026-04-30 v19a: DISABLED. Backtest 2019 ablation showed Fix #6 was THE
# largest over-filter (~$50K cost in 2019 alone, ~63% of total v15→v19a
# delta). ICT canonical does NOT require minimum FVG width — the 3-candle
# imbalance is sufficient (candle1.high < candle3.low for bull). The 2pt
# + 0.20 ratio thresholds were our invention without ICT basis.
#
# The 04-29 NY PM trade #4 loss was a single sample; over 7 years this
# filter cuts hundreds of valid micro-FVG setups. Bad trade-off.
SB_FVG_QUALITY_ENABLED = False        # v19a: ICT canonical, no width filter
SB_MIN_FVG_WIDTH_PTS = 2.0            # (irrelevant — gate disabled)
SB_MIN_FVG_TO_STOP_RATIO = 0.20       # (irrelevant — gate disabled)


# 2026-04-30 — HTF Continuation strategy (second strategy, complements SB).
# Setup: Daily bias bullish/bearish + price in discount/premium + pullback
# into 5-min OB or FVG. ICT canonical (Daily candle anatomy: accumulation →
# manipulation → distribution). Mutually-exclusive ~80% of time vs SB.
#
# Stop sizing: structural (last 5min swing - 1tick), capped to:
#   MIN 15pt — avoid wick-stop-outs on tight blocks
#   MAX 80pt — keep 2R intraday-achievable
HTF_CONT_STOP_MIN_PTS = 15.0
HTF_CONT_STOP_MAX_PTS = 80.0
HTF_CONT_PROXIMITY_PTS = 5.0          # how close to OB.proximal to fire
HTF_CONT_MAX_TRADES_PER_ZONE = 1      # 1 setup per KZ → 3 trades/day max

# Same-setup cooldown (Fix #3 analog, falls back to SB_SAME_SETUP_*).
HTF_CONT_SAME_SETUP_COOLDOWN_MIN = 30
HTF_CONT_SAME_SETUP_PRICE_TOL_PTS = 5.0


# 2026-04-29 hardening — news blackout. SWC daily mood explicitly
# warned about FOMC at 12:00 CT today; bot took 3 trades AFTER FOMC
# during the post-announcement whipsaw, all losers. New gate skips
# trading around scheduled high-impact events.
NEWS_BLACKOUT_MIN_BEFORE = 30   # block N min BEFORE event
NEWS_BLACKOUT_MIN_AFTER = 60    # block N min AFTER event
NEWS_BLACKOUT_MIN_RISK = "high" # 'high' or 'extreme' triggers blackout
NEWS_BLACKOUT_ENABLED = True

# 2026-05-19 — NY OPEN BUFFER (SHIPPED after cross-period A/B + placebo)
# NY has TWO open events that produce liquidity wicks in equity index
# futures within their first ~15 min:
#   1. 08:30 ET (07:30 CT) — pre-market open + scheduled data releases
#   2. 09:30 ET (08:30 CT) — stock market cash open (NYSE/NASDAQ)
#
# Live demonstration (2026-05-19): NA1+NA2 lost $405 to the 09:30 ET
# cash-open wick (NA2 filled @28907 at 08:30:31, stopped @28924.75 at
# 08:30:32 CT — 1 second in trade).
#
# 3-year cross-period A/B with BEFORE=10/AFTER=15:
#   Year  | Baseline       | Treatment        | Δ
#   2023  | $153,981       | $183,424         | +$29,443 (+19.1%)
#   2024  | $143,283       | $158,910         | +$15,627 (+10.9%)
#   2025  | $75,436        | $85,075          | +$9,639  (+12.8%)
#   3-yr  | $372,701       | $427,409         | +$54,708 (+14.7%)
#
# PLACEBO TEST (10:30 CT random buffer, 3 years):
#   Year  | Baseline       | Placebo @10:30   | vs Treatment @08:30
#   2023  | $153,981       | $183,176 (+19%)  | ~tie (placebo equally good)
#   2024  | $143,283       | $134,506 (-6%)   | treatment +$24,404 better
#   2025  | $75,436        | $80,564 (+7%)    | treatment +$4,511 better
#   3-yr  | $372,701       | $398,246 (+6.9%) | treatment +$29,164 (+8.6%)
#
# Decomposition: cascade effect = +6.9%, microstructure-specific = +8.6%.
# Both effects are real. Cascade preserves kill_switch + position budget
# (any mid-NY-AM blackout helps); microstructure-specific shows in 2024
# (Fed pivot regime) where 08:30 CT wick had unique characteristics.
#
# Trade count: treatment has MORE trades than baseline (+211 across 3yr).
# Mechanism: blocking the wick window preserves consecutive_losses
# counter → bot doesn't trip kill_switch → more later setups accepted.
# CAVEAT — carry-in position exposure (deferred, see CLAUDE.md
# Pendientes watch-list). The gate rejects NEW signals during the buffer
# but does NOT touch positions already open going into the buffer:
#   * Winner with trail stop: wick can harvest trail at adverse price
#     → exits with less profit. Existing 1-min trail + ratchet provide
#     partial protection but not buffer-aware.
#   * Loser open at buffer start: stop gets slipped by wick, AND
#     increments consecutive_losses → can trip kill_switch, defeating
#     the cascade effect the buffer is meant to preserve.
# Frequency in practice is low (SB trades typically last 5-50 min
# within their own KZ). Mitigation paths (in order of intervention):
#   1. Hold stops static during buffer (minimal change)
#   2. Pre-buffer aggressive ratchet at -5 min (lock +0.5R if winner)
#   3. Force flatten at -5 min (Combine-mode, not paper-research)
# Revisit if live evidence shows the failure mode hurting us.
NY_OPEN_EVENTS_CT = [(7, 30), (8, 30)]   # (hour, minute) tuples in CT
NY_OPEN_BUFFER_BEFORE_MIN = 10  # block 10 min before each event
NY_OPEN_BUFFER_AFTER_MIN = 15   # block 15 min after each event

# 2026-05-19 — DAILY_PROFIT_CAP raised for paper-mode research.
# In a real Combine, $1,500/day is the canonical cap (lock the win,
# preserve the trailing drawdown buffer). But in paper-trading research
# mode we WANT full-day data — capping at $1,500 means we lose all NY AM
# and NY PM observations on days like 2026-05-19 where London alone hit
# the target by 05:14 CT.
#
# When transitioning to live Combine: revert to 1500.
DAILY_PROFIT_CAP = 10000      # paper research — effectively off (real Combine = 1500)
HARD_CLOSE_HOUR = 15          # 3:00 PM CT — flatten everything
HARD_CLOSE_MINUTE = 0
MIN_CONFLUENCE = 7            # Minimum 7/20 to take a trade
MAX_MNQ_TRADES_PER_DAY = 15  # Global daily cap. Silver Bullet v4 RTH Mode
                              # uses kill_switch (3 consecutive losses) + per-KZ
                              # reset as the real guards; this is an upper bound
                              # that lets 3 zones × ~5 attempts each fit comfortably.
                              # Was 3 (NY AM Reversal era) — too tight for RTH SB.
MAX_CONTRACTS = 50            # Max 50 MNQ contracts
TRADE_MANAGEMENT = "trailing"  # "fixed" | "partials_be" | "trailing"

# Topstep Compliance
TOPSTEP_MLL = 2000            # Maximum Loss Limit: $2,000
TOPSTEP_DLL = 1000            # Daily Loss Limit: $1,000
TOPSTEP_PROFIT_TARGET = 3000  # $50K Combine profit target
TOPSTEP_ACCOUNT_SIZE = 50000  # $50K Combine

# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------
HEARTBEAT_INTERVAL_S = 5      # Write to Supabase every 5s
HEARTBEAT_OFFLINE_S = 15      # 15s without heartbeat = OFFLINE
HEARTBEAT_ALERT_S = 30        # 30s = RED ALERT
HEARTBEAT_FLATTEN = True      # Flatten all on heartbeat failure

# ---------------------------------------------------------------------------
# VPIN Toxicity Levels
# ---------------------------------------------------------------------------
# 2026-05-04: VPIN_SHIELD_ENABLED defaults to False for live-vs-backtest
# parity. The 7-yr Silver Bullet backtest ($1.17M NQ, $818K ES, $1.36M YM)
# was run WITHOUT VPIN — the backtester never imports the toxicity module
# and no setup is gated on VPIN. In live, VPIN was halting/down-sizing
# trades that the backtest took at full size, creating a measurable
# divergence (e.g. 2026-05-04 NY PM trade fired at VPIN 0.621 with size
# reduced 4→3 contracts). To compare live performance to backtest fairly,
# the shield is OFF: VPINEngine is not initialized, set_vpin_overrides
# is never called, no halt/flatten triggers from VPIN.
#
# Re-enable later if a live A/B shows VPIN's missed-trade cost is smaller
# than its phantom-loser-prevention benefit. Until then, parity > theory.
VPIN_SHIELD_ENABLED = False
VPIN_CALM = 0.35              # < 0.35: Calm — normal trading
VPIN_NORMAL = 0.45            # 0.35-0.45: Normal — normal trading
VPIN_ELEVATED = 0.55          # 0.45-0.55: Elevated — alert only
VPIN_HIGH = 0.70              # 0.55-0.70: High — tighten stops, -25% size, +1 min confluence
VPIN_EXTREME = 0.70           # > 0.70: EXTREME — FLATTEN ALL. HALT TRADING.
VPIN_HIGH_SIZE_REDUCTION = 0.25   # Reduce position size by 25% when VPIN high
VPIN_HIGH_CONFLUENCE_BUMP = 1     # Add +1 to min confluence when VPIN high

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
# IFVG (Inverted Fair Value Gap) fallback — when a regular FVG is not
# available in the bias direction, NY AM Reversal used to fall back to the
# IFVG pool. Backtests (2024 full year, both with and without the fallback)
# showed ZERO impact on trade count / P&L — the regular FVG pool is always
# populated enough that the IFVG path never fires in practice. Disabled
# 2026-04-19 to shrink the active surface area. Set to True to reactivate;
# the scripts/run_backtest.py `--no-ifvg` flag is the ablation override.
IFVG_ENABLED = False

# ---------------------------------------------------------------------------
# Confluence Scoring
# ---------------------------------------------------------------------------
# Weights sum to 19, so the ACHIEVABLE max is 19 — MAX_CONFLUENCE used to
# advertise 20 which was a drift between the table and the actual
# factors (audit finding 2026-04-17). The tier thresholds (12+=A+, 9+=high,
# 7+=standard) are calibrated against the real ceiling and unchanged.
# If a 20th factor is added in the future, bump MAX_CONFLUENCE accordingly.
CONFLUENCE_WEIGHTS = {
    "liquidity_grab":       2,   # ICT
    "fair_value_gap":       2,   # ICT
    "order_block":          2,   # ICT
    "market_structure_shift": 2, # ICT
    "kill_zone":            1,   # Time
    "ote_fibonacci":        1,   # ICT
    "htf_bias_aligned":     1,   # ICT HTF
    "htf_ob_fvg_alignment": 1,   # ICT HTF
    "target_at_pdh_pdl":    1,   # ICT
    "sentiment_alignment":  1,   # SWC
    "gex_wall_alignment":   2,   # GEX
    "gamma_regime":         1,   # GEX
    "vpin_validated_sweep":  1,  # VPIN
    "vpin_quality_session":  1,  # VPIN
}
# Derived — single source of truth is CONFLUENCE_WEIGHTS above.
MAX_CONFLUENCE = sum(CONFLUENCE_WEIGHTS.values())

# Confluence tiers
CONFLUENCE_A_PLUS = 12        # 12+ = A+ full position
CONFLUENCE_HIGH = 9           # 9-11 = high confidence
CONFLUENCE_STANDARD = 7       # 7-8 = standard
# < 7 = NO TRADE

# ---------------------------------------------------------------------------
# Risk Ladder + Per-KZ Loss Caps (2026-04-22 Combine-aware sizing)
# ---------------------------------------------------------------------------
# Default flat-$250 risk per trade + 3-consecutive-loss kill switch (existing
# RISK_PER_TRADE / KILL_SWITCH_LOSSES) is NOT legal in the Topstep $50K
# Combine — the current per-KZ reset allows up to 3 × 3 = 9 losses in a day
# (-$2,250) which breaks the $1,000 DLL on trade #4. Live paper works
# because no broker enforces the DLL halt, but Combine will bust us.
#
# Two independent knobs — toggle both OFF by default for backward-compat
# with existing backtests / walk-forward JSONs:
#
# 1. RISK_LADDER — step down risk after each loss so we get 5 shots instead
#    of 3 inside the same DLL budget:
#       trade 1 loss: $250 risk (cumul -$250)
#       trade 2 loss: $200         (cumul -$450)
#       trade 3 loss: $150         (cumul -$600)
#       trade 4 loss: $100         (cumul -$700)
#       trade 5 loss: $50          (cumul -$750, $250 buffer to DLL)
#    After 5 losses → hard halt for the day.
#    Wins do NOT reset the ladder (C3 variant — eliminates martingale-like
#    reset-after-win pattern). Position size for trade N depends only on
#    losses_today count, not the cumulative PnL.
#
# 2. KZ_LOSS_CAPS — cap losing trades per kill zone so one bad KZ can't
#    burn all daily shots. London's higher inherent loss rate (36% WR on
#    2024 vs 47% NY AM) means we want to bleed less there. Default cap
#    of 2 for London lets NY AM/PM still take setups after a bad London.
#
# Enable via:
#   - config: set RISK_LADDER_ENABLED = True
#   - backtest CLI: --risk-ladder 250,200,150,100,50 --kz-loss-cap london=2
#   - live: read from .env if you want runtime override
# ---------------------------------------------------------------------------
RISK_LADDER_ENABLED: bool = False
RISK_LADDER: tuple = (250, 200, 150, 100, 50)  # risk amounts by loss-count
# Per-kill-zone cap on LOSING trades in a single day. Zones not listed have
# no cap (only the ladder/DLL/kill-switch limits apply). Empty dict = no
# KZ caps globally.
KZ_LOSS_CAPS: dict = {}   # default off; set e.g. {"london": 2} to enable

# ---------------------------------------------------------------------------
# Silver Bullet — applicable confluence subset (Option B display, 2026-04-22)
# ---------------------------------------------------------------------------
# SB uses a different entry model than NY AM Reversal — it enters on FVG
# proximal edge (not OTE fib), it does NOT require HTF bias, and it does not
# scope HTF OB/FVG overlay. Additionally, its 5 structural requirements
# (sweep, FVG, MSS, kill_zone, framework>=10pts) are HARD GATES — without
# them the signal never reaches the scorer, so scoring them would add +7
# guaranteed points that don't discriminate A+ from standard setups.
#
# SB_APPLICABLE_FACTORS is the subset of CONFLUENCE_WEIGHTS keys that
# actually differentiate SB setup quality. The engine still uses the full
# 19-pt scorer internally for historical compatibility (Signal /Trade DB
# columns, 7 years of backtest comparability) — but logs + Telegram show
# the SB-applicable sub-score alongside the full score so the number is
# interpretable at a glance.
#
# Derivation: in strategies/silver_bullet.py.evaluate(), the scorer call
# passes sweep, fvgs, obs, structure_event, kill_zone=True, htf_bias,
# key_levels + live edge state (SWC/GEX/VPIN). It does NOT pass
# swing_high/swing_low (so ote_fibonacci never scores) nor htf_fvgs/htf_obs
# (so htf_ob_fvg_alignment never scores). Of the remaining 12 factors, the
# 4 structural ones (liquidity_grab, fair_value_gap, market_structure_shift,
# kill_zone) are gates — we exclude them from the sub-score too.
SB_APPLICABLE_FACTORS = {
    "target_at_pdh_pdl",      # +1 — target quality: institutional pool vs intraday
    "order_block",            # +2 — Institutional Orderflow Entry Drill
    "htf_bias_aligned",       # +1 — nice-to-have, not required by ICT
    "sentiment_alignment",    # +1 — SWC
    "gex_wall_alignment",     # +2 — dealer hedging flow reinforcement
    "gamma_regime",           # +1 — vol regime
    "vpin_validated_sweep",   # +1 — institutional flow confirmation
    "vpin_quality_session",   # +1 — non-toxic session
}
# The SB-applicable denominator — sum of those 8 factors' weights.
SB_APPLICABLE_MAX = sum(CONFLUENCE_WEIGHTS[k] for k in SB_APPLICABLE_FACTORS)  # 10

# 2026-05-05 — SB_LIVE_FACTORS: the subset of SB_APPLICABLE_FACTORS that
# can actually score under the current engine configuration. The full
# theoretical max (SB_APPLICABLE_MAX = 10) assumes every data feed is
# wired up: VPIN ticks, GEX options OI, SWC sentiment, OB detection.
# In live today:
#   * VPIN_SHIELD_ENABLED = False  → vpin_validated_sweep, vpin_quality_session = 0
#   * No GEX options data loader   → gex_wall_alignment, gamma_regime = 0
#   * SWC active (Finnhub + news)  → sentiment_alignment scoreable
#   * OB detector wired            → order_block scoreable
#   * HTF bias function wired      → htf_bias_aligned scoreable
#   * tracked_levels seeded        → target_at_pdh_pdl scoreable
#
# So the LIVE-attainable max is 5 pts. Logs + post_mortem + Telegram
# should display X / SB_LIVE_MAX so a "2/5" reads as "40% of attainable
# quality" not "20% of theoretical-max-with-modules-we-don't-run".
#
# When VPIN/GEX get re-enabled, add their factor names back to
# SB_LIVE_FACTORS to lift the live max accordingly.
SB_LIVE_FACTORS = {
    "target_at_pdh_pdl",      # +1 — tracked_levels active
    "order_block",            # +2 — OB detector active
    "htf_bias_aligned",       # +1 — HTF bias function wired
    "sentiment_alignment",    # +1 — SWC active
    # +0 — gex_wall_alignment   (no options loader)
    # +0 — gamma_regime         (no options loader)
    # +0 — vpin_validated_sweep (VPIN_SHIELD_ENABLED=False)
    # +0 — vpin_quality_session (VPIN_SHIELD_ENABLED=False)
}
SB_LIVE_MAX = sum(CONFLUENCE_WEIGHTS[k] for k in SB_LIVE_FACTORS)  # 5

# ---------------------------------------------------------------------------
# Timeframes
# ---------------------------------------------------------------------------
TIMEFRAMES = {
    "1min": 1,
    "5min": 5,
    "15min": 15,
    "1H": 60,
    "4H": 240,
    "D": 1440,
    "W": 10080,
}

# ---------------------------------------------------------------------------
# Kill Zones (CT — Central Time)
# ---------------------------------------------------------------------------
KILL_ZONES = {
    "asian": {
        "start": (20, 0),    # 8:00 PM CT
        "end": (0, 0),       # 12:00 AM CT
    },
    # 2026-05-01 — v19a-WIDE: Kill zones widened to non-overlapping full
    # ICT sessions for Silver Bullet. Backtest 7-yr 2019-2025 confirmed
    # +97.9% P&L boost ($591K → $1.17M) vs narrow KZ. WR 63.3%, PF 3.30.
    # See SCALING_TO_MALDIVAS.md for full math + plan.
    #
    # London: 02:00-08:30 ET = 01:00-07:30 CT (institutional London open
    #         through NY pre-open handover)
    # NY AM:  08:30-13:00 ET = 07:30-12:00 CT (NY indices open through
    #         lunch / NY PM transition)
    # NY PM:  13:00-16:00 ET = 12:00-15:00 CT (NY PM through close)
    "london": {
        "start": (1, 0),     # 1:00 AM CT  (2:00 AM ET)
        "end": (7, 30),      # 7:30 AM CT  (8:30 AM ET) — was 4:00
    },
    "london_silver_bullet": {
        "start": (2, 0),     # 2:00 AM CT  (3:00 AM ET) — inside London KZ
        "end": (3, 0),       # 3:00 AM CT  (4:00 AM ET)
    },
    "ny_am": {
        "start": (7, 30),    # 7:30 AM CT  (8:30 AM ET) — was 8:30
        "end": (12, 0),      # 12:00 PM CT (1:00 PM ET)
    },
    "ny_pm": {
        "start": (12, 0),    # 12:00 PM CT (1:00 PM ET) — was 13:30
        "end": (15, 0),      # 3:00 PM CT  (4:00 PM ET)
    },
    "silver_bullet": {
        # ICT canonical (2026-04-20 audit): AM Silver Bullet is 10:00-11:00 ET
        # = 9:00-10:00 CT. Previous 10:00-11:00 CT was wrong by 1 hour — the
        # bot was firing Silver Bullet setups a full hour after the
        # algorithmic window had closed. ICT windows are ALWAYS ET.
        "start": (9, 0),     # 9:00 AM CT = 10:00 AM ET
        "end": (10, 0),      # 10:00 AM CT = 11:00 AM ET
    },
    "pm_silver_bullet": {
        # ICT PM Silver Bullet window: 2:00-3:00 PM ET = 1:00-2:00 PM CT.
        # Third and last Silver Bullet window of the NY session day.
        "start": (13, 0),    # 1:00 PM CT = 2:00 PM ET
        "end": (14, 0),      # 2:00 PM CT = 3:00 PM ET
    },
}

# ---------------------------------------------------------------------------
# Strategy Parameters
# ---------------------------------------------------------------------------
STRATEGIES = {
    "ny_am_reversal": {
        "rr_ratio": 3.0,           # 1:3 Risk:Reward
        "entry_tf": "5min",
        "context_tf": "15min",
        "bias_tf": ["D", "W"],
        "kill_zone": "ny_am",
        "max_trades_per_day": 2,
    },
    "silver_bullet": {
        "rr_ratio": 2.0,           # 1:2 Risk:Reward
        "entry_tf": "1min",
        "context_tf": "5min",
        "kill_zone": "silver_bullet",
        "max_trades_per_day": 1,
    },
    "swing_htf": {
        "rr_ratio": 2.0,           # 1:2 Risk:Reward
        "entry_tf": "4H",
        "context_tf": "D",
        "bias_tf": ["W"],
        "max_positions": 5,
        "hold_days_min": 2,
        "hold_days_max": 15,
    },
}

# ---------------------------------------------------------------------------
# Strategy Lab — 9 Anti-Overfit Gates
# ---------------------------------------------------------------------------
LAB_GATES = {
    "sharpe_improvement": 0.1,        # >= +0.1
    "win_rate_max_degradation": -0.02, # < -2%
    "drawdown_max_increase": 0.10,     # < +10%
    "walk_forward_positive": 0.70,     # >= 70% windows positive
    "cross_instrument_min": 2,         # 2 out of 3 (NQ, ES, YM)
    "cross_instrument_total": 3,
    "noise_max_degradation": 0.30,     # < 30% degradation
    "inversion_must_lose": True,
    "occam_max_new_params": 2,         # <= 2 new parameters
    "validation_must_improve": True,
}

# Data splits (LOCKED)
LAB_DATA_SPLITS = {
    "train": (2019, 2022),
    "validation": (2023, 2023),
    "test": (2024, 2025),             # LOCKED — requires auth code
}
LAB_TEST_AUTH_PREFIX = "JUAN_APPROVED_FINAL_TEST"

# ---------------------------------------------------------------------------
# Swing Point Detection — lookback bars on each side
# ICT: tighter lookback on lower TFs, wider on HTF
# ---------------------------------------------------------------------------
SWING_LOOKBACK = {
    "1min":  3,
    "5min":  5,
    "15min": 4,
    "1H":    3,
    "4H":    3,
    "D":     3,
    "W":     2,
}
SWING_MAX_HISTORY = 50   # Keep last 50 swing points per detector instance

# ---------------------------------------------------------------------------
# GEX (Gamma Exposure)
# ---------------------------------------------------------------------------
GEX_REFRESH_INTERVAL_MIN = 30  # Refresh GEX data every 30 minutes

# ---------------------------------------------------------------------------
# FVG Mitigation Mode
# ICT rule (2026-04-20 video): an FVG is only INVALIDATED when a candle
# BODY closes beyond the distal edge. Wicks through the gap do not count.
# 50-75% fill is NORMAL retrace / add-position zone per ICT, NOT invalidation.
#
# Modes:
#   "body_close" — ICT canonical: bullish FVG invalid when close < bottom,
#                  bearish FVG invalid when close > top. No ratio.
#   "ratio"      — legacy: FVG marked mitigated at FVG_MITIGATION_RATIO fill.
#                  Kept for backward-compat and A/B testing only.
# ---------------------------------------------------------------------------
# 2026-04-25: which strategies are allowed to fire signals in live mode.
# Backtester ignores this flag (it takes --strategy from CLI). Set this to
# the tuple of strategies to ENABLE — anything not listed gets skipped in
# main._evaluate_strategies. Default: SB only while we focus live trading
# on Silver Bullet. To re-enable NY AM Reversal: add "ny_am_reversal".
STRATEGIES_ENABLED = ("silver_bullet",)

# 2026-04-27: ICT canonical session ranges for liquidity tracking.
# Each session's running high/low becomes a LiquidityLevel after the
# session closes (AH/AL, LH/LL, NAH/NAL, NPH/NPL). These join PDH/PDL/
# PWH/PWL as valid sweep targets — Silver Bullet's gate now accepts
# the full ICT taxonomy of pools, not just daily/weekly references.
# Times are CT (US/Central). NY AM uses the canonical ICT 7-9 CT range
# distinct from the wider trading kill zone (8:30-12 CT).
# 2026-05-01 — Session windows aligned to KZ trading windows for cleaner
# H/L tracking. Non-overlapping. Asian extended to capture full overnight
# (CME re-open 17:00 → London open 01:00). Each session's H/L becomes
# tracked liquidity for the NEXT session's sweep targets.
SESSION_RANGES = {
    "asian":  {"start": (17, 0),  "end": (1, 0),   "high_type": "AH",  "low_type": "AL"},
    "london": {"start": (1, 0),   "end": (7, 30),  "high_type": "LH",  "low_type": "LL"},
    "ny_am":  {"start": (7, 30),  "end": (12, 0),  "high_type": "NAH", "low_type": "NAL"},
    "ny_pm":  {"start": (12, 0),  "end": (15, 0),  "high_type": "NPH", "low_type": "NPL"},
}

FVG_MITIGATION_MODE = "body_close"   # "body_close" (ICT) | "ratio" (legacy)
FVG_MITIGATION_RATIO = 0.75          # only used when FVG_MITIGATION_MODE == "ratio"
# 2026-04-24 Batch 4: made explicit (was silent default in detectors/fair_value_gap.py).
# Maximum FVG history per timeframe before oldest are pruned.
FVG_MAX_HISTORY = 100

# ---------------------------------------------------------------------------
# OB Proximity Gate
# ICT entry requirement: price must be AT or inside the OB when the signal
# fires. This constant is the maximum allowed distance above OB.high (long)
# or below OB.low (short) before the signal is rejected.
# London session fire at 44 pts above OB.high (2026-04-20) confirmed the
# need for this gate — market orders that far from the OB are not OB entries.
# ---------------------------------------------------------------------------
OB_PROXIMITY_TOLERANCE = 3.0      # pts — max gap from OB edge to current price

# 2026-04-24 Batch 4: made explicit (were silent defaults in detectors/order_block.py).
OB_MAX_HISTORY = 100          # max OBs retained per timeframe
OB_ATR_MULTIPLIER = 1.5       # LEGACY — no longer used for displacement (v3b uses ATR_FLOOR)
OB_ATR_PERIOD = 14            # ATR window for OB_DISPLACEMENT_ATR_FLOOR
OB_SWEEP_LOOKBACK = 5         # bars before OB candle to search for liquidity sweep
OB_FVG_LOOKFORWARD = 3        # bars after OB candle to find the confirming FVG

# ---------------------------------------------------------------------------
# Limit Order TTL
# Unfilled limit entry orders are cancelled after this many 1-min bars.
# With a 5-min entry TF, 10 bars ≈ 50 min — enough for a retrace to the OB
# without holding through the next major session move.
# ---------------------------------------------------------------------------
LIMIT_ORDER_TTL_BARS = 10         # cancel unfilled limit entry after N bars

# ---------------------------------------------------------------------------
# OB Age Decay
# OBs older than OB_MAX_AGE_BARS × 5-min bars are expired automatically.
# 500 bars × 5 min = 2500 min ≈ 41h RTH ≈ 6.4 trading days.
#
# Rationale 2026-04-20 (v3b revert): ICT methodology says OBs do not expire
# by time — only by narrative/bias change. v2/v3a ran with AGE=96 as a
# safety net; with FVG-required + Mean Threshold mitigation + ATR floor on
# displacement (all added in v3), stale OBs self-purge and the aggressive
# age cap no longer earns its keep. Reverting to 500 gives OBs the runway
# ICT intends while still providing a hard ceiling for truly stale state.
# ---------------------------------------------------------------------------
OB_MAX_AGE_BARS = 500             # 5-min bars; ~41h RTH (~6 trading days) before OB expires

# ---------------------------------------------------------------------------
# OB Detection — ICT canonical rules (2026-04-20)
# ---------------------------------------------------------------------------
# FVG-required filter (ICT hard rule): "without imbalance there is no order
# block". Enforces that every OB emitted by the detector has an associated
# FVG in the same direction within OB_FVG_LOOKFORWARD bars. If the FVG is
# missing, the candle is NOT recorded as an OB.
OB_REQUIRE_FVG = True
# Displacement magnitude — AND of two conditions (v3b 2026-04-20):
#   1. body >= OB_DISPLACEMENT_BODY_RATIO × OB body  (ICT proportional rule:
#      "two to three times that as a rally away")
#   2. body >= OB_DISPLACEMENT_ATR_FLOOR × ATR(14)   (noise floor — keeps
#      tiny ranging-market setups from passing the proportional check with
#      a 2pt-OB × 2 = 4pt displacement that is pure chop)
# v3a used only rule 1 and produced 30% more low-quality trades. ICT
# traders implicitly apply a visual noise filter; in code we need the
# ATR floor to stand in for it.
OB_DISPLACEMENT_BODY_RATIO = 2.0
OB_DISPLACEMENT_ATR_FLOOR = 1.0
# Mean Threshold — OB mitigated when close crosses the 50% point of the
# OB body (open-to-close midpoint, NOT wick-to-wick). Bullish OB mitigated
# when close < mean_threshold; bearish OB mitigated when close > mean_threshold.
# "measure the open to the close on the down candle... do not use the wicks"
OB_MEAN_THRESHOLD_RATIO = 0.50

# ---------------------------------------------------------------------------
# Database Tables
# ---------------------------------------------------------------------------
DB_TABLES = [
    "trades",
    "signals",
    "daily_performance",
    "bot_state",
    "market_levels",
    "post_mortems",
    "strategy_candidates",
]

# ---------------------------------------------------------------------------
# Trading Mode
# ---------------------------------------------------------------------------
MODE_PAPER = "paper"
MODE_LIVE = "live"
MODE_BACKTEST = "backtest"
