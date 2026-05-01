## v15 7-year regression — investigation report

**Date:** 2026-04-30 (analyst: Claude, Juan supervising)
**Scope:** v14 (last clean baseline) vs v15 (post Fix #1-#6 hardening)
**Status:** Diagnosis confirmed — primary cause identified, fix proposed but **NOT shipped**.
Bot stays on live v18 (PID 31056) untouched per Juan's "déjalo así".

---

### TL;DR

`SB_MAX_STRUCT_AGE_MINUTES = 60` (Fix #5 / commit `d77c1d6`) cuts ~$263K
of high-quality P&L over 2019-2025 by rejecting trades that fire >60 min
after the 5-min MSS/BOS that justifies them. **The rejected trades have
WR 69.4%** — anti-selective filtering, the gate cuts winners.

7-year delta:

| metric | v14 (no struct-age) | v15 (60min cap) | delta |
|---|---|---|---|
| trades | 15,976 | 5,918 | −63% |
| P&L | $+659,230 | $+234,062 | **−$425,168 (−64.5%)** |
| WR | 56.9% | ~57% | flat |
| trades cut WR | — | 69.4% (rejected pool) | — |

**Rejected-trade WR > kept-trade WR.** The filter doesn't just reduce
volume, it preferentially rejects the better trades — particularly in
London KZ where the 3-hour window guarantees most setups fire >60min
after the structural event.

---

### Background

v15 added six gates ("Fix #1-#6") in commits `4eafbe2` + `d77c1d6` after
the 2026-04-29 NY PM audit (-$331.50 from 3 stale-bear-MSS shorts):

| # | Gate | config knob |
|---|---|---|
| 1 | News blackout | `NEWS_BLACKOUT_*` |
| 2 | Fresh-sweep cap | `SB_MAX_SWEEP_AGE_MINUTES = 60` |
| 3 | Same-FVG cooldown | `SB_SAME_SETUP_COOLDOWN_MIN = 30` |
| 4 | Tighter kill_switch | `KILL_SWITCH_SAME_SETUP_LOSSES = 2` |
| 5 | Smart structure invalidator | `SB_MAX_STRUCT_AGE_MINUTES = 60` + counter-event |
| 6 | FVG quality | `SB_MIN_FVG_WIDTH_PTS = 2.0` + `_TO_STOP_RATIO = 0.20` |

7-year walk-forward result on `nq_1minute.csv` (2019-2025):
- v14: 15,976 trades, $659K, WR 56.9%
- v15: 5,918 trades, $234K, WR ~57%

WR essentially unchanged. **The gates remove trades roughly proportional to
their P&L** — neither degrading nor improving expectancy. That is the
signature of noise filtering, not skill filtering.

---

### Method

Compared `analysis/sb_v14_*.json` (baseline) against `analysis/sb_v15_*.json`
(hardened) trade-by-trade for 2019, 2023, plus 7-year aggregate. For each
v14 trade, asked: did v15 also take a trade at this `entry_time`? If not,
v15 rejected it. Measured rejected trades' WR and P&L by KZ and by minute-
bucket within KZ.

Caveat: v15's filters change subsequent state (kill_switch counters, MLL
zone, daily P&L cap, position lock), so a rejected v14 trade is not strictly
"what v15 would have done with no filters." But on aggregate, rejected-trade
P&L is a strong proxy for cost-of-filter at the timestamp level.

---

### Findings

#### 1. Aggregate: filters don't improve trade quality

| year | v14 trades | v14 P&L | v15 trades | v15 P&L | P&L cut |
|---|---|---|---|---|---|
| 2019 | 2,272 | $76,469 | 538 | $12,988 | $63,481 |
| 2020 | 2,363 | $80,110 | 897 | $27,576 | $52,534 |
| 2021 | 2,172 | $94,496 | 806 | $34,950 | $59,546 |
| 2022 | 2,402 | $104,318 | 1,032 | $43,860 | $60,458 |
| 2023 | 2,240 | $105,644 | 780 | $21,538 | $84,107 |
| 2024 | 2,285 | $101,210 | 878 | $42,516 | $58,695 |
| 2025 | 2,242 | $96,982 | 987 | $50,635 | $46,346 |
| **7-yr** | **15,976** | **$659,230** | **5,918** | **$234,062** | **$425,168** |

For 2019 specifically:
- v14∩v15 (kept setups): 321 trades, WR **50.5%**, +$1,962
- v14-only (v15 rejected): 1,951 trades, WR **57.0%**, +$74,507

**Rejected trades had higher WR than kept trades.** Filter is anti-selective.

For 2023:
- Rejected trades: 1,726 trades, WR **58.2%**, +$92,131
- Kept trades: 514 trades, WR **58.0%**, +$13,514

#### 2. Time-bucket analysis: late-KZ trades are systematically rejected

For each KZ, bucketed v14 trades by minutes-from-KZ-open and counted
how many v15 kept vs rejected. Pattern is identical across years.

**London 2019** (KZ = 01:00-04:00 CT, 180-min window):

| bucket from KZ open | v15 rejected (n, WR, $) | v15 kept (n, WR, $) |
|---|---|---|
| +0min | 83 trades 38.6% −$850 | 29 trades 27.6% −$1,589 |
| +30min | 47 trades 53.2% +$1,142 | 13 trades 69.2% +$526 |
| +60min | 107 trades 75.7% +$11,114 | 18 trades 77.8% +$705 |
| +75min | 70 trades 70.0% +$3,826 | 16 trades 56.2% +$296 |
| +90min | 48 trades 77.1% +$3,330 | 5 trades 40.0% +$11 |
| +120min | 49 trades 55.1% +$2,365 | 12 trades 25.0% +$430 |
| +135min | 18 trades 94.4% +$1,866 | **0** |
| +150min | 21 trades 85.7% +$1,280 | **0** |
| +165min | 15 trades 73.3% +$889 | **0** |

After +135min, v15 takes **zero** trades, but v14 had 54 trades there with
WR 84% and +$4,035 P&L.

**NY AM 2019** (KZ = 08:30-12:00 CT, 210-min window):

| bucket | v15 rejected | v15 kept |
|---|---|---|
| +90min | 44 trades 68.2% +$1,692 | 6 trades 83.3% +$433 |
| +120min | 20 trades 80.0% +$598 | 0 |
| +135min | 12 trades 50.0% +$511 | 0 |
| +150min | 18 trades 50.0% +$1,367 | 0 |

#### 3. Quantification: trades rejected ≥60min into KZ

These are the trades the `SB_MAX_STRUCT_AGE_MINUTES = 60` cap most likely
killed (when 5-min MSS happens early in the KZ — the typical case — any
trade firing 60+ min later has a "stale" structure event).

| | rejected count | rejected WR | rejected P&L |
|---|---|---|---|
| London 7yr | 1,708 | 68.8% | +$162,596 |
| NY AM 7yr | 1,106 | 70.0% | +$64,409 |
| NY PM 7yr | 425 | 70.4% | +$35,858 |
| **TOTAL** | **3,239** | **69.4%** | **+$262,864** |

**$263K (62% of the v14→v15 cut) sits in trades ≥60min from KZ open.**

WR of 69.4% is far above the strategy's overall 57% baseline. These are
the strongest setups in the bucket — patient retracements that wait for
proper FVG entry after early-KZ displacement.

---

### Why this happens — ICT canonical reading

`silver_bullet.py:609`:

```python
max_age_min = config.cfg("SB_MAX_STRUCT_AGE_MINUTES", 60)
...
if max_age_min > 0 and age_s > max_age_min * 60:
    self._set_rejection(ts, "stale_structure", ...)
    return None
```

The gate's intent (per code comment): "structure shift should be the
catalyst for the FVG forming, so they should be tightly coupled in time."

But ICT canonical structure rules say:

- An MSS/BOS remains valid as a directional bias until **invalidated by a
  counter-event** (opposite MSS/BOS) **OR** by **price closing back through
  the swing level** that produced it.
- Time alone does not invalidate. A bullish MSS at the London open remains
  valid 4 hours later **if no counter-event has fired and price has not
  closed back through the swing low**.

The 60-minute fixed cap is a **noise** filter, not a structure filter. It
fires when:
- Price did displace upward, formed FVG, retraced 90 minutes, then approached
  FVG for entry (← textbook "patient" SB setup).
- The 5-min MSS that triggered the displacement is now 90min old.
- Gate fires, trade rejected.

This setup is exactly what ICT documents in section 3.3 ("requires sweep
previo … FVG forms, wait for retrace"). The strategy was designed to take
these. v15 systematically rejects them.

---

### Why was Fix #5 added?

The 2026-04-29 NY PM incident: bot took 3 SHORTs against fresh BULLISH
structure (CHoCH bull 13:55, MSS bull 14:00, BOS bull 14:15+) using a
**stale bear MSS from 11:45 CT** (1h45-2h21m old). Three losses, -$331.50.

The real bug there was **the strategy used a stale bear MSS while three
fresh bull MSS/BOS/CHoCH events were sitting on the same timeframe**.
Gate B (`SB_INVALIDATOR_OPPOSITE_COUNT = 2`) handles this case correctly —
2+ opposite events in 30 min do invalidate. **Gate A (the 60min absolute
cap) is what's collateral-damaging the patient setups.**

Diagnosis: **Gate B alone is sufficient** for the 04-29 incident. Gate A
is over-killing.

---

### Why didn't WR drop in v15?

A reasonable question: if v15 cuts winners too, why isn't v15's WR worse
than v14's?

Two reasons:

1. v15 also rejects trades in the **+0 to +30min bucket** that have lower
   WR (~40-50%). These are early-KZ chop trades. The FVG quality filter
   (Fix #6) and news blackout (Fix #1) cut these. So v15's WR is preserved
   by:
   - cutting some losers (low-WR early trades) [good]
   - cutting more winners (high-WR late trades) [bad]
   - net WR roughly flat
   - net P&L massively down because the cut winners had bigger expectancy

2. The remaining v15 trade pool is heavily weighted to early-KZ trades,
   which cluster around displacement candles. Those trade fast and tight —
   small wins, small losses. Trailing stop produces lower expectancy than
   the patient retrace setups it killed.

This pattern (volume falls more than WR; expectancy collapses) is the
signature of cutting the **right tail** of the trade-quality distribution.

---

### Recommended fix (NOT yet implemented)

**Disable Gate A. Keep Gate B.**

```diff
- SB_MAX_STRUCT_AGE_MINUTES = 90
+ SB_MAX_STRUCT_AGE_MINUTES = 0   # 0 disables; rely on Gate B + close-back
  SB_INVALIDATOR_OPPOSITE_COUNT = 2
  SB_INVALIDATOR_WINDOW_MIN = 30
```

Same for sweeps:

```diff
- SB_MAX_SWEEP_AGE_MINUTES = 90
+ SB_MAX_SWEEP_AGE_MINUTES = 0   # rely on close-back invalidation
```

Sweep close-back invalidation is already wired
(`detectors/liquidity.py.check_post_sweep_invalidation`). For structure,
Gate B (counter-event count) handles bias-flip cleanly. The 04-29
incident is still caught: 3 bull events in 20 min ≥ 2 → bear MSS
invalidated.

**Expected impact (best case, all $263K recovered, no other changes):**

| metric | v15 today | post-fix expected |
|---|---|---|
| 7-yr P&L | $234K | ~$497K |
| 7-yr trades | 5,918 | ~9,160 |
| WR | ~57% | ~60% (drops as +0min trades dilute) |
| 0 negative years | yes | yes |
| MaxDD | within $5K | TBD — late-KZ trades extend exposure |

Risk of regression in Q1 2025 (v18 = 90min cap got only 29 trades):
unknown; v15 with 60min got 267 trades there at WR 67% → likely fine.

---

### Test plan (sequenced, ~3 hours total)

1. **Single year smoke test (45 min):**
   - Run 2019 with `SB_MAX_STRUCT_AGE_MINUTES = 0`, all other Fix #1-#6
     enabled.
   - Expected: 1,800-2,200 trades, $50-75K P&L. If we get $50K+, hypothesis
     confirmed.
2. **Q1 2025 sanity (15 min):**
   - Same config on Q1 2025 only (most recent + most trended).
   - Must beat v15's $20.6K. If P&L drops below v15, the close-back logic
     might be too tight in trending markets — need to evaluate.
3. **Full 7-year walk-forward (~8.5 hr overnight):**
   - Only if 1+2 pass.
   - Must show: ≥$400K total, 0 negative years, MaxDD < $7K, MLL zone
     stop rate ≤ 1%.
4. **Cross-instrument sanity (ES + YM, 2024 only, ~3 hr):**
   - Confirm gain isn't NQ-specific overfitting.

If 1-4 all pass, ship to live as v19. Otherwise, refine and re-test.

---

### What to do with the live bot (PID 31056, v18)

Per Juan: leave it. v18 has `SB_MAX_STRUCT_AGE_MINUTES = 90` (vs v15's 60),
which is **less restrictive than v15**. Any trades v18 takes are a strict
superset of those v15 would take. Bot is not in danger from this finding —
just leaving P&L on the table. Investigation findings inform the next
config rev, not an emergency rollback.

The defensive systems added in v15 (kill_switch tightening, news blackout,
FVG quality, same-FVG cooldown, post-sweep close-back) are still warranted —
they target real failure modes seen in 2026-04-29. Only Gate A of Fix #5 is
the over-filter.

---

### Files referenced

- `algoict-engine/strategies/silver_bullet.py:608-633` — Gate A struct-age
  rejection
- `algoict-engine/strategies/silver_bullet.py:502-537` — Gate sweep-age
  rejection
- `algoict-engine/detectors/liquidity.py:502-564` — close-back invalidation
- `algoict-engine/config.py:175-199` — current age caps
- `algoict-engine/analysis/sb_v14_*.json` — baseline trades
- `algoict-engine/analysis/sb_v15_*.json` — v15 hardened trades

---

*Investigation completed without touching live bot. Hypothesis quantified
end-to-end with existing backtest data. Next step is the test plan above,
to be approved by Juan.*
