---
name: toxicity
description: "Skill para el VPIN Toxicity Shield — calcula Volume-Synchronized Probability of Informed Trading directamente de la data de volumen de MNQ. Detecta cuando smart money esta ejecutando agresivamente, valida liquidity grabs de ICT, filtra calidad de Kill Zones, y protege contra flash crashes. Activa cuando el usuario menciona 'toxicity', 'VPIN', 'order flow', 'informed trading', 'flash crash', 'volatility warning', 'session quality', o 'smart money'."
argument-hint: "[scan | status | history | calibrate]"
user-invocable: true
allowed-tools: Read, Write, Bash
---

# VPIN Toxicity Shield — The Storm Detector

> *"VPIN dice CUANDO. ICT dice DONDE. Juntos = timing + precision."*

## Por Que Existe Este Modulo

ICT detecta patrones. SWC lee el sentimiento. GEX ve a los dealers. Pero NINGUNO sabe cuando smart money (hedge funds, instituciones) esta ejecutando ordenes agresivas AHORA MISMO en el book de MNQ. VPIN lo detecta en tiempo real, usando la data de volumen que ya recibimos del WebSocket.

**VPIN mide la "toxicidad" del flujo de ordenes** — que tan probable es que traders informados esten dominando el tape. Cuando VPIN sube, un movimiento violento esta cargandose. No predice direccion — predice MAGNITUD.

**El edge:** Los traders ICT saben donde entrar pero no cuando viene el movimiento real. VPIN dice "el movimiento viene AHORA" + ICT dice "entra AQUI" = timing perfecto.

**Lo mejor:** Se calcula con la data que YA tenemos. Cero costo adicional.

## Cuando Se Activa

- "Como esta la toxicidad?", "VPIN status?", "Hay actividad de smart money?"
- "Es seguro operar ahora?", "Calidad de la sesion?"
- Automaticamente en real-time: corre con cada volume bucket
- Automaticamente como SHIELD: VPIN > 0.70 = CERRAR TODO

## Conceptos Clave

### VPIN (Volume-Synchronized Probability of Informed Trading)
Metrica que mide la probabilidad de que traders informados esten adversamente seleccionando a los market makers. Desarrollada por Easley, Lopez de Prado, y O'Hara (2010). Se calcula en "volume time" — sincronizada con la actividad del mercado, no con el reloj.

### Volume Time vs Clock Time
En vez de medir cada 5 minutos (clock time), VPIN mide cada N contratos operados (volume time). Esto es crucial porque la informacion llega con el volumen, no con el tiempo. 5 minutos de mercado dormido ≠ 5 minutos de mercado activo.

### Bulk Volume Classification (BVC)
Metodo para clasificar cada barra de volumen como "buy" o "sell" sin necesidad de data de Level 2 o tick-by-tick trade direction. Usa la distribucion normal de cambios de precio para estimar la fraccion de compras vs ventas.

### Order Flow Toxicity
Cuando un lado (buyers o sellers informados) domina agresivamente el tape, los market makers pierden dinero en cada trade. Eventualmente se retiran → liquidez desaparece → precio explota. VPIN mide este proceso en tiempo real.

## Niveles de VPIN

| VPIN Range | Estado | Accion del Bot |
|------------|--------|----------------|
| < 0.35 | **Calm** — mercado balanceado | Normal operation |
| 0.35 - 0.45 | **Normal** — actividad tipica | Normal operation |
| 0.45 - 0.55 | **Elevated** — algo de actividad informada | Alerta, tighten stops 10% |
| 0.55 - 0.70 | **High** — smart money activo | Min confluence +1, reduce position 25% |
| > 0.70 | **EXTREME** — toxicidad maxima | **CERRAR TODO. NO OPERAR.** |

## 4 Funciones del Toxicity Shield

### 1. Storm Warning — Alerta de Volatilidad Inminente

VPIN sube de normal a high (>0.55):
- **Si tiene posicion abierta:** Tighten stop al breakeven o cerrar parcial
- **Si NO tiene posicion:** Preparar. Despues del spike, habra FVGs y displacement perfectos
- **Telegram:** "⚠️ VPIN 0.62 — Storm loading. Tightening stops."

VPIN extremo (>0.70):
- **CERRAR TODAS LAS POSICIONES INMEDIATAMENTE**
- **DESACTIVAR TRADING hasta que VPIN baje a <0.55**
- **Telegram:** "🚨 VPIN 0.74 — EXTREME TOXICITY. All positions FLATTENED. Trading HALTED."

### 2. Liquidity Grab Validator — +1 Confluence

ICT detecta un liquidity grab (sweep de BSL/SSL, PDH/PDL, equal highs/lows). Pero fue real?

- **VPIN alto (>0.45) ANTES del sweep:** Los informados estaban acumulando → el sweep es REAL → smart money esta detras → **+1 punto confluence**
- **VPIN bajo (<0.35) durante el sweep:** Solo fue noise, no hay actividad informada → **no bonus**

```python
def validate_liquidity_grab(self, sweep_detected: bool, vpin_at_sweep: float) -> int:
    if sweep_detected and vpin_at_sweep > 0.45:
        return 1  # +1 confluence: VPIN validates the sweep
    return 0
```

### 3. Kill Zone Quality Filter — +1 Confluence

No todas las Kill Zones son iguales. A veces el NY AM abre y no pasa nada.

- **VPIN alto durante Kill Zone (>0.45):** Instituciones activas → setups ICT van a holdear → **+1 punto confluence**
- **VPIN bajo durante Kill Zone (<0.35):** Mercado dormido → FVGs y OBs no van a funcionar → **no bonus, considerar skip**

```python
def assess_kill_zone_quality(self, in_kill_zone: bool, current_vpin: float) -> dict:
    if in_kill_zone and current_vpin > 0.45:
        return {'quality': 'high', 'bonus': 1, 'note': 'Active KZ — institutions present'}
    elif in_kill_zone and current_vpin < 0.35:
        return {'quality': 'low', 'bonus': 0, 'note': 'Dead KZ — consider skipping'}
    return {'quality': 'normal', 'bonus': 0, 'note': 'Standard session'}
```

### 4. Flash Crash Protection

La ultima linea de defensa. Si VPIN alcanza niveles extremos, el mercado puede colapsar en segundos. El kill switch de 3 losses no te protege de un gap de 200 puntos.

```python
def flash_crash_check(self, current_vpin: float) -> bool:
    """Returns True if trading must STOP immediately."""
    if current_vpin > 0.70:
        # FLATTEN EVERYTHING. NOW.
        self.emergency_flatten()
        self.disable_trading()
        self.telegram.send("🚨 VPIN EXTREME — FLASH CRASH PROTECTION ACTIVATED")
        return True
    return False
```

## Arquitectura

```
REAL-TIME (corre con cada volume bucket, ~cada 1-3 minutos durante RTH)
│
├── Volume Bucket Collector
│   ├── Recibe trades del WebSocket de TopstepX
│   ├── Agrupa en buckets de V contratos (V = daily_volume / 50)
│   ├── Cada bucket tiene: total_volume, price_change
│   └── OUTPUT: completed volume bucket
│
├── Bulk Volume Classification
│   ├── Clasifica cada bucket como buy/sell fraction
│   ├── buy_fraction = CDF(price_change / sigma, 0, 1)
│   ├── sell_fraction = 1 - buy_fraction
│   ├── No requiere Level 2 data — usa distribucion normal
│   └── OUTPUT: buy_volume, sell_volume per bucket
│
├── VPIN Calculator
│   ├── Mantiene rolling window de N buckets (N=50 tipico)
│   ├── VPIN = (1/N) × Σ |buy_volume_i - sell_volume_i| / V
│   ├── Rango: 0.0 (perfectamente balanceado) a 1.0 (100% toxico)
│   └── OUTPUT: current_vpin (float 0-1)
│
├── Toxicity Classifier
│   ├── Clasifica VPIN en: calm | normal | elevated | high | extreme
│   ├── Calcula CDF historico para contexto (que tan raro es este nivel)
│   └── OUTPUT: toxicity_level, percentile
│
└── Shield Actions
    ├── Flash Crash Check: VPIN > 0.70 → flatten + halt
    ├── Storm Warning: VPIN > 0.55 → tighten stops, alerts
    ├── Confluence Bonus: validate sweeps + kill zone quality
    └── OUTPUT → risk_manager + confluence_scorer
```

## Implementacion

### Estructura de archivos
```
algoict-engine/
├── toxicity/
│   ├── vpin_engine.py              # Motor principal: orchestrates everything
│   ├── volume_buckets.py           # Volume bucket collector from WebSocket
│   ├── bulk_classifier.py          # Bulk Volume Classification (BVC)
│   ├── vpin_calculator.py          # VPIN rolling calculation
│   ├── toxicity_classifier.py      # Level classification + CDF percentile
│   ├── shield_actions.py           # Flash crash protection + storm warning
│   └── vpin_confluence.py          # +1/+1 bonus for sweep validation + KZ quality
│
└── tests/
    ├── test_volume_buckets.py
    ├── test_bulk_classifier.py
    ├── test_vpin_calculator.py
    └── test_shield_actions.py
```

### VPIN Calculator — Core Math

```python
# toxicity/vpin_calculator.py
import numpy as np
from scipy.stats import norm
from collections import deque
from dataclasses import dataclass

@dataclass
class VPINReading:
    """Single VPIN measurement."""
    vpin: float               # 0.0 to 1.0
    toxicity: str             # calm | normal | elevated | high | extreme
    percentile: float         # Historical CDF percentile (0-100)
    timestamp: float
    bucket_count: int         # How many buckets in the window

class VPINCalculator:
    """
    Volume-Synchronized Probability of Informed Trading.
    
    Based on Easley, Lopez de Prado, O'Hara (2010).
    Uses Bulk Volume Classification (no Level 2 needed).
    Calculates from standard OHLCV data via WebSocket.
    """
    
    NUM_BUCKETS = 50          # Standard: 50 buckets per window
    
    def __init__(self, daily_volume: int = 500_000):
        """
        Args:
            daily_volume: Expected daily volume for MNQ.
                         Used to calculate bucket size.
                         V = daily_volume / NUM_BUCKETS
        """
        self.bucket_size = daily_volume // self.NUM_BUCKETS
        self.buckets = deque(maxlen=self.NUM_BUCKETS)
        self.vpin_history = deque(maxlen=1000)  # For CDF/percentile
        self._sigma = None  # Rolling price change std
    
    def add_trade(self, price: float, volume: int, timestamp: float):
        """
        Called for every trade received from WebSocket.
        Accumulates into volume buckets. When a bucket fills,
        classifies it and recalculates VPIN.
        """
        self._current_bucket_volume += volume
        self._current_bucket_prices.append(price)
        
        if self._current_bucket_volume >= self.bucket_size:
            # Bucket complete — classify and calculate
            bucket = self._finalize_bucket()
            self.buckets.append(bucket)
            
            if len(self.buckets) >= self.NUM_BUCKETS:
                return self._calculate_vpin()
        
        return None  # Not enough data yet
    
    def _finalize_bucket(self) -> dict:
        """Classify completed bucket using BVC."""
        prices = self._current_bucket_prices
        price_change = prices[-1] - prices[0]
        
        # Update rolling sigma
        if self._sigma is None:
            self._sigma = abs(price_change) + 0.01  # Initial estimate
        else:
            self._sigma = 0.95 * self._sigma + 0.05 * abs(price_change)  # EMA
        
        # Bulk Volume Classification
        # buy_fraction = CDF(price_change / sigma)
        z = price_change / self._sigma if self._sigma > 0 else 0
        buy_fraction = norm.cdf(z)
        sell_fraction = 1 - buy_fraction
        
        total_v = self._current_bucket_volume
        buy_volume = total_v * buy_fraction
        sell_volume = total_v * sell_fraction
        
        # Reset for next bucket
        self._current_bucket_volume = 0
        self._current_bucket_prices = []
        
        return {
            'buy_volume': buy_volume,
            'sell_volume': sell_volume,
            'imbalance': abs(buy_volume - sell_volume),
            'total_volume': total_v,
        }
    
    def _calculate_vpin(self) -> VPINReading:
        """
        VPIN = (1/N) × Σ |V_buy_i - V_sell_i| / V
        
        Where:
        - N = number of buckets (50)
        - V = bucket size
        - V_buy_i, V_sell_i = classified buy/sell volume per bucket
        """
        imbalances = [b['imbalance'] for b in self.buckets]
        vpin = sum(imbalances) / (self.NUM_BUCKETS * self.bucket_size)
        vpin = min(max(vpin, 0.0), 1.0)  # Clamp
        
        # Classify
        if vpin > 0.70:
            toxicity = 'extreme'
        elif vpin > 0.55:
            toxicity = 'high'
        elif vpin > 0.45:
            toxicity = 'elevated'
        elif vpin > 0.35:
            toxicity = 'normal'
        else:
            toxicity = 'calm'
        
        # Historical percentile
        self.vpin_history.append(vpin)
        if len(self.vpin_history) > 100:
            sorted_h = sorted(self.vpin_history)
            percentile = (sorted_h.index(vpin) / len(sorted_h)) * 100
        else:
            percentile = 50.0  # Not enough history
        
        return VPINReading(
            vpin=vpin,
            toxicity=toxicity,
            percentile=percentile,
            timestamp=time.time(),
            bucket_count=len(self.buckets),
        )
```

### Shield Actions — Protection Layer

```python
# toxicity/shield_actions.py

class ToxicityShield:
    """
    The last line of defense.
    Overrides everything else when toxicity is extreme.
    """
    
    EXTREME_THRESHOLD = 0.70    # Flatten everything
    HIGH_THRESHOLD = 0.55       # Tighten stops, reduce size
    ELEVATED_THRESHOLD = 0.45   # Alert, minor adjustments
    RECOVERY_THRESHOLD = 0.55   # Must drop below to re-enable trading
    
    def __init__(self, risk_manager, telegram, supabase):
        self.risk = risk_manager
        self.tg = telegram
        self.db = supabase
        self.trading_halted = False
    
    async def on_vpin_update(self, reading: VPINReading):
        """Called every time VPIN is recalculated (every volume bucket)."""
        
        # === EXTREME: FLATTEN AND HALT ===
        if reading.vpin > self.EXTREME_THRESHOLD:
            if not self.trading_halted:
                await self.risk.emergency_flatten()
                self.trading_halted = True
                await self.tg.send(
                    f"🚨 *FLASH CRASH PROTECTION*\n"
                    f"VPIN: {reading.vpin:.3f} (EXTREME)\n"
                    f"Percentile: {reading.percentile:.0f}%\n"
                    f"ALL POSITIONS FLATTENED\n"
                    f"TRADING HALTED until VPIN < {self.RECOVERY_THRESHOLD}"
                )
                await self.db.table('bot_state').update({
                    'is_running': False,
                    'halt_reason': f'VPIN extreme: {reading.vpin:.3f}',
                }).execute()
            return
        
        # === Recovery check ===
        if self.trading_halted and reading.vpin < self.RECOVERY_THRESHOLD:
            self.trading_halted = False
            await self.tg.send(
                f"✅ VPIN recovered to {reading.vpin:.3f}\n"
                f"Trading RE-ENABLED"
            )
            await self.db.table('bot_state').update({
                'is_running': True,
                'halt_reason': None,
            }).execute()
        
        # === HIGH: Tighten + reduce ===
        if reading.vpin > self.HIGH_THRESHOLD:
            self.risk.set_vpin_overrides(
                min_confluence_adjustment=+1,   # Raise bar by 1
                position_multiplier=0.75,       # 75% size
                stop_tighten_pct=0.10,          # Tighten stops 10%
            )
            if reading.vpin > 0.60:
                await self.tg.send(
                    f"⚠️ VPIN {reading.vpin:.3f} — Storm warning\n"
                    f"Stops tightened. Size reduced to 75%."
                )
        
        # === ELEVATED: Minor alert ===
        elif reading.vpin > self.ELEVATED_THRESHOLD:
            self.risk.set_vpin_overrides(
                min_confluence_adjustment=0,
                position_multiplier=1.0,
                stop_tighten_pct=0.0,
            )
        
        # === CALM/NORMAL: Reset ===
        else:
            self.risk.clear_vpin_overrides()
```

### VPIN Confluence Integration

```python
# toxicity/vpin_confluence.py

class VPINConfluenceIntegrator:
    """
    Integrates VPIN into ICT confluence scoring.
    Two bonus points possible:
    +1 for validated liquidity grab (VPIN high during sweep)
    +1 for high-quality Kill Zone (VPIN elevated during KZ)
    """
    
    def calculate_vpin_bonus(
        self,
        current_vpin: float,
        sweep_detected: bool,
        in_kill_zone: bool,
    ) -> dict:
        bonus = 0
        notes = []
        
        # 1. Validated Sweep (+1)
        if sweep_detected and current_vpin > 0.45:
            bonus += 1
            notes.append(f"VPIN {current_vpin:.2f} validates sweep — smart money behind it (+1)")
        elif sweep_detected and current_vpin < 0.35:
            notes.append(f"VPIN {current_vpin:.2f} low during sweep — likely noise, no bonus")
        
        # 2. Kill Zone Quality (+1)
        if in_kill_zone and current_vpin > 0.45:
            bonus += 1
            notes.append(f"Active Kill Zone — VPIN {current_vpin:.2f} confirms institutional presence (+1)")
        elif in_kill_zone and current_vpin < 0.35:
            notes.append(f"Dead Kill Zone — VPIN {current_vpin:.2f}, consider skipping")
        
        return {
            'vpin_bonus_points': min(bonus, 2),
            'vpin_value': current_vpin,
            'vpin_notes': notes,
        }
```

## Updated Confluence Scoring — FINAL FINAL (max 20 pts)

| Factor | Pts | Source |
|--------|-----|--------|
| Liquidity grab | +2 | ICT |
| Fair Value Gap | +2 | ICT |
| Order Block | +2 | ICT |
| Market Structure Shift | +2 | ICT |
| Kill Zone | +1 | Time |
| OTE Fibonacci | +1 | ICT |
| HTF bias | +1 | ICT HTF |
| HTF OB/FVG alignment | +1 | ICT HTF |
| PDH/PDL target | +1 | ICT |
| Sentiment alignment | +1 | SWC |
| GEX wall alignment | +2 | GEX |
| Gamma regime | +1 | GEX |
| **VPIN validated sweep** | **+1** | **VPIN (NEW)** |
| **VPIN quality session** | **+1** | **VPIN (NEW)** |
| **Max** | **20** | **ICT+SWC+GEX+VPIN** |

**Tiers:** 12+ = A+ | 9-11 = high | 7-8 = standard | <7 = NO TRADE

## Integration en main.py

```python
# In the main trading loop:

# 1. Every trade from WebSocket feeds VPIN
async def on_trade(price, volume, timestamp):
    reading = vpin_calculator.add_trade(price, volume, timestamp)
    if reading:
        # Update shield
        await toxicity_shield.on_vpin_update(reading)
        
        # Update dashboard
        await supabase.table('bot_state').update({
            'current_vpin': reading.vpin,
            'vpin_toxicity': reading.toxicity,
        }).execute()

# 2. Before executing any trade:
def pre_trade_check(signal):
    if toxicity_shield.trading_halted:
        return None  # BLOCKED by VPIN shield
    
    # Add VPIN bonus to confluence
    vpin_bonus = vpin_confluence.calculate_vpin_bonus(
        current_vpin=vpin_calculator.latest.vpin,
        sweep_detected=signal.has_sweep,
        in_kill_zone=session_manager.is_kill_zone(),
    )
    signal.confluence_score += vpin_bonus['vpin_bonus_points']
    
    return signal
```

## Dashboard Integration

```
Dashboard components:
├── VPINGauge.tsx          # Circular gauge: 0-1 with color zones
├── ToxicityTimeline.tsx   # VPIN over time, color-coded
└── ShieldStatus.tsx       # "ACTIVE" / "HALTED" badge with reason
```

## Data Source

**Costo: $0 adicional.**

VPIN se calcula directamente del stream de trades de MNQ que ya recibimos del WebSocket de TopstepX. No necesita API adicional, data adicional, ni suscripcion nueva. Solo necesita el volumen y precio de cada trade.

Para backtest: se calcula de la data historica de 1min que ya tenemos (FirstRateData). No es exactamente igual a tick-by-tick, pero la aproximacion con barras de 1min es suficiente para validar el concepto.

## Backtest del VPIN Shield

Comparar:
1. **Sin VPIN:** Cuantos trades se ejecutaron durante periodos de VPIN extremo? Cuanto perdieron?
2. **Con VPIN Shield:** Cuantos de esos trades se habrian evitado? Cuanto se habria ahorrado?
3. **VPIN Confluence:** Trades con VPIN bonus vs sin bonus — diferencia en win rate?

Si VPIN Shield previene aunque sea 1 loss catastrofico de $500+ → se paga solo para siempre.

## Fases

| Cuando | Que |
|--------|-----|
| Phase 1 (Week 3) | Build calculators, test with historical data, backtest VPIN levels |
| Phase 2 (Week 6) | Connect to live WebSocket, real-time VPIN, shield active |
| Phase 3 (Week 9) | Dashboard: VPINGauge, ToxicityTimeline, ShieldStatus |

---

*Toxicity Shield — "VPIN dice cuando la bomba va a explotar. ICT dice donde refugiarse. Juntos, sobrevives y ganas."*
