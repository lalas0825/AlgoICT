# AlgoICT — BUSINESS_LOGIC.md
### Generado por /new-app | SaaS Factory V4

---

## 1. Producto

**AlgoICT** — Bot ICT automatizado con 6 capas de inteligencia. ICT Core (price action), SWC (sentimiento), GEX (gamma exposure), VPIN (order flow toxicity), Strategy Lab (AI researcher), Post-Mortem (AI analyst). Diseñado para pasar Topstep $50K Combine.

---

## 2. Motores

**Motor 1: MNQ Intraday** — TopstepX API, $14.50/mes, max 50 MNQ, Python local Windows.
**Motor 2: Swing S&P 500** — Alpaca API (free), 500 stocks, hold 2-15 dias.

---

## 3. Estrategias

| # | Nombre | RR | Kill Zone | Entry | Max |
|---|--------|-----|-----------|-------|-----|
| 1 | NY AM Reversal | 1:3 | 8:30-11:00 AM | 5min | 2/dia |
| 2 | Silver Bullet | 1:2 | 10:00-11:00 AM | 1min | 1/dia |
| 3 | Swing HTF | 1:2 | Daily scan | 4H | 5 pos |

---

## 4. Risk (HARDCODED)

$250/trade (floor() + expand stop) | Kill switch 3 losses | Profit cap $1,500/dia | Hard close 3:00 PM CT | Min confluence 7/20 | Max 3 MNQ trades/dia | Heartbeat 5s | VPIN >0.70 = flatten | Topstep MLL $2K / DLL $1K | Max 50 MNQ

---

## 5. Confluence (20 pts)

ICT: liquidity grab (+2), FVG (+2), OB (+2), MSS (+2), KZ (+1), OTE (+1), HTF bias (+1), HTF OB/FVG (+1), PDH/PDL (+1)
SWC: sentiment alignment (+1)
GEX: wall alignment (+2), regime (+1)
VPIN: validated sweep (+1), quality session (+1)
**12+ = A+ | 9-11 = high | 7-8 = standard | <7 = NO TRADE**

---

## 6. Edge Modules

**SWC:** Pre-market scan (calendario + noticias + FedWatch → Daily Mood via Claude API). Event days: dynamic min_confluence + position size. Post-release scanner: ICT setups in retrace after spike.

**GEX:** Pre-market (NQ options → call wall resistance, put wall support, gamma flip, regime). Positive gamma → scalps. Negative → trend. Bonus: ICT+GEX alignment.

**VPIN:** Real-time from MNQ WebSocket (zero extra cost). Storm warning (>0.55), validated sweeps (+1), KZ quality (+1), flash crash protection (>0.70 = flatten all).

**Strategy Lab:** Claude generates ICT-grounded hypotheses. 9 anti-overfit gates (Sharpe, win rate, drawdown, walk-forward, cross-instrument NQ+ES+YM, stress test, inversion, Occam, validation). Data split: Train 2019-22 / Val 2023 / Test 2024-25 LOCKED. Human approves.

**Post-Mortem:** Every loss → Claude analyzes → 9 categories → pattern detection → alerts if 3+ same category.

---

## 7. Database — 7 Tables

`trades` `signals` `daily_performance` `bot_state` `market_levels` `post_mortems` `strategy_candidates`

---

## 8. Data + Costs

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

## 9. Roadmap

| Phase | Focus |
|-------|-------|
| 1 | Backtester + ICT + SWC-A + GEX-A + VPIN-A |
| 2 | Paper trading + SWC-B + GEX-B + VPIN live |
| 3 | Dashboard + swing + SWC-C + GEX-C + VPIN UI |
| 4 | Strategy Lab + optimization + Go Live |

---

## 10. Future

Signal-as-a-service ($49-99/mes), strategy marketplace, mobile app, other prop firms.

---

*AlgoICT — "ICT ve velas. SWC ve contexto. GEX ve fuerzas. VPIN ve smart money. Strategy Lab evoluciona. Post-Mortem aprende."*
