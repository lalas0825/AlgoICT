---
name: Milestone 2 — Key Lessons & Patterns
description: Critical bugs found, dedup strategies, testing patterns that worked
type: feedback
---

## Critical Bugs & Fixes

### 1. OB Loop Boundary (Fixed)
**Bug:** OrderBlockDetector loop was `range(1, len(candles) - 1)` which excluded the last candle.  
**Impact:** All OB tests failed because displacement is typically the last candle in test fixtures.  
**Fix:** Changed to `range(1, len(candles))`.  
**How to apply:** When iterating over detection points that can occur at the final bar, always include `len(df)`. Use conditional checks inside the loop if you need exclusions, not loop bounds.

### 2. Cross-Timeframe Collision in Dedup (Fixed)
**Bug:** Using `existing_ts = {timestamp for object in list}` caused collisions when same timestamp appeared on different timeframes (5min and 15min data arriving together).  
**Impact:** FVG/OB/Displacement detectors re-detected the same price level across different TFs.  
**Fix:** Changed all to `existing_keys = {(ts, timeframe) for object in list}`.  
**How to apply:** Always include all dimensions that distinguish unique events in dedup tuples. Timestamp alone is insufficient in multi-TF systems.

### 3. FVG Cascading Test Data (Learned)
**Issue:** `test_multiple_fvgs_in_sequence` expected 2 FVGs but detected 3 due to adjacent 3-candle gaps.  
**Root cause:** Test data had consecutive rising bars that created unintended overlapping gaps.  
**Fix:** Carefully design test data so only the intended patterns exist (introduced a "false gap" bar to break cascade).  
**How to apply:** When building test fixtures for 3-candle patterns, sketch the expected gaps on paper first. Verify no adjacent or overlapping patterns.

---

## Patterns That Worked

### Greedy Single-Pass Clustering (Liquidity)
**What:** Cluster swings by price proximity using a single forward pass without backtracking.
```python
cluster = [sorted_swings[0]]
for sp in sorted_swings[1:]:
    centre = sum(s.price for s in cluster) / len(cluster)
    if abs(sp.price - centre) / centre <= threshold_pct:
        cluster.append(sp)
    else:
        flush(cluster); cluster = [sp]
flush(cluster)
```

**Why it worked:** Simple, O(N log N), no complex merging logic, passed 35 tests first try.  
**When to use:** Any proximity-based clustering where order doesn't matter (swings, levels, price zones).  
**Gotcha:** Cluster centre is mean of current cluster, not a fixed value — allows some flexibility.

### State Machines for Structure (MarketStructure)
**Pattern:** Maintain per-timeframe state (neutral/bullish/bearish) + pending state (for CHoCH confirmation).

**Why it worked:** Clear transitions, consumed_ts dedup prevents re-triggering, follow-through logic is explicit.  
**When to use:** Any multi-step signal that has distinct states and confirmation requirements.

### Dataclass + Detector Pattern (All Detectors)
**Pattern:**
```python
@dataclass
class Signal: ...

class SignalDetector:
    def detect(...) -> list[Signal]: ...
    def get_active(...): ...
    def update_mitigation(...): ...
    def clear(): ...
```

**Why it worked:** Consistent across all 7 detectors, easy to compose, tests are predictable.  
**How to apply:** Use this template for any new detector.

### Dedup via Tuple Keys
**Pattern:** Store `{(timestamp, timeframe): bool}` in memory for O(1) dedup checks.

**Why:** Multi-timeframe systems need multi-dimensional dedup. Tuple keys scale better than compound keys.  
**How to apply:** Always ask: "What dimensions define uniqueness in this detector?" Use all of them in the tuple.

---

## Testing Patterns That Worked

### 1. Mock Factory Functions
**Pattern:**
```python
def _mk_bullish_fvg(bottom=99.0, top=101.0) -> FVG:
    return FVG(top=top, bottom=bottom, direction="bullish", ...)

# Use: result = score(fvgs=[_mk_bullish_fvg()])
```

**Why:** Tests are more readable, factories are reusable, easy to vary one parameter.  
**Applied to:** All detectors + confluence tests.

### 2. Boundary Testing
**Pattern:** Test exact threshold (should NOT trigger), just above (SHOULD trigger), just below (should NOT).

Example (Displacement):
- `body == 2.0 × ATR` → NOT detected (strict >)
- `body == 2.01 × ATR` → detected

**Why:** Catches off-by-one logic errors.

### 3. Negative Cases
**Test that things DON'T happen:**
- FVG outside range → no score
- OB wrong direction → unvalidated
- Sweep unswept → no liquidity_grab

**Why:** Prevents false positives in production.

### 4. Per-Timeframe Isolation
**Pattern:** Create signals on 5min, then separately on 15min, verify no collision.

Example (test_per_timeframe_stored_separately):
```python
det.detect(df, "5min")
det.detect(df, "15min")  # Same df, different TF
tfs = {f.timeframe for f in det.fvgs}
assert "5min" in tfs and "15min" in tfs
```

**Why:** Catches dedup bugs early.

---

## Architectural Decisions

### Confidence Scoring (HTF Bias)
**Decision:** Weekly bias takes priority over daily. Both can influence final direction, but weekly is "the boss."

```python
if weekly_bias != "neutral":
    direction = weekly_bias
else:
    direction = daily_bias
```

**Why:** ICT principle — institutional structure (weekly) defines primary direction.  
**Applied to:** HTF bias confidence calculation.

### Order Block Validation
**Decision:** OB is only "validated" (more significant) if **BOTH** nearby sweep AND nearby FVG exist.

```python
validated = has_sweep and has_fvg  # AND, not OR
```

**Why:** Reduces false positives. Single factor (sweep or FVG alone) is weak validation.  
**Alternative considered:** Accept either sweep OR FVG. Rejected — too loose.

### OTE Fibonacci Retracement Zones
**Decision:** Uses Fibonacci retracement, not extension.

- Long: Entry in 61.8–78.6% retracement from swing high → [21.4%, 38.2%] from low
- Short: Entry in 61.8–78.6% retracement from swing low → [61.8%, 78.6%] from low

**Why:** ICT pattern — optimal trade entry occurs in the retracement of the last impulse.  
**Note:** Math verified across 7 dedicated tests.

### Confluence Max Score (19 not 20)
**Decision:** Accepted actual weights (19) over aspirational docs (20).

**Why:** Code is the source of truth. Weights are set in config.CONFLUENCE_WEIGHTS.  
**How to apply:** When docs and code disagree, verify which is authoritative.

---

## Code Quality Lessons

1. **Always run tests immediately after changes.** The OB loop bug would have been caught in seconds with `pytest`.
2. **Use dataclasses for signal objects.** Reduces boilerplate, auto-implements __repr__, enforces structure.
3. **Store detector state in lists with dedup dicts.** Keeps history while enabling O(1) duplicate checks.
4. **Group similar tests in classes (TestIndividualFactors, TestOTE, etc.).** Makes reports easier to read.
5. **Test boundary conditions.** Exact threshold, just above, just below.

---

## Composability Insights

**Each detector is independent but composable:**
- SwingPointDetector feeds MarketStructureDetector
- MarketStructureDetector + FVG feed OrderBlockDetector
- All feed ConfluenceScorer

**No circular dependencies.** Layers flow down, not back up. This enables:
- Offline testing of each detector
- Easy swapping of implementations
- Clear dependency tree

---

## Next Session Preparation

1. **Milestone 3 will add SWC (sentiment).** Expect new detector pattern: sentiment levels (bullish/neutral/bearish) + confluence adjuster.
2. **Milestone 4 adds GEX (gamma).** More complex state (regime flips). Use same dedup+validation pattern.
3. **Milestone 5 adds VPIN (toxicity).** Real-time calculations. May need streaming architecture — reuse detector pattern.

---

**Applied all lessons to Milestone 2. Ready to scale to Milestone 3+.**
