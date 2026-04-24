# Silver Bullet — Combine Readiness Checklist

## Status by metric (as of 2026-04-21, 3/5 walk-forward years + v4 2024)

| Criterion | Target | Actual | Status |
|-----------|--------|--------|--------|
| **Walk-forward PF ≥ 1.15** | ≥ 4/5 years | TBD (3/5 done) | 🟡 partial |
| **Walk-forward WR** | ≥ 40% | 13.9% (2019), 15.6% (2020), 15.0% (2024) | 🔴 FAIL |
| **Max drawdown per year** | < 20% of $50K ($10K) | TBD | 🟡 need data |
| **Consecutive losers cap** | ≤ 5 in any stretch | TBD | 🟡 need data |
| **Total P&L ≥ $3K in 1 year** | ≥ $3K | 2019: $8,956 ✅ / 2020: $49,648 ✅ / 2024: $11,102 ✅ | 🟢 PASS |
| **Combine Simulator pass** | ZERO violations | not run yet | ⚪ pending |
| **Strategy Lab 9 gates pass** | All 9 | not run yet | ⚪ pending |
| **Paper trade 30 days** | 0 regressions | not started | ⚪ pending |

## Current blocking issue

**WR of 15% is mathematically profitable (PF > 1.0) but psychologically risky for Combine.**

Math: avg_win × WR > avg_loss × (1-WR)
  - Current: $1,464 × 0.15 = $220 vs $231 × 0.85 = $196 → edge $24/trade
  - Breakeven WR: 1/(1+6.5) = 13.3% — we're 1.7% above breakeven
  - If avg_win drops 20% (losing some monster winners in certain market regimes) → slip below breakeven

Risk: 5-losers streaks have 44% probability per year → $1,155 drawdown per streak.
  - Combine MLL = $2,000. Two bad streaks without winners between = MLL breach.
  - 7-loser streak (32% probability) → $1,617 DD, critical.

## Decision tree

### Path A — Deploy as-is to Combine (YOLO)
- Pros: PF positive across 3 years, +$69K aggregate
- Cons: WR risk makes early-Combine failure likely
- Odds of Combine pass: estimated 40-55%

### Path B — Implement SB v2 with partials + trail (RECOMMENDED)
- Goal: raise WR to 30-40%, tighten drawdown, keep PF > 1.2
- Timeline: ~2h implement, ~6h re-run walk-forward
- Odds of Combine pass: estimated 65-75% if v2 walks forward positive

### Path C — Full rejection-confirmation rewrite
- Goal: raise WR to 40-50% with fewer/higher-quality trades
- Timeline: ~6h implement, ~6h re-run walk-forward
- Odds of Combine pass: estimated 70-80% if v3 walks forward positive
- Risk: more invasive change, could lose the edge entirely

## Path B detailed plan (if we go this route)

### v2 changes to silver_bullet.py
1. Read `config.TRADE_MANAGEMENT` — add `"partials_be"` as new SB default
2. New exit logic (in silver_bullet.py):
   - Position opened: stop at FVG candle 1, target at liquidity pool
   - At 1R reached: close floor(contracts/2), move stop to entry (BE)
   - Remaining runs to original target with trailing
3. Config: `SB_PARTIAL_AT_R = 1.0` (fraction of stop distance for partial exit)
4. Config: `SB_PARTIAL_PCT = 0.50` (percent of position to close at partial)

### Tests to add
- `test_sb_partial_at_1r`: 50% off when price reaches 1R
- `test_sb_stop_moved_to_be_after_partial`: stop = entry after partial
- `test_sb_full_exit_on_be_hit`: remaining closes at entry if price returns
- `test_sb_trailing_after_partial`: remaining uses trailing to target

### Backtest to re-run
- v5b: 2019-2024 walk-forward with partial_be + trailing hybrid
- Expected: WR 30-40%, PF 1.2-1.5, DD tighter

### Success criteria for Path B
- WR ≥ 30% in ≥4/6 years
- PF ≥ 1.2 in ≥4/6 years
- Max DD < $8K in any year
- Aggregate P&L ≥ +$50K over 6 years

If all pass → promote to Combine Simulator run.

## Awaiting

1. **Q1 2024 trade-level analysis** (~10 min) — validates hypotheses about WHY losers happen
2. **v5 2021-2023 results** (~3h) — completes walk-forward sample to 5 years
3. **Decision point**: Path A / B / C based on above data
