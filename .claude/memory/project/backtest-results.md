---
name: Backtest Results Archive
description: Backtesting results, Combine Simulator runs, and comparative analysis
type: project
---

## Backtest Results — By Milestone

_Baseline and comparative backtests stored here as milestones complete._

### Milestone 1 (Foundation)

**Status:** Pending  
**Expected:** After Task 25 (Backtester Core)

---

### Milestone 2 (ICT Detectors)

**Status:** Pending  
**Expected:** After Task 29 (Run Baseline Backtests)

**Planned Baselines:**
- NY AM Reversal on MNQ 2023-2025
- Silver Bullet on MNQ 2023-2025
- Combine Simulator run
- Risk audit (ZERO violations required)

---

### Milestone 4 (Backtester + Combine Sim)

**Status:** Pending  
**Expected:** Task 29-32

**Comparisons:**
- ICT Pure baseline
- + SWC Calendar Adjuster
- + SWC + GEX alignment
- + SWC + GEX + VPIN shield

---

## Template: Backtest Run

```
## Run: [Strategy] [Date Range]

**Date:** YYYY-MM-DD  
**Strategy:** [ny_am_reversal | silver_bullet | swing_htf]  
**Data:** [MNQ | NQ | ES | YM] 1min  
**Period:** YYYY-MM-DD to YYYY-MM-DD  

**Parameters:**
- Min confluence: 7
- Risk per trade: $250
- Kill switch: 3 losses
- Daily cap: $1,500

**Results:**

| Metric | Value |
|--------|-------|
| Total trades | N |
| Win rate | X% |
| Profit factor | Y |
| Max drawdown | Z% |
| Sharpe ratio | A |
| Topstep MLL compliance | PASS / FAIL |

**Notes:** 
- Violations: [list any rule violations]
- Observations: [interesting patterns, edge cases]

**Combine Simulation:**
- Starting balance: $50,000
- Target: $3,000
- MLL: $2,000 trailing
- DLL: $1,000 per day
- Result: PASS / FAIL (days to pass)
```

---

## Decision Tree: When to Backtest

1. **After ICT Detector completion** → Baseline with pure ICT
2. **After each layer added** → Comparative backtest (ICT vs ICT+SWC vs ICT+SWC+GEX+VPIN)
3. **After parameter tuning** → Full Combine Simulator
4. **Before any live trading** → Final validation gate (12 months ZERO violations)

---

## Known Gotchas

- **Overfitting risk:** Strategy Lab has 9-gate protection; validation set is LOCKED (2023 only)
- **Forward bias:** Test set (2024-2025) never used in development, only final validation
- **COVID anomalies:** March 2020 data exhibits unusual patterns; consider separate analysis
- **Spread cost:** Not modeled in backtests; assume $1-2/contract slippage in live

---

## Success Criteria (Milestone 10)

- [ ] Final Combine Simulator: PASS with margin (> $3,000 profit in sim)
- [ ] Risk audit: ZERO MLL/DLL violations across test period
- [ ] Paper trading (2 weeks): Backtest behavior matches live behavior
- [ ] Post-mortem insights: Top 3 loss patterns identified and ruled out in Strategy Lab
- [ ] Go/No-Go decision: All stakeholders (backtest + paper + Lab) aligned

