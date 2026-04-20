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
MAX_MNQ_TRADES_PER_DAY = 3   # Max 3 MNQ trades per day
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
        "start": (10, 0),    # 10:00 AM CT — inside NY AM KZ
        "end": (11, 0),      # 11:00 AM CT
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
# FVG Mitigation Ratio
# ICT standard: 50% (midpoint). Extended to 75% to keep FVGs alive longer,
# allowing more time for price to return to the gap after a sweep.
# Bearish FVG: mitigated when price >= bottom + ratio * range (filling upward)
# Bullish FVG: mitigated when price <= top   - ratio * range (filling downward)
# ---------------------------------------------------------------------------
FVG_MITIGATION_RATIO = 0.75

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
# Prevents stale weekly/multi-day OBs from polluting the active pool.
# ---------------------------------------------------------------------------
OB_MAX_AGE_BARS = 1000            # 5-min bars; ~83h RTH (~13 trading days) before OB expires

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
