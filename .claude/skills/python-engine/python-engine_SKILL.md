---
name: python-engine
description: "Skill para trabajar con el motor de trading Python. Activa cuando el usuario pide cambios en detectors, strategies, risk, brokers, timeframes, o backtest. Navega al directorio algoict-engine/ y trabaja con Python. Siempre corre tests despues de cada cambio."
argument-hint: "[detector|strategy|risk|broker|backtest|timeframe]"
user-invocable: true
allowed-tools: Read, Write, Bash
---

# Python Engine Skill

## Cuando se activa
- Cualquier trabajo en el motor de trading Python
- Cambios en detectores ICT (swing points, FVG, OB, market structure, liquidity, displacement)
- Cambios en estrategias (NY AM Reversal, Silver Bullet, Swing HTF)
- Cambios en risk management (position sizer, kill switch, profit cap, Topstep compliance)
- Cambios en brokers (TopstepX, Alpaca)
- Cambios en timeframe management
- Cualquier referencia a "el motor", "el engine", "el bot", "los detectores"

## Directorio de trabajo
```bash
cd algoict-engine/
```

Siempre verificar que estas en este directorio antes de ejecutar cualquier comando Python.

## Regla de Oro: Tests After Every Change

**NUNCA hacer commit sin correr tests:**
```bash
python -m pytest tests/ -v
```

Si algun test falla:
1. Arreglar el codigo
2. Correr tests de nuevo
3. Solo cuando TODOS pasen → commit

## Estructura del Engine

```
algoict-engine/
├── main.py                     # Entry point (NO TOCAR hasta que backtest pase)
├── config.py                   # Constantes — el unico archivo de configuracion
│
├── timeframes/                 # Aggregacion y analisis multi-TF
│   ├── tf_manager.py           # 1min → 5/15/60/240/D/W
│   ├── htf_bias.py             # Weekly/Daily bias
│   └── session_manager.py      # Kill Zones, Asian range, London bias
│
├── detectors/                  # ICT pattern detection (core)
│   ├── swing_points.py         # Swing H/L
│   ├── market_structure.py     # BOS, CHoCH, MSS
│   ├── fair_value_gap.py       # FVG
│   ├── order_block.py          # OB
│   ├── liquidity.py            # BSL/SSL, PDH/PDL, equal levels
│   ├── displacement.py         # Displacement candles
│   └── confluence.py           # Multi-TF scoring (0-14)
│
├── strategies/                 # Trading strategies
│   ├── ny_am_reversal.py       # 1:3 RR, 5min entry
│   ├── silver_bullet.py        # 1:2 RR, 1min entry
│   └── swing_htf.py            # 1:2 RR, 4H entry
│
├── risk/                       # Risk management (HARDCODED)
│   ├── position_sizer.py       # floor() + expand stop
│   ├── risk_manager.py         # Kill switch, profit cap
│   └── topstep_compliance.py   # MLL, DLL, limits
│
├── backtest/                   # Backtesting system
├── agents/                     # AI agents (post-mortem)
├── core/                       # Heartbeat
├── alerts/                     # Telegram
├── db/                         # Supabase client
└── tests/                      # pytest unit tests
```

## Patron de Desarrollo para Detectores

Cada detector sigue el mismo patron:

```python
# detectors/fair_value_gap.py
import pandas as pd
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class FVG:
    """Represents a Fair Value Gap."""
    top: float              # Upper boundary
    bottom: float           # Lower boundary
    direction: str          # 'bullish' | 'bearish'
    timeframe: str          # '5min' | '15min' | 'daily'
    candle_index: int       # Index of middle candle
    timestamp: pd.Timestamp
    mitigated: bool = False
    mitigated_pct: float = 0.0

class FairValueGapDetector:
    """Detects Fair Value Gaps across multiple timeframes."""
    
    def __init__(self, timeframes: List[str] = ['5min', '15min', 'daily']):
        self.timeframes = timeframes
        self.active_fvgs: List[FVG] = []
    
    def detect(self, candles: pd.DataFrame, timeframe: str) -> List[FVG]:
        """Scan candles for new FVGs."""
        # Implementation...
        pass
    
    def update_mitigation(self, current_price: float) -> None:
        """Check if any active FVGs have been mitigated."""
        pass
    
    def get_active(self, timeframe: str = None) -> List[FVG]:
        """Return unmitigated FVGs, optionally filtered by TF."""
        pass
```

### Reglas de implementacion:
1. **Dataclass para cada concepto ICT** — typed, serializable
2. **Un detector por concepto** — no mezclar FVG con OB
3. **Multi-TF aware** — cada detector acepta `timeframe` parameter
4. **Active tracking** — cada detector mantiene lista de levels/zones activos
5. **Mitigation tracking** — saber cuando un nivel ya fue "usado"

## Patron de Desarrollo para Strategies

```python
# strategies/ny_am_reversal.py
class NYAMReversalStrategy:
    """ICT 2022 Model — NY AM Session Reversal."""
    
    KILL_ZONE_START = "08:30"  # EST
    KILL_ZONE_END = "11:00"    # EST
    MIN_CONFLUENCE = 7
    RISK_REWARD = 3.0
    MAX_TRADES_PER_SESSION = 2
    
    def __init__(self, detectors: dict, risk_manager, session_manager):
        self.detectors = detectors
        self.risk = risk_manager
        self.session = session_manager
        self.trades_today = 0
    
    def evaluate(self, candles_5min, candles_15min, htf_bias) -> Optional[Signal]:
        """
        Main evaluation loop. Called on every new 5min candle.
        Returns Signal if setup found, None otherwise.
        """
        # 1. Check pre-conditions
        if not self.session.is_kill_zone('ny_am'):
            return None
        if self.trades_today >= self.MAX_TRADES_PER_SESSION:
            return None
        if self.risk.kill_switch_triggered:
            return None
        if self.risk.profit_cap_triggered:
            return None
        
        # 2. Check HTF alignment
        if htf_bias.direction == 'neutral':
            return None
        
        # 3. Run detectors on 15min
        structure_15 = self.detectors['structure'].get_state('15min')
        
        # 4. Run detectors on 5min
        fvgs = self.detectors['fvg'].get_active('5min')
        obs = self.detectors['ob'].get_active('5min')
        sweep = self.detectors['liquidity'].check_grab(candles_5min)
        
        # 5. Score confluence
        score = self.detectors['confluence'].score(
            sweep=sweep, fvgs=fvgs, obs=obs,
            structure=structure_15, htf_bias=htf_bias,
            kill_zone='ny_am'
        )
        
        if score < self.MIN_CONFLUENCE:
            return None
        
        # 6. Build signal
        return self._build_signal(sweep, fvgs, obs, score, htf_bias)
```

## Risk Manager — NUNCA modificar estas constantes

```python
# risk/risk_manager.py — HARDCODED VALUES
MAX_RISK_PER_TRADE = 250        # Dolares, 0.5% de $50K
KILL_SWITCH_LOSSES = 3          # Losses consecutivos
KILL_SWITCH_AMOUNT = 750        # 3 × $250
DAILY_PROFIT_CAP = 1500         # Consistency target
HARD_CLOSE_CT = "15:00"         # 3:00 PM CT (10 min buffer)
NEWS_BLACKOUT_MINUTES = 15      # Antes y despues de FOMC/NFP/CPI
MAX_TRADES_MNQ = 3              # 2 NY AM + 1 Silver Bullet
MNQ_POINT_VALUE = 2.0           # $2 por punto MNQ
MAX_CONTRACTS_TOPSTEPX = 50     # 5 mini × 10:1 ratio
```

**Si necesitas cambiar algo de risk:** documentarlo en `.claude/memory/feedback/` explicando POR QUE, y correr backtest completo con los nuevos parametros antes de aplicar.

## Tests — Estructura

Cada detector tiene su test file con datos historicos conocidos:

```python
# tests/test_fvg.py
def test_bullish_fvg_detected():
    """Known bullish FVG: candle[0].high < candle[2].low"""
    candles = pd.DataFrame({
        'high':  [100, 108, 105],
        'low':   [95,  97,  102],
        'open':  [96,  100, 103],
        'close': [99,  107, 104],
    })
    detector = FairValueGapDetector()
    fvgs = detector.detect(candles, '5min')
    assert len(fvgs) == 1
    assert fvgs[0].direction == 'bullish'
    assert fvgs[0].top == 102  # candle[2].low
    assert fvgs[0].bottom == 100  # candle[0].high

def test_fvg_mitigation():
    """FVG mitigated when price fills 50%+"""
    # ...

def test_no_fvg_when_overlapping():
    """No FVG when candle[0].high >= candle[2].low"""
    # ...
```

## Workflow para nuevos features

1. Escribir el test PRIMERO (TDD)
2. Implementar el detector/strategy
3. Correr `python -m pytest tests/ -v`
4. Si pasa → correr backtest para ver impacto
5. Si backtest mejora → commit + actualizar memoria
6. Si backtest empeora → revertir

## Comandos frecuentes

```bash
# Tests
python -m pytest tests/ -v
python -m pytest tests/test_fvg.py -v  # Solo un test

# Backtest rapido
python -m backtest.backtester --strategy ny_am_reversal --data ../data/mnq_1min.csv --start 2024-06-01 --end 2024-12-31

# Backtest completo
python -m backtest.backtester --strategy ny_am_reversal --data ../data/mnq_1min.csv --start 2023-01-01

# Combine Simulator
python -m backtest.combine_simulator --data ../data/mnq_1min.csv --start 2024-01-01 --end 2024-12-31

# Paper trading
python main.py --mode paper

# Lint
python -m flake8 --max-line-length 120
```
