<h1 align="center">AlgoICT</h1>

<p align="center">
  <strong>6 Layers of Intelligence. ICT Methodology. One Mission: Pass the Combine.</strong><br/>
  <em>Powered by SaaS Factory V4</em>
</p>

---

## What is AlgoICT

AlgoICT automates the ICT (Inner Circle Trader) methodology by Michael J. Huddleston with 6 proprietary intelligence layers that no other trading bot has:

| Layer | Module | What It Sees |
|-------|--------|-------------|
| Price Action | **ICT Core** | Candles, structure, institutional patterns |
| Context | **SWC** | News, economic calendar, AI market mood |
| Structure | **GEX** | Options dealers hedging futures |
| Flow | **VPIN** | Smart money executing in real-time |
| Evolution | **Strategy Lab** | AI discovers new patterns (9 anti-overfit gates) |
| Defense | **Post-Mortem** | AI learns from every loss |

**Two engines:** MNQ futures intraday (TopstepX) + S&P 500 stocks swing (Alpaca)

---

## Stack

| Layer | Tech |
|-------|------|
| Engine | Python 3.12+ (local Windows) |
| MNQ Broker | TopstepX API (ProjectX) |
| Stocks Broker | Alpaca API |
| AI Agents | Claude API (Sonnet) |
| Dashboard | Next.js 16 + Tailwind + shadcn/ui |
| Database | Supabase (PostgreSQL + Realtime) |
| Testing | pytest + Playwright |
| Deploy | Vercel (dashboard) + Local (engine) |

---

## 3 Strategies

| # | Name | Exit | Kill Zone (CT) | Entry TF |
|---|------|------|----------------|----------|
| 1 | NY AM Reversal | 1:3 RR | 8:30–12:00 | 5min |
| 2 | Silver Bullet | Trailing (no fixed TP) | London 01–04 / NY AM 08:30–12 / NY PM 13:30–15 (RTH Mode v4) | 1min |
| 3 | Swing HTF | 1:2 RR | Daily scan | 4H |

Silver Bullet is FVG-only (no HTF bias required) with a ≥10pt framework gate. See [`SILVER_BULLET_STRATEGY_GUIDE.md`](SILVER_BULLET_STRATEGY_GUIDE.md) for the full setup anatomy, visual walkthroughs, and SB-specific confluence table.

---

## Confluence Scoring

**Engine-wide**: 19 points across 14 factors (`config.CONFLUENCE_WEIGHTS`) — liquidity grab +2, FVG +2, OB +2, MSS +2, KZ +1, OTE +1, HTF bias +1, HTF OB/FVG +1, PDH/PDL +1, SWC +1, GEX wall +2, GEX regime +1, VPIN sweep +1, VPIN session +1.

**NY AM Reversal** uses the full 19-pt scale. Tiers: `12+ = A+ | 9-11 = high | 7-8 = standard | <7 = NO TRADE`. Min confluence enforced as a hard gate.

**Silver Bullet** uses a 10-pt SB-specific subset (see `config.SB_APPLICABLE_FACTORS`): `target_at_pdh_pdl +2, OB +1, HTF bias +1, SWC +1, GEX wall +2, GEX regime +1, VPIN sweep +1, VPIN session +1`. The 5 structural factors (sweep, FVG, MSS, KZ, framework≥10pts) are hard gates, scored 0 pts each. SB does NOT enforce a minimum confluence — filtering happens at the gates + kill switch + MLL zones. Logs + Telegram show both numbers: `confluence=11/19 (SB: 4/10)`.

---

## Risk (Hardcoded)

$250/trade (floor() + expand stop) — Kill switch: 3 consecutive losses/session — Profit cap: $1,500/day — Hard close: 3:00 PM CT — VPIN ≥0.70: FLATTEN ALL (resume ≤0.55) — Heartbeat: 5s or flatten — Topstep MLL $2,000 / DLL $1,000 — Max 50 MNQ contracts.

**Topstep MLL zones** (auto-activated with `--topstep`): normal < 40% | warning ≥40% (−25% size, min_conf +1) | caution ≥60% (−50% size, min_conf +2) | stop ≥85% (block new entries). 95% Combine pass rate on NY AM 2024.

---

## Telegram Verbosity

Three levels via `TELEGRAM_VERBOSITY` in `.env`:

| Level | What you get | Volume/day |
|-------|-------------|------------|
| `quiet` | Trade entries/exits, kill switch, heartbeat, daily summary, VPIN shield | 5–10 msgs |
| `normal` (default) | Above + KZ enter/close summaries, liquidity sweeps, signal fired | 15–25 msgs |
| `verbose` | Above + near-miss rejected signals (FVG present but no sweep, framework <10pts, etc.) | 40–80 msgs |

Throttled per alert-type to prevent reject-storms. See `config.TELEGRAM_THROTTLE_SEC`.

---

## 7 Custom Skills

| Skill | Purpose |
|-------|---------|
| `/python-engine` | Motor Python, TDD, detector patterns |
| `/backtest` | Backtester, Combine Simulator, validation gate |
| `/post-mortem` | Claude API loss analysis, 9 categories |
| `/sentiment` | SWC: news, calendar, mood, post-release scanner |
| `/gamma` | GEX: Black-Scholes, call/put walls, gamma flip |
| `/strategy-lab` | AI researcher, 9 anti-overfitting gates |
| `/toxicity` | VPIN: order flow toxicity, flash crash shield |

---

## Quick Start

```bash
# Setup
cd algoict-engine
pip install -r requirements.txt
cp .env.example .env

# Tests (1,477 passing as of 2026-04-22)
python -m pytest tests/ -v

# Backtest (Silver Bullet Q1 2024)
python scripts/run_backtest.py --strategy silver_bullet \
    --databento ../data/nq_1minute.csv --start 2024-01-01 --end 2024-03-31 \
    --topstep --combine-reset-on-breach --no-supabase

# Combine Simulator
python scripts/combine_simulator.py --data ../data/mnq_1min.csv

# Paper trading
python main.py --mode paper

# Strategy Lab
python -m strategy_lab.lab_engine --mode generate --count 5

# Dashboard
cd ../algoict-dashboard && npm run dev
```

---

## Validation Status (2026-04-22)

- **Tests**: 1,477 passing (engine) · dashboard build ✓
- **7-year walk-forward** (2019–2025, Silver Bullet v8 trailing RTH Mode):
  - **14,186 trades · 43.8% WR · +$673,000 aggregate · PF 1.91**
  - **0 negative years** (range $70K - $116K, std dev $15K)
  - **Monthly hit rate 91.7%** (77 of 84 months positive)
  - **Daily hit rate 54.4%** (983 of 1,808 trading days positive)
  - **DLL breach rate 0.61%** (11 days ≤ -$1000 in 1,808 days)
- **Full 2024 baseline**: 2,067 trades · 44.1% WR · +$115,547 · **PF 2.05** · max DD $3,864 · 7 combine resets
- **Kill-zone contribution across 7 years**: London 64.9% · NY AM 24.4% · NY PM 10.7%
- **Combine Simulator**: 72.4% pass rate (210 random-start attempts)
- **Q1 2024 equal_levels A/B**: flat-to-negative (kept OFF); see `SILVER_BULLET_STRATEGY_GUIDE.md` §11
- **Q1 2024 risk ladder A/B**: survives better (−71% combine resets, −28% max DD) but cuts P&L 82% → **rejected**, V8 flat $250 retained

---

## Costs

| Item | Cost |
|------|------|
| Topstep Combine | $49/mo |
| TopstepX API | $14.50/mo |
| FirstRateData (MNQ+NQ+ES+YM) | ~$160 once |
| Claude API | ~$10-15/mo |
| GEX data (optional upgrade) | $0-49/mo |
| Everything else | Free |
| **Monthly** | **$72-130** |

---

## Key Files

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Factory OS — brain of the agent |
| `BUSINESS_LOGIC.md` | Complete product spec |
| `BUILD_TASKS.md` | Sequential build guide for Claude Code |
| `SILVER_BULLET_STRATEGY_GUIDE.md` | SB theory, visual walkthroughs, SB-specific confluence |
| `SILVER_BULLET_RESULTS.md` | 7-year walk-forward + Combine Simulator results |
| `.claude/skills/*.md` | 7 custom skills |

---

<p align="center">
  <em>"ICT ve velas. SWC ve contexto. GEX ve fuerzas. VPIN ve smart money. Strategy Lab evoluciona. Post-Mortem aprende."</em>
</p>
