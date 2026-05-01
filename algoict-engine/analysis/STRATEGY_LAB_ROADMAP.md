# Strategy Lab Roadmap

## Objetivo futuro: Strategy Lab sobre v19a-WIDE para subir WR

**Status**: pendiente, NO ejecutar ahora.

**Objetivo concreto**: tomar v19a-WIDE como baseline (WR ~64%, PF ~3.2, P&L ~$165K/año proyectado) y usar Strategy Lab para generar hipótesis que **suban WR a 75-80%**.

**Filosofía**: ya tenemos una strategy con edge clara (PF 3.2). En vez de buscar volumen extra, buscamos QUALITY filters que conviertan losers en non-trades.

## Cuándo correr

- DESPUÉS de que v19a-WIDE esté shippeado en live y validado al menos 2 semanas
- DESPUÉS de pasar el Topstep Combine al menos 1 vez con la versión actual
- En período donde el mercado esté CERRADO (weekend) para no competir CPU con bot live

## Cómo correr (cuando llegue el momento)

```bash
cd algoict-engine
python -m strategy_lab.lab_engine --mode overnight --count 20 --baseline v19a_wide
```

Con prompt customizado para el LLM:

```
Baseline: v19a-WIDE Silver Bullet variant.
- 7-yr backtest: $1M+ P&L, WR ~64%, PF ~3.2
- Setup: sweep + 1min FVG + 5min MSS/BOS + framework ≥ 10pt
- KZ: full sessions (london 01-07:30, ny_am 07:30-12, ny_pm 12-15 CT)
- Risk: $250 trailing, $50K Topstep combine

Goal: GENERATE 20 hypotheses to RAISE WR from 64% to 75-80%.
Each hypothesis must:
- Be ICT-grounded (no random param tweaks)
- Add at most 1 filter or 1 condition
- Specifically target rejecting the 36% LOSING trade types
- NOT reduce trade volume by more than 30%

Focus areas:
- Pre-trade quality filters (e.g. ATR-based regime detection)
- Post-sweep confirmation timing (e.g. wait for MSS before FVG)
- HTF context filters (e.g. weekly bias alignment, daily range)
- Volatility regime gates (e.g. skip extreme news days)
```

## Validation framework

- 9 anti-overfit gates aplicados sobre 2023 (validation set)
- Si pasa → run en train 2019-2022 para confirmar
- 2024-2025 quedan **bloqueados** hasta autorización final

## Pass criteria para shippear cualquier candidate

| Métrica | Threshold |
|---|---|
| WR vs baseline | ≥ +10pp (target 74%+) |
| PF vs baseline | ≥ +0.5 (target 3.7+) |
| Volume reduction | ≤ -30% (mantener ≥ 1,400 trades/año) |
| Cross-instrument | 2/3 (NQ + ES + YM) en train period |
| Walk-forward | ≥ 70% windows positive |
| Noise resilience | < 30% degradación |
| Inversion test | Must lose money cuando se invierte |
| Occam's razor | ≤ 2 nuevos params |
| Negative years | 0 en validation+train |

## Estimación de ROI

Si subimos WR de 64% → 75% manteniendo R:R ~1.7 y volumen actual:
- Expected: ~$1.5M/año (vs $1M actual)
- 50% boost adicional sobre v19a-WIDE

Si llegamos a 80% WR:
- Expected: ~$2M+/año
- Strategy "casi bulletproof" para combine pass

## Costos esperados

- API: ~$0.50 (20 hipótesis con caching)
- CPU: ~30 horas overnight para validation completa de survivors
- Tiempo humano: 2-3 horas analizando outputs + decisión final
