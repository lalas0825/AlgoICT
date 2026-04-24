"""
AlgoICT Configuration — ALL constants, risk rules, kill zones, timeframes.
Sensei Rule: These values are HARDCODED. No dynamic overrides in production.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(BASE_DIR / ".env", override=True)

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
KILL_SWITCH_LOSSES = 3        # 3 consecutive losses = done for the day
KILL_SWITCH_AMOUNT = 750      # $750 max daily loss from kill switch
DAILY_PROFIT_CAP = 1500       # $1,500/day — stop trading after this
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
    "london": {
        "start": (1, 0),     # 1:00 AM CT  (2:00 AM ET)
        "end": (4, 0),       # 4:00 AM CT  (5:00 AM ET)
    },
    "london_silver_bullet": {
        "start": (2, 0),     # 2:00 AM CT  (3:00 AM ET) — inside London KZ
        "end": (3, 0),       # 3:00 AM CT  (4:00 AM ET)
    },
    "ny_am": {
        "start": (8, 30),    # 8:30 AM CT — extended to cover late NY AM setups
        "end": (12, 0),      # 12:00 PM CT (was 11:00)
    },
    "ny_pm": {
        "start": (13, 30),   # 1:30 PM CT
        "end": (15, 0),      # 3:00 PM CT
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
FVG_MITIGATION_MODE = "body_close"   # "body_close" (ICT) | "ratio" (legacy)
FVG_MITIGATION_RATIO = 0.75          # only used when FVG_MITIGATION_MODE == "ratio"

# ---------------------------------------------------------------------------
# OB Proximity Gate
# ICT entry requirement: price must be AT or inside the OB when the signal
# fires. This constant is the maximum allowed distance above OB.high (long)
# or below OB.low (short) before the signal is rejected.
# London session fire at 44 pts above OB.high (2026-04-20) confirmed the
# need for this gate — market orders that far from the OB are not OB entries.
# ---------------------------------------------------------------------------
OB_PROXIMITY_TOLERANCE = 3.0      # pts — max gap from OB edge to current price

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
