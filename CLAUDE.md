# AlgoICT — Factory OS

> *"Todo es un Skill. Agent-First. El usuario habla, tu construyes."*
> *Powered by SaaS Factory V4*

---

## Que es Este Proyecto

**AlgoICT** — sistema de trading automatizado con 6 capas de inteligencia:

| Layer | Modulo | Que Ve |
|-------|--------|--------|
| Price Action | **ICT Core** (7 detectors) | Velas, estructura, patrones institucionales |
| Context | **SWC** (sentiment) | Noticias, calendario, mood AI |
| Structure | **GEX** (gamma) | Dealers de opciones hedgeando futuros |
| Flow | **VPIN** (toxicity) | Smart money ejecutando en tiempo real |
| Evolution | **Strategy Lab** (AI researcher) | Descubre patrones con 9 gates anti-overfit |
| Defense | **Post-Mortem** (AI analyst) | Aprende de cada error |

**Dos motores:** MNQ intraday (TopstepX) + S&P 500 swing (Alpaca)
**Objetivo:** Pasar Topstep $50K Combine ($3,000 profit target)
**Stack:** Python engine (Windows) + Next.js dashboard (Vercel) + Supabase (bus de datos)

---

## Filosofia (Sensei Rules)

1. **Separacion:** Python = ordenes. Dashboard = READ-ONLY. Supabase = transacciones atomicas.
2. **Heartbeat:** 5s → Supabase. 15s → OFFLINE. 30s → ALERTA ROJA. Falla → flatten.
3. **Validation Gate:** NO `main.py` hasta Combine Simulator pase 12 meses ZERO violaciones.
4. **Strategy Lab:** Genera hipotesis con razon ICT, 9 gates anti-overfit, humano aprueba.
5. **Toxicity Shield:** VPIN > 0.70 = FLATTEN TODO. Override absoluto.
6. **Override Emocional:** Bot se detiene → NO intervenir.

---

## Golden Path

| Capa | Tecnologia |
|------|------------|
| Engine | Python 3.12+ (local Windows) |
| MNQ Broker | TopstepX API (ProjectX) — REST+WS+SignalR |
| Stocks Broker | Alpaca API — REST+WS |
| Data | pandas, numpy, ta-lib, scipy |
| AI Agents | anthropic (Claude Sonnet) |
| Dashboard | Next.js 16 + React 19 + Tailwind + shadcn/ui |
| Database | Supabase (PostgreSQL + Realtime + RLS) |
| Testing | pytest + Playwright MCP |
| Deploy | Vercel (dashboard) + Local (engine) |

---

## Confluence Scoring (max 20 pts, min 7)

| Factor | Pts | Source |
|--------|-----|--------|
| Liquidity grab | +2 | ICT |
| Fair Value Gap | +2 | ICT |
| Order Block | +2 | ICT |
| Market Structure Shift | +2 | ICT |
| Kill Zone | +1 | Time |
| OTE Fibonacci | +1 | ICT |
| HTF bias aligned | +1 | ICT HTF |
| HTF OB/FVG alignment | +1 | ICT HTF |
| Target at PDH/PDL | +1 | ICT |
| Sentiment alignment | +1 | SWC |
| GEX wall alignment | +2 | GEX |
| Gamma regime | +1 | GEX |
| VPIN validated sweep | +1 | VPIN |
| VPIN quality session | +1 | VPIN |

**12+ = A+ full position | 9-11 = high | 7-8 = standard | <7 = NO TRADE**

---

## Estructura

```
algoict/
├── CLAUDE.md                           # Este archivo
├── BUSINESS_LOGIC.md                   # Spec /new-app
├── README.md
├── .mcp.json
│
├── algoict-engine/
│   ├── main.py                         # Entry: heartbeat + WS + strategies
│   ├── config.py                       # ALL constants
│   ├── .env / requirements.txt
│   │
│   ├── brokers/
│   │   ├── topstepx.py                 # TopstepX (auth, WS, REST, flatten)
│   │   └── alpaca_client.py            # Alpaca (stocks)
│   │
│   ├── timeframes/
│   │   ├── tf_manager.py               # 1min → 5/15/60/240/D/W
│   │   ├── htf_bias.py                 # Weekly/Daily bias
│   │   └── session_manager.py          # Kill Zones, Asian, London
│   │
│   ├── detectors/                      # ICT Core
│   │   ├── swing_points.py
│   │   ├── market_structure.py         # BOS, CHoCH, MSS
│   │   ├── fair_value_gap.py           # FVG + mitigation
│   │   ├── order_block.py
│   │   ├── liquidity.py               # BSL/SSL, PDH/PDL, equal levels
│   │   ├── displacement.py
│   │   └── confluence.py               # 0-20 (ICT+SWC+GEX+VPIN)
│   │
│   ├── sentiment/                      # SWC Module
│   │   ├── swc_engine.py               # Pre-market orchestrator
│   │   ├── economic_calendar.py        # CPI, NFP, FOMC, GDP events
│   │   ├── news_scanner.py             # Alpha Vantage headlines
│   │   ├── fedwatch.py                 # CME rate probabilities
│   │   ├── social_scanner.py           # Fear&Greed + X/Reddit (Phase D)
│   │   ├── mood_synthesizer.py         # Claude API daily mood
│   │   ├── release_monitor.py          # Real-time release detection
│   │   └── confluence_adjuster.py      # Dynamic min_confluence
│   │
│   ├── gamma/                          # GEX Module
│   │   ├── gex_engine.py               # Pre-market GEX scan
│   │   ├── options_data.py             # NQ options OI (CBOE/MenthorQ)
│   │   ├── gex_calculator.py           # Black-Scholes + GEX per strike
│   │   ├── regime_detector.py          # Positive/negative/flip
│   │   ├── gex_overlay.py              # Call wall, put wall, levels
│   │   └── gex_confluence.py           # ICT+GEX alignment bonus
│   │
│   ├── toxicity/                       # VPIN Module
│   │   ├── vpin_engine.py              # Real-time orchestrator
│   │   ├── volume_buckets.py           # WebSocket → volume buckets
│   │   ├── bulk_classifier.py          # BVC: buy/sell classification
│   │   ├── vpin_calculator.py          # VPIN rolling calculation
│   │   ├── toxicity_classifier.py      # Level: calm→extreme
│   │   ├── shield_actions.py           # Flash crash protection
│   │   └── vpin_confluence.py          # Sweep + KZ quality bonus
│   │
│   ├── strategies/
│   │   ├── ny_am_reversal.py           # 1:3 RR, 5min entry
│   │   ├── silver_bullet.py            # 1:2 RR, 1min entry
│   │   └── swing_htf.py               # 1:2 RR, 4H entry
│   │
│   ├── risk/
│   │   ├── position_sizer.py           # floor() + expand stop
│   │   ├── risk_manager.py             # Kill switch, profit cap
│   │   └── topstep_compliance.py       # MLL, DLL, limits
│   │
│   ├── backtest/
│   │   ├── backtester.py               # Core engine
│   │   ├── combine_simulator.py        # $50K Combine sim
│   │   ├── data_loader.py              # FirstRateData + yfinance
│   │   ├── report.py                   # Stats + equity curve
│   │   └── risk_audit.py              # ZERO violations
│   │
│   ├── strategy_lab/                   # AI Researcher
│   │   ├── lab_engine.py               # Pipeline orchestrator
│   │   ├── hypothesis_generator.py     # Claude API: ICT hypotheses
│   │   ├── data_splitter.py            # Train/Val/Test LOCKED
│   │   ├── walk_forward.py             # Rolling window validation
│   │   ├── cross_instrument.py         # NQ+ES+YM validation
│   │   ├── stress_tester.py            # Noise, shift, remove, inversion
│   │   ├── occam_checker.py            # Complexity penalty
│   │   ├── candidate_manager.py        # Save/rank candidates
│   │   ├── anti_overfit_gates.py       # 9 gates
│   │   └── lab_report.py
│   │
│   ├── agents/
│   │   └── post_mortem.py              # Claude API: loss analysis
│   │
│   ├── core/
│   │   └── heartbeat.py               # 5s → flatten on fail
│   │
│   ├── alerts/
│   │   └── telegram_bot.py             # All alerts
│   │
│   ├── db/
│   │   └── supabase_client.py          # Atomic writes
│   │
│   └── tests/                          # 19 test files
│       ├── test_swing_points.py
│       ├── test_market_structure.py
│       ├── test_fvg.py
│       ├── test_order_block.py
│       ├── test_liquidity.py
│       ├── test_confluence.py
│       ├── test_position_sizer.py
│       ├── test_risk_manager.py
│       ├── test_combine_sim.py
│       ├── test_economic_calendar.py
│       ├── test_confluence_adjuster.py
│       ├── test_news_scanner.py
│       ├── test_gex_calculator.py
│       ├── test_regime_detector.py
│       ├── test_gex_confluence.py
│       ├── test_volume_buckets.py
│       ├── test_vpin_calculator.py
│       ├── test_shield_actions.py
│       └── test_anti_overfit.py
│
├── algoict-dashboard/
│   ├── src/app/(main)/
│   │   ├── page.tsx                    # Main dashboard
│   │   ├── trades/page.tsx             # Journal
│   │   ├── backtest/page.tsx           # Results + equity
│   │   ├── signals/page.tsx            # 20-pt confluence log
│   │   ├── post-mortems/page.tsx       # AI analysis
│   │   ├── strategy-lab/page.tsx       # Candidates + sessions
│   │   └── controls/page.tsx           # Bot + heartbeat + VPIN
│   │
│   ├── src/features/
│   │   ├── dashboard/components/
│   │   │   ├── PnLCard.tsx
│   │   │   ├── PositionTable.tsx
│   │   │   ├── RiskGauge.tsx
│   │   │   ├── HeartbeatIndicator.tsx
│   │   │   ├── SentimentCard.tsx       # SWC mood + events
│   │   │   ├── GEXOverlay.tsx          # Call/put walls on chart
│   │   │   ├── GammaRegimeIndicator.tsx
│   │   │   ├── VPINGauge.tsx           # Toxicity gauge 0-1
│   │   │   ├── ToxicityTimeline.tsx    # VPIN over time
│   │   │   └── ShieldStatus.tsx        # ACTIVE/HALTED badge
│   │   ├── charts/components/CandlestickChart.tsx
│   │   ├── strategy-lab/components/
│   │   │   ├── CandidateCard.tsx
│   │   │   └── GateResults.tsx
│   │   └── post-mortem/components/PostMortemCard.tsx
│   │
│   └── src/shared/
│
├── .claude/
│   ├── skills/                         # 7 Custom Skills
│   │   ├── python-engine/SKILL.md
│   │   ├── backtest/SKILL.md
│   │   ├── post-mortem/SKILL.md
│   │   ├── sentiment/SKILL.md
│   │   ├── gamma/SKILL.md
│   │   ├── strategy-lab/SKILL.md
│   │   └── toxicity/SKILL.md
│   │
│   ├── memory/
│   │   ├── MEMORY.md
│   │   ├── user/
│   │   ├── feedback/
│   │   ├── project/
│   │   └── reference/
│   │
│   └── PRPs/
│
└── data/ (gitignored)
    ├── mnq_1min.csv
    ├── nq_1min.csv
    ├── es_1min.csv                     # Strategy Lab cross-instrument
    ├── ym_1min.csv                     # Strategy Lab cross-instrument
    ├── nq_options_oi/                  # GEX calculation
    └── sp500/
```

---

## 7 Custom Skills + 13 Factory = 20 Total

| # | Skill | Que Hace |
|---|-------|----------|
| 1 | `/python-engine` | Motor Python: detectors, strategies, risk, TDD |
| 2 | `/backtest` | Backtests + Combine Simulator + risk audit + validation gate |
| 3 | `/post-mortem` | Claude API loss analysis, 9 categories, pattern detection |
| 4 | `/sentiment` | SWC: calendario, noticias, mood, post-release scanner |
| 5 | `/gamma` | GEX: Black-Scholes, call/put walls, gamma flip, regime |
| 6 | `/strategy-lab` | AI researcher: hypotheses, 9 anti-overfit gates, candidates |
| 7 | `/toxicity` | VPIN: order flow toxicity, storm warning, flash crash shield |
| 8-20 | Factory V4 | primer, prp, bucle-agentico, sprint, qa, memory-manager, frontend, backend, supabase-admin, vercel-deployer, documentacion, calidad, codebase-analyst |

---

## Estrategias

### 1. NY AM Reversal (1:3) — Primary
W/D bias → 15min structure → 5min entry. Kill Zone 8:30-11:00 AM. Max 2/dia.

### 2. Silver Bullet (1:2)
5min context → 1min entry. Kill Zone 10:00-11:00 AM. Max 1/dia.

### 3. Swing HTF (1:2)
Weekly → Daily → 4H entry. S&P 500 stocks. Hold 2-15 dias. Max 5 positions.

---

## Risk Rules (HARDCODED)

| Regla | Valor |
|-------|-------|
| Riesgo/trade | $250 — floor() + expand stop |
| Kill switch | 3 losses ($750) → done |
| Profit cap | $1,500/dia |
| Hard close | 3:00 PM CT |
| Min confluence | 7/20 |
| Max MNQ trades | 3/dia |
| Heartbeat | 5s o flatten |
| VPIN shield | >0.70 = flatten + halt |
| Topstep MLL/DLL | $2,000 / $1,000 |
| Max contracts | 50 MNQ |

---

## Strategy Lab — 9 Gates

| Gate | Threshold |
|------|-----------|
| Sharpe improvement | >= +0.1 |
| Win rate no degrada | < -2% |
| Drawdown no aumenta | < +10% |
| Walk-forward | >= 70% windows positive |
| Cross-instrument | 2/3 (NQ, ES, YM) |
| Noise resilience | < 30% degradation |
| Inversion loses | Must be true |
| Occam's Razor | <= 2 new params |
| Validation (2023) | Must improve |

**Data:** Train 2019-2022 | Validation 2023 | Test 2024-2025 (LOCKED, auth code required)

---

## VPIN Toxicity Levels

| VPIN | Estado | Bot Action |
|------|--------|------------|
| < 0.35 | Calm | Normal |
| 0.35-0.45 | Normal | Normal |
| 0.45-0.55 | Elevated | Alert |
| 0.55-0.70 | High | Tighten stops, -25% size, +1 min confluence |
| > 0.70 | **EXTREME** | **FLATTEN ALL. HALT TRADING.** |

---

## Database — 7 Tables

`trades` `signals` `daily_performance` `bot_state` `market_levels` `post_mortems` `strategy_candidates`

---

## Comandos

```bash
# Tests
cd algoict-engine && python -m pytest tests/ -v

# Backtest
python -m backtest.backtester --strategy ny_am_reversal --data ../data/mnq_1min.csv

# Combine Simulator
python -m backtest.combine_simulator --data ../data/mnq_1min.csv

# Paper trading
python main.py --mode paper

# Strategy Lab
python -m strategy_lab.lab_engine --mode generate --count 5
python -m strategy_lab.lab_engine --mode overnight --count 20
python -m strategy_lab.lab_engine --approve H-001 --auth JUAN_APPROVED_FINAL_TEST

# Dashboard
cd algoict-dashboard && npm run dev
```

## .env
```
TOPSTEPX_USERNAME=
TOPSTEPX_API_KEY=
TOPSTEPX_API_URL=https://api.topstepx.com/api
TOPSTEPX_WS_URL=wss://realtime.topstepx.com/api
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ALPACA_BASE_URL=https://paper-api.alpaca.markets
SUPABASE_URL=
SUPABASE_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ANTHROPIC_API_KEY=
ALPHA_VANTAGE_API_KEY=
MENTHORQ_API_KEY=
```

---

*AlgoICT — SaaS Factory V4 | 20 Skills | 6 Intelligence Layers | 20-Point Confluence*
*"ICT ve velas. SWC ve contexto. GEX ve fuerzas. VPIN ve smart money. Strategy Lab evoluciona. Post-Mortem aprende."*
