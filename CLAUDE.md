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

## Confluence Scoring (engine-wide max **19** pts · NY AM min 7)

> Source of truth: `config.CONFLUENCE_WEIGHTS`. `MAX_CONFLUENCE` is derived
> (`sum(weights.values())`) so logs / telemetry / Telegram alerts always
> reflect the real ceiling. The advertised "20" of early docs never matched
> the actual weight table — audit 2026-04-17 closed the drift.

| Factor | Pts | Source |
|--------|-----|--------|
| Liquidity grab | +2 | ICT |
| Fair Value Gap (or IFVG fallback) | +2 | ICT |
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

**Sum = 19.** NY AM Reversal tiers: **12+ = A+ | 9-11 = high | 7-8 = standard | <7 = NO TRADE**.

### Silver Bullet sub-score (SB_APPLICABLE_FACTORS, 2026-04-22)

SB uses a different entry model (FVG-only, no HTF bias required, no OTE entry) — most 19-pt factors don't apply. `config.SB_APPLICABLE_FACTORS` isolates the 8 that actually discriminate SB setup quality:

| Factor | Pts SB |
|--------|--------|
| Target at PDH/PDL/PWH/PWL | +2 |
| Order Block overlap (Institutional Orderflow Drill) | +1 |
| HTF bias aligned | +1 |
| Sentiment alignment (SWC) | +1 |
| GEX wall alignment | +2 |
| Gamma regime | +1 |
| VPIN validated sweep | +1 |
| VPIN quality session | +1 |
| **SB_APPLICABLE_MAX** | **10** |

**Structural gates (0 pts each, must all pass)**: sweep, 1-min FVG, 5-min MSS/BOS, kill zone, framework ≥10pts.

**Not applicable to SB (always 0)**: OTE Fibonacci (SB enters on FVG proximal, not 61.8-78.6 retrace), HTF OB/FVG alignment (SB doesn't scope HTF overlay).

SB does **NOT enforce a min_confluence gate** as of 2026-05-18 (`config.SB_MIN_LIVE_CONFLUENCE = 0`). The Q1 2024 conclusion that "scoring is noise for SB" was re-tested and CONFIRMED by 3-year cross-period validation. Gate code (`SB_MIN_LIVE_CONFLUENCE`, `SB_REQUIRE_HTF_BIAS`) remains in `silver_bullet.py` (default OFF) for future regime-aware filter research, but is not shipped.

**Real filtering**: structural gates (sweep, 1-min FVG, 5-min MSS/BOS, kill zone, framework ≥10pts, ≥2R target, stop floor) + kill switch + MLL + VPIN. The confluence score is still computed for paper trail; logs + Telegram show dual display: `confluence=11/19 (SB: 4/10)`.

**Why the gate was tested and rejected (2026-05-18 audit)**:

| Year | Baseline P&L | Treatment P&L (min=1) | Δ |
|------|------:|------:|------:|
| 2023 | $153,981 | $152,366 | −$1,615 (−1.0%) |
| 2024 | $143,283 | $128,196 | **−$15,087 (−10.5%)** ❌ |
| Q1 2025 | $23,911 | $29,510 | +$5,599 (+23%) |
| Full 2025 | $75,436 | $76,248 | +$811 (+1.1%) |
| **3-year** | **$372,701** | **$356,810** | **−$15,891 (−4.3%)** |

The Q1 2025 +23% result was a seasonal Jan-Mar overfit (cancelled by Q2-Q4 to net +1.1% full year). 2024 (Fed pivot + AI breakout regime) strongly punished the gate because simple pullback setups won regardless of confluence quality. Score=0 trades in 2024 averaged **$471/trade** — ~3× the year's overall average. The "score=0 = noise" hypothesis is regime-dependent: friendly to recent regime, hostile to 2024-style trending regime.

**Rejected experiment (2026-05-18)**: `SB_REQUIRE_HTF_BIAS = True` (mandatory HTF alignment) cut 53% of trades and dropped P&L 63% in Q1 2025. Counter-trend SHORTS with conf>=1 are profitable in bullish regimes — they have other quality factors (sentiment, OB, target). Gate code remains in `silver_bullet.py` (default OFF) for future A/B testing.

**Lesson learned**: never ship a strategy gate from a single-quarter A/B. Cross-period (3+ years, multiple regimes) is required before changing default behavior. The lighter regime-sensitive gates (min_conf, HTF mandatory) are exactly the kind of features that look great on the optimization window and quietly destroy out-of-sample performance.

Full details in [`SILVER_BULLET_STRATEGY_GUIDE.md`](SILVER_BULLET_STRATEGY_GUIDE.md) §8.

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

### 1. NY AM Reversal (1:3) — OB-based primary
W/D bias → 15min structure → 5min OB entry at OTE fib. Kill Zone 8:30-12:00 CT. Uses full 19-pt scoring with hard gate `MIN_CONFLUENCE=7`.

### 2. Silver Bullet v4 RTH Mode — FVG-only, no-bias
5min context → 1min FVG entry. ICT canonical windows are narrower (London SB 02-03, AM SB 09-10, PM SB 13-14 CT), but we run the wider kill-zone windows (London 01-04, NY AM 08:30-12, NY PM 13:30-15) to capture setups forming slightly outside. Trailing exit (no fixed TP). No HTF bias required. No confluence gate (replaced by structural gates + kill switch). Unlimited trades per zone; per-KZ kill-switch reset so losing 3 in London doesn't lock NY AM. Full spec in `SILVER_BULLET_STRATEGY_GUIDE.md`.

### 3. Swing HTF (1:2)
Weekly → Daily → 4H entry. S&P 500 stocks. Hold 2-15 dias. Max 5 positions.

---

## Risk Rules (HARDCODED)

| Regla | Valor |
|-------|-------|
| Riesgo/trade | $250 — floor() + expand stop |
| Kill switch | 3 consecutive losses per SESSION (not day) → halt that KZ only |
| Profit cap | $1,500/dia |
| Hard close | 3:00 PM CT |
| Min confluence | NY AM: 7/19 (hard gate) · SB: 0 (no gate — 3-year cross-period A/B 2026-05-18 confirmed gate is regime-dependent and net-negative) |
| Max MNQ trades/dia | 15 (global cap; kill_switch + MLL handle real filtering) |
| Heartbeat | 5s o flatten |
| VPIN shield | activar ≥0.70 · resume ≤0.55 (histéresis) |
| Topstep MLL/DLL | $2,000 / $1,000 |
| Max contracts | 50 MNQ |

### Topstep MLL zones (activadas via `--topstep`, default ON en `main.py`)

| Zona | Drawdown | Acción | Validado |
|------|----------|--------|----------|
| normal  | < 40% MLL (<$800)  | tamaño completo | — |
| warning | ≥ 40% MLL ($800+)  | −25% size, min_conf +1 | M17b |
| caution | ≥ 60% MLL ($1,200+)| −50% size, min_conf +2 | M17b |
| stop    | ≥ 85% MLL ($1,700+)| bloquea nuevas entradas | M17b |

**Combine rolling pass rate con defaults 40/60/85:** 19/20 = 95% (NY AM 2024).
Override via CLI: `--mll-warning-pct / --mll-caution-pct / --mll-stop-pct`
con validator `warning < caution < stop` en argparse.

### Trade management (`config.TRADE_MANAGEMENT`)

- **trailing** (default, live + backtest) — no fixed target, trails last 5-min swing
- **partials_be** — backtester: close 50% at 1R + move stop to BE. **NO implementado en live todavía** — live loggea ERROR loud si este modo está activo.
- **fixed** — standard SL/TP at signal.stop/target

Backtester default lee `config.TRADE_MANAGEMENT` para paridad con live.

### Single-instance lock

`algoict-engine/.engine.lock` (PID file, `**/.claude/worktrees/`-style).
`main._acquire_engine_lock()` refuses a second `python main.py` con
mensaje actionable (`taskkill /F /PID <n>`). Stale locks se reclaman
automáticamente si el PID está muerto. Previene el bug del 2026-04-17
donde 3 procesos zombie triple-fired la misma señal London.

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
| ≥ 0.70 | **EXTREME** | **FLATTEN ALL. HALT TRADING.** |

**Histéresis (M17b post-audit):** activa a ≥0.70 · resume solo a ≤0.55.
Dead band de 0.15 evita halt/resume flapping cuando VPIN oscila sobre
el boundary 0.70.

### Flatten paths (VPIN extreme / hard close / signalr exhausted)

Todos llaman `_flatten_all` que:
1. Captura cada posición abierta + cancela brackets (stop + target)
2. Llama `broker.flatten_all()`
3. Sintetiza `_on_trade_closed(trade_dict)` por cada posición usando last
   1-min close como exit proxy → `risk.record_trade(pnl)` actualiza
   daily_pnl + MLL, Supabase escribe trade row, Telegram manda exit alert.

Este patrón cerró el bug 2026-04-18 donde flatten paths perdían P&L silently.

---

## Telegram Verbosity (2026-04-22)

Tres niveles vía `TELEGRAM_VERBOSITY` en `.env` (default `normal`):

| Level | Alertas | Volumen/día |
|-------|---------|-------------|
| `quiet` | Entries/exits, kill switch, heartbeat, daily summary, VPIN shield | 5–10 |
| `normal` | Anterior + **KZ enter** (bias + tracked levels + VPIN + SWC) + **KZ close summary** (evals, sweeps, rejects top-4) + **liquidity sweep detected** (level, candle, watch-for) + signal fired (dual /19 /10 display) | 15–25 |
| `verbose` | Anterior + **near-miss rejects** (FVG present + no sweep, framework <10pts, no 5min MSS, etc.) | 40–80 |

**Throttling built-in** (`config.TELEGRAM_THROTTLE_SEC`):
- `near_miss`: 300s por `(kz, reason)` → 18 rejects iguales = 3 alertas máx
- `sweep`: 0 (flag `level.swept` previene re-alertar)
- `kz_enter` / `kz_summary`: 0 (una por transición KZ)

**Implementación**:
- `alerts/telegram_bot.py` — `_should_send()` gate unificado (verbosity + per-bucket throttle)
- `strategies/silver_bullet.py` — `last_rejection` dict con `is_near_miss` flag en 5 reject sites
- `main.py._evaluate_strategies` — KZ transition detection, KZ stats tracking (evaluations, fvgs_seen, sweeps, rejections, reject_reasons, signals_fired, trades_taken, pnl), drain de `state.pending_sweep_alerts` en async context

---

## Equal Levels Refresh (OFF per 2026-04-22 A/B)

`detectors/liquidity.py.refresh_equal_levels_into()` detecta clusters de swing highs/lows dentro de `threshold_pct` (default 0.1% ≈ 27pts @ MNQ 27K) y los merge a `tracked_levels`. Wired al backtester vía `--equal-levels` (+ `--equal-levels-threshold-pct` / `--equal-levels-min-count`).

**Q1 2024 A/B**: feature **neta negativa** (-$1,283, PF -0.08). Desglose:
- London KZ regresa fuerte (-$2,064) — sweeps overnight de equal-levels son algo noise
- NY AM (+$492) y NY PM (+$288) mejoran modestamente
- Simulated NY-only hybrid: +$780 vs baseline, PF 1.47, +1.9pp WR → clean win si gated

**Decisión**: OFF en live por defecto. Considerar NY-only gate tras más sesiones reales. NO wired to main.py.

---

## Database — 7 Tables

`trades` `signals` `daily_performance` `bot_state` `market_levels` `post_mortems` `strategy_candidates`

### Migrations

| # | Archivo | Resumen |
|---|---------|---------|
| 0001 | `0001_init.sql` | Schema inicial |
| 0002 | `0002_market_data.sql` | Tabla `market_data` (1min OHLCV) |
| 0003 | `0003_bot_state_overlays.sql` | Extiende `bot_state` con JSONB para detector overlays (fvg_top3, ifvg_top3, ob_top3, tracked_levels, struct_last3, last_displacement) + scalars (bias_direction/zone, daily/weekly_bias, active_kz, mll_zone, min_confluence, bot_status). Consumido por el dashboard chart via `useBotStateOverlay`. |

Aplicar con `supabase db push` o ejecutar SQL manual en Supabase dashboard.

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
TELEGRAM_VERBOSITY=normal   # quiet | normal | verbose
ANTHROPIC_API_KEY=
ALPHA_VANTAGE_API_KEY=
MENTHORQ_API_KEY=
```

---

## Dashboard Chart (M17 / Chart Overlay)

`/chart` page renderea en real-time lo que el bot VE:

| Overlay | Fuente | Render |
|---------|--------|--------|
| Candlesticks + volumen | `/api/bars` + Realtime `market_data` | lightweight-charts v5, volume en subpanel bottom 20% |
| Kill Zone shading | Timezone CT computed client-side (Intl) | Histogram strip bottom 5%, colors: London azul / NY AM emerald / Silver Bullet amber / NY PM orange |
| FVG / OB zones | `bot_state.fvg_top3` / `ob_top3` (JSONB) | Rectangles (Solid for FVG, heavier for OB) |
| IFVG | `bot_state.ifvg_top3` | Rectangles with **dashed** outline |
| Tracked levels | `bot_state.tracked_levels` | Horizontal priceLines: PDH/PDL azul, PWH/PWL morado, EQH/EQL amber. Swept → zinc-500 dashed + ✖ label |
| Structure events | `bot_state.struct_last3` | Markers: MSS/BOS arrows, CHoCH circles |
| Signal fires | `signals` table (Realtime) | "FIRE {score}" arrow marker |
| Trade entry/exit | `market_levels.trades` | arrowUp/Down + P&L text |
| Info panel | `bot_state` scalars | Status, KZ, bias (d/w), VPIN, SWC mood, MLL zone, min_conf, P&L, last displacement |

**Hooks:**
- `useChartAnnotations(symbol, tf, window)` — market_levels + trades
- `useBotStateOverlay()` — bot_state Realtime subscription
- `useSignalsLive(symbol)` — signals table Realtime subscription

**Toggles:** OverlayToggleBar con 6 checkboxes (Volume / Kill Zones / FVG / OB / Levels / Trades).

Requiere migration `0003_bot_state_overlays.sql` aplicada.

---

## Session Snapshot (2026-04-24)

### 7-year walk-forward (SB v8 trailing RTH Mode, 2019–2025)

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

**Consistency**:
- 0 negative years · mean $96,143 · median $92,203 · std $15,320
- Monthly hit rate 91.7% · Daily hit rate 54.4% · DLL breach rate 0.61%
- **KZ contribution** (agg): London 64.9% · NY AM 24.4% · NY PM 10.7%

**V9 (session-recency fix) 7-year**: +$606K · 0 negative years · 97.6% monthly hit · combine pass 76.7% (up from 72.4%) · resets 64 → 33 (−48%).

**Cross-instrument** (7-yr): ES +$444K · YM +$575K · 0 negative years each.

### Tests + infra (2026-04-24)
- **1,479 unit tests passing** (was 1,477; +2 from Bug J searchOpen/error)
- **5 integration tests** (`tests/test_topstepx_live_contract.py`) — opt-in via `TOPSTEPX_INTEGRATION=1`
- `scripts/audit_config_defaults.py` — 23/23 config keys explicit (0 silent defaults)

### 2026-04-22 → 2026-04-24: 33 bugs fixed in 3 days

**Phase 1 — 2026-04-22** (phantom fill + wiring):
- Phantom fill bug in `_poll_position_status` (fake +$2,154 "win")
- MAX_MNQ_TRADES_PER_DAY 3→15
- 1-min FVG + 5-min structure wired in live
- `end_of_day()` called in `_reset_for_new_day`

**Phase 2 — 2026-04-23 V9** (session recency + phantom cleanup):
- **Bug A** — session-recency filter for 5-min / 15-min structure events
- **Bug B** — phantom cleanup respects `LIMIT_ORDER_TTL_BARS` + KZ boundary
- **Bug C** — TTL sweep KZ-aware
- **Bug D** — single-position guard in `_evaluate_strategies`
- PWH/PDH forming-bar fix (`as_of_ts` param in `detectors/liquidity.py`)

**Phase 3 — 2026-04-24 AM** (trail + structure + API contract):
- **Bug E** — trail gate on `entry_order.filled_price is None` (no trail on unfilled)
- **Bug F** — trail stop direction validation (SHORT stop BUY above price)
- **Bug G** — 5-min MSS/BOS structure invalidation rule (opposite BOS invalidates)
- **Bug H** — target order skipped in trailing mode (broker deviation cap)
- **Bug I** — Telegram trail alert gated on broker `status != rejected`
- **Orphan alert** — `send_emergency_alert` on reconcile cleanup
- **Bug J** 🚨 — `get_positions` endpoint: `GET /Position/account/{id}` 404s → `POST /Position/searchOpen`. Bot was blind to real positions for DAYS.
- **Bug K** 🚨 — User Hub `SubscribeAccounts` wrong signature → no fill events. Added `SubscribeOrders/Positions/Trades(int accountId)`.
- **Bug L** — poll-path sends `send_trade_opened` alert on first detected fill

**Phase 4 — 2026-04-24 PM** (12 more from full audit, 4 parallel agents):
- **C1** signals table `direction` column (was writing `signal_type` → PGRST23502 silent failure, dashboard blank forever)
- **C2** detector state cleared on `_reset_for_new_day`
- **C3** `send_kill_switch_alert` wired (was defined, zero callers)
- **C4** CHoCH + MSS/BOS invalidator symmetry
- **C5** displacement session-recency filter
- **C6** `record_trade(order_id=)` dedup (no triple-booking)
- **C7** `end_of_day()` called post-flatten (not just next morning)
- **C8** `cancel_order` return checked at 6 callsites (ghost orders escalated)
- **H1** reconciler 5-second timing guard (broker position API lag safety)
- **H2** User Hub fill path stamps `filled_price`
- **H3** poll `get_positions` exception logged (was silent)
- **H4** VPIN alert respects verbosity (extreme/normalized always fire)
- **H10** broken swings filtered from `_latest_unconsumed_swing`
- **H11** hard-close Telegram alert pro-activo

**Phase 5 — 2026-04-24 night (Batch 4 systemic hardening)**:
- `config.cfg(name, default)` — fail-loud config accessor
- `scripts/audit_config_defaults.py` — CI scanner for missing keys
- `tests/test_topstepx_live_contract.py` — 5 integration tests vs real API
- Session-recency audit + design comment for FVG/OB (intentionally not filtered per ICT)
- Silent-`.debug` → `.warning` escalation in reconciler + KZ rollback
- `core/health.py` — atomic `.health.json` snapshot every 10s for external monitors

### A/B tests rejected (features stay OFF)
- **equal_levels_refresh** (Q1 2024) — flat-to-neg (−$1,283). Kept OFF.
- **Risk ladder + London 2L cap** (Q1 2024) — cuts P&L 82%. London cap would kill the KZ producing 64.9% of 7-year P&L. Rejected.
- **FVG quality gate trio** (Q1 2025 Phase 1 EDA, 2026-05-22) — 3 ICT-canonical filters (displacement ≥2.0× avg body, sweep linkage within 10 bars, premium/discount quadrant) tested individually + combined. **ALL throw-out-winners.** Best variant (quadrant alone) cut 50% trades, +13pp WR, but P&L still fell 28%. Worst (sweep linkage) produced 7 trades in 3 months. The "noise FVGs" the filters target are net-profitable because structural gates downstream (sweep, 1m FVG, 5m MSS/BOS, KZ, framework ≥10pts) already filter effectively. Detector still computes `displacement_ratio` + `quadrant_position` on every FVG (zero perf cost, useful for vision-validator counterfactual). Phase 2 cross-period NOT run — Q1 2025 deltas too brutally negative to justify compute. Code stays behind `SB_FVG_REQUIRE_*` flags (default OFF). See `analysis/fvg_quality_phase1_q1_2025.py`. **Insight**: this REINFORCES the SB design — bias-agnostic, FVG permissive, downstream gates strict. Don't double-filter at the FVG level.
- **FVG c3 close confirmation** (Cross-period 2023-2024-2025, 2026-05-23) — forensic-driven filter from live audit: 3/3 sampled losing trades on Thu 5/21 had FVG c3.close inside c2 range (wick test only, no body commit). Hypothesis: filtering c3-wick-only FVGs would improve quality. **Cross-period 3-year said KILL — loses in 3/3 years**: 2023 −30.2% (−$55K), 2024 −31.9% (−$50K), 2025 −28.2% (−$27K), agg −30.4% (−$132K). Same throw-out-winners as the trio. The c3-wick-only FVGs ARE net-profitable across regimes; the forensic sample (3 losing trades) was outcome-biased. Lesson reinforced: detector permissive is the design. Detector still computes `c3_close_beyond_c2` field (zero cost, valuable telemetry for vision counterfactual). Code stays behind `SB_FVG_REQUIRE_C3_CONFIRMATION` flag (default OFF). See `analysis/fvg_c3_crossperiod.py`. **Meta-insight**: 4 different ICT-canonical FVG-quality filters tested, 4 killed cross-period. Pattern is conclusive — the bottleneck for SB performance is NOT FVG geometric strictness. Look elsewhere (execution path, regime context, structure detector BOS-vs-MSS distinction, opportunity-replace tier behavior).
- **MSS-after-counter flip gate** (Cross-period 2023-2024-2025, 2026-05-23) — forensic-driven from Thu 5/21 trade #2 (-$143 WTF LONG): bot fired LONG with aligned=[BOS bull 13:10, BOS bull 13:15, BOS bull 13:30] after 250pt bearish drop. Per ICT: BOS = continuation, CHoCH/MSS = real flip. Pure BOS chain after counter-direction event = recovery rally of opposite trend, not legitimate flip. Hypothesis: require ≥1 MSS or CHoCH in aligned set when most_recent_opp exists. **Cross-period 3-year said KILL — loses in 3/3 years** but MUCH SMALLER magnitude than FVG filters: 2023 −8.4% (−$15K), 2024 −2.4% (−$3.8K), 2025 −11.4% (−$10.8K), agg −6.8% (−$30K). Trade cut also small (1.4-9.1%), WR delta neutral (-0.2 to +0.2 pp). Gate IS chirurgico — targets the right edge case — but those edge cases are still net-profitable across all 3 backtest regimes. Code behind `SB_REQUIRE_MSS_AFTER_COUNTER` flag (default OFF). See `analysis/mss_after_counter_crossperiod.py`. **Conclusive meta-finding** (5 different filters tested in 2 days, 5 killed cross-period): the SB detector + strategy as-shipped maximizes 3-year edge. The "WTF trades" perceived in any given live week ARE net-positive across regimes. Live-vs-backtest divergence (if real) is in EXECUTION PATH (opportunity-replace, fill timing, slippage), not detection or filtering. Next investigation should be a parity replay (re-run live week's bars through backtester) before more filter experiments.

### Current feature decisions
- **`RISK_LADDER_ENABLED` = False** (infrastructure in place, ready if needed)
- **`KZ_LOSS_CAPS` = {}** (no per-KZ loss caps)
- **`equal_levels_refresh` OFF**
- **SB confluence gate** — REJECTED after cross-period validation (2026-05-18). Q1 2025 showed +23% but 3-year (2023-2025) showed −4.3%. 2024 alone lost −10.5% because Fed-pivot + AI-breakout regime favored score=0 simple pullbacks. Gate code stays behind `SB_MIN_LIVE_CONFLUENCE` flag (default 0).
- **SB HTF bias mandatory** — rejected (2026-05-18 A/B cut P&L 63% in Q1 2025 because counter-trend SHORTS with conf>=1 are profitable). Gate code stays behind `SB_REQUIRE_HTF_BIAS` flag (default False).
- **`TRADE_MANAGEMENT` = "trailing"** (matches live + backtest)
- **Silver Bullet v4 RTH Mode** — wider KZ coverage (London 01-04 / NY AM 08:30-12 / NY PM 13:30-15 CT)
- **NY Open Buffer SHIPPED** (2026-05-19) — `NY_OPEN_BUFFER_BEFORE_MIN=10`,
  `NY_OPEN_BUFFER_AFTER_MIN=15`, events at 07:30 + 08:30 CT. +14.7% 3-yr P&L
  with disclosure that ~7% is generic cascade effect (placebo also helped).
- **Camino C4 Vision-overlay AI validator** SHIPPED in SHADOW mode
  (2026-05-20). Sends chart images to Claude vision API at each SB signal
  fire. Captures `bot_assessment` (fvg/sweep/mss accuracy) + decision
  (fire/skip/half). Prompt v2 (2026-05-21) embeds ICT canonical rules +
  detailed visual pattern reference. Phase 2 active mode pending 3-5 days
  shadow validation.
- **Camino C2 text-only AI overlay** DISABLED (`KZ_VALIDATOR_ENABLED=False`)
  in favor of vision. Code retained for fallback.
- **HTF-weak conditional gate** DISABLED (`SB_HTF_WEAK_MIN_CONF=0`) in favor
  of vision. Code retained.

### Defensive systems now live
- **Telegram alerts on state transitions**: fire, trade_opened (fill-gated), trade_closed, trail (broker-accept-gated), kill_switch, MLL zone change, phantom/orphan cleanup, NAKED stop, hard close, VPIN extreme/normalized
- **`.engine.lock` PID file** — prevents zombie multi-fire (2026-04-17)
- **`.health.json`** — bot writes every 10s; external monitor reads.
- **External monitor (`scripts/monitor.ps1`)** — Windows Task Scheduler runs every 60s, independent of bot process. Reads `.health.json` + alerts via Telegram (canal A, same bot) + local `.monitor_alerts.log` fallback. Catches what the bot cannot alert on itself:
  * **bot_dead** (`.health.json` mtime > 60s → crash/deadlock)
  * **heartbeat_stale** (ts field > 90s old → bot hung writing stale data)
  * **ws_feed_stale** (`last_bar_age_s` > 20 min during market hours → SignalR dropped)
  * **user_hub_dead** (after 60s uptime grace)
  * **position_divergence** (local vs broker — the Bug J check)
  * **kill_switch** + **mll_danger** (re-alert in case bot's own alert never delivered)
  * Dedup: same alert re-fires at most every 15 min. Resolve: fires `[OK] RESOLVED` when condition clears.
  * Auto-quiet after **3 consecutive alerts** of the same code without resolution (so a weekend off doesn't flood Telegram every 15 min). Resumes alerting on resolve.
  * Install: `powershell -ExecutionPolicy Bypass -File scripts\install_monitor.ps1`
  * Verify: `Get-ScheduledTask -TaskName AlgoICT-Monitor`
  * Tail live: `Get-Content .monitor_alerts.log -Tail 20 -Wait`
  * **Pause during bot-off windows** (weekend, maintenance): `scripts\install_monitor.ps1 -Disable` (stops + clears state)
  * **Resume when bot relaunches**: `scripts\install_monitor.ps1 -Enable`
  * Uninstall: `scripts\install_monitor.ps1 -Uninstall`
- **Reconciler 5s grace period** — no false-orphan during broker fill propagation
- **`record_trade(order_id=)` idempotency** — triple-path dedup (User Hub + poll + reconcile)
- **Session-recency filters** — structure (Bug A) + displacement (C5). FVG/OB intentionally NOT filtered per ICT.

### Pendientes watch-list
- Telegram "DELETE" banner on mobile (awaiting user screenshot)
- C9 confluence-scorer missing-data flag (nice-to-have, deferred)
- C10 `OrderResult` frozen-refactor wrapper (defensive, not urgent)
- H6 flatten exit price accuracy via broker fill-query (workaround: last 1-min close, ~1pt off)
- Bug G ICT-canonical refinement (currently OFF — see v12 below)
- **NY_OPEN_BUFFER carry-in position exposure** (2026-05-19, deferred): the
  buffer rejects NEW signals during 07:20-07:45 and 08:20-08:45 CT but
  does NOT touch positions that are already open going INTO the buffer.
  Two failure modes:
  * **Winner trade wicked out**: trail stop gets harvested by the cash-
    open wick at adverse price → exits with less profit than potential.
    Partial protection exists via 1-min swing trail + ratchet-to-+1R but
    not buffer-aware. Money left on table.
  * **Loser trade gets stopped during wick**: violent wick fills the
    stop with slippage → bigger loss than expected. Also increments
    `consecutive_losses` → can trip kill_switch, defeating the cascade
    effect that the buffer is supposed to preserve.
  Mitigation paths (in increasing order of intervention):
  1. Hold stops static during buffer (no trail tightening) — minimal
  2. Pre-buffer aggressive ratchet (5 min before): if unrealized >= 1R,
     lock stop at +0.5R or +1R. Asymmetric: protects winners, no action
     on losers. Risk: premature exit on what would have been a runner.
  3. Force flatten 5 min before buffer — most radical. Combine-mode
     play, not paper-research-mode play.
  Decision 2026-05-19: do nothing (status quo). Frequency of carry-in
  positions through the buffer is low (SB trades typically last
  5-50 min, mostly closing within their own KZ). Revisit if live
  evidence shows the failure mode hurting us materially. Backtest path 2
  before shipping any of these.
- **BE-shield-at-+1R** (2026-05-19, REJECTED on small sample): proposed
  to move stop to entry when MFE reaches +1R, on top of existing +2R
  ratchet. Tested counterfactually on 11 losers + 5 winners from
  2026-05-18 + 2026-05-19. Result: net -$281 across the 16-trade
  sample. Saves 2 losers (+$280) but scratches 1 big winner (-$630 on
  T2_19 London). Pareto-negative because LOSERS rarely reach +1R MFE
  (8/11 are "instant adverse" with MFE <1R), while WINNERS often reach
  +1R only to retrace through BE before continuing. Code/analysis in
  `analysis/be_shield_simulation.py`. Decision: not shipped. Sample is
  small — re-investigate only if a 3-yr backtest shows clear edge,
  which we won't run unless live evidence reopens the question.
- **Regime detection / "give the bot eyes"** (2026-05-19, deferred):
  User raised the core insight that today's losses (NY PM 5/5) weren't
  preventable by structural filters — they were CONTEXTUAL. Same setup
  (LONG, bias=bearish, struct=all-bull-recent) won in London (T1_19
  +$210) and lost in NY PM (PM1_19 -$95). The differentiator was
  session/KZ context, not bar-level features.
  Investigation paths considered:
  * **Camino A — Daily AI briefing** (Claude API at 6 AM CT each
    morning): consumes calendar + news + HTF + prior session outcome,
    returns regime classification + per-KZ modifiers. High leverage,
    hard to backtest (no Claude calls for 3-yr historical bars).
  * **Camino B — Session tracker** (deterministic, backteseable):
    instant-adverse counter per KZ + cross-KZ cascade gate. If 2+
    trades in current KZ went MFE <0.5R, halt KZ. If previous KZ
    tripped kill_switch, current KZ requires extra confluence.
  * **Camino C — Live AI overlay** (Claude per decision): NOT for
    per-signal (untestable at scale, latency/cost prohibitive). BUT
    a **per-KZ tiered version is viable** — see C2 shadow plan below.
  Decision: defer A and B for now. Today's loss pattern is one data
  point. Need 3-5 more "giveback days" or "chop days" before
  investing. When triggered: Camino B first (backteseable), Camino A
  second. Recorded in `analysis/be_shield_simulation.py` and bar-state
  extraction patterns in session log 2026-05-19.

- **Camino C2 — Per-KZ AI overlay in SHADOW mode** (2026-05-19,
  planned for 2026-05-20 build): the user's "give the bot eyes" idea
  framed as a tier-2 AI overlay. Build now, observe for 3 weeks, only
  activate if shadow data shows edge.

  **Design**:
  * Trigger: at each KZ entry (3× per day — London, NY AM, NY PM)
  * Input to Claude: bar/setup context, session state (P&L_today,
    prior KZ outcome, drawdown from peak), macro (SWC mood, calendar
    events today), HTF bias, recent trade history (last 5 W/L
    pattern, instant-adverse count today)
  * Claude output (JSON): `{decision: "fire"|"skip"|"half", confidence,
    size_multiplier, rationale}`
  * Bot behavior in SHADOW: log decision to Telegram + new Supabase
    table `ai_overlay_decisions` BUT do NOT modify trade execution.
    Continues with current canonical strategy.

  **Why shadow first**: backtest is impossible at per-KZ-call scale
  (3-yr would need ~2,300 Claude calls, doable but expensive AND
  Claude wasn't trained for trading judgment so historical calls
  would be educated guesses, not real edge). Shadow gives us REAL
  live evidence without risking production.

  **Evaluation after 3 weeks (~45-60 KZ entries)**:
  * Counterfactual P&L: what P&L would we have realized if bot had
    obeyed Claude's decisions?
  * Agreement rate: how often did Claude match what the bot did?
  * Asymmetry: when Claude said "skip", did the KZ lose? When
    Claude said "fire", did the KZ win?
  * Decision criteria: ship to ACTIVE if counterfactual P&L > actual
    P&L by some margin (e.g., +10% over the 3-week period). Kill if
    Claude's calls would have hurt or been neutral.

  **Cost**: ~$0.05/call × 3 calls/day × 21 days = ~$3 for full
  shadow period. Trivial.

  **Infrastructure exists**: `AI_MODEL_*` slots already in config
  (post_mortem, mood_synthesis, hypothesis_gen). Adding
  `AI_MODEL_KZ_VALIDATOR` is just one new constant + prompt template
  + integration in main.py at KZ transition.

  **Build steps (estimated ~1 day)**:
  1. Prompt template design (`sentiment/kz_validator.py` or similar)
  2. `validate_kz_entry(context) → KZValidatorDecision` function
  3. Call site in main.py at each KZ enter (already alerted via
     `KZ enter alert sent`)
  4. Supabase table `ai_overlay_decisions` migration
  5. Telegram alert with Claude's decision (shadow tag in subject)
  6. Counterfactual P&L tracker (Python script that processes the
     shadow table + actual trades to compute hypothetical outcome)

  **Failure modes to watch for**:
  * Claude too cautious → skips too much → undertrade
  * Claude rationalizes anything (decisions look thoughtful but
    aren't predictive)
  * Sample size insufficient in 3 weeks (only ~45-60 KZ entries —
    might extend to 6 weeks for stronger signal)

  **Active mode (Phase 2, design finalized 2026-05-20)**:

  **Decision: BLOCK + GATE** (synchronous wait for Claude before
  limit placement). Alternative ("place + cancel-if-skip") rejected
  because: if limit fills in the 1-3 sec window while waiting for
  Claude, bot has a position Claude wanted to veto. BLOCK is clean
  and the 1-3 sec latency is irrelevant for SB (limits often pend
  10-60 min anyway, the 7 hard gates don't expire in 3 sec).

  **Flow per signal**:
    1. SB.evaluate() returns Signal
    2. Bot builds context (setup + day state + macro)
    3. Bot AWAITS Claude (asyncio.wait_for, timeout=5s)
    4. Decision branching:
       - "fire" (1.0x): place limit normal (canonical execution)
       - "half" (0.5x): signal.contracts //= 2 (keep stop_pts, halve
                       $risk), then place limit
       - "skip" (0.0x): signal = None, skip _execute_signal entirely
    5. Telegram alert with 🟢 APPROVED / 🟡 HALF-SIZED / 🛑 VETOED
    6. Supabase + JSONL log with `obeyed=true`

  **Fallback on API failure / timeout**:
    - Default: FIRE (canonical) — never block trades on infrastructure
    - Log WARNING + Telegram "AI Overlay unreachable, falling back"

  **Safety mechanisms**:
    - Kill switch: if cumulative AI-attributable loss > $500 over
      recent N days, auto-flip back to shadow mode and alert user
    - Manual override: Telegram `/ai off` (shadow) / `/ai force`
      (bypass vetos) for emergencies
    - Permanent bypass: config flag `KZ_VALIDATOR_BYPASS = True`

  **New telemetry fields needed in ai_overlay_decisions**:
    - `obeyed: bool` — did the bot follow the decision
    - `bot_pnl_outcome: real` — actual P&L if fired
    - `would_have_pnl: real` — counterfactual if NOT obeyed
    - `daily_ai_savings` — rolling impact aggregate

  **Daily Telegram summary** (post-hard-close):
    ```
    🤖 AI Overlay Daily (DATE)
    Decisions: N (fire/half/skip counts)
    Skips that would have lost: X/Y (saved $Z) ✓
    Skips that would have won: A/B (cost $C) ✗
    Halves vs full: D ($E saved/cost)
    Net AI attribution: ±$F vs canonical
    ```

  **Code changes (Phase 2 implementation, ~1 day)**:
    1. Convert `_run_kz_validator_shadow` to `_run_kz_validator` with
       a mode param (shadow vs active)
    2. In main.py SB branch, if `KZ_VALIDATOR_SHADOW_MODE=False`:
       - `decision = await _run_kz_validator_active(...)`
       - Apply decision: signal=None / signal.contracts//=2 / no-op
    3. New Supabase columns (migration 0005)
    4. Telegram commands handler for /ai off, /ai force
    5. Counterfactual tracker auto-runs nightly

  **Phased rollout to active**:
    - Phase 1.0 (now): shadow per-signal
    - Phase 1.5 (~3 weeks): analyze counterfactual; if positive →
      proceed; if neutral/negative → kill feature
    - Phase 2.0: active SKIP veto ONLY (no HALF yet); daily summary
    - Phase 2.5: enable HALF after SKIP proves stable
    - Phase 3.0: auto-disable kill switch + Telegram commands

### v12 backtest validation (2026-04-25)

After Q1 2025 v10 disaster (-$3,836, WR 21%) revealed regression vs V9 hist
(+$22K, WR 50%), bisected to root cause:

**Bug F backtester `bar_close` validation** mirrored live broker constraint
into backtester where it was inappropriate. Rejected ~30% of valid trail
tightenings → losers stayed at original stop instead of trailing to BE
→ WR collapsed.

Fix: reverted `_update_trailing_stop` in `backtest/backtester.py` to V9
behavior (no `bar_close` check). Live `_manage_open_positions` keeps its
broker-side validation (correct for live execution).

**v12 = V8/V9 historical match**:
- Q1 2025: 377 trades · WR 50.1% · +$22,508 · PF 2.21
- Full 2025: 1,758 trades · WR 48.6% · +$80,134 · PF 1.95 · 0 negative months
- **Identical to V9 hist 2025 to the dollar** ($80,134)

**Bug G left disabled** (`_BUG_G_ENABLED = False` in silver_bullet.py).
Bisect showed Bug G filters trades essentially randomly w.r.t. outcome.
Future work: refine to ICT-canonical version (only invalidate if price
crosses swing level that caused last_struct).

**`STRATEGIES_ENABLED = ("silver_bullet",)`** in config.py — NY AM
Reversal held offline in live (still wired in main.py but evaluate()
skipped). Re-enable: add `"ny_am_reversal"` to the tuple.

### 2026-05-18 — SB live ops + min_conf gate

**Live session audit (London 2026-05-18, 5 trades):**
- 2W / 3L · WR 40% · −$122 net
- Score distribution: 0/5 → 0W/2L (−$406.50) · 1/5 → 0W/1L (−$192.50) · 2/5 → 2W/0L (+$477.00)
- Pattern matched 2026-05-14 NY PM trade (also score=0, also loss). 3/3 score=0 trades across 2 sessions = losses.

**Q1 2025 A/B re-test (2026-05-18) — pareto-dominant winner**:

| Config | Trades | WR | P&L | PF | Avg win | Avg loss |
|--------|-------:|----:|----:|----:|--------:|---------:|
| Baseline (no gate) | 183 | 64.5% | $23,911 | 2.96 | $306 | −$187 |
| `SB_REQUIRE_HTF_BIAS = True` (rejected) | 86 | 62.8% | $8,797 | 2.38 | $281 | −$199 |
| **`SB_MIN_LIVE_CONFLUENCE = 1` (REJECTED post cross-period)** | 185 | 67.6% | $29,510 | 3.70 | $324 | −$182 |

**3-year cross-period A/B (full validation, 2026-05-18 audit)**:

| Year | Baseline | Treatment (min=1) | Δ | Verdict |
|------|---------:|------------------:|---:|---------|
| 2023 | $153,981 (1154 trades, WR 61.7%, PF 3.00) | $152,366 (1110 trades) | −$1,615 | tie |
| 2024 | $143,283 (972 trades, WR 63.6%, PF 3.35) | $128,196 (940 trades) | −$15,087 | **−10.5%** |
| Q1 2025 | $23,911 | $29,510 | +$5,599 | overfit sample |
| Full 2025 | $75,436 (599 trades, WR 62.6%, PF 2.91) | $76,248 (570 trades) | +$811 | +1.1% (Q2-Q4 cancelled Q1 gain) |
| **3-year** | **$372,701** | **$356,810** | **−$15,891** | **−4.3%** |

**Why the gate fails cross-period**: 2024 (Fed pivot + AI breakout) had strong directional moves where simple SB pullback setups won regardless of quality factor presence. The 32 trades blocked by min=1 in 2024 had avg P&L of $471/trade — 3× the year's overall avg of $147/trade. Score=0 ≠ noise in that regime. The Q1 2025 +23% improvement was Jan-Mar seasonal sample that disappeared on the rest of the year ($811 net delta in full 2025).

**Lesson**: never ship a strategy filter from a single-quarter A/B. Q1 → Full Year P&L delta collapse from +23% to +1.1% inside 2025 was the first red flag; 2024 −10.5% confirmed regime-dependence. Required: 3+ years cross-period with regime diversity before changing default behavior.

**Live impact**: today's London KZ score=0 losses (T1, T2) would still happen with no gate. That's variance, not pattern. Live continues with `SB_MIN_LIVE_CONFLUENCE = 0`.

**Shipped configs (config.py)**:
- `SB_MIN_LIVE_CONFLUENCE = 1` (active in live + backtest)
- `SB_REQUIRE_HTF_BIAS = False` (code stays for future A/B, default off)

### 2026-05-18 — Reconciler log noise fix

**Symptom**: 14 false `WARNING: Position reconcile: ORPHAN in local state` over a 50-min span during 2026-05-18 London KZ, while bot was actually waiting on a legitimate pending limit (29048.50 long, 55 bars old). Opportunity Replace Tier 2.5 eventually refreshed it correctly — the bot was operating fine, but the log gave the impression of bot being bricked.

**Root cause**: Broker `/Position/searchOpen` returns ONLY filled positions, not resting limits. So an unfilled limit always appears "orphan" to the naive `local_symbols − broker_symbols` check. The pre-fix code logged WARNING unconditionally, then iterated and correctly skipped cleanup for unfilled-limit positions. Result: noisy WARNING with no cleanup action.

**Fix** (`main.py` line 2783+): collect `orphan_keys` first (filtered for unfilled limits + grace period), then only WARN if `orphan_keys` is non-empty. Otherwise DEBUG. No-op functionally.

### 2026-05-19 — Day audit + giveback lesson

**Day outcome**: 8 trades · 3W / 5L (technically — there were more
losing PM trades, see below) · Net realized +$339 · Peak drawdown
-$1,190 (78% giveback of London profits).

Breakdown:
- **London** (3W/0L): +$1,529.50 — T1 (LONG score=0, +$210), T2
  (SHORT score=1, +$1,127.50, 50-min trail captured 112pts), T3
  (SHORT score=1, +$192). Profit cap (paper config raised to
  $10,000 this morning, hence no auto-halt) would have stopped
  trading at the canonical $1,500 cap — confirmed Combine value.
- **NY AM** (0W/2L): -$405 — NA1 (SHORT score=2 -$192), NA2 (SHORT
  score=2 -$213, 1-SECOND trade — fill 08:30:31, stop 08:30:32,
  classic cash-open kill wick). Drove the NY_OPEN_BUFFER ship.
- **NY PM** (0W/5L): -$785.50 — PM1-PM3 LONGs into bullish struct
  that exhausted, then PM4-PM5 SHORTs after CHoCH bear at 13:55 CT
  that didn't follow through. Chop/reversal regime. None preventable
  by gates we've shipped.

Key lessons:
1. **Profit cap exists for a reason**. Disabling it for paper
   research cost us $1,012.50 in giveback. Worth the data, but the
   tuition fee is real. Re-enable for Combine.
2. **All NY PM losers had score=1** — confluence score did not
   discriminate. Confirms the 3-yr cross-period finding from earlier.
3. **Same structural setup wins in some KZs and loses in others**
   (T1_19 London +$210 LONG vs PM1_19 NY PM -$95 LONG, both with
   identical bias + struct + last_disp at fire). The discriminator
   is session context, not bar features. Roadmap: see "Regime
   detection" entry under Pendientes watch-list.
4. **Bot keeps placing limits far from current price** (e.g., 14:35
   CT pending SHORT @ 29096.25 when price was 28944 = 152pt away).
   This is canonical ICT SB (wait for retrace into FVG) but produces
   stale limits that often die at hard close without filling. Not a
   bug, but worth tracking if it persistently consumes risk-budget
   slots. Tracked under Pendientes as "limits far from price" if
   pattern repeats.

### 2026-05-19 — NY Open Buffer (SHIPPED with disclosure)

**Live trigger**: 2026-05-19 NY AM session lost −$405 in 2 trades, both stopped near NY equity cash open (09:30 ET / 08:30 CT). NA2 filled @28907 at 08:30:31 and stopped @28924.75 at 08:30:32 — **1 second in trade**, classic cash-open kill wick.

**Rule shipped** (`config.NY_OPEN_BUFFER_*`): reject SB evaluations within ±buffer of two NY open events:
- 08:30 ET = 07:30 CT (pre-market open + data releases)
- 09:30 ET = 08:30 CT (stock cash open)

Default `BEFORE=10, AFTER=15` → blackouts at 07:20-07:45 CT AND 08:20-08:45 CT.

**3-year cross-period A/B**:

| Year | Baseline | Treatment | Δ |
|------|---------:|----------:|---:|
| 2023 | $153,981 | $183,424 | +$29,443 (+19.1%) |
| 2024 | $143,283 | $158,910 | +$15,627 (+10.9%) |
| 2025 | $75,436  | $85,075  | +$9,639  (+12.8%) |
| **3-yr** | **$372,701** | **$427,409** | **+$54,708 (+14.7%)** |

**Counterintuitive finding**: treatment has MORE trades than baseline (+211 across 3-yr). Mechanism = cascade effect: blocking bad trades in the wick window preserves `consecutive_losses` counter and prevents kill_switch from tripping → bot stays in market for more setups later in session.

**Placebo test** (10:30 CT random buffer, same widths):
- 3-yr placebo: $398,246 (+6.9% vs baseline)
- Treatment is $29,164 (+8.6%) better than placebo cross-period
- 2023, 2025: placebo ≈ treatment (cascade dominates)
- 2024: treatment +$24,404 better than placebo (microstructure-specific value, Fed pivot regime)

**Decomposition**:
- Cascade effect (generic mid-NY-AM blackout): +6.9%
- Microstructure-specific (08:30 CT wick avoidance): additional +7.8%
- Combined: +14.7%

**Honest disclosure**: The dominant mechanism is cascade (risk budget preservation), not microstructure. In 2 of 3 years, ANY mid-NY-AM blackout would have produced similar results. Only 2024 showed clear microstructure-specific value. We ship at 08:30 CT because:
1. Microstructure intuition has theoretical grounding (known wick at cash open)
2. Treatment is net-better than placebo in aggregate (+8.6%)
3. Doesn't hurt in any year (worst case ≈ placebo)

**Future research**: if cascade is the dominant effect, a generalized trade-pacing rule (max 1 trade per N bars) might capture similar value with cleaner semantics. Deferred.

### 2026-05-20 — Camino C4: Vision-overlay AI validator (SHIPPED in shadow mode)

**Motivation**: 12 losing trades in a row (cross-day 5/19 + 5/20) raised
the question "is the bot's strategy broken OR is the bot reading the
chart wrong?". Text-only validators (C2, HTF-weak gate) only consume
bot-generated context — circular trust problem: if bot detectors are
biased, validators inherit the error.

**Solution**: send actual chart images (1-min + 5-min PNG) to Claude
vision API along with text context. Claude validates bot's annotations
(FVG/sweep/struct) against raw candles.

**Architecture**:
- `agents/chart_renderer.py` — matplotlib chart generator
  * `render_1min_signal_chart` — last 90 bars w/ swings, FVGs, levels,
    proposed entry/stop/target as horizontal lines
  * `render_5min_htf_chart` — last 60 bars 5-min for HTF context
  * Returns base64 PNG strings
- `agents/vision_validator.py` — Claude multimodal API integration
  * `VisionValidatorAgent` + `VisionValidatorDecision` dataclass
  * Sends text + 0/1/2 images via base64 to Claude vision API
  * Same fire/skip/half decision shape as C2 + new `bot_assessment` field
- `main.py` — signal-fire hook in SB branch
  * `_run_vision_validator_shadow` background task (asyncio.to_thread for
    chart render + API call, non-blocking)
  * Mutually exclusive with C2 (vision wins when both enabled)
- `supabase/migrations/0005_vision_overlay_decisions.sql` — table
- JSONL fallback: `analysis/vision_overlay_shadow.jsonl` (restart-safe)

**Cost**: ~$0.017/call × ~5 unique signals/day ≈ $0.10/day = $3/month
**Latency**: 3-6 sec (chart matplotlib ~1-2s + vision API 2-4s)
**Acceptable for SB**: limit orders pend 10-60 min anyway, bot doesn't
wait (background task).

**First-day results (2026-05-21)**:
- 50 decisions logged: 1 FIRE, 49 SKIP
- Problem: Claude was using "counter-trend vs HTF" as #1 skip reason
- Effectively recreating `SB_REQUIRE_HTF_BIAS = True` gate (already
  rejected cross-period -63% Q1 2025)
- Root cause: prompt mentioned "Counter-trend exposure" as a check —
  Claude latched onto direction over structure

**Prompt v2 (2026-05-21, commit f81f493) — major rewrite**:
- Embedded full ICT canonical rules from 2024 Mentorship (Silver Bullet
  bias-agnostic doctrine, FVG validity, sweep/MSS requirements, target =
  liquidity pool, Judas swing warning, BE warning, Premium/Discount)
- Added detailed VISUAL PATTERN REFERENCE section with ASCII diagrams
  showing how a REAL FVG/sweep/MSS/displacement looks vs how FAKES look
  (taught at "3-year-old level" per user request)
- Explicit "WHAT JUSTIFIES SKIP" vs "WHAT DOES NOT JUSTIFY SKIP" lists
  to break Claude's HTF-bias reflex
- New JSON output field `bot_assessment`:
  ```
  {
    "fvg_assessment": "accurate" | "questionable" | "wrong" | "missing",
    "sweep_assessment": same,
    "mss_assessment": same,
    "overall": "short sentence on bot's chart reading"
  }
  ```
  Independent of trade decision. Lets us accumulate data on systematic
  detector errors — original motivation for vision overlay.

**Decision criteria for Phase 2 (active mode)**:
- 3-5 days of shadow data with new prompt
- If vision counterfactual P&L > actual P&L by margin → ship active
- If `bot_assessment` consistently flags wrong/questionable → bot
  detectors need fixing (separate work)

**Telegram alert format** (Phase 1 shadow):
```
[VISION-SHADOW] AI Vision - KZ LONDON
[FIRE] FIRE (size 1.0x, conf 0.78, images 2)
Rationale: FVG c1-c3 gap clean with big c2 green displacement,
sweep of PDL 28814 visible with long wick reject, target PWH
29784 in clear sight, range regime.
Bot accuracy: FVG=accurate | sweep=accurate | MSS=questionable
  Bot's FVG annotation matches, minor doubt on 5-min MSS.
(SHADOW: bot continues canonical)
```

**Config (active 2026-05-21)**:
- `VISION_VALIDATOR_ENABLED = True`
- `VISION_VALIDATOR_SHADOW_MODE = True`
- `KZ_VALIDATOR_ENABLED = False` (C2 disabled — vision supersedes)
- `SB_HTF_WEAK_MIN_CONF = 0` (HTF-weak gate disabled — vision supersedes)
- `AI_MODEL_VISION_VALIDATOR = "claude-sonnet-4-6"`

**Tests**: 23 new in test_vision_validator.py (decision dataclass, prompt
structure, bot_assessment parsing, Telegram message). Full suite 1581/1581.

### 2026-05-21 — Day audit (with vision overlay running)

**Day outcome**: 12 trades, -$239 to -$389 net (P&L accounting variance
between my sum vs health.json daily_pnl — investigated later). Vision
shadow: 49/50 SKIP votes with old prompt. Prompt rewritten same evening
(commit f81f493) for next-day test.

Pattern observations:
- 4 winners (T2 +$232, T4 +$171, T5 +$134, T10 +$217)
- 8 losers (range -$61 to -$177)
- Recovery attempts in NY PM mostly failed (T11/T12 lost despite NY AM
  partial recovery)
- WR cross-day (5/19 + 5/20 + 5/21) still well below 60% baseline
- Strategy edge concern remains — fix prompted vision overlay rewrite

### 2026-05-18 — Asyncio liveness watchdog import fix

`main.py` watchdog block used `time.time()`/`time.sleep()` but `time` was never module-imported (only inside the local try/except). Watchdog silently failed at startup with `name 'time' is not defined`. Fix: added local `import time` at the top of the try block. Confirmed active in launch log: `Asyncio liveness watchdog started (threshold=90s, check_interval=30s)`.

---

*AlgoICT — SaaS Factory V4 | 20 Skills | 6 Intelligence Layers | 19-Point Confluence (SB sub: 10)*
*"ICT ve velas. SWC ve contexto. GEX ve fuerzas. VPIN ve smart money. Strategy Lab evoluciona. Post-Mortem aprende."*
