---
name: backtest
description: "Skill para correr backtests, el Combine Simulator, y generar reportes de rendimiento. Activa cuando el usuario pide backtest, simulacion, validacion de estrategias, o pregunta si el sistema pasa el Combine. Siempre corre risk_audit despues de cada backtest."
argument-hint: "[strategy] [--start DATE] [--end DATE]"
user-invocable: true
allowed-tools: Read, Write, Bash
---

# Backtest Skill

## Cuando se activa
- "Corre el backtest", "Backtest NY AM", "Backtest Silver Bullet"
- "Simula el Combine", "Pasa el Combine?", "Cuantos dias para pasar?"
- "Cuantos trades gano?", "Cual es el win rate?", "Drawdown maximo?"
- "Compara estrategias", "Cual es mejor?", "Expectancy?"
- Cualquier referencia a rendimiento historico o validacion

## Directorio de trabajo
```bash
cd algoict-engine/
```

## Validation Gate — REGLA ABSOLUTA

> **NO se puede correr `main.py` (paper o live) hasta que el Combine Simulator pase 12 meses con CERO violaciones de reglas de riesgo.**

Antes de aprobar el paso a paper trading, verificar:
1. Risk audit: ZERO trades que violen $250 max risk
2. Risk audit: ZERO dias que excedan $1,000 daily loss
3. Risk audit: ZERO dias que excedan $1,500 profit cap
4. Combine Simulator: el sistema PASA el Combine (llega a $3,000 sin romper MLL)
5. Worst losing streak: el kill switch de 3 losses aguanta
6. Min 200 trades simulados para significancia estadistica

## Workflow Completo de Backtest

### Paso 1: Cargar Data
```bash
python -c "
from backtest.data_loader import load_futures_data
df = load_futures_data('../data/mnq_1min.csv')
print(f'Loaded {len(df)} candles from {df.index[0]} to {df.index[-1]}')
"
```

### Paso 2: Correr Backtest
```bash
# Una estrategia
python -m backtest.backtester \
  --strategy ny_am_reversal \
  --data ../data/mnq_1min.csv \
  --start 2023-01-01 \
  --end 2025-12-31

# Todas las estrategias MNQ
python -m backtest.backtester \
  --strategy all_mnq \
  --data ../data/mnq_1min.csv \
  --start 2023-01-01
```

### Paso 3: Risk Audit (OBLIGATORIO)
```bash
python -m backtest.risk_audit --results backtest/results/latest.json
```

El risk audit verifica que CADA trade simulado cumple con:
- Risk per trade <= $250
- Position sizing via floor()
- Kill switch habria activado despues de 3 losses
- Profit cap habria parado el bot en $1,500/dia
- Hard close antes de 3:00 PM CT
- Min confluence >= 7 puntos
- No trades durante news blackout

**Si el audit encuentra CUALQUIER violacion:** el backtest es INVALIDO. Arreglar el codigo y correr de nuevo.

### Paso 4: Combine Simulator
```bash
python -m backtest.combine_simulator \
  --data ../data/mnq_1min.csv \
  --start 2024-01-01 \
  --end 2024-12-31
```

El Combine Simulator simula exactamente las reglas del Topstep $50K:
- Starting balance: $50,000
- Profit target: $3,000
- MLL: $2,000 trailing from balance high (end-of-day)
- DLL: $1,000 per day
- Consistency: best day < 50% of total profit
- Bot rules: $250/trade, kill switch, profit cap

**Output:**
```
=== COMBINE SIMULATION RESULTS ===
Passed: YES/NO
Days to pass: X
Final balance: $XX,XXX
Max drawdown: $XXX
Best day: $XXX (XX% of total — consistency OK/FAIL)
Worst day: -$XXX
Total trades: XXX
Win rate: XX%
Avg win: $XXX | Avg loss: -$XXX
Profit factor: X.XX
Expectancy: $XX per trade
Sharpe ratio: X.XX
Worst losing streak: X trades
Kill switch activations: X days
Profit cap activations: X days
Risk violations: X (MUST BE 0)
```

### Paso 5: Generar Reporte
```bash
python -m backtest.report --results backtest/results/latest.json --output backtest/results/report.md
```

### Paso 6: Guardar en Memoria
Despues de cada backtest significativo, guardar resultados en:
```
.claude/memory/project/backtest-results.md
```

Formato:
```markdown
## Backtest: [Strategy] — [Date Range]
- **Date run:** YYYY-MM-DD
- **Passed Combine:** YES/NO
- **Win rate:** XX%
- **Expectancy:** $XX/trade
- **Max drawdown:** $XXX
- **Key insight:** [que aprendimos]
- **Parameters changed:** [si se ajusto algo]
```

## Metricas que el Reporte DEBE incluir

### Performance
- Total trades
- Win rate / Loss rate
- Average win ($) / Average loss ($)
- Expectancy per trade ($)
- Profit factor (gross profit / gross loss)
- Largest win / Largest loss

### Risk
- Maximum drawdown ($ and %)
- Worst day P&L
- Worst consecutive losses
- Number of kill switch activations
- Number of profit cap activations
- Risk violations (MUST be 0)

### Combine-Specific
- Days to reach $3,000 profit target
- Best single day (consistency check: < $1,500?)
- MLL survival (never hit $2,000 trailing drawdown?)
- Passed: YES / NO

### Distribution
- Trades per Kill Zone (NY AM vs Silver Bullet)
- Win rate per Kill Zone
- Trades per day of week
- Win rate per day of week
- Trades per confluence score range (7-8 vs 9-10 vs 11+)
- Win rate per confluence score range
- Average trade duration

### Equity Curve
- Generate CSV with daily balance for charting in dashboard

## Comparar Estrategias

Cuando el usuario pide comparar:
```bash
python -m backtest.backtester --strategy ny_am_reversal --data ../data/mnq_1min.csv --start 2024-01-01 --output results_nyam.json
python -m backtest.backtester --strategy silver_bullet --data ../data/mnq_1min.csv --start 2024-01-01 --output results_sb.json
python -m backtest.report --compare results_nyam.json results_sb.json
```

## Cuanto Data Usar

| Tipo | Rango | Proposito |
|------|-------|-----------|
| Quick test | 3 meses | Validar cambios rapidos |
| Standard | 12 meses | Validacion seria |
| Extended | 2-3 anios | Significancia estadistica |
| Full (NQ) | 2019-2025 | Validacion maxima |

**Regla:** Para aprobar paso a paper trading, MINIMO 12 meses con 200+ trades.
