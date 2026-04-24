# AlgoICT — BUSINESS_LOGIC.md
### Generado por /new-app | SaaS Factory V4
### Última actualización: 2026-04-22

---

## 1. Producto

**AlgoICT** — Bot ICT automatizado con 6 capas de inteligencia. ICT Core (price action), SWC (sentimiento), GEX (gamma exposure), VPIN (order flow toxicity), Strategy Lab (AI researcher), Post-Mortem (AI analyst). Diseñado para pasar Topstep $50K Combine ($3,000 profit target, $2,000 MLL, $1,000 DLL).

---

## 2. Motores

**Motor 1: MNQ Intraday** — TopstepX API, $14.50/mes, max 50 MNQ, Python local Windows.
**Motor 2: Swing S&P 500** — Alpaca API (free), 500 stocks, hold 2-15 dias.

---

## 3. Estrategias

| # | Nombre | Exit Mode | Kill Zone (CT) | Entry TF | Trigger |
|---|--------|-----------|----------------|----------|---------|
| 1 | NY AM Reversal | 1:3 RR (fixed) | 8:30–12:00 | 5min | OB + OTE fib + HTF bias |
| 2 | Silver Bullet (v4 RTH) | Trailing 5min swing | London 01–04 · NY AM 08:30–12 · NY PM 13:30–15 | 1min | FVG-only + sweep + 5min MSS + framework≥10pts |
| 3 | Swing HTF | 1:2 RR | Daily scan | 4H | Weekly → Daily → 4H |

**Silver Bullet v4 RTH Mode**: ICT canonical windows are narrower (London SB 02-03, AM SB 09-10, PM SB 13-14 CT), but we run the wider kill-zone windows to capture setups that form slightly outside. Unlimited trades per zone; kill_switch (3 consecutive losses → halt session) + per-KZ reset is the real guard. See `SILVER_BULLET_STRATEGY_GUIDE.md` for full theory + visual walkthroughs.

---

## 4. Risk (HARDCODED)

$250/trade (floor() + expand stop) | Kill switch 3 consecutive losses/session | Profit cap $1,500/dia | Hard close 3:00 PM CT | Max 15 MNQ trades/dia (cap global) | Heartbeat 5s o flatten | VPIN ≥0.70 = FLATTEN ALL (resume ≤0.55, histéresis) | Topstep MLL $2K / DLL $1K | Max 50 MNQ

**Topstep MLL zones** (auto-activadas con `--topstep`):

| Zona | Drawdown | Acción |
|------|----------|--------|
| normal  | < 40% MLL (<$800)  | tamaño completo |
| warning | ≥ 40% MLL ($800+)  | −25% size, min_conf +1 |
| caution | ≥ 60% MLL ($1,200+)| −50% size, min_conf +2 |
| stop    | ≥ 85% MLL ($1,700+)| bloquea nuevas entradas |

**Combine rolling pass rate** (NY AM 2024, defaults 40/60/85): 19/20 = 95%.

---

## 5. Confluence Scoring

**Engine-wide**: 19 pts / 14 factores (`config.CONFLUENCE_WEIGHTS`, source of truth):

| Factor | Pts | Capa |
|--------|-----|------|
| Liquidity grab (sweep BSL/SSL/PDH/PDL/PWH/PWL/equal levels) | +2 | ICT |
| Fair Value Gap alineado | +2 | ICT |
| Order Block alineado | +2 | ICT |
| Market Structure Shift (BOS/CHoCH/MSS) | +2 | ICT |
| Kill Zone activa | +1 | Time |
| OTE Fibonacci (61.8-78.6 retrace) | +1 | ICT |
| HTF bias aligned | +1 | ICT HTF |
| HTF OB/FVG alignment | +1 | ICT HTF |
| Target at PDH/PDL/PWH/PWL | +1 | ICT |
| Sentiment alignment | +1 | SWC |
| GEX wall alignment | +2 | GEX |
| Gamma regime | +1 | GEX |
| VPIN validated sweep | +1 | VPIN |
| VPIN quality session | +1 | VPIN |

### NY AM Reversal
Usa los 19 pts completos. Tiers: `12+ = A+ full position | 9-11 = high | 7-8 = standard | <7 = NO TRADE`. **Hard gate** sobre `MIN_CONFLUENCE=7` (ajustable por MLL caution/warning).

### Silver Bullet (SB-specific subset, 2026-04-22)
De los 14 factores, solo 8 discriminan calidad de setup en SB — los otros 4 son **gates estructurales** (no scorear) y 2 no aplican. Subset en `config.SB_APPLICABLE_FACTORS`:

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
| **Max (SB_APPLICABLE_MAX)** | **10** |

**Gates estructurales** (si faltan → signal rechazado antes del scorer):
- Sweep de opposite pool
- 1-min FVG en dirección del setup
- 5-min MSS/BOS
- Kill zone activa
- Framework ≥10pts a next unswept liquidity

**Factores no aplicables a SB**: OTE Fibonacci (SB entra en FVG proximal, no en 61.8-78.6 retrace) · HTF OB/FVG alignment (SB no hace overlay HTF en el signal path).

SB **no** aplica gate de confluence (Q1 2024 análisis: scoring era noise). Filtrado real: gates + kill switch + MLL + VPIN shield. Score se loggea dual: `confluence=11/19 (SB: 4/10)` para que el número sea interpretable en la escala correcta.

---

## 6. Edge Modules

**SWC:** Pre-market scan (calendario + noticias + FedWatch → Daily Mood via Claude API). Event days: dynamic min_confluence + position size. Post-release scanner: ICT setups en retrace tras spike.

**GEX:** Pre-market (NQ options → call wall resistance, put wall support, gamma flip, regime). Positive gamma → scalps. Negative → trend. Bonus: ICT+GEX alignment.

**VPIN:** Real-time desde MNQ WebSocket (zero extra cost). Storm warning (≥0.55), validated sweeps (+1), KZ quality (+1), flash crash protection (≥0.70 = FLATTEN ALL, histéresis resume ≤0.55).

**Strategy Lab:** Claude genera hipótesis ICT-grounded. 9 anti-overfit gates (Sharpe, win rate, drawdown, walk-forward, cross-instrument NQ+ES+YM, stress test, inversion, Occam, validation). Data split: Train 2019-22 / Val 2023 / Test 2024-25 LOCKED. Human approves via auth code.

**Post-Mortem:** Cada pérdida → Claude analiza → 9 categorías → pattern detection → alerta si 3+ same category.

---

## 7. Telegram Verbosity (2026-04-22)

Tres niveles via `TELEGRAM_VERBOSITY` en `.env`:

| Level | Alertas | Volumen/día |
|-------|---------|-------------|
| `quiet` | Entries/exits, kill switch, heartbeat, daily summary, VPIN shield | 5–10 |
| `normal` (default) | Anterior + KZ enter/close summaries, liquidity sweeps, signal fired | 15–25 |
| `verbose` | Anterior + near-miss rejects (FVG+no-sweep, framework <10pts, etc.) | 40–80 |

**Throttling** por tipo de alerta (`config.TELEGRAM_THROTTLE_SEC`):
- `near_miss`: 300s por `(kz, reason)` — evita reject-storm (18 rejects iguales → 3 alertas máx)
- `sweep`: 0 (una por level swept, el flag previene re-alertar)
- `kz_enter` / `kz_summary`: 0 (una por transición KZ)
- `fvg`: 60s por `(kz, direction)` — verbose only

---

## 8. Database — 7 Tables

`trades` `signals` `daily_performance` `bot_state` `market_levels` `post_mortems` `strategy_candidates`

### Migrations
| # | Archivo | Resumen |
|---|---------|---------|
| 0001 | `0001_init.sql` | Schema inicial |
| 0002 | `0002_market_data.sql` | Tabla `market_data` (1min OHLCV) |
| 0003 | `0003_bot_state_overlays.sql` | JSONB overlays (fvg_top3, ifvg_top3, ob_top3, tracked_levels, struct_last3, last_displacement) + scalars (bias/KZ/VPIN/MLL/min_conf/status) |

---

## 9. Data + Costs

| Source | Cost |
|--------|------|
| FirstRateData MNQ+NQ | ~$60 once |
| FirstRateData ES+YM (Lab) | ~$60-100 once |
| TopstepX API | $14.50/mes |
| Topstep Combine | $49/mes |
| Claude API | ~$10-15/mes |
| Alpha Vantage | Free/$49 |
| CBOE/MenthorQ (GEX) | Free/$49 |
| VPIN | $0 (from existing data) |
| Supabase/Vercel/Alpaca | Free |
| **Monthly** | **$72-130** |
| **One-time** | **$120-160** |

---

## 10. Validation Status (2026-04-22)

### Tests + infra
- **Tests**: 1,477 passing (engine) · dashboard build ✓
- **Combine Simulator**: 72.4% pass rate (210 attempts, random start day)

### 7-year walk-forward (2019–2025, Silver Bullet v8 trailing RTH Mode)

| Año | Trades | WR | P&L | PF | MaxDD | Resets | DLL>-$1K days |
|-----|--------|-----|------|-----|-------|--------|---------------|
| 2019 | 2,110 | 43.1% | +$70,028 | 1.68 | $3,030 | 10 | 0 |
| 2020 | 2,049 | 43.7% | +$92,203 | 1.84 | $5,813 | 10 | 2 |
| 2021 | 1,916 | 40.7% | +$110,598 | 2.06 | $5,790 | 12 | 1 |
| 2022 | 2,101 | 44.8% | +$103,804 | 2.01 | $3,810 | 8 | 1 |
| 2023 | 1,991 | 45.3% | +$91,062 | 1.88 | $4,261 | 8 | 3 |
| 2024 | 2,067 | 44.1% | +$115,547 | 2.05 | $3,864 | 7 | 2 |
| 2025 | 1,952 | 44.9% | +$89,759 | 1.86 | $3,032 | 9 | 2 |
| **AGG** | **14,186** | **43.8%** | **+$673,000** | **1.91** | — | 64 | 11 |

### Consistency
- **Zero negative years** — los 7 años positivos
- **Mean annual P&L $96,143** · median $92,203 · std dev $15,320 (CV 15.9%)
- **Monthly hit rate 91.7%** — 77 de 84 meses positivos (solo ~1 mes negativo/año)
- **Daily hit rate 54.4%** — 983 de 1,808 trading days positivos
- **DLL breach rate 0.61%** — solo 11 días de 1,808 con P&L ≤ −$1,000 (1.6 días/año)

### Kill-zone contribution (7 años aggregate)
- **London: $436,600 (64.9%)** — workhorse en CADA año, sin excepción
- **NY AM: $164,344 (24.4%)**
- **NY PM: $72,057 (10.7%)** — weakest KZ

### A/B tests rechazados (feature stays OFF)
- **Equal levels refresh (Q1 2024)**: flat-to-neg (−$1,283, London regresa −$2,064). NY-only hybrid sí positivo (+$780), re-evaluar con más data real post-Combine
- **Risk ladder 250/200/150/100/50 + London 2L cap (Q1 2024)**: sobrevive mejor (−71% combine resets, −28% max DD) pero corta P&L 82% ($14,768 → $2,638, PF 1.47 → 1.15). London cap específicamente **cortaría el KZ más productivo** (64.9% del P&L agg). **Rechazado**: flat $250 v8 retained

### Bug fixes 2026-04-22
- **Phantom fill** en `_poll_position_status`: `entry_order.filled_price is None` → cancel stop/target + clean state (bug report: bot reportó +$2,154 sin fill real)
- **MAX_MNQ_TRADES_PER_DAY**: 3 → 15 (silenciaba NY AM tras London 3 trades)
- **1-min FVG + 5-min structure** ahora detect en live (antes solo 5-min FVG / 15-min structure → SB no veía sus propios triggers)
- **end_of_day()** ahora called en `_reset_for_new_day` (Topstep MLL trailing peak nunca advanzaba)

---

## 11. Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Backtester + ICT + SWC-A + GEX-A + VPIN-A | ✅ Done |
| 2 | Paper trading + SWC-B + GEX-B + VPIN live | 🟢 Active (paper OK, live blockers: none technical) |
| 3 | Dashboard + swing + SWC-C + GEX-C + VPIN UI | 🟡 Chart v1 live; swing pending |
| 4 | Strategy Lab + optimization + Go Live | 🟡 Lab ops; Go Live pendiente Combine pass real |

---

## 12. Future

Signal-as-a-service ($49-99/mes), strategy marketplace, mobile app, other prop firms.

---

*AlgoICT — "ICT ve velas. SWC ve contexto. GEX ve fuerzas. VPIN ve smart money. Strategy Lab evoluciona. Post-Mortem aprende."*
