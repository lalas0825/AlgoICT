---
name: Strategy Lab Session 1 Results
description: 5 hypotheses through 9 anti-overfit gates for NY AM Reversal
type: project
---

# Strategy Lab — Session 1
_Session: S1_20260411_0012_

## Baseline (Training 2019-2022)
| Metric | Value |
|--------|-------|
| Trades | 2047 |
| Win Rate | 34.6% |
| Sharpe | 3.509 |
| P&L | $+216,832 |
| PF | 1.71 |
| Max DD | $10,168 |

## Summary: 0/5 hypotheses passed all 9 gates

| ID | Name | Gates | Score | ΔSharpe | ΔWR | Status |
|-----|------|-------|-------|---------|-----|--------|
| H-001 | Skip Summer Chop | 7/9 | 61 | +0.178 | +1.7% | FAIL |
| H-002 | High-Confidence Shorts Only | 3/9 | 20 | -2.090 | -6.6% | FAIL |
| H-003 | Minimum 10-Point OB Stop | 7/9 | 46 | -1.029 | +0.6% | FAIL |
| H-004 | Max 40-Point OB Stop | 6/9 | 59 | +0.135 | +1.0% | FAIL |
| H-005 | Require 2+ Aligned FVGs | 5/9 | 47 | +0.000 | +0.0% | FAIL |

### H-001: Skip Summer Chop
**ICT Reasoning:** ICT teaches that May-June has reduced institutional flow as smart money positions before Q3. The NY session becomes range-bound with more false breakouts and liquidity grabs that fail to convert. Walk-forward shows W09 and W15 (both May-Jun) are the ONLY negative windows.
**Condition:** `month NOT IN (5, 6)`
**Parameters:** 0

| Metric | Baseline | Hypothesis | Delta |
|--------|----------|------------|-------|
| Trades | 2047 | 1704 | -343 |
| WR | 34.6% | 36.3% | +1.7% |
| Sharpe | 3.509 | 3.687 | +0.178 |
| PF | 1.71 | 1.85 | +0.15 |
| Max DD | $10,168 | $7,268 | |

**Gate Results:**

| Gate | Result | Metric | Threshold | Detail |
|------|--------|--------|-----------|--------|
| 1_sharpe_improvement | PASS | 0.178 | 0.100 | ΔSharpe=+0.178 >=  0.1 |
| 2_win_rate_delta | PASS | 0.017 | -0.020 | ΔWR=+1.7% >= -2% |
| 3_drawdown_delta | PASS | -0.285 | 0.100 | DD change=-28.5% <= 10% |
| 4_walk_forward | PASS | 0.833 | 0.700 | 20/24 positive (83.3%) >= 70% |
| 5_cross_instrument | PASS | 0.000 | 2.000 | SKIPPED — no ES/YM data available |
| 6_noise_resilience | FAIL | 0.789 | 0.300 | Noise degradation=78.9% > 30% |
| 7_inversion_loses | FAIL | 6.099 | 3.687 | Inv Sharpe=6.099 >= hyp=3.687 |
| 8_occam_razor | PASS | 0.000 | 2.000 | 0 params <= 2 |
| 9_validation_improves | PASS | 0.137 | 0.050 | Val ΔSharpe=+0.137 >= 0.05 |

### H-002: High-Confidence Shorts Only
**ICT Reasoning:** ICT emphasizes trading WITH institutional order flow. Shorts against a weekly bullish trend with only medium-confidence bias are counter-institutional. The dynamic HTF bias detector returns confidence='low' or 'medium' when weekly and daily disagree. Requiring 'high' confidence for shorts ensures both W and D are aligned bearish before shorting.
**Condition:** `IF direction=='short' THEN bias.confidence=='high'`
**Parameters:** 0

| Metric | Baseline | Hypothesis | Delta |
|--------|----------|------------|-------|
| Trades | 2047 | 1943 | -104 |
| WR | 34.6% | 27.9% | -6.6% |
| Sharpe | 3.509 | 1.419 | -2.090 |
| PF | 1.71 | 1.25 | -0.46 |
| Max DD | $10,168 | $14,179 | |

**Gate Results:**

| Gate | Result | Metric | Threshold | Detail |
|------|--------|--------|-----------|--------|
| 1_sharpe_improvement | FAIL | -2.090 | 0.100 | ΔSharpe=-2.090 < 0.1 |
| 2_win_rate_delta | FAIL | -0.066 | -0.020 | ΔWR=-6.6% < -2% |
| 3_drawdown_delta | FAIL | 0.394 | 0.100 | DD change=+39.4% > 10% |
| 4_walk_forward | FAIL | 0.625 | 0.700 | 15/24 positive (62.5%) < 70% |
| 5_cross_instrument | PASS | 0.000 | 2.000 | SKIPPED — no ES/YM data available |
| 6_noise_resilience | PASS | 0.019 | 0.300 | Noise degradation=1.9% <= 30% |
| 7_inversion_loses | FAIL | 9.445 | 1.419 | Inv Sharpe=9.445 >= hyp=1.419 |
| 8_occam_razor | PASS | 0.000 | 2.000 | 0 params <= 2 |
| 9_validation_improves | FAIL | -0.890 | 0.050 | Val ΔSharpe=-0.890 < 0.05 |

### H-003: Minimum 10-Point OB Stop
**ICT Reasoning:** Very tight Order Blocks (< 10 NQ points) often represent noise rather than true institutional activity. ICT OBs represent areas of significant institutional buying/selling, which creates meaningful price zones — not 2-3 point clusters. A tight OB stop also means a very close target (1:3 RR), making the trade low-expectancy.
**Condition:** `abs(entry_price - stop_price) >= 10`
**Parameters:** 1

| Metric | Baseline | Hypothesis | Delta |
|--------|----------|------------|-------|
| Trades | 2047 | 927 | -1120 |
| WR | 34.6% | 35.2% | +0.6% |
| Sharpe | 3.509 | 2.480 | -1.029 |
| PF | 1.71 | 1.77 | +0.06 |
| Max DD | $10,168 | $4,789 | |

**Gate Results:**

| Gate | Result | Metric | Threshold | Detail |
|------|--------|--------|-----------|--------|
| 1_sharpe_improvement | FAIL | -1.029 | 0.100 | ΔSharpe=-1.029 < 0.1 |
| 2_win_rate_delta | PASS | 0.006 | -0.020 | ΔWR=+0.6% >= -2% |
| 3_drawdown_delta | PASS | -0.529 | 0.100 | DD change=-52.9% <= 10% |
| 4_walk_forward | PASS | 0.708 | 0.700 | 17/24 positive (70.8%) >= 70% |
| 5_cross_instrument | PASS | 0.000 | 2.000 | SKIPPED — no ES/YM data available |
| 6_noise_resilience | PASS | 0.044 | 0.300 | Noise degradation=4.4% <= 30% |
| 7_inversion_loses | FAIL | 5.203 | 2.480 | Inv Sharpe=5.203 >= hyp=2.480 |
| 8_occam_razor | PASS | 1.000 | 2.000 | 1 params <= 2 |
| 9_validation_improves | PASS | 0.137 | 0.050 | Val ΔSharpe=+0.137 >= 0.05 |

### H-004: Max 40-Point OB Stop
**ICT Reasoning:** Wide OBs (> 40 NQ points) produce trades with large dollar risk per contract. With $250 max risk and $2/point, a 40-point stop allows 3 contracts. Wider stops force 1-2 contracts with the same $250 risk — but the RR math means losses are larger in absolute terms. ICT identifies that wide OBs often form during high-volatility events where the probability of stop-run increases.
**Condition:** `abs(entry_price - stop_price) <= 40`
**Parameters:** 1

| Metric | Baseline | Hypothesis | Delta |
|--------|----------|------------|-------|
| Trades | 2047 | 1914 | -133 |
| WR | 34.6% | 35.6% | +1.0% |
| Sharpe | 3.509 | 3.644 | +0.135 |
| PF | 1.71 | 1.77 | +0.07 |
| Max DD | $10,168 | $9,371 | |

**Gate Results:**

| Gate | Result | Metric | Threshold | Detail |
|------|--------|--------|-----------|--------|
| 1_sharpe_improvement | PASS | 0.135 | 0.100 | ΔSharpe=+0.135 >=  0.1 |
| 2_win_rate_delta | PASS | 0.010 | -0.020 | ΔWR=+1.0% >= -2% |
| 3_drawdown_delta | PASS | -0.078 | 0.100 | DD change=-7.8% <= 10% |
| 4_walk_forward | PASS | 0.917 | 0.700 | 22/24 positive (91.7%) >= 70% |
| 5_cross_instrument | PASS | 0.000 | 2.000 | SKIPPED — no ES/YM data available |
| 6_noise_resilience | FAIL | 0.758 | 0.300 | Noise degradation=75.8% > 30% |
| 7_inversion_loses | FAIL | 6.568 | 3.644 | Inv Sharpe=6.568 >= hyp=3.644 |
| 8_occam_razor | PASS | 1.000 | 2.000 | 1 params <= 2 |
| 9_validation_improves | FAIL | -5.336 | 0.050 | Val ΔSharpe=-5.336 < 0.05 |

### H-005: Require 2+ Aligned FVGs
**ICT Reasoning:** ICT teaches that multiple Fair Value Gaps in the same direction indicate sustained institutional pressure — not just a single impulsive move. A single FVG could be a one-off sweep, but 2+ aligned FVGs show that institutions committed to the direction across multiple candles. This filters out weak setups where only one FVG exists.
**Condition:** `len(aligned_fvgs) >= 2`
**Parameters:** 1

| Metric | Baseline | Hypothesis | Delta |
|--------|----------|------------|-------|
| Trades | 2047 | 2047 | +0 |
| WR | 34.6% | 34.6% | +0.0% |
| Sharpe | 3.509 | 3.509 | +0.000 |
| PF | 1.71 | 1.71 | +0.00 |
| Max DD | $10,168 | $10,168 | |

**Gate Results:**

| Gate | Result | Metric | Threshold | Detail |
|------|--------|--------|-----------|--------|
| 1_sharpe_improvement | FAIL | 0.000 | 0.100 | ΔSharpe=+0.000 < 0.1 |
| 2_win_rate_delta | PASS | 0.000 | -0.020 | ΔWR=+0.0% >= -2% |
| 3_drawdown_delta | PASS | 0.000 | 0.100 | DD change=+0.0% <= 10% |
| 4_walk_forward | PASS | 0.917 | 0.700 | 22/24 positive (91.7%) >= 70% |
| 5_cross_instrument | PASS | 0.000 | 2.000 | SKIPPED — no ES/YM data available |
| 6_noise_resilience | FAIL | 0.324 | 0.300 | Noise degradation=32.4% > 30% |
| 7_inversion_loses | FAIL | 7.234 | 3.509 | Inv Sharpe=7.234 >= hyp=3.509 |
| 8_occam_razor | PASS | 1.000 | 2.000 | 1 params <= 2 |
| 9_validation_improves | FAIL | 0.000 | 0.050 | Val ΔSharpe=+0.000 < 0.05 |

**Why:** Strategy Lab validates hypotheses before promotion to production.
**How to apply:** Candidates that pass all 9 gates → `JUAN_APPROVED_FINAL_TEST` to unlock Test Set.