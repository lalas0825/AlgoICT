# AlgoICT Session Notes — April 20, 2026

## Resumen del Día

### Lo que hicimos hoy (cronológico):
1. Bot arrancó a las ~05:22 CT con todos los fixes de los días anteriores
2. London KZ (01:00-04:00 CT): 2 signals FIRE, 2 trades ejecutados, 2 losses (-$269 total)
3. Auditoría completa de London — 6 bugs identificados y arreglados
4. NY AM KZ (08:30-12:00 CT): 0 trades, 429 EVALs todos rechazados
5. Auditoría de NY AM — root cause: ob=0 durante casi toda la sesión
6. Investigación profunda del detector de OBs
7. Backtests por KZ con nuevos parámetros (corriendo)
8. Discusión sobre estrategia: FVG entry vs OB entry

### Bugs arreglados hoy (commits):
- `fbc84e9` — Tick rounding (_snap), ORPHAN resolution, Supabase fallback
- `52cb7a3` — User hub max-retry cap + REST polling fallback + trailing Telegram
- `9685c11` — OB proximity gate (3pts) + limit entry orders
- `ef43150` — FVG→0.75 (revert), OB purge softened (>100 bars), OB_MAX_AGE→1000
- `8ade7a0` — OB purge by BOS, limit TTL 10 bars, FVG 50%→75%, OB age decay

### Estado actual del bot:
- PID: 56584
- Config: proximity gate 3pts, limit orders, TTL 10 bars, FVG 75%, OB purge >100 bars, OB age 1000 bars
- KZ activas: london, ny_am, ny_pm (pero London pierde dinero)
- User hub: fallback a REST polling (paper mode no soporta SubscribeAccounts)
- TRADE_MANAGEMENT: trailing (wired al live engine)

---

## Auditoría London KZ — 20 Abril 2026

### Timeline:
- 00:45 CT: SWC re-scan choppy → risk_on
- 01:05 CT: Signal 1 FIRE — LONG 6×MNQ, confluence 9/19
- 01:10 CT: Signal 2 FIRE — LONG 6×MNQ, confluence 7/19
- Entry calculado: 26,620 (OB level) — fill real: ~26,657 (market order)
- Stop: 26,605.75 (OB distal) — 51pts de riesgo real vs 14pts calculados
- Target: 26,666.88 → RECHAZADO por tick misalignment
- Precio subió a 26,693 (+37pts desde fill) pero sin target → trailing stop
- Trailing: 26,605→26,612→26,616→26,644
- 03:04 CT: precio cae a 26,641, stop hit en 26,644
- P&L: Trade 1 -$170, Trade 2 -$99, Total -$269

### 6 Bugs encontrados:
1. CRITICAL: No proximity check — entró 44pts arriba del OB con market order
2. CRITICAL: Target 26,666.88 no alineado a tick 0.25 → rechazado
3. HIGH: ORPHAN state no se resolvía (3h de phantom operations)
4. HIGH: User hub falla en paper mode → no fill detection → no Telegram WIN/LOSS
5. MEDIUM: Supabase signal_type column missing
6. LOW: No Telegram notification de trailing stop updates

### Todos arreglados (ver commits arriba)

---

## Auditoría NY AM KZ — 20 Abril 2026

### Resultado: 0 trades, 429 EVALs rechazados

### Razones:
- no_ob: 124 (56%) — ZERO OBs activos durante casi toda la sesión
- otros no_valid_setup: 51 (23%)
- vpin_halted: 34 (15%) — halt 09:59-10:33 CT (VPIN 0.757)
- outside_kz: 11 (5%)

### Root cause:
- Único OB (26,648-26,659) formado en pre-market, 50+ pts debajo del precio
- Proximity gate rechazó correctamente (gap 70pts > tolerancia 3pts)
- OB mitigado a las 10:00 CT cuando close penetró distal
- Mercado ranging 10:00-12:00: bodies 5-8pts, threshold 12pts (1.5×ATR) → 0 OBs nuevos
- OB_ATR_MULTIPLIER = 1.5 es demasiado estricto para días ranging

---

## Investigación: Detector de Order Blocks

### Cómo funciona:
1. Busca velas con body ≥ 1.5× ATR(14) = "displacement"
2. Camina hacia atrás buscando última vela contraria = OB candle
3. OB = high/low de esa vela, dirección = dirección del displacement
4. Mitigación: close penetra el distal (OB.low para bullish)
5. No hay TTL por tiempo (solo age decay de 1000 bars = ~13 días)
6. Purge por BOS contrario solo si OB tiene >100 bars de edad

### Problema identificado:
- 1.5× ATR en 5min MNQ = ~12-18pts de body requerido
- En días ranging (~30-40% de los días), ninguna vela alcanza ese threshold
- Resultado: ob=0 toda la sesión → estrategia ciega
- Un trader ICT vería OBs más pequeños que el detector ignora

### Parámetros actuales:
- OB_ATR_MULTIPLIER = 1.5 (strict)
- OB_ATR_PERIOD = 14
- OB_MAX_HISTORY = 100
- OB_MAX_AGE_BARS = 1000
- OB_SWEEP_LOOKBACK = 5
- OB_FVG_LOOKFORWARD = 3
- OB_PROXIMITY_TOLERANCE = 3.0 pts

---

## Discusión Abierta: Estrategia de Entry

### Problema fundamental:
La estrategia NY AM Reversal entra SIEMPRE en el OB (limit order al borde proximal). El FVG solo sirve como gate (¿existe? sí/no). En ICT real, puedes entrar en el FVG cuando tiene confluencia con OB/sweep.

### Lo que pasó en London:
- FVG 26,654-26,658 estaba exactamente donde el precio estaba (recuadro azul del user)
- OB 26,606-26,620 estaba 44pts abajo
- El bot ignoró el FVG como entry y puso limit en el OB
- Con market orders (viejo backtest), entraba al precio de mercado pero calculaba P&L desde el OB → números inflados

### Hallazgo sobre backtests anteriores:
Los "beautiful numbers" (+$197K, PF 3.57) asumían fills perfectos al precio del OB. En realidad, con market orders el fill es al precio de mercado (potencialmente 20-50pts del OB). Con limit orders, muchos trades no se llenan porque el precio no retrace. Ambos modelos tienen problemas.

### Opciones discutidas:
1. Market orders + stop ajustado post-fill (stop estructural: bajo swing low, FVG, o BOS)
2. Limit orders con TTL (actual, pero produce menos trades)
3. FVG entry mode (entry en FVG, OB como validación)
4. ENTRY_MODE configurable: "ob" | "fvg" | "best"

### Nota importante sobre FVG vs OB entry:
En la mayoría de los casos FVG.bottom == OB.high (son el mismo nivel, porque el OB es la vela justo antes del displacement). La diferencia solo existe cuando el OB está varias velas antes del displacement (hay dojis/indecisión entre OB y FVG).

---

## Backtests por KZ (corriendo / completados)

### Config: proximity gate ON, limit orders ON, TTL 10 bars, FVG 75%, OB purge >100 bars

| KZ | Trades | WR | PF | P&L | Status |
|---|---|---|---|---|---|
| London | 319 | 21.3% | 0.45 | -$30,959 | ✅ DONE |
| NY AM | ??? | ??? | ??? | ??? | CORRIENDO (lento por OneDrive I/O) |
| NY PM | ??? | ??? | ??? | ??? | PENDIENTE |
| ALL | ??? | ??? | ??? | ??? | PENDIENTE |

### London: CONFIRMADO NEGATIVO — no funciona con esta estrategia

### Nota: backtests lentos (~75 min cada uno) por OneDrive sync bloqueando I/O del CSV de 396MB. El usuario planea migrar el proyecto a C:\ esta tarde.

---

## Próximos Pasos (cuando el usuario retome la sesión)

### INMEDIATOS:
1. Esperar resultados de backtests NY AM / NY PM / ALL
2. Si NY AM es positivo → confirma que la estrategia funciona en esa KZ con limit orders
3. Si NY AM es negativo → el modelo de limit orders es el problema, volver a market orders con safeguards

### DISCUSIÓN PENDIENTE:
4. El usuario va a mandar screenshot del chart 5min de hoy con OBs marcados
5. Comparar OBs que ve el trader vs OBs que detectó el bot
6. Determinar si OB_ATR_MULTIPLIER = 1.5 es demasiado estricto
7. Evaluar si bajar a 1.0-1.2 produce más OBs de calidad

### IMPLEMENTACIÓN PENDIENTE:
8. Market orders con stop estructural post-fill (propuesta del usuario):
   - Market order (fill inmediato, como antes)
   - Post-fill: buscar el nivel estructural más cercano debajo del fill (swing low, FVG, OB, BOS)
   - Stop en ese nivel (no en el OB distal que puede estar 50pts abajo)
   - Recalcular contracts basado en el stop real
   - Max distance gate: si fill > 15pts del OB → cerrar inmediatamente
9. Re-correr backtests con market orders + stop estructural
10. Migrar proyecto de OneDrive a C:\ para backtests rápidos

### LONG TERM:
11. Desactivar London para NY AM Reversal
12. Silver Bullet como estrategia separada para London
13. Counter-bias mode (estructura en cualquier dirección, HTF bias solo para size)
14. Breaker Block strategy (fase 2)
15. OTE zone alignment (fase 2)

---

## Archivos de referencia:
- Documentos generados: /mnt/outputs/AlgoICT_*.docx (5 reportes)
- Engine log: engine.log (sobreescrito en cada restart)
- Backtest logs: bt_2024_london.log, bt_2024_nyam2.log, bt_2024_nypm2.log, bt_2024_all2.log
- Config principal: config.py
- Estrategia: strategies/ny_am_reversal.py, strategies/silver_bullet.py
- OB detector: detectors/order_block.py
- FVG detector: detectors/fair_value_gap.py

---
---

# AlgoICT Session Notes — April 21, 2026

## TL;DR del día
1. **Silver Bullet rewrite completo (v4)** → **primer backtest positivo** del proyecto: 2024 ALL 3 windows = **+$11,102, PF 1.11**. AM SB solo = +$10,411 PF 1.33. PM SB solo = +$7,035 PF 1.23. London SB = -$8,953 PF 0.78.
2. **NY AM Reversal 3 iteraciones (v2/v3a/v3b)** → todas negativas. Confirmado: la estrategia OB-based está estructuralmente rota. **Pausada**.
3. **Canon ICT extraído** del video "How ICT Picks Winning FVG's & Orderblocks" (Oct-2024) — guardado en `~/.claude/projects/.../memory/ict_*.md`. 4 archivos de referencia.
4. **Donchian-Vol** (trend-following baseline) creado como segunda estrategia. Walk-forward 2019-2024 corriendo AHORA en paralelo con v5.
5. **v5 (Silver Bullet walk-forward 2019-2023)** corriendo AHORA. ETA total de ambos: ~8-10 horas.

---

## Cronología del día

### Mañana — Auditoría de v1 y v2 (trailing + partials_be variants)
Todos los backtests de NY AM Reversal en 2024 salieron negativos:
- v1 (baseline trailing, OB_AGE=1000): ALL 597 trades / WR 22.3% / PF 0.59 / -$41,704
- v2 (partials_be, OB_AGE=96): ALL 454 trades / WR 24.2% / PF 0.29 / -$49,206 (PEOR — partials_be cortaba ganadores)

### Extracción canon ICT
El usuario pasó video de ICT "How ICT Picks Winning FVG's & Orderblocks" (https://www.youtube.com/live/svYZKOrWPRo, Oct-25-2024). Via NotebookLM se extrajeron reglas específicas en 8 secciones:
- OB validity (FVG required ES absoluto)
- FVG behavior (body_close invalida, no 75% fill)
- Silver Bullet (FVG-based NO OB-based, 3 ventanas 60min ET, no HTF bias, framework ≥10pts MNQ)
- Entry mechanics (limit preferred, 1-tick offset)
- Stop placement (FVG candle 1, OB low, +1 tick buffer)
- Targets = liquidity pools (NUNCA RR fijo)

### Implementación v3a → v3b (detectores ICT)
Cambios aplicados en [detectors/order_block.py](algoict-engine/detectors/order_block.py) y [detectors/fair_value_gap.py](algoict-engine/detectors/fair_value_gap.py):
1. `OB_REQUIRE_FVG=True` — FVG obligatorio para OB válido (ICT hard rule)
2. `OB_DISPLACEMENT_BODY_RATIO=2.0` — displacement ≥ 2× OB body (no ATR)
3. `OB_DISPLACEMENT_ATR_FLOOR=1.0` — floor ATR añadido en v3b para filtrar noise
4. `OB_MEAN_THRESHOLD=0.50` — mitigación por 50% de OB body (no wick)
5. `FVG_MITIGATION_MODE="body_close"` — FVG solo invalida con body-close más allá del distal
6. OrderBlock dataclass: agregó `open_price`, `close_price` para Mean Threshold
7. FVG dataclass: agregó `stop_reference` (candle 1 extreme) para Silver Bullet stops
8. `OB_MAX_AGE_BARS`: 1000 → 96 (v3a) → 500 (v3b, ICT dice no caduca por tiempo)

**Resultados v3b (NY AM Reversal 2024):**
- London: 347 / WR 22.2% / PF 0.62 / **-$23,572** (mejor que v1, pero aún negativo)
- NY AM: 370 / WR 19.2% / PF 0.51 / **-$32,868** (PEOR que v1's -$18,980)
- NY PM: 248 / WR 10.9% / PF 0.38 / **-$30,032** (mejor que v1)
- ALL: 665 / WR 21.8% / PF 0.65 / **-$41,194** (flat vs v1)

**Veredicto NY AM Reversal**: estructural broken. No se flipa con tweaks de detectores. **PAUSADO**.

### Silver Bullet rewrite v4 — PRIMER BACKTEST POSITIVO
Reescrito completo en [strategies/silver_bullet.py](algoict-engine/strategies/silver_bullet.py) (394 LOC, 35 tests pasan). Cambios:
- Entry: FVG proximal + 1 tick (no OB)
- Stop: FVG candle 1 extreme ± 1 tick (no OB distal)
- Target: nearest unswept liquidity pool, **framework ≥ 10 pts MNQ**
- 3 ventanas: `london_silver_bullet` (02-03 CT), `silver_bullet` AM (09-10 CT fixed de 10-11 CT wrong!), `pm_silver_bullet` (13-14 CT nuevo)
- NO HTF bias required (ICT explicit)
- MIN_CONFLUENCE = 5 (vs 7 de NY AM)

**Resultados v4 (Silver Bullet 2024):**
| Ventana | Trades | WR | PF | Avg Win | Avg Loss | P&L |
|---------|--------|----|----|---------|----------|---------|
| London SB | 184 | 7.1% | 0.78 | $2,404 | -$235 | -$8,953 |
| **AM SB** | **173** | **20.2%** | **1.33** | $1,200 | -$229 | **+$10,411** ✅ |
| **PM SB** | **164** | **18.9%** | **1.23** | $1,211 | -$229 | **+$7,035** ✅ |
| **ALL** | **494** | **15.0%** | **1.11** | $1,464 | -$231 | **+$11,102** ✅ |

### Donchian-Vol baseline (MVP trend-following)
Creado en [strategies/donchian_vol.py](algoict-engine/strategies/donchian_vol.py) (~350 LOC, 14 tests pasan). Filosofía "simplicity beats complexity":
- Señal: 20-bar Donchian breakout + volume ≥ 1.5× avg + body ≥ 1.0× ATR(14)
- Filtros: ATR regime (current > median of last 60), kill zones (london/ny_am/ny_pm)
- Stop: 2× ATR(20) del entry
- Target: trailing (far, chandelier-like)
- Sin HTF bias, sin confluence, sin ICT primitives

## Backtests corriendo AHORA (background)

**v5** — Silver Bullet walk-forward 2019-2023 (5 años). Launched 05:00 CT.
**v6** — Donchian-Vol walk-forward 2019-2024 (6 años). Launched 05:06 CT.

ETA total: ~8-10 horas (ambos comparten I/O del CSV 396MB, slowdown ~1.5-2×).

Logs: `bt_v5_{year}.log` y `bt_v6_{year}.log`.

## Próximos pasos (cuando regreses)

### Inmediato
1. **Extraer resultados de v5 (SB walk-forward)** — ¿PF > 1.15 en ≥4/5 años? → validated edge
2. **Extraer resultados de v6 (Donchian walk-forward)** — comparar baseline vs Silver Bullet
3. **Decision gate**:
   - Si **ambos positivos** → paper trade ambos en paralelo (diversificación)
   - Si **solo SB positivo** → paper trade solo SB
   - Si **solo Donchian positivo** → paper trade Donchian, archivar SB como "lucky 2024"
   - Si **ambos negativos en walk-forward** → investigar sweep detection / tracked_levels quality

### Mediano plazo (próxima semana)
4. **Decidir London SB**: los 5 años walk-forward dirán si London es estructuralmente malo o solo 2024 tuvo mala suerte
5. **Combine Simulator run** con la(s) estrategia(s) ganadora(s). Target $3K profit, MLL $2K, zero violations
6. **Paper trade 30 días** antes de live money

### Largo plazo
7. Strategy Lab con 9 gates anti-overfit para tunear parámetros de la(s) estrategia(s) validada(s)
8. Dashboard update para mostrar signals de Silver Bullet / Donchian-Vol en vez de NY AM Reversal
9. Live engine wire-up con las estrategias validadas

## Archivos clave tocados hoy

- [config.py](algoict-engine/config.py) — nuevos constantes ICT + KZ fixes
- [detectors/order_block.py](algoict-engine/detectors/order_block.py) — rewrite con FVG-required + Mean Threshold
- [detectors/fair_value_gap.py](algoict-engine/detectors/fair_value_gap.py) — body_close mode + stop_reference
- [strategies/silver_bullet.py](algoict-engine/strategies/silver_bullet.py) — **REWRITE COMPLETO** FVG-based
- [strategies/donchian_vol.py](algoict-engine/strategies/donchian_vol.py) — NUEVO, baseline trend-following
- [scripts/run_backtest.py](algoict-engine/scripts/run_backtest.py) — registrado donchian_vol
- [tests/test_silver_bullet.py](algoict-engine/tests/test_silver_bullet.py) — rewrite completo, 35 tests
- [tests/test_donchian_vol.py](algoict-engine/tests/test_donchian_vol.py) — NUEVO, 14 tests

## Métricas de tests
- **1477/1477 passing** (pre-día: 1463, +14 Donchian-Vol)
- Sin regresiones en otras strategies

## Commits pendientes (si quieres hacer checkpoint)

Hay MUCHO trabajo sin commitear. Sugerencia de sequence:
```bash
git add detectors/order_block.py detectors/fair_value_gap.py config.py
git commit -m "ICT detector canon: FVG-required OBs, Mean Threshold, body-close FVG mitigation"

git add strategies/silver_bullet.py tests/test_silver_bullet.py
git commit -m "Silver Bullet rewrite: FVG-based entry, 3 ET windows, framework ≥10pts"

git add strategies/donchian_vol.py tests/test_donchian_vol.py scripts/run_backtest.py
git commit -m "Donchian-Vol baseline: 20-bar breakout + vol target, non-ICT benchmark"

git add tests/test_session_manager.py tests/test_order_block.py tests/test_fvg.py
git commit -m "Tests updated for new ICT semantics (body_close, Mean Threshold, 9-10 CT SB)"

git add SESSION_NOTES.md run_4bt_v2.ps1 run_4bt_v3a.ps1 run_4bt_v3b.ps1 run_4bt_v4.ps1 run_v5_walkforward.ps1 run_v6_donchian_walkforward.ps1
git commit -m "Session notes + backtest runner scripts for v2-v6"
```

