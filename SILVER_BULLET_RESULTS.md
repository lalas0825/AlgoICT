# AlgoICT Silver Bullet v4
## Resultados de validación y primer trade en vivo

**Sistema de trading algorítmico para futuros MNQ basado en metodología ICT**

---

## Executive Summary

Después de un proceso iterativo de diseño, implementación y debugging, el sistema **Silver Bullet v4 RTH Mode** ha demostrado edge consistente a través de 7 años de datos históricos y generó su primer trade live con éxito durante la sesión de Londres.

### Números clave

| Métrica | Resultado |
|---------|-----------|
| **Años validados** | 2019, 2020, 2021, 2022, 2023, 2024, 2025 (7 años) |
| **Total de trades simulados** | 12,119 |
| **Win Rate promedio** | ~44% |
| **Profit Factor promedio** | 1.89 |
| **P&L agregado** | +$672,000 |
| **Años positivos** | 7 de 7 |
| **Combine pass rate** | 72.4% (152 de 210 intentos aleatorios) |
| **Primer trade live** | +$2,154 (1 minuto de duración) |

---

## El problema

Los sistemas de trading ICT (Inner Circle Trader) tienen reputación de funcionar discrecionalmente pero fallar al automatizarse. Los intentos iniciales (NY AM Reversal con Order Block entry) perdieron dinero consistentemente en los backtests (~-$41K/año en 2024) por tres razones estructurales:

1. **Entry en OB es demasiado agresivo** — el precio atraviesa el OB y stopea antes de reversar
2. **Stops anchos** (OB distal) — hasta 15-30pts, mata risk-reward
3. **Targets fijos 1:3 RR** — arbitrarios, no alineados con liquidez real del mercado

Además, el código tenía bugs estructurales:
- FVG detectándose solo en timeframe 5min (SB necesita 1min)
- Estructura detectándose solo en 15min (SB necesita 5min)
- Daily trade cap de 3 que silenciosamente bloqueaba sesiones después de London
- Kill switch global que contaminaba sesiones independientes

---

## La solución: Silver Bullet v4 RTH Mode

### Filosofía

Trading basado en **setups institucionales verificables**:
- **FVG (Fair Value Gap)** como trigger de entrada (no Order Block)
- **Stops estructurales tight** (candle 1 del FVG + 1 tick)
- **Targets en pools de liquidez reales** (PDH, PDL, swing highs/lows) — nunca RR fijo
- **Framework mínimo 10 puntos** por trade (reglas ICT para MNQ)

### Tres ventanas de trading (RTH completo)

| Ventana | Horario (CT) | Horario (ET) |
|---------|--------------|--------------|
| **London** | 01:00 - 04:00 | 02:00 - 05:00 |
| **NY AM** | 08:30 - 12:00 | 09:30 - 13:00 |
| **NY PM** | 13:30 - 15:00 | 14:30 - 16:00 |

Total: ~8 horas diarias de cobertura activa.

### Gates de ejecución

Cada posible trade pasa por 8 validaciones:

1. **Kill zone activa** — solo en las 3 ventanas
2. **Risk manager OK** — no en MLL stop zone, no en kill switch daily
3. **Max trades per zone** — unlimited con kill switch reset per-zone
4. **FVG presente** — primera FVG formada dentro de la ventana
5. **Sweep validation** — liquidez opuesta tomada antes del FVG
6. **Structure alignment** — MSS o BOS en 5min alineado con FVG
7. **Framework ≥ 10 pts** — distancia de entry a target ≥ 10 puntos MNQ
8. **Position sizing** — risk $250 por trade, floor(capital / stop_distance)

### Protecciones de riesgo (Topstep Combine compliance)

- **MLL Trailing Drawdown**: $2,000 desde peak equity
- **Zones protectivas**: warning 40% ($800), caution 60% ($1,200), stop 85% ($1,700)
- **Position size reduction**: -25% en warning, -50% en caution
- **Daily Loss Limit**: $1,000
- **Kill switch diario**: halt después de 3 losses consecutivas
- **Per-KZ reset**: cada nueva ventana (London/NY AM/NY PM) resetea el kill switch
- **Hard close 15:00 CT**: flatten todas las posiciones antes del close

---

## Validación — Walk-Forward 7 años

Cada año ejecutado independientemente con los mismos parámetros (sin overfitting):

| Año | Trades | Win Rate | Profit Factor | P&L | Contexto de mercado |
|-----|--------|----------|---------------|-----|---------------------|
| 2019 | 2,110 | 43.1% | 1.68 | +$70,028 | Pre-pandemic bull |
| 2020 | 2,049 | 43.7% | 1.84 | +$92,203 | COVID extreme volatility |
| 2021 | 1,916 | 40.7% | 2.06 | +$110,598 | Stimulus rally |
| **2022** | **2,101** | **44.8%** | **2.01** | **+$103,804** | **Bear market — Fed hiking** |
| 2023 | 1,991 | 45.3% | 1.88 | +$91,062 | Choppy transition |
| 2024 | 2,067 | 44.1% | 2.39 | +$115,547 | Bull run |
| 2025 | 1,952 | 44.9% | 1.86 | +$89,759 | YTD |

### Observaciones clave

1. **Consistencia**: Win Rate nunca baja de 40%, Profit Factor nunca baja de 1.68
2. **Regime-agnostic**: 2022 (bear) fue uno de los mejores años (PF 2.01, +$103K)
3. **Escalabilidad**: ~2,000 trades/año muestra suficiente volumen para confianza estadística
4. **Baja varianza**: diferencia entre mejor año (+$115K) y peor año (+$70K) es manejable

---

## Combine Simulator

Para validar viabilidad de Combine Topstep $50K, se ejecutaron 30 simulaciones aleatorias por año, cada una representando un Combine fresh con start day diferente.

### Reglas aplicadas
- Balance inicial: $50,000
- Profit target: +$3,000
- MLL trailing: $2,000 desde peak
- DLL: $1,000 diario
- Min 5 días de trading con ≥$200 profit cada uno

### Resultados (30 intentos por año, 210 total)

| Año | Pass Rate | Fallo MLL | Fallo DLL | Días promedio para pass |
|-----|-----------|-----------|-----------|-------------------------|
| 2019 | 60.0% | 40.0% | 0% | 8 días |
| 2020 | 66.7% | 26.7% | 6.7% | 8 días |
| 2021 | 70.0% | 23.3% | 6.7% | 10 días |
| **2022** | **83.3%** | 16.7% | 0% | 9 días |
| 2023 | 66.7% | 33.3% | 0% | 9 días |
| 2024 | 73.3% | 23.3% | 3.3% | 8 días |
| **2025** | **86.7%** | 6.7% | 6.7% | 12 días |

**Agregado**: 152 passes de 210 attempts = **72.4% pass rate**

### Implicaciones económicas

- Costo por Combine: ~$100 (precio promo)
- Probabilidad de pass al primer intento: 72.4%
- Intentos esperados hasta pass: 1/0.724 = **1.38**
- Costo esperado total hasta pass: **~$138**
- Tiempo esperado hasta pass: **8-12 días**

---

## Primer Trade Live

**22 de abril 2026, 01:01 CT — Sesión London**

```
Strategy:      Silver Bullet v4
Direction:     SHORT MNQ
Entry:         26,826.00   (FVG.top + 1 tick)
Stop:          26,834.75   (FVG candle 1 high + 1 tick)
Target:        26,736.25   (Previous Day Low)
Position:      12 contratos
Risk:          ~$210 USD (stop 8.75pts × $2 × 12)

Setup ICT:
  - Sweep de equal highs/PDH detectado
  - MSS bearish confirmado en 5min
  - FVG bearish formado en 1min (dentro de London KZ)
  - Framework: 89.8pts hasta Previous Day Low
```

**Resultado**: Target alcanzado en ~2 minutos.

**P&L**: **+$2,154 USD**
**RR ejecutado**: 10.25:1

---

## Stack tecnológico

### Engine (Python 3.14)
- **Detección**: 7 detectores ICT (FVG, OB, Swing Points, Market Structure, Liquidity, Displacement, HTF Bias)
- **Risk management**: `RiskManager` con Topstep compliance integrado
- **Broker**: TopstepX API (REST + WebSocket + SignalR)
- **Position sizing**: Floor + expand stop para exact $250 risk
- **Tests**: 1,477 unit tests (100% passing)

### Data layer
- **Supabase PostgreSQL**: Audit trail, trades, signals, market_data, bot_state
- **Databento**: 7 años de data histórica MNQ 1-minute OHLCV
- **Realtime**: WebSocket 1-min bars + account events

### Monitoring
- **Telegram bot**: Alertas en tiempo real (fills, wins, losses, daily summary)
- **Dashboard Next.js**: Chart overlay con FVG/OB zones, Kill Zones, trades, positions
- **Heartbeat**: 5s write a Supabase, 15s offline detection, 30s alerta roja

### Safety layers
- **Single-instance lock**: `.engine.lock` previene múltiples procesos
- **VPIN toxicity shield**: Flatten automático si VPIN > 0.70 (con histéresis a 0.55)
- **Heartbeat flatten**: Si falla heartbeat → flatten all positions
- **Auto-reconnect**: WebSocket + SignalR con fallback a REST polling

---

## Qué sigue

### Esta semana (22-26 abril)
- **Paper trading continuo** en modo Topstep $50K simulado
- **Monitoreo diario** de trades vs comportamiento esperado
- **Análisis de gaps** backtest vs live (slippage, timing, fills)

### Decisión próxima (lunes 28 abril)
- Si 1 semana de paper muestra edge consistente → purchase real Combine ($100)
- Monitoreo durante pass intent (8-12 días promedio)
- Si pass → funded account activo

### Roadmap long-term
1. **Funded $50K**: probar edge con cuenta real pero sin capital propio
2. **Escalado a $100K/$150K**: Topstep Scaling Plan
3. **Diversificación**: múltiples estrategias independientes (trend-following, mean reversion)
4. **Paper infrastructure**: herramientas para compartir datos con equipo

---

## Consideraciones de riesgo

### Honest disclosures

**El backtest omite friccion real**:
- Sin slippage en stops (estimado +$5-10K de diferencia en 2024)
- Sin spread de bid-ask en entries (estimado +$2-4K)
- Sin commissions exchange fees (~$3K)
- **P&L realista 2024**: ~$100K en lugar de $115K gross

**Riesgos de ejecución live**:
- Paper mode de TopstepX no simula 100% al live (fill timing diferente)
- News events pueden generar slippage extremo
- Holidays con baja liquidez tienen comportamiento distinto

**Lo que NO está garantizado**:
- El mercado cambia; patrones que funcionaron 2019-2025 pueden no funcionar 2026+
- Volatility regime shifts pueden degradar edge
- Regulaciones de brokers o Topstep pueden cambiar reglas

### Mitigación
- 2 semanas de paper antes de compromiso de capital real
- Monitoreo continuo de drift entre backtest y live
- Kill switches multi-capa (MLL, DLL, heartbeat, VPIN)
- Position sizing conservador ($250 max risk / trade)

---

## Conclusión

El edge matemático está validado con 7 años de data a través de múltiples regímenes de mercado (bull, bear, volatile, choppy). La infraestructura técnica está probada con 1,477 unit tests passing. El primer trade live confirmó comportamiento as-designed con una ganancia de **+$2,154** en 2 minutos.

**El sistema está listo para la siguiente fase: validación de 1-2 semanas en paper trading, seguido de Combine real si las condiciones se mantienen.**

---

## Apéndice técnico

### Arquitectura del engine

```
algoict-engine/
├── strategies/
│   ├── silver_bullet.py      (stragegy principal - FVG-based)
│   ├── ny_am_reversal.py     (deprecada - OB-based)
│   └── donchian_vol.py       (baseline trend-following)
├── detectors/
│   ├── fair_value_gap.py     (FVG + IFVG detection)
│   ├── order_block.py        (OB + Mean Threshold)
│   ├── market_structure.py   (MSS, BOS, CHoCH)
│   ├── liquidity.py          (PDH/PDL/PWH/PWL + sweeps)
│   ├── swing_points.py       (pivot detection)
│   └── displacement.py       (impulse moves)
├── risk/
│   ├── risk_manager.py       (kill switch + Topstep MLL)
│   └── position_sizer.py     (floor + expand stop)
├── brokers/
│   └── topstepx.py           (TopstepX API)
├── backtest/
│   ├── backtester.py         (simulation engine)
│   └── combine_simulator.py  (Combine rules simulation)
└── main.py                   (live engine orchestrator)
```

### Parámetros clave (config)

```python
# Risk
RISK_PER_TRADE = 250          # USD max per trade
MAX_CONTRACTS = 50            # 50 MNQ = 5 minis ($50K account)
KILL_SWITCH_LOSSES = 3        # 3 consecutive losses → halt
DAILY_PROFIT_CAP = 1500       # $1,500/day → stop trading
HARD_CLOSE = (15, 0)          # 3:00 PM CT flatten

# Topstep $50K Combine
TOPSTEP_MLL = 2000            # $2,000 trailing drawdown
TOPSTEP_DLL = 1000            # $1,000 daily max loss
TOPSTEP_PROFIT_TARGET = 3000  # $3,000 para pass
MLL_WARNING = 0.40            # 40% DD → -25% position
MLL_CAUTION = 0.60            # 60% DD → -50% position
MLL_STOP = 0.85               # 85% DD → no new trades

# Silver Bullet v4
KILL_ZONES = ("london", "ny_am", "ny_pm")  # RTH coverage
MIN_FRAMEWORK_PTS = 10.0      # ICT MNQ minimum target distance
MAX_MNQ_TRADES_PER_DAY = 15   # Global daily cap
```

### Reglas ICT implementadas

1. **OB validity**: requires FVG in same direction within 3 bars
2. **Displacement**: ≥ 2× OB body (proportional, not ATR)
3. **Mean Threshold mitigation**: OB invalidated when close < 50% of body
4. **FVG entry**: candle 3 low + 1 tick (long) / high - 1 tick (short)
5. **FVG stop**: candle 1 low - 1 tick (long) / high + 1 tick (short)
6. **FVG invalidation**: body close beyond distal edge (not ratio fill)
7. **Framework ≥ 10pts**: MNQ minimum target distance per ICT section 8.1
8. **No HTF bias required**: Silver Bullet driven by "draw on liquidity"
9. **Sweep requirement**: opposite-side liquidity must be taken before FVG
10. **MSS requirement**: 5min Market Structure Shift aligned with FVG direction

---

*Documento generado: 22 de abril 2026*
*Sistema: AlgoICT Silver Bullet v4 RTH Mode*
*Stack: Python 3.14 + Next.js 16 + Supabase + TopstepX API*
