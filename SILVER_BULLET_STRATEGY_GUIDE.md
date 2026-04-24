# Silver Bullet — Strategy & Visual Guide

> **Target**: Topstep $50K Combine ($3,000 profit, $2,000 MLL, $1,000 DLL)
> **Instrument**: MNQ (Micro E-mini Nasdaq-100 futures)
> **Entry TF**: 1-minute · **Context TF**: 5-minute
> **Risk/trade**: $250 · **Framework min**: 10 MNQ points (40 ticks)
> **Code**: `algoict-engine/strategies/silver_bullet.py`
> **Source**: ICT 2024 Mentorship (Oct 25, 2024)

---

## Table of contents

1. [The theory in one paragraph](#1-theory-in-one-paragraph)
2. [The three daily windows (kill zones)](#2-the-three-daily-windows-kill-zones)
3. [Setup anatomy — what the bot looks for](#3-setup-anatomy--what-the-bot-looks-for)
4. [Visual walkthrough — bullish Silver Bullet](#4-visual-walkthrough--bullish-silver-bullet)
5. [Visual walkthrough — bearish Silver Bullet](#5-visual-walkthrough--bearish-silver-bullet)
6. [What the bot actually SEES (dashboard overlays)](#6-what-the-bot-actually-sees-dashboard-overlays)
7. [Entry / stop / target — exact ICT rules](#7-entry--stop--target--exact-ict-rules)
8. [Confluence scoring (0–19 points)](#8-confluence-scoring-019-points)
9. [Risk management layers](#9-risk-management-layers)
10. [Why some sessions end with 0 trades](#10-why-some-sessions-end-with-0-trades)
11. [What the bot does NOT see (honest limitations)](#11-what-the-bot-does-not-see-honest-limitations)

---

## 1. Theory in one paragraph

**Silver Bullet** is ICT's scalping model for the three highest-probability 60-minute windows of the NY session. Price is assumed to run algorithmically — it visits one pool of stop-orders, reverses, then travels to the next pool. The trade is: wait for price to **take liquidity** (sweep stops) on one side, then when it **shifts structure** in the opposite direction creating a Fair Value Gap (FVG), enter on the retrace into that FVG with a stop just beyond the FVG's far side, targeting the next pool of stops.

> "No es necesariamente el bias — predominantemente solo tienes que considerar dónde está el próximo nivel de atracción de liquidez." — ICT

No HTF bias required. No fixed risk:reward. Direction comes from the FVG; target is the nearest unswept pool of liquidity ≥10 points away.

---

## 2. The three daily windows (kill zones)

All Silver Bullet windows are defined in **ET** (New York local). CT is always ET − 1h.

| Window | ET | CT | Why it matters |
|--------|-----|-----|----------------|
| **London Open SB** | 03:00–04:00 | 02:00–03:00 | London traders step in; Asia range is complete |
| **AM Session SB**  | 10:00–11:00 | 09:00–10:00 | Post-open liquidity run — sweeps of PDH/PDL/EQL |
| **PM Session SB**  | 14:00–15:00 | 13:00–14:00 | Late-day continuation / mean reversion |

**In code** (`config.KILL_ZONES`, CT):
```
london_silver_bullet : 02:00-03:00 CT
silver_bullet        : 09:00-10:00 CT
pm_silver_bullet     : 13:00-14:00 CT
```

> **v4 "RTH Mode" note**: the live engine currently arms the WIDER kill zones (`london` 01-04 CT, `ny_am` 08:30-12 CT, `ny_pm` 13:30-15 CT) so it can catch setups that form slightly outside the strict 60-min windows. The strict Silver Bullet windows sit *inside* those wider zones.

### Daily timeline (CT)

```
            Asian KZ          London KZ             NY AM KZ              NY PM KZ
         |------------||-----|SB|------||----|SB|-----||---|SB|----|
 20:00   00:00   02  02:00  03:00     08:30 09:00 10:00 12:00 13:00 14:00 15:00
                        ^^^ Silver Bullet windows ^^^
```

---

## 3. Setup anatomy — what the bot looks for

**ALL of the following must be true** in order before a Signal fires:

1. **In an active kill zone** — current 1-min bar timestamp is inside one of the three SB windows (or wider RTH windows in v4).
2. **Sweep of OPPOSITE liquidity** has happened recently — SSL / PDL / PWL / equal_lows for a long; BSL / PDH / PWH / equal_highs for a short. `level.swept == True` in `tracked_levels`.
3. **5-min structure shift** — a BOS or MSS on the 5-min timeframe, in the direction of the trade, exists in the recent context buffer.
4. **1-min FVG** formed INSIDE the window, in the direction of the trade — first FVG in the window wins; direction of the FVG = direction of the trade.
5. **Framework ≥ 10 MNQ points** — distance from entry price to the next unswept liquidity pool in the trade direction ≥ 10.0 points. Sub-10pt setups are rejected.
6. **Not in cancel window** — current bar is NOT inside the last 10 minutes of the active kill zone.
7. **Kill switch not tripped** — today's 3-consecutive-loss counter for THIS kill zone is below 3. (Each SB window has its own budget — losing 3 in London does NOT lock NY AM.)
8. **Not past hard close** — before 15:00 CT on any given trading day.

### The chronological story

```
 [ before window ]       [ INSIDE window ]               [ after entry ]
                                                         
  1. price takes      2. structure shift    3. FVG        4. price retraces
     liquidity on       (MSS/BOS) on           forms on      INTO the FVG
     opposite side      5-min in our           1-min from
     (SSL/BSL)          direction              displacement
                                            ---> ENTRY -----> TARGET (next pool)
```

---

## 4. Visual walkthrough — bullish Silver Bullet

Scenario: London Open SB, 02:00–03:00 CT. Price spent Asia grinding lower, taking out equal lows. Then reverses.

```
 price
   |
   |          Liquidity target: BSL /     ..................... <- TARGET (BSL)
   |          equal_highs above                                    (≥10 pts above entry)
   |                                       ___________
   |                                      |         |     <-- FVG (bullish gap)
   |                                      | (fvg)   |         entry = fvg.top + 1 tick
   |                                      |_________|        
   |                                                 \
   |                                                  \                  
   |                                    /|                             
   |                                   / |      <-- displacement up (big green candle)
   |                                  /  |          creates the FVG                 
   |                   .............-.   |
   |                                 \__/         <-- SWEEP of SSL / equal_lows (wick through, close back up)
   |                                          
   |    ..............................................  <-- old equal_lows / SSL (now swept)
   |                     |              |         |
   |                     v              v         v
   |                  take-stops     MSS up     FVG formed
   |                  (sweep)        on 5min    on 1min
   |____________________________________________________________ time
     01:50 CT          02:05          02:12     02:18   02:25
```

**Exact mechanics** (ICT canonical):

| Piece | Value |
|-------|-------|
| `entry_price` | `FVG.top + 1 tick` |
| `stop_price`  | `FVG.stop_reference (candle 1 low) - 1 tick` |
| `target_price`| nearest unswept BSL / PDH / PWH / equal_highs above, distance ≥ 10 pts |
| `direction`   | `long` (bullish FVG) |

**Why the sweep is required**: without a sweep, the FVG is just a gap. With a sweep, the FVG is the "receipt" of the algorithm flipping from accumulation to distribution — smart money is now long.

---

## 5. Visual walkthrough — bearish Silver Bullet

Scenario: NY AM SB, 09:00–10:00 CT. Price grinds higher overnight, takes PDH, then reverses.

```
 price
   |    ..............................................   <-- PDH / equal_highs (now swept)
   |                /\___/                                <-- SWEEP (wick above PDH, close back below)
   |               /     \
   |              /       \                               <-- displacement down (big red candle)
   |                       \  |
   |                        \ |    creates the FVG
   |                         \|
   |                          .
   |                           ___________
   |                          |         |    <-- FVG (bearish gap)
   |                          | (fvg)   |        entry = fvg.bottom - 1 tick
   |                          |_________|        
   |                          /
   |                         /    <-- price retraces UP INTO fvg (order fills here)
   |                        /
   |                       v    <-- ENTRY
   |
   |
   |          ...............................    <-- TARGET (SSL / equal_lows / PDL)
   |                                                 (≥10 pts below entry)
   |____________________________________________________________ time
     09:00 CT     09:08          09:14    09:20
```

**Exact mechanics** (mirror of the bullish case):

| Piece | Value |
|-------|-------|
| `entry_price` | `FVG.bottom - 1 tick` |
| `stop_price`  | `FVG.stop_reference (candle 1 high) + 1 tick` |
| `target_price`| nearest unswept SSL / PDL / PWL / equal_lows below, distance ≥ 10 pts |
| `direction`   | `short` (bearish FVG) |

---

## 6. What the bot actually SEES (dashboard overlays)

The `/chart` page in the dashboard renders in real time *everything the bot is using to make decisions*. Overlays come from two Supabase Realtime channels:

| Overlay | Source column | Render |
|---------|---------------|--------|
| Candles + volume | `market_data` (1-min OHLCV) | lightweight-charts v5, volume subpanel |
| Kill zone shading | computed client-side (Intl / CT) | bottom 5% histogram strip |
| FVG zones | `bot_state.fvg_top3` JSONB | solid rectangles (green=bull, red=bear) |
| Inverted FVG | `bot_state.ifvg_top3` | **dashed**-outline rectangles |
| Order Blocks | `bot_state.ob_top3` | heavier rectangles |
| Tracked levels | `bot_state.tracked_levels` | horizontal price lines |
| · PDH / PDL | `type: 'PDH'/'PDL'` | blue lines |
| · PWH / PWL | `type: 'PWH'/'PWL'` | purple lines |
| · Equal H/L | `type: 'equal_highs'/'equal_lows'` | amber lines |
| · Swept level | `swept: true` | zinc-500 dashed + ✖ label |
| Structure events | `bot_state.struct_last3` | MSS/BOS arrows, CHoCH circles |
| Signal fire | `signals` table realtime | "FIRE {score}" arrow marker |
| Trade entry/exit | `market_levels.trades` | arrows + P&L text |

The **info panel** in the top-right mirrors `bot_state` scalars:

```
 status:   ACTIVE          bias:    bullish (D) / bearish (W)
 KZ:       ny_am           min_conf: 7
 VPIN:     0.42 (normal)   MLL zone: normal
 SWC mood: cautious        daily P&L: +$125
 last displacement:  09:12:00 up 14.50pts
```

If you ever suspect "the bot didn't see X", the first place to look is the **tracked_levels** panel — if a level is missing, it wasn't seeded; if it's not swept, the sweep rule fails; if it's amber-dashed-✖, the bot used it and discarded it.

---

## 7. Entry / stop / target — exact ICT rules

### Entry

- **Limit order preferred** ("more efficient and professional" — ICT).
- **Market order acceptable** if the limit is missed by fast movement.
- **No rejection wait** — first touch = fill. No confirmation candle.
- **If the limit runs away: CANCEL, don't chase.** Better to miss than to slip.
- **1-tick offset** from FVG proximal edge (long: `fvg.top + 1 tick`; short: `fvg.bottom - 1 tick`).

### Stop

- **1 tick beyond FVG distal edge** (long: `fvg.stop_reference - 1 tick`; short: `fvg.stop_reference + 1 tick`).
- The FVG's "stop reference" is candle-1 of the FVG (the pre-gap bar).
- **Never widen the stop on a bad fill** — take the loss, maintain structural integrity.
- **No ATR-based stops.** Ever.

### Target

- **NEVER fixed RR.** Targets are pools of liquidity:
  - PDH / PDL (previous day high/low)
  - PWH / PWL (previous week high/low)
  - Equal highs / equal lows (resting buy/sell stops)
  - Old swing highs/lows, imbalance gaps
- **MNQ minimum framework**: ≥ 10 points / 40 ticks to the next pool. Below 10 pts, skip the trade.
- Can scalp 5 points once in profit if uncomfortable, but the framework *filter* is 10.

### Trade management (live + backtest default)

Three modes in `config.TRADE_MANAGEMENT`:

| Mode | Behavior | Where used |
|------|----------|------------|
| `trailing` **(default)** | No fixed TP — trail to last 5-min swing | live + backtest |
| `partials_be` | Close 50% at 1R + move stop to BE | backtest only; live logs ERROR |
| `fixed` | Standard SL/TP at signal price | ablations |

> **ICT warning on BE**: "don't run your stop up real quick to break even — just let it move." `partials_be` contradicts ICT guidance on strong-runway days. Use `trailing` live.

---

## 8. Confluence scoring — Silver Bullet specific (0–10 points)

> **Historical note**: the 19-point confluence table in `config.CONFLUENCE_WEIGHTS` was designed for **NY AM Reversal**, which trades OB entries inside the OTE fib zone with HTF bias confirmation. Silver Bullet uses a different entry model (FVG-only, no bias required) — most of those factors don't apply. This section shows the factors **SB actually evaluates**.

### Structural gates (required — 0 pts each)

These **must all be present** for the signal to even reach the scorer. Scoring them would be redundant (every SB signal would automatically earn +7 just for existing).

| Gate | Rule |
|------|------|
| Sweep of opposite pool | `sweep.swept == True` on SSL/BSL/PDL/PDH/PWL/PWH/EQL/EQH |
| 1-min FVG in direction | first unmitigated FVG inside the window, matching trade direction |
| 5-min MSS / BOS | structure event in trade direction within recent context |
| Active kill zone | bar timestamp inside London / NY AM / NY PM SB window |
| Framework ≥ 10 pts | distance from entry to next unswept liquidity pool |

### Scored factors (SB-specific, max 10 pts)

These are the factors that actually **discriminate** between an average SB setup and an A+ one.

| Factor | Pts | What it means for SB |
|--------|-----|----------------------|
| **Target at PDH / PDL / PWH / PWL** | +2 | target is a daily/weekly institutional pool, not just an intraday equal level — stronger magnetism |
| **OB overlap at entry** | +1 | ICT "Institutional Orderflow Entry Drill" — FVG sitting inside a validated 1-min OB = tighter stop, higher conviction |
| **HTF bias aligned** | +1 | not a requirement (ICT explicit), but adds conviction when the D/W bias agrees with the FVG direction |
| **SWC sentiment aligned** | +1 | Claude-synthesized daily mood agrees with trade direction |
| **GEX wall near target** | +2 | dealer hedging flow reinforces the move — gamma wall acts as magnet |
| **Gamma regime favorable** | +1 | positive-gamma (mean-reverting) or negative-gamma (trending) state matches setup |
| **VPIN validated sweep** | +1 | the sweep that triggered this setup happened during genuine institutional flow (not retail noise) |
| **VPIN quality session** | +1 | current session is not toxic (VPIN < 0.55) — healthy flow regime |
| **Max** | **10** | |

### Not applicable to SB (removed)

| Factor | Why not in SB |
|--------|---------------|
| OTE Fibonacci | SB enters on FVG proximal edge, not on the 61.8–78.6 retrace zone — scorer never receives `swing_high/swing_low` from SB |
| HTF OB/FVG alignment | SB is scoped to 1-min entries + 5-min context; it doesn't pre-compute HTF overlay — scorer never receives `htf_fvgs/htf_obs` |

### Tiers (SB-specific 0–10 scale)

| Score | Tier | Sizing |
|-------|------|--------|
| `6+`  | **A+** | full position |
| `4–5` | **high** | full position |
| `2–3` | **standard** | full position |
| `0–1` | **low** | full position (gates already passed — edge comes from structure, score just adds color) |

### Current hard gate: **none**

Silver Bullet v4 operates **without a hard confluence threshold**. Q1 2024 analysis showed:
- Higher scores (6–9) had **0–16% WR**
- Minimum score (5) had **37.8% WR**

The scoring function was actively *noise* for SB. Instead, real filtering is done by:
- The 5 **structural gates** above (hard reject if any fail)
- **RiskManager kill switch** (3 consecutive losses → halt session)
- **MLL zones** (size/gate adjustments as drawdown grows)
- **VPIN shield** (flatten + halt on VPIN ≥ 0.70)

The score is still **computed and logged** on every fired signal so we have paper-trail diagnostics — but it doesn't gate entries.

### Code reference

The 19-point `config.CONFLUENCE_WEIGHTS` dict is shared between both strategies; the scorer (`detectors/confluence.py`) just sees whatever inputs each strategy passes to `.score()`. SB passes exactly 7 of the 14 inputs — the other 7 score zero for SB by construction, so the de-facto SB ceiling is already ~10 pts in practice. The tiers in `config.py` (`CONFLUENCE_A_PLUS=12`, `CONFLUENCE_HIGH=9`, `CONFLUENCE_STANDARD=7`) are **NY-AM-Reversal-calibrated** and should be ignored for SB.

---

## 9. Risk management layers

The bot has FIVE layers of risk containment — any layer can veto a trade or halt the day.

```
 ┌─────────────────────────────────────────────────────────┐
 │ Layer 1: Strategy self-filter                           │
 │    · framework ≥10pts  · not in cancel window           │
 │    · sweep+MSS+FVG all present                          │
 ├─────────────────────────────────────────────────────────┤
 │ Layer 2: RiskManager                                    │
 │    · kill switch: 3 consecutive losses → halt session   │
 │    · daily loss limit: -$750 → halt day                 │
 │    · profit cap: +$1,500 → halt day                     │
 │    · hard close: 15:00 CT → flatten                     │
 ├─────────────────────────────────────────────────────────┤
 │ Layer 3: Topstep MLL zones                              │
 │    · normal   (<40%): full size                         │
 │    · warning  (≥40%): -25% size, +1 min_conf            │
 │    · caution  (≥60%): -50% size, +2 min_conf            │
 │    · stop     (≥85%): block new entries                 │
 ├─────────────────────────────────────────────────────────┤
 │ Layer 4: VPIN toxicity shield                           │
 │    · VPIN ≥0.70 → FLATTEN ALL, halt trading             │
 │    · resume only at ≤0.55 (hysteresis)                  │
 ├─────────────────────────────────────────────────────────┤
 │ Layer 5: Heartbeat → broker                             │
 │    · 5s heartbeat to Supabase                           │
 │    · 15s silence → bot flags OFFLINE                    │
 │    · 30s silence → ALERT                                │
 │    · connection loss → flatten                          │
 └─────────────────────────────────────────────────────────┘
```

### Position sizing

Risk = $250 per trade. Contracts = `floor($250 / (stop_distance_pts * $2/pt)) `.

Example: entry 17,007.25, stop 17,003.25 → stop distance 4 pts = $8/contract → 31 contracts.
If the stop is too tight (e.g. 2pts = $4/contract → 62 contracts would exceed 50-contract cap), the engine **expands the stop** rather than reducing size, to stay at full risk on viable setups.

---

## 10. Why some sessions end with 0 trades

The bot can legitimately produce 0 trades in a whole session and still be operating correctly. Example from the **2026-04-22** paper session:

| Hour | What happened | Why no trade |
|------|---------------|--------------|
| 02:00–03:00 CT (London SB) | Market consolidated, no sweep of SSL | Rule 2 fails (no sweep) |
| 09:00–10:00 CT (AM SB)     | Hit PWH as breakout (body closed above) | Sweep requires close *back below* the level |
| 13:00–14:00 CT (PM SB)     | Price drifted toward PDL but never reached it | Rule 2 fails (no sweep of opposite pool) |

The bot's rejection log looks like:
```
EVAL silver_bullet [09:17]: confluence=5, signal=reject, reason=framework_lt_10pts
EVAL silver_bullet [09:24]: confluence=7, signal=reject, reason=no_opposite_sweep
EVAL silver_bullet [13:42]: confluence=6, signal=reject, reason=outside_kz
```

0 trades on a day when PDH/PDL/PWH/PWL stayed out of reach is **the correct behavior** — the framework rule exists precisely to keep the bot from chasing noise.

---

## 11. What the bot does NOT see (honest limitations)

Listing these explicitly so expectations stay calibrated:

1. **Order flow microstructure** (at the tick level). The bot uses 1-min bars. VPIN toxicity is approximated from bulk volume classification, not real bid/ask imbalance.
2. **News headlines between bars.** SWC sentiment is snapshotted pre-market and updated periodically. Intra-minute headline moves are invisible until the next bar closes.
3. **Tape / DOM.** No depth-of-book, no iceberg detection, no stop-hunt visualization from the book.
4. **Options OI intraday.** GEX is computed pre-market from prior close OI. Walls can move intraday from big block trades — bot won't see until next update.
5. **Correlated market moves.** The bot does not cross-reference ES, YM, DXY, or VIX in the live signal path. Those are only used in Strategy Lab validation.
6. **Discretionary context** — earnings days, Fed decisions, ETF rebalances. The `economic_calendar` module blocks trading around major events, but the list is finite.
7. **Equal highs/lows intraday refresh** — currently **OFF** in live. Q1 2024 A/B showed mixed signal (NY KZ +$780, London -$2,064). Waiting for more real sessions before enabling per-KZ.

---

## Appendix — code pointers

| Concept | File | Lines |
|---------|------|-------|
| Silver Bullet strategy class | `strategies/silver_bullet.py` | 123–end |
| FVG detection | `detectors/fair_value_gap.py` | full file |
| Sweep detection | `detectors/liquidity.py` | `check_sweep()` |
| 5-min MSS/BOS | `detectors/market_structure.py` | `update()` |
| Confluence scoring | `detectors/confluence.py` | full file |
| Position sizer | `risk/position_sizer.py` | `calculate_position()` |
| Kill switch / MLL zones | `risk/risk_manager.py` | `enable_topstep_mode()` |
| Kill zone config | `config.py` | 174–209 |
| Live engine entry | `main.py` | strategy loop |
| Backtest entry | `scripts/run_backtest.py` | `build_backtester()` |

### Validated numbers (corrected 2026-04-22)

**Full 2024** (trailing mode, 3-KZ RTH):

| Metric | Value |
|--------|-------|
| Trades | 2,067 |
| Win rate | 44.1% |
| Total P&L | +$115,547 |
| **Profit factor** | **2.05** (was erroneously published as 1.47 — that was Q1 PF, mis-propagated) |
| Avg win / loss | $247.88 / −$96.39 |
| Expectancy/trade | $55.90 |
| Max drawdown | $3,864 |
| Combine resets | 7 |
| Positive months | 11 of 12 (only Sept −$1,740 negative) |

**7-year walk-forward (2019–2025)**:

| Año | Trades | WR | P&L | PF | MaxDD | Resets |
|-----|--------|-----|------|-----|-------|--------|
| 2019 | 2,110 | 43.1% | +$70,028 | 1.68 | $3,030 | 10 |
| 2020 | 2,049 | 43.7% | +$92,203 | 1.84 | $5,813 | 10 |
| 2021 | 1,916 | 40.7% | +$110,598 | 2.06 | $5,790 | 12 |
| 2022 | 2,101 | 44.8% | +$103,804 | 2.01 | $3,810 | 8 |
| 2023 | 1,991 | 45.3% | +$91,062 | 1.88 | $4,261 | 8 |
| 2024 | 2,067 | 44.1% | +$115,547 | 2.05 | $3,864 | 7 |
| 2025 | 1,952 | 44.9% | +$89,759 | 1.86 | $3,032 | 9 |
| **AGG** | **14,186** | **43.8%** | **+$673,000** | **1.91** | — | 64 |

**Key consistency metrics**:
- **Zero negative years** — all 7 years positive
- Mean annual P&L: $96,143 · median $92,203 · std dev $15,320 (CV 15.9%)
- Worst year ($70K) is still 61% of best year ($116K) — tight band
- **Monthly hit rate: 91.7%** (77 of 84 months positive)
- **Daily hit rate: 54.4%** (983 of 1,808 trading days positive)
- **DLL breach rate: 0.61%** (only 11 days ≤ −$1,000 in 7 years)

**Kill-zone contribution (7-year aggregate)**:

| KZ | Trades | WR | P&L | % of total |
|----|--------|-----|------|------------|
| **London** | 6,403 | 43.7% | **$436,600** | **64.9%** |
| NY AM | 4,684 | 46.8% | $164,344 | 24.4% |
| NY PM | 3,099 | 39.5% | $72,057 | 10.7% |

London is the workhorse in **every single year** — not a Q1 anomaly. Any filter that cuts London (e.g. "London 2L cap") would cut the primary P&L source.

**Combine Simulator**: 72.4% pass rate (210 random-start attempts).

---

*AlgoICT — Silver Bullet strategy guide · last updated 2026-04-22*
