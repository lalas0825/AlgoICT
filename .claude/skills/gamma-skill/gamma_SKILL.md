---
name: gamma
description: "Skill para el modulo GEX-Guided ICT. Integra Gamma Exposure (GEX) del mercado de opciones de NQ como capa adicional de confluencia para el trading de MNQ futures. Detecta call walls, put walls, gamma flip, y regimen de volatilidad. Activa cuando el usuario menciona gamma, GEX, opciones, call wall, put wall, dealer, hedging, pinning, o volatility regime."
argument-hint: "[scan | levels | regime | overlay]"
user-invocable: true
allowed-tools: Read, Write, Bash
---

# GEX-Guided ICT — The Proprietary Edge

> *"ICT ve donde esta la liquidez. GEX ve donde los dealers ESTAN OBLIGADOS a actuar. Juntos, ven el mapa completo."*

## Por Que Existe Este Modulo

Los bots ICT operan en MNQ pero son ciegos a las fuerzas que REALMENTE mueven el precio: los dealers de opciones hedgeando sus posiciones comprando y vendiendo FUTUROS NQ. Cuando miles de contratos de opciones se concentran en un strike, los market makers estan FORZADOS a comprar o vender futuros en ese nivel. Esto crea soportes, resistencias, y regimenes de volatilidad INVISIBLES para el price action.

**El flow:**
```
Opciones NQ en CME (calls, puts, open interest)
        │
        ▼
Dealer necesita mantener delta-neutral
        │
        ▼
Compra/vende FUTUROS NQ para hedgear
        │
        ▼
El precio de MNQ se mueve ← ESTO operamos nosotros
```

**GEX-Guided ICT fusiona:**
- La PRECISION de ICT (FVG, OB, MSS) para entries exactos
- La INTELIGENCIA de GEX para saber DONDE los dealers van a actuar
- Resultado: confluencia que integra fuerzas ESTRUCTURALES del mercado

## Conceptos Clave

### Gamma Exposure (GEX)
Medida agregada de cuanto gamma tienen los dealers en cada strike. Cuando GEX es alto en un nivel, los dealers hedgean agresivamente ahi, creando un "iman" de precio.

### Call Wall
Strike con la mayor concentracion de calls abiertos. Actua como RESISTENCIA porque los dealers que vendieron esas calls deben VENDER futuros cuando el precio sube hacia el strike.

### Put Wall
Strike con la mayor concentracion de puts abiertos. Actua como SOPORTE porque los dealers que vendieron esos puts deben COMPRAR futuros cuando el precio baja hacia el strike.

### Gamma Flip
El nivel de precio donde GEX cambia de positivo a negativo. Por ENCIMA del flip = gamma positiva (mercado estable, mean-reversion). Por DEBAJO = gamma negativa (volatilidad amplificada, momentum).

### Positive Gamma Environment
Dealers hedgean CONTRA el movimiento (compran en dips, venden en rallies). Resultado: volatilidad comprimida, rangos estrechos, precio tiende a "pinning" en strikes de alta GEX. IDEAL para Silver Bullet scalps.

### Negative Gamma Environment
Dealers hedgean EN LA DIRECCION del movimiento (venden en caidas, compran en subidas). Resultado: volatilidad amplificada, movimientos explosivos, cascadas. IDEAL para NY AM Reversal con targets amplios.

## Como Se Integra con ICT

### 1. GEX Levels como Liquidity Levels
ICT marca BSL/SSL, PDH/PDL, equal highs/lows. GEX agrega:
- Call Wall = resistencia estructural (dealers FORZADOS a vender)
- Put Wall = soporte estructural (dealers FORZADOS a comprar)
- High GEX strikes = zonas de "pinning" donde el precio se pega

**En el Confluence Scorer:**
Si un nivel ICT (FVG, OB, liquidity pool) coincide con un GEX wall → +2 puntos BONUS.

### 2. Gamma Regime como Filtro de Estrategia
Pre-market, el bot determina el gamma regime:
- **Positive Gamma** → priorizar Silver Bullet (scalp, rangos estrechos)
- **Negative Gamma** → priorizar NY AM Reversal (tendencia, targets amplios)
- **Near Gamma Flip** → reducir position size, mercado puede explotar en cualquier direccion

### 3. GEX Wall como Target Refinado
En vez de solo PDH/PDL como target, el bot puede:
- TP1 = siguiente GEX wall (call wall para shorts, put wall para longs)
- Estos son niveles donde los dealers LITERALMENTE paran el precio
- Mas fiable que PDH/PDL solo

### 4. Gamma Flip como Confirmacion de MSS
Si el precio rompe el Gamma Flip level Y hay un MSS de ICT:
- Los dealers empiezan a hedgear EN la direccion del break (amplificando)
- La estructura de ICT confirma el cambio
- Confluencia MAXIMA: estructura + dealers empujando juntos

## Arquitectura

```
PRE-MARKET (5:30 AM EST)
│
├── Fetch NQ Options Data
│   ├── Open Interest por strike (calls + puts)
│   ├── 0DTE + weeklies + monthlies
│   └── SOURCE: CBOE delayed data (free) o SpotGamma/MenthorQ API
│
├── Calculate GEX Levels
│   ├── Net GEX per strike = gamma × OI × 100 × spot²  × 0.01
│   ├── Call Wall = strike con max call GEX
│   ├── Put Wall = strike con max put GEX
│   ├── Gamma Flip = nivel donde net GEX cruza de + a -
│   └── High GEX zones = strikes con GEX > 1 std dev
│
├── Determine Gamma Regime
│   ├── Current price vs Gamma Flip → positive or negative
│   ├── Magnitude of total GEX → how strong is the regime
│   └── OUTPUT: regime, strength, key_levels[]
│
└── Generate GEX Overlay
    ├── Call Wall level → mark on chart as resistance
    ├── Put Wall level → mark on chart as support
    ├── Gamma Flip level → mark as regime boundary
    ├── High GEX zones → mark as "sticky" price areas
    └── OUTPUT → gex_levels{} para confluence scorer + risk manager

DURING TRADING (cada 30 min update)
│
├── Monitor price vs GEX levels
│   ├── Approaching Call Wall? → prepare for rejection or breakout
│   ├── Approaching Put Wall? → prepare for bounce or breakdown
│   ├── Crossing Gamma Flip? → regime change alert
│   └── OUTPUT → dynamic level updates
│
└── Adjust Confluence Scoring
    ├── ICT level + GEX level alignment → bonus points
    ├── Gamma regime → strategy priority adjustment
    └── OUTPUT → modified confluence score
```

## Implementacion

### Estructura de archivos
```
algoict-engine/
├── gamma/
│   ├── gex_engine.py           # Motor principal GEX
│   ├── options_data.py         # Fetch NQ options OI data
│   ├── gex_calculator.py       # Calcula GEX por strike, call/put walls, flip
│   ├── regime_detector.py      # Positive vs negative gamma regime
│   ├── gex_overlay.py          # Genera levels para chart + confluence
│   └── gex_confluence.py       # Integra GEX con ICT confluence scorer
│
└── tests/
    ├── test_gex_calculator.py  # Test calculo GEX con datos conocidos
    ├── test_regime_detector.py # Test positive/negative regime detection
    └── test_gex_confluence.py  # Test bonus scoring cuando ICT + GEX alinean
```

### GEX Calculator — Core Math

```python
# gamma/gex_calculator.py
import numpy as np
from scipy.stats import norm
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class GEXLevel:
    """A significant gamma exposure level."""
    strike: float
    net_gex: float          # Positive = stabilizing, Negative = amplifying
    call_gex: float
    put_gex: float
    level_type: str         # 'call_wall' | 'put_wall' | 'gamma_flip' | 'high_gex'
    
@dataclass
class GammaRegime:
    """Current gamma environment."""
    regime: str             # 'positive' | 'negative' | 'neutral'
    gamma_flip: float       # Price level where regime changes
    call_wall: float        # Highest call GEX strike (resistance)
    put_wall: float         # Highest put GEX strike (support)
    total_gex: float        # Net GEX of entire market
    strength: str           # 'weak' | 'moderate' | 'strong'
    high_gex_zones: List[float]  # Strikes with above-average GEX

class GEXCalculator:
    """
    Calculates Gamma Exposure from NQ options open interest.
    Uses Black-Scholes gamma + OI to determine dealer exposure.
    """
    
    def __init__(self, risk_free_rate: float = 0.05):
        self.rf = risk_free_rate
    
    def calculate_gex(
        self,
        spot: float,
        strikes: np.ndarray,
        call_oi: np.ndarray,
        put_oi: np.ndarray,
        days_to_expiry: np.ndarray,
        implied_vol: np.ndarray,
    ) -> GammaRegime:
        """
        Calculate GEX for all strikes and determine regime.
        
        GEX formula (per strike):
        Call GEX = gamma × call_OI × 100 × spot² × 0.01
        Put GEX = gamma × put_OI × 100 × spot² × 0.01 × -1
        Net GEX = Call GEX + Put GEX
        
        Assumptions (standard):
        - Dealers are LONG calls (investors sell calls for income)
        - Dealers are SHORT puts (investors buy puts for protection)
        - So: call GEX is positive (dealers sell on rally = stabilizing)
        - And: put GEX is negative (dealers sell on dip = amplifying)
        """
        
        # Calculate Black-Scholes gamma for each strike
        T = days_to_expiry / 365.0
        T = np.maximum(T, 1/365)  # Min 1 day to avoid division by zero
        
        d1 = (np.log(spot / strikes) + (self.rf + 0.5 * implied_vol**2) * T) / (implied_vol * np.sqrt(T))
        gamma = norm.pdf(d1) / (spot * implied_vol * np.sqrt(T))
        
        # GEX per strike
        multiplier = 100 * spot**2 * 0.01  # Standard GEX normalization
        call_gex = gamma * call_oi * multiplier
        put_gex = gamma * put_oi * multiplier * -1  # Dealers short puts
        net_gex = call_gex + put_gex
        
        # Find key levels
        call_wall_idx = np.argmax(call_gex)
        put_wall_idx = np.argmin(put_gex)  # Most negative = strongest put wall
        
        # Gamma flip: where net GEX changes sign
        sign_changes = np.where(np.diff(np.sign(net_gex)))[0]
        if len(sign_changes) > 0:
            # Find the flip closest to current spot
            flip_idx = sign_changes[np.argmin(np.abs(strikes[sign_changes] - spot))]
            gamma_flip = (strikes[flip_idx] + strikes[flip_idx + 1]) / 2
        else:
            gamma_flip = spot  # No flip found, use spot
        
        # Determine regime
        total_gex = np.sum(net_gex)
        if spot > gamma_flip:
            regime = 'positive'
        else:
            regime = 'negative'
        
        # Strength based on total GEX magnitude
        gex_std = np.std(net_gex)
        if abs(total_gex) > 2 * gex_std:
            strength = 'strong'
        elif abs(total_gex) > gex_std:
            strength = 'moderate'
        else:
            strength = 'weak'
        
        # High GEX zones
        threshold = np.mean(np.abs(net_gex)) + np.std(np.abs(net_gex))
        high_gex_zones = strikes[np.abs(net_gex) > threshold].tolist()
        
        return GammaRegime(
            regime=regime,
            gamma_flip=gamma_flip,
            call_wall=strikes[call_wall_idx],
            put_wall=strikes[put_wall_idx],
            total_gex=total_gex,
            strength=strength,
            high_gex_zones=high_gex_zones,
        )
```

### GEX × ICT Confluence Integration

```python
# gamma/gex_confluence.py

class GEXConfluenceIntegrator:
    """
    Integrates GEX levels into the ICT confluence scoring system.
    Adds bonus points when ICT and GEX levels align.
    """
    
    ALIGNMENT_THRESHOLD_POINTS = 15  # MNQ points proximity for alignment
    
    def calculate_gex_bonus(
        self,
        signal_price: float,
        signal_direction: str,  # 'long' | 'short'
        target_price: float,
        regime: GammaRegime,
    ) -> dict:
        """
        Calculate bonus confluence points from GEX data.
        
        Returns dict with:
        - gex_bonus_points: 0-3 extra points
        - gex_regime_filter: should this strategy run?
        - gex_target_adjustment: refined target based on GEX walls
        - gex_notes: human-readable explanation
        """
        bonus = 0
        notes = []
        target_adj = target_price
        regime_ok = True
        
        # === 1. ICT Level + GEX Wall Alignment (+2 bonus) ===
        # If entry is near a GEX wall in the right direction
        if signal_direction == 'long':
            # Entry near put wall = strong support from dealers
            if abs(signal_price - regime.put_wall) < self.ALIGNMENT_THRESHOLD_POINTS:
                bonus += 2
                notes.append(f"Entry aligns with Put Wall at {regime.put_wall} (+2)")
            # Target near call wall = natural resistance from dealers
            if abs(target_price - regime.call_wall) < self.ALIGNMENT_THRESHOLD_POINTS * 2:
                target_adj = regime.call_wall
                notes.append(f"Target refined to Call Wall at {regime.call_wall}")
                
        elif signal_direction == 'short':
            # Entry near call wall = strong resistance from dealers
            if abs(signal_price - regime.call_wall) < self.ALIGNMENT_THRESHOLD_POINTS:
                bonus += 2
                notes.append(f"Entry aligns with Call Wall at {regime.call_wall} (+2)")
            # Target near put wall = natural support from dealers
            if abs(target_price - regime.put_wall) < self.ALIGNMENT_THRESHOLD_POINTS * 2:
                target_adj = regime.put_wall
                notes.append(f"Target refined to Put Wall at {regime.put_wall}")
        
        # === 2. Gamma Regime Alignment (+1 bonus) ===
        if regime.regime == 'positive':
            # Stable environment — good for scalps and mean reversion
            if signal_direction in ['long', 'short']:
                bonus += 1
                notes.append(f"Positive gamma regime — stable, mean-reversion favored (+1)")
        elif regime.regime == 'negative':
            # Volatile environment — good for momentum/trend trades
            bonus += 1
            notes.append(f"Negative gamma regime — momentum favored (+1)")
        
        # === 3. Gamma Flip Proximity Warning ===
        flip_distance = abs(signal_price - regime.gamma_flip)
        if flip_distance < self.ALIGNMENT_THRESHOLD_POINTS:
            # Near the flip — high uncertainty zone
            bonus = max(0, bonus - 1)
            notes.append(f"WARNING: Near Gamma Flip ({regime.gamma_flip}) — reduce size")
            regime_ok = False  # Suggest caution
        
        # === 4. Strategy Priority by Regime ===
        strategy_priority = {
            'positive': 'silver_bullet',   # Scalps work in stable gamma
            'negative': 'ny_am_reversal',  # Trend trades in volatile gamma
            'neutral': 'both',
        }
        
        return {
            'gex_bonus_points': min(bonus, 3),  # Cap at 3
            'gex_regime_filter': regime_ok,
            'gex_target_adjustment': target_adj,
            'gex_strategy_priority': strategy_priority.get(regime.regime, 'both'),
            'gex_regime': regime.regime,
            'gex_strength': regime.strength,
            'gex_notes': notes,
        }
```

## Data Sources para NQ GEX

| Source | Data | Cost | Update | Best For |
|--------|------|------|--------|----------|
| **CBOE Delayed** | NQ options OI by strike | Free | End of day (EOD) | Phase A backtest |
| **CME QuikStrike** | NQ options OI + greeks | Free (limited) | EOD | Validation |
| **MenthorQ** | NQ GEX levels pre-calculated | $49/mes | Pre-market + intraday | Phase B live |
| **SpotGamma** | Full GEX model + 0DTE | $99/mes | Real-time | Phase C advanced |
| **Calculate own** | From raw OI + Black-Scholes | Free (code) | EOD (free) or live ($) | Maximum control |

**Recomendacion:** Empezar calculando GEX nosotros mismos con CBOE data (free) para backtest. Luego evaluar MenthorQ ($49/mes) o SpotGamma ($99/mes) para live trading si el backtest prueba valor.

## Updated Confluence Scoring — FINAL (max 18 points)

| Factor | Points | Source |
|--------|--------|--------|
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
| **GEX wall alignment** | **+2** | **GEX (NEW)** |
| **Gamma regime alignment** | **+1** | **GEX (NEW)** |
| **Max total** | **18** | **ICT + SWC + GEX** |

**Scoring tiers:**
- 12+ = MAXIMUM confidence, full position, A+ setup
- 9-11 = HIGH confidence, full position
- 7-8 = STANDARD, proceed with normal size
- < 7 = NO TRADE

## Fases de Implementacion

### Fase A (Week 3, con backtest): Calcular GEX historico
- Descargar NQ options OI historico (CBOE o CME)
- Calcular GEX por strike para cada dia de backtest
- Agregar call wall, put wall, gamma flip como niveles al backtester
- Comparar: trades que coinciden con GEX walls vs trades que no
- Medir: mejora el win rate cuando ICT + GEX se alinean?

### Fase B (Week 6, con paper trading): GEX pre-market scan
- Fetch NQ options OI diario (CBOE free o MenthorQ $49/mes)
- Calcular GEX, call/put walls, gamma flip pre-market
- Integrar GEX levels en confluence scorer
- Determinar gamma regime → ajustar prioridad de estrategia
- Telegram: incluir GEX levels en daily briefing

### Fase C (Week 9+, advanced): Real-time GEX updates
- SpotGamma o MenthorQ real-time data
- Update GEX levels cada 30 min durante trading
- Gamma Flip crossing alerts
- Refinar targets con GEX walls en real-time

## Backtest Validation

Comparar 3 configuraciones:
1. **ICT Pure** (baseline)
2. **ICT + SWC** (sentiment)
3. **ICT + SWC + GEX** (full stack)

Metricas a comparar:
- Win rate en trades alineados con GEX walls vs no alineados
- Drawdown en dias de gamma negativa con/sin regime filter
- Precision de targets: GEX wall target vs PDH/PDL target
- Sharpe ratio improvement

**Si GEX no mejora resultados → desactivar sin remordimiento. Data decides.**

---

*"Los traders de ICT ven las velas. Los traders de opciones ven el gamma. AlgoICT ve AMBOS. Ese es el edge."*
