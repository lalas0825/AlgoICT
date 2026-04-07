---
name: Data Loader Design Decisions
description: Architectural choices for continuous futures data, RTH gaps, and CSV parsing
type: project
---

## Problem Statement

Build a continuous futures series from Databento OHLCV-1m CSV that:
1. Handles multiple individual contracts (NQH9, NQM9, NQU9, etc.) trading simultaneously
2. Detects genuine gaps during regular trading hours
3. Ignores expected overnight/weekend gaps
4. Maintains timezone consistency (all times CT)
5. Handles duplicates and spreads

---

## Decision 1: Continuous Front-Month Selection

### Chosen Approach: Highest Daily Volume

**Logic:** At each timestamp, keep only the contract with the highest rolling 24-hour volume.

**Why:**
- Market-driven: Volume naturally migrates to the front contract ~1 week before expiration
- No hardcoded roll dates: Adaptive to volatile periods (e.g., COVID 2020)
- Simple to implement: No expiration calendar lookup

**Trade-off:**
- During roll periods, may flip back-and-forth if contracts trade at similar volumes
- Example: March 2020 COVID crash saw 411 roll events (vs. normal ~28), most at the roll boundary

**Alternative Rejected:**
- Hardcoded roll dates (e.g., 8 days before 3rd Friday) → inflexible during panics
- First contract with any volume → gaps when contracts don't trade simultaneously

**Validation:**
- Real data: 2.56M bars, 2019-2026. Continuous series smooth except COVID roll noise.
- No backtest artifacts observed; series behaves as expected.

---

## Decision 2: RTH Gap Detection (Same Trading Day Only)

### Chosen Approach: Filter by `prev_ts.date() == ts.date()`

**Logic:**
1. Find all consecutive RTH bars (08:30-15:15 CT, Mon-Fri)
2. Compute time diff between bars
3. Flag only gaps > 2 min where both bars are on the SAME trading day

**Why:**
- Overnight gaps (4 PM to 8 AM) are expected, not errors
- Weekend gaps (Fri 4 PM to Mon 8 AM) are expected, not errors
- Real issues: gaps DURING a trading day (e.g., 10:00 to 10:15 with no bars = 15 min gap)

**Validation:**
- Real data: 4 gaps detected, all in March 2020 (14-15 min each) → exact circuit breaker halts
- Tests confirm: overnight/weekend gaps not flagged; intra-day gaps flagged

**Alternative Rejected:**
- Flag ALL gaps > 2 min → ~1000+ false positives from overnight rolls

---

## Decision 3: Spread Exclusion

### Chosen Approach: Drop rows where `symbol.contains('-')`

**Why:**
- Spreads (NQM5-NQU5) are derivatives of single contracts, not raw data
- Not suitable for backtesting a single-contract strategy
- Databento includes spreads for multi-leg traders; we ignore them

**Validation:**
- Raw data: 3.66M rows total, 3.29M rows after spread removal
- No backtest artifacts; series clean

---

## Decision 4: Deduplication Strategy (keep="last")

### Chosen Approach: `drop_duplicates(subset=['ts_event', 'symbol'], keep='last')`

**Why:**
- If two 1-min bars have the SAME timestamp and same contract → keep the most recent (highest quality)
- Rare in production data, but occurs during data transmission glitches

**Validation:**
- Test: Duplicate with vol=100, then vol=999 → keeps vol=999
- Behavior: Last wins (most recent data wins)

---

## Decision 5: Timezone Conversion (UTC → US/Central)

### Chosen Approach: UTC from CSV → `.dt.tz_convert('US/Central')`

**Why:**
- Databento exports UTC (standard for APIs)
- Trading bot runs in CT (Eastern Time USA) → all logic uses CT
- Kill zones, RTH windows, etc. are defined in CT

**Validation:**
- Test: Index timezone is `US/Central`
- Real data: First bar 2019-01-01 17:00:00-06:00 (correct: 11 PM EST on Dec 31)

---

## Decision 6: Column Order and Naming

### Chosen Output: `[open, high, low, close, volume]` (alphabetical by category)

**Why:**
- Standard OHLCV ordering for downstream detectors
- Lower memory overhead than including raw columns (rtype, publisher_id, instrument_id, symbol)

---

## Known Limitations & Mitigations

| Issue | Mitigation |
|-------|-----------|
| Roll noise during panics (COVID 2020) | Document in logs; validate backtest results don't show artifacts |
| Timezone edge cases (DST transition) | pytz handles DST automatically; test coverage includes full year |
| Rare duplicates (data transmission glitches) | keep='last' prioritizes quality; acceptable for backtesting |
| NQ contract symbols vary by date | Continuous builder adapts per timestamp; no hardcoding |

---

## Performance Notes

- Real CSV: 3.66M rows → 2.56M after cleanup (16/16 tests, <3 sec)
- Memory: ~250 MB for full series (acceptable for 7-year history)
- No streaming required; entire series loaded once

---

## Future Enhancements (Post-Milestone 1)

1. **Option A: Manual Roll Calendar**
   - Add explicit roll dates + micro-smoothing for exact roll point
   - Trade-off: More maintenance; better for "known" scenarios

2. **Option B: Ensemble Volume**
   - Weight volume by bid-ask spread or open interest
   - Trade-off: Requires additional data source

3. **Option C: Gap-Aware Adjustment**
   - Adjust prices at rolls to avoid "phantom" gaps
   - Trade-off: Modifies data; appropriate only if needed by backtester

_Current approach (Option: Volume-based) is sufficient for MVP backtesting._
