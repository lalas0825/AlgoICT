---
name: Milestone 1 — Foundation (In Progress)
description: Tasks 1-3 complete. Task 4 (tf_manager) in progress. Target: 100% by 2026-04-13
type: project
---

## Milestone 1: Foundation (Tasks 1-8)

**Goal:** Project scaffolded, data loaded, timeframes aggregating  
**Timeline:** Started 2026-04-07  
**Status:** 37.5% complete (3/8 tasks done)

---

## ✅ Task 1: Scaffold Project — DONE (2026-04-07)

**Output:**
- `algoict-engine/` with 15 packages + `__init__.py`
- `config.py` (280 lines) — ALL risk constants, kill zones, confluence weights, strategy params, VPIN thresholds, Strategy Lab 9 gates
- `requirements.txt` — pandas, numpy, ta-lib, scipy, anthropic, supabase, pytest, yfinance
- `.env.example` — 13 environment variables
- `data/` directory with .gitkeep
- `.gitignore` — excludes .env, __pycache__, data/*.csv, node_modules, .next
- Root docs: CLAUDE.md, BUSINESS_LOGIC.md copied to project root

**Decisions:**
- Risk constants are HARDCODED in config.py — match CLAUDE.md Risk Rules exactly
- Strategy parameters organized per strategy (ny_am_reversal, silver_bullet, swing_htf)
- Lab 9-gate thresholds pre-configured
- Data splits LOCKED: train 2019-2022, validation 2023, test 2024-2025

---

## ✅ Task 2: Config Constants — DONE (implicit with Task 1)

All constants from CLAUDE.md Risk Rules section present in `config.py`:
- RISK_PER_TRADE = 250
- KILL_SWITCH_LOSSES = 3
- KILL_SWITCH_AMOUNT = 750
- DAILY_PROFIT_CAP = 1500
- HARD_CLOSE_HOUR = 15 (3 PM CT)
- VPIN thresholds: CALM (0.35), NORMAL (0.45), ELEVATED (0.55), HIGH (0.70), EXTREME (0.70)
- Confluence: MAX = 20, MIN = 7, CONFLUENCE_A_PLUS = 12

---

## ✅ Task 3: Data Loader — DONE (2026-04-07)

**File:** `backtest/data_loader.py` (180 lines)
**Tests:** `tests/test_data_loader.py` (16/16 PASS)

### Functions

**`load_futures_data(filepath, symbol_filter=None, start_date=None, end_date=None) -> pd.DataFrame`**
- Reads Databento OHLCV-1m CSV
- Builds continuous front-month series (picks highest daily volume contract at each bar)
- Converts UTC → US/Central timezone
- Excludes spreads (symbol contains '-')
- Validates: no gaps > 2 min during RTH (08:30-15:15 CT)
- Returns: DatetimeIndex CT, columns [open, high, low, close, volume], sorted, no duplicates

**`load_sp500_daily(tickers, period='5y') -> dict[str, pd.DataFrame]`**
- Downloads daily OHLCV via yfinance for S&P 500 stocks
- Returns dict: ticker → DataFrame

### Real Data Stats (nq_1min.csv)

| Metric | Value |
|--------|-------|
| Bars | 2,559,241 |
| Date range | 2019-01-01 → 2026-04-06 |
| Timezone | US/Central ✓ |
| RTH gaps | 4 (all Marzo 2020 circuit breakers — correct) |
| Continuous rolls | 411 (noisy during COVID; ~28 normal) |

### Key Decisions

1. **Continuous Front-Month Building:** At each timestamp, select the contract with the highest daily volume. This naturally replicates the market's roll behavior without hardcoding roll dates.
2. **Spread Exclusion:** Drop any symbol containing '-' (spreads like NQM5-NQU5).
3. **RTH Gap Detection:** Only flag gaps within the SAME trading day (same date). Overnight and weekend gaps are expected, not flagged.
4. **Deduplication:** When two rows have the same (ts_event, symbol), keep the LAST (keep='last').

### Test Coverage

- Returns DataFrame with correct columns and dtypes
- Index is DatetimeIndex in US/Central
- Sorted ascending, no duplicates
- Spreads excluded
- RTH gaps detected correctly (14-15 min COVID halts)
- Overnight/weekend gaps ignored (not flagged)
- Date filtering works (start_date, end_date)
- Symbol filtering works (force single contract)
- Gap detection logic filters by same trading day

---

## ✅ Task 4: Timeframe Manager — DONE (2026-04-07)

**File:** `timeframes/tf_manager.py` (180 lines)
**Tests:** `tests/test_tf_manager.py` (20 tests, 20/20 PASS)

**Implementation:**
- Class `TimeframeManager` with `aggregate(df_1min, target_tf) -> pd.DataFrame`
- Support: 5min, 15min, 1H, 4H, D, W using pandas `resample()`
- OHLCV: `first(O), max(H), min(L), last(C), sum(V)`
- Daily/Weekly anchored at 18:00 CT (CME Globex session open) — correct for ICT
- Cache dict; `clear_cache()` method
- Validation: columns, DatetimeIndex, timezone-aware
- Test coverage: OHLCV math, bar counts, daily/weekly aggregation, caching, validation

---

## ✅ Task 5: Session Manager — DONE (2026-04-07)

**File:** `timeframes/session_manager.py` (150 lines)
**Tests:** `tests/test_session_manager.py` (28 tests, 28/28 PASS)

**Implementation:**
- Class `SessionManager` with kill zone detection
- `is_kill_zone(timestamp, zone) -> bool` — 'asian', 'london', 'ny_am', 'silver_bullet', 'ny_pm'
- Kill zones read directly from `config.KILL_ZONES` (US/Central)
- Asian zone wraps midnight (20:00–00:00 CT) — correct logic
- All zones use `start <= time < end` (end exclusive)
- `get_asian_range(date, df_1min) -> (high, low)` — 19:00 CT prev evening
- `get_london_session(date, df_1min) -> (high, low)` — 02:00–04:59 CT (excludes 05:00)
- `get_ny_am_session(date, df_1min)` — convenience helper 08:30–11:00 CT
- Returns `(nan, nan)` if no data available
- Test coverage: all kill zones (including Asian midnight wrap), session ranges, edge cases

## 📋 Task 6-8: Pending

- Task 6: HTF Bias (Weekly/Daily bias detection)
- Task 7: Foundation Tests (verify all test files exist and pass)
- Task 8: Init Memory (already done in this session)

---

## 🎯 Next Actions

1. **Task 6:** Build `htf_bias.py` + tests (est. 1 hour)
2. **Task 7:** Verify all test files exist and pass
3. **Task 8:** Memory already initialized
4. **Commit:** Task 6 → commit
5. **Commit:** Final Milestone 1 commit after Task 7

## Summary

**Milestone 1 Foundation is 62.5% complete (5/8 tasks).**

### Completed (This Session)
- Task 1: Scaffold (config, requirements, structure)
- Task 2: Config constants (hardcoded risk rules)
- Task 3: Data loader (continuous front-month, 2.56M bars, 16/16 tests)
- Task 4: Timeframe manager (6 TFs, OHLCV aggregation, 20/20 tests)
- Task 5: Session manager (kill zones, HTF ranges, 28/28 tests)

### Test Summary
- **Total:** 64/64 PASS
- data_loader: 16/16
- tf_manager: 20/20
- session_manager: 28/28

### No Blockers
All decisions documented in memory files. Ready for HTF Bias detector next.
