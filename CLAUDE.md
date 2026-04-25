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

SB does **NOT enforce a min_confluence gate** (Q1 2024 analysis confirmed scoring was noise for SB — higher scores had lower WR). Real filtering: structural gates + kill switch + MLL + VPIN. The score is still computed for paper trail; logs + Telegram show dual display: `confluence=11/19 (SB: 4/10)`.

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
| Min confluence | NY AM: 7/19 (hard gate) · SB: 0 (no gate, structural gates handle) |
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

### Current feature decisions
- **`RISK_LADDER_ENABLED` = False** (infrastructure in place, ready if needed)
- **`KZ_LOSS_CAPS` = {}** (no per-KZ loss caps)
- **`equal_levels_refresh` OFF**
- **SB confluence gate** — removed (structural gates handle filtering)
- **`TRADE_MANAGEMENT` = "trailing"** (matches live + backtest)
- **Silver Bullet v4 RTH Mode** — wider KZ coverage (London 01-04 / NY AM 08:30-12 / NY PM 13:30-15 CT)

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

---

*AlgoICT — SaaS Factory V4 | 20 Skills | 6 Intelligence Layers | 19-Point Confluence (SB sub: 10)*
*"ICT ve velas. SWC ve contexto. GEX ve fuerzas. VPIN ve smart money. Strategy Lab evoluciona. Post-Mortem aprende."*
