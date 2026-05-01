# Scaling to Maldivas — Multi-Account Plan

## Status

- **Strategy validada**: v19a-WIDE, 7-yr backtest 2019-2025 ✓
  - $1,170,354 total P&L
  - WR 63.3% consistente todos los años
  - PF aggregate 3.30
  - 0 negative years
  - MaxDD per year max $5,188 (well under $7K threshold)
- **Combine simulation**: 275 valid passes, 99.3% pass rate ✓
- **Funded simulation**: $1.04M trader payout, 3 funded accounts over 7-yr ✓
- **Bot status**: OFF, ready for Sunday restart con todos los fixes ✓

---

## Phase 0: Live Validation ($50K Combine)

**Period**: First 1-2 weeks live, starting Monday after first Globex open.

**Goal**: Probar que bot v19a-WIDE opera estable en LIVE sin bugs costosos.

### Success criteria (must hit ALL)

```
Performance vs backtest:        ≥ 70% del expected P&L per week
WR live:                        ≥ 55% over first 30 trades
Bug-free operation:             0 zombie events, 0 deadlocks
Combine pass:                   $50K Combine passed in ≤ 14 days
MLL fail rate:                  0 in first 30 days
Slippage:                       ≤ 15% degradation vs backtest avg trade
```

### Failure scenarios (any → STOP, investigate)

```
Live P&L < 50% backtest:        red flag, debug
2+ MLL fails in first 30 days:  red flag
Bot crash > 1× per week:        infra issue
WR < 50%:                       strategy may not generalize
```

### Phase 0 expected outcomes

```
Days 1-7: 0-2 Combines passed, +$3-8K profit
Days 7-14: 1-3 Funded accounts, +$5-15K profit
End of Phase 0 (day 14): clear data on whether to scale
```

---

## Phase 1: Scale to 5 × $150K

**Trigger**: Phase 0 success criteria met AND user manual approval.

**Setup**: All 5 accounts are TopstepX $150K Combines.

### Account configuration

```
Account 1: $150K master (runs primary bot)
Accounts 2-5: $150K followers (copy trade master via Topstep)
Total capital under management: $750,000
Subscription cost: 5 × $299/mo = $1,495/mo = $17,940/yr
```

### Topstep $150K rules (all 5 accounts identical)

```
Starting balance:        $150,000
Profit target:           $9,000 (reach $159K to pass)
MLL trail:               $4,500 (3% of account)
DLL:                     $3,000
Position size limit:     up to 15 contracts
Min trading days:        5
Consistency rule:        best day < 50% of total profit
```

### Position sizing on $150K

```
Single $50K test: $250 risk / trade = ~1-3 contracts
Single $150K:     $750 risk / trade = ~3-9 contracts (3x scaling)

Conservative scaling option: $562 risk / trade (2.25x) maintains
4% MLL safety ratio (since $150K MLL is 3% of account vs 4% on $50K).
DECISION: Start with 3x ($750 risk) and revisit after 30 days.
```

### Scaling math

```
Single $50K backtest baseline:           $148K/año (sequential)
Single $150K theoretical (3x):           $444K/año
5 × $150K theoretical (parallel):        $2,222,400/año
```

### Realistic haircuts

```
Theoretical:                              $2,222,400/año
- Slippage (10% on bigger size):            -$222,000
- Latency on copy trading (5%):             -$111,000
- Synchronized fail risk (10%):             -$222,000
- Subscription costs:                        -$17,940
─────────────────────────────────────────────────
GROSS:                                    $1,649,460/año

- Federal + state tax (~32%):               -$528,000
─────────────────────────────────────────────────
NET TO BANK:                              ~$1,121,000/año
                                          ~$93,400/mes
```

### Conservative scenario (live = 70% of backtest)

```
Single $150K @ 70% performance:          $311K/año
5 × $150K @ 70%:                         $1,555,000 GROSS
After haircuts (30%):                    $1,089,000 GROSS
After taxes:                             ~$740,000 NET
                                         ~$62,000/mes NET
```

### Pessimistic scenario (live = 50% of backtest)

```
5 × $150K @ 50%:                         $1,111,000 GROSS
After haircuts (30%):                    $778,000 GROSS  
After taxes:                             ~$529,000 NET
                                         ~$44,000/mes NET
```

---

## Phase 2: Optimization (Months 6+)

**Trigger**: Phase 1 stable for 3+ months with consistent payouts.

### Possible optimizations

1. **Strategy Lab on v19a-WIDE** (separate roadmap doc):
   - Generate hypotheses to raise WR from 63% to 75-80%
   - Test position sizing by confluence score
   - Each variant validated rigorously on 2023 (held-out from training)

2. **Add second strategy** for diversification:
   - HTF Continuation already validated (10% boost, 98% overlap)
   - OR explore: Swing HTF (Daily/Weekly), GEX-driven, VPIN regime
   - Goal: ≥ 30% uncorrelated days vs SB

3. **Tighten risk for live performance variance**:
   - If live MLL fails ≥ 3/year: tighten MLL warning to 30% (vs 40%)
   - If live DD > 2x backtest: reduce position size 25%

---

## Operational Checklist

### Daily routine (post-Phase 1)

```
Pre-market (07:00 CT):
  □ Health check: 5 accounts all alive
  □ Confirm overnight P&L logged correctly
  □ Check for Telegram alerts overnight

NY AM open (08:30 CT):
  □ Bot fires within 5 min of any setup
  □ Telegram fires for each signal
  □ Position sync: master vs follower checks

NY close (15:00 CT):
  □ Hard close fires correctly
  □ All 5 accounts flat
  □ Daily summary received via Telegram
  □ Daily P&L matches across accounts (within slippage)

EOD review (15:30 CT):
  □ Combine progress on each account
  □ Any account near MLL → flag
  □ Any account near profit target → prep for new combine
```

### Weekly review

```
□ Combines passed this week
□ Funded accounts that failed (if any)
□ WR live vs backtest
□ Total payout banked
□ Subscription cost vs revenue ratio
□ Any anomalies in copy trading sync
```

### Monthly review

```
□ Live performance vs backtest comparison
□ Tax provisions set aside (32%)
□ Subscription paid up
□ Strategy refinements considered
□ Maldivas progress update
```

---

## Risk Triggers

### Stop-trading triggers (immediately halt all 5 accounts)

```
1. 2+ MLL failures in same week           → audit bot
2. Bot crash mid-trade (orphan position)  → debug
3. Live performance < 30% of backtest     → strategy reset
4. Synchronized 5-account loss > $7,500   → emergency review
5. Topstep flags account for review        → comply, pause
```

### Resume criteria

```
1. Bot uptime ≥ 7 days continuous
2. Last week WR ≥ 55%
3. Last week P&L ≥ 30% of backtest expected
4. 0 unhandled errors in logs
```

---

## Timeline to Maldivas

```
Week 1-2:   Phase 0 ($50K test)
            Outcome: pass/fail decision

Week 3-4:   Phase 1 setup (5 × $150K Combines)
            Outcome: 0-3 Funded accounts active

Month 2:    Multi-funded operating
            Outcome: ~$30-50K cash in (Phase 1 ramp-up)

Month 3-4:  All 5 funded stable
            Outcome: ~$60-90K/mes cash flow

Month 6:    Validated multi-account at scale
            Outcome: Maldivas down payment 🏝️

Year 1:     ~$700K-1M total cash NET
Year 2+:    Continue or refine via Strategy Lab
```

---

## What ISN'T in this plan (yet)

- Strategy Lab automated optimization → see `STRATEGY_LAB_ROADMAP.md`
- Specific Topstep copy trading setup steps → manual user task
- Tax structure (LLC vs personal, retirement contributions) → CPA task
- Capital allocation across multiple props (Topstep + Apex + Tradeify) → Phase 3

---

## Bottom Line

```
Backtest 7-yr:                   $1,170,354 (real, deterministic)
Single $50K Combine sim:         $148K/año
Single $150K (3x scaling):       $444K/año theoretical
5 × $150K Funded:                $1.65M/año GROSS realistic
After taxes:                     ~$1.12M/año NET realistic
                                 ~$93K/mes

Conservative @ 70% live:         ~$62K/mes NET
Pessimistic @ 50% live:          ~$44K/mes NET

ALL paths lead to Maldivas. Variance is timing (6-18 months).
```

The math is real. Execution is what matters. Phase 0 test starts Monday.
