<h1 align="center">AlgoICT</h1>

<p align="center">
  <strong>6 Layers of Intelligence. 20-Point Confluence. One Mission: Pass the Combine.</strong><br/>
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

| # | Name | RR | Kill Zone | Entry |
|---|------|-----|-----------|-------|
| 1 | NY AM Reversal | 1:3 | 8:30-11:00 AM | 5min |
| 2 | Silver Bullet | 1:2 | 10:00-11:00 AM | 1min |
| 3 | Swing HTF | 1:2 | Daily scan | 4H |

---

## 20-Point Confluence

ICT (14): liquidity grab +2, FVG +2, OB +2, MSS +2, KZ +1, OTE +1, HTF bias +1, HTF OB/FVG +1, PDH/PDL +1
SWC (1): sentiment alignment +1
GEX (3): wall alignment +2, regime +1
VPIN (2): validated sweep +1, quality session +1

**12+ = A+ | 9-11 = high | 7-8 = standard | <7 = NO TRADE**

---

## Risk (Hardcoded)

$250/trade (floor() + expand stop) — Kill switch: 3 losses — Profit cap: $1,500/day — VPIN >0.70: flatten all — Heartbeat: 5s or flatten — Topstep MLL $2K / DLL $1K — Max 50 MNQ

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

# Tests
python -m pytest tests/ -v

# Backtest
python -m backtest.backtester --strategy ny_am_reversal --data ../data/mnq_1min.csv

# Combine Simulator
python -m backtest.combine_simulator --data ../data/mnq_1min.csv

# Paper trading
python main.py --mode paper

# Strategy Lab
python -m strategy_lab.lab_engine --mode generate --count 5

# Dashboard
cd ../algoict-dashboard && npm run dev
```

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
| `AlgoICT_Tasks.md` | 185 tasks for Focustack |
| `.claude/skills/*.md` | 7 custom skills |

---

<p align="center">
  <em>"ICT ve velas. SWC ve contexto. GEX ve fuerzas. VPIN ve smart money. Strategy Lab evoluciona. Post-Mortem aprende."</em>
</p>
