---
name: strategy-lab
description: "Skill para el Strategy Lab — agente AI que genera hipotesis de trading basadas en ICT, las valida con un pipeline anti-overfitting de 5 capas, y produce estrategias candidatas para revision humana. NO es un optimizador ciego. Es un investigador con tesis fundamentada. Activa cuando el usuario menciona 'strategy lab', 'genera estrategia', 'descubre patrones', 'optimiza', 'encuentra edge', o 'que patrones hay'."
argument-hint: "[generate | validate | candidates | report | status]"
user-invocable: true
allowed-tools: Read, Write, Bash
---

# Strategy Lab — El Investigador que Genera Estrategias

> *"No busca la mejor curva. Busca POR QUE algo funciona y luego verifica si la data lo confirma."*

## Por Que es Diferente a Todo lo Demas

La mayoria de los "AI trading bots" hacen esto:
```
Probar 10,000 combinaciones → seleccionar la mejor → overfitting → perder dinero
```

Strategy Lab hace esto:
```
Claude RAZONA en lenguaje ICT → genera HIPOTESIS con logica fundamental
→ 5 capas anti-overfitting matan falsos positivos → humano valida al final
```

**La diferencia clave:** El agente no busca patrones en datos crudos. PIENSA en ICT y genera hipotesis que tienen RAZON de ser. Luego la data confirma o rechaza. Si 1,000 traders pusieran a un ML a optimizar, 999 encontrarian ruido. Nosotros encontramos MECANISMOS REALES del mercado.

## Cuando Se Activa

- "Strategy Lab, genera hipotesis", "Que patrones hay en mis backtests?"
- "Descubre algo nuevo", "Encuentra un edge", "Optimiza la estrategia"
- "Muestra candidatas", "Que hipotesis han pasado?"
- Puede correr como batch overnight: genera 10 hipotesis, valida todas, reporta al amanecer

## Regla Absoluta

> **El Strategy Lab NUNCA aplica cambios al bot en vivo. NUNCA.**
> Solo genera candidatas. Juan las revisa. Juan decide.

---

## Arquitectura

### Data Split — Sacrosanto

```
DATA HISTORICA MNQ/NQ (2019-2025, ~6 anos)
│
├── TRAINING SET (60%) — Anos 2019-2022
│   El agente SOLO ve estos datos para generar hipotesis.
│   Walk-forward validation ocurre DENTRO de este set.
│
├── VALIDATION SET (20%) — Ano 2023
│   Primera vez que la hipotesis ve datos nuevos.
│   Si falla aqui → descartada (era overfitting al training).
│
└── TEST SET (20%) — Anos 2024-2025 — INTOCABLE
    NUNCA se usa durante desarrollo de hipotesis.
    Solo se usa UNA VEZ cuando Juan aprueba una candidata.
    Si tocas este set durante investigacion → contaminado → inutil.
```

**REGLA:** Si algun codigo intenta leer el Test Set durante generacion/validacion de hipotesis, el sistema BLOQUEA la operacion y lanza error.

### Pipeline de 8 Pasos

```
PASO 1: GENERAR HIPOTESIS (Claude API)
│   Claude recibe: ICT concepts + backtest stats + loss patterns + post-mortems
│   Claude genera: hipotesis en lenguaje ICT con logica fundamental
│   Ejemplo: "Los FVGs de 15min que estan DENTRO de un OB semanal
│            tienen mayor probabilidad de holdear vs FVGs aislados"
│
│   FILTRO: La hipotesis debe tener RAZON FUNDAMENTAL en ICT.
│   Si es una combinacion arbitraria de numeros → rechazada antes de backtest.
│
▼
PASO 2: BACKTEST EN TRAINING SET (2019-2022)
│   Corre la hipotesis como modificacion de la estrategia existente.
│   Compara vs BASELINE (estrategia original sin la hipotesis).
│
│   GATE 1: Sharpe ratio mejora >= 0.1? NO → descartada.
│   GATE 2: Win rate NO empeora mas de 2%? NO → descartada.
│   GATE 3: Max drawdown NO aumenta mas de 10%? NO → descartada.
│
▼
PASO 3: WALK-FORWARD VALIDATION (rolling windows en Training)
│   Divide Training en ventanas de 6 meses train + 2 meses test:
│   - Ventana 1: Train Ene-Jun 2019 → Test Jul-Ago 2019
│   - Ventana 2: Train Mar-Ago 2019 → Test Sep-Oct 2019
│   - ... (avanza 2 meses cada vez)
│   - Ventana N: Train Ene-Jun 2022 → Test Jul-Ago 2022
│
│   GATE 4: La hipotesis debe ser POSITIVA en >= 70% de las ventanas.
│   Si solo funciona en algunas ventanas → era overfitting temporal.
│
▼
PASO 4: CROSS-INSTRUMENT VALIDATION
│   Corre la misma hipotesis en ES (S&P 500) y YM (Dow) futures.
│   Los principios ICT son universales — si es real, funciona en todos.
│
│   GATE 5: Funciona en al menos 2 de 3 instrumentos (NQ, ES, YM)?
│   NO → era ruido especifico de NQ → descartada.
│
▼
PASO 5: STRESS TEST (romper la estrategia intencionalmente)
│   5 pruebas de estres:
│   a) Agregar ruido gaussiano a precios (±0.1%)
│   b) Desplazar senales 1 barra adelante y atras
│   c) Remover 10% de datos aleatoriamente
│   d) Duplicar el spread (slippage simulation)
│   e) Invertir la hipotesis (si long → short) — debe PERDER dinero
│
│   GATE 6: Sobrevive a/b/c/d con degradacion < 30%?
│   GATE 7: La version invertida (e) PIERDE dinero? (confirma direccionalidad)
│   Si colapsa o la inversion tambien gana → era aleatorio.
│
▼
PASO 6: OCCAM'S RAZOR CHECK
│   Cuenta parametros nuevos que la hipotesis agrega.
│
│   GATE 8: Agrega maximo 1-2 parametros nuevos?
│   Si la hipotesis necesita 5+ condiciones → probablemente es curve-fitting.
│   Mas simple > mas complejo. Siempre.
│
▼
PASO 7: VALIDATION SET (2023) — Primera vez en datos no vistos
│   Corre la hipotesis en 2023 completo.
│   Este es el momento de verdad.
│
│   GATE 9: Mejora vs baseline en datos NUNCA VISTOS?
│   NO → descartada definitivamente. Era overfitting al Training.
│   SI → CANDIDATA APROBADA.
│
▼
PASO 8: CANDIDATA REGISTRADA
│   Se guarda en .claude/memory/project/strategy-candidates.md
│   Se envia resumen a Telegram.
│   Juan revisa y decide si promover.
│
│   Si Juan aprueba → se corre UNA VEZ en Test Set (2024-2025).
│   Si pasa Test Set → se integra al bot.
│   Si falla Test Set → descartada PERMANENTEMENTE.
│   El Test Set solo se puede usar UNA VEZ por candidata.
```

---

## Estructura de Archivos

```
algoict-engine/
├── strategy_lab/
│   ├── lab_engine.py              # Orquestador del pipeline completo
│   ├── hypothesis_generator.py    # Claude API: genera hipotesis ICT
│   ├── data_splitter.py           # Train/Validation/Test splits (con lock en Test)
│   ├── walk_forward.py            # Rolling window validation
│   ├── cross_instrument.py        # Prueba en NQ, ES, YM
│   ├── stress_tester.py           # Noise, shift, remove, spread, inversion
│   ├── occam_checker.py           # Cuenta parametros, penaliza complejidad
│   ├── candidate_manager.py       # Guarda, rankea, reporta candidatas
│   ├── anti_overfit_gates.py      # Las 9 gates consolidadas
│   └── lab_report.py              # Genera reporte de la sesion
│
└── tests/
    ├── test_data_splitter.py      # Verifica que Test Set esta bloqueado
    ├── test_walk_forward.py       # Verifica rolling windows
    ├── test_stress_tester.py      # Verifica cada tipo de estres
    └── test_anti_overfit.py       # Verifica que gates bloquean correctamente
```

---

## Hypothesis Generator (Claude API)

```python
# strategy_lab/hypothesis_generator.py

class HypothesisGenerator:
    """
    Generates ICT-grounded hypotheses using Claude API.
    NOT random parameter combinations. Reasoned ideas
    based on ICT theory + observed patterns in backtest data.
    """
    
    MODEL = "claude-sonnet-4-20250514"
    
    async def generate(self, context: dict) -> list[Hypothesis]:
        """
        Context includes:
        - Current strategy performance (win rate, Sharpe, drawdown)
        - Post-mortem patterns (top loss categories)
        - ICT concepts reference (from NotebookLM research)
        - Previous hypotheses tested (avoid repeats)
        - Market regime stats (volatile vs calm periods)
        """
        
        prompt = f"""You are a senior ICT quant researcher. Your job is to 
generate TESTABLE trading hypotheses grounded in ICT methodology.

CURRENT STRATEGY PERFORMANCE:
{json.dumps(context['baseline_stats'], indent=2)}

TOP LOSS PATTERNS (from post-mortem):
{json.dumps(context['loss_patterns'], indent=2)}

ICT CONCEPTS AVAILABLE:
{json.dumps(context['ict_concepts'], indent=2)}

PREVIOUSLY TESTED HYPOTHESES (avoid repeats):
{json.dumps(context['previous_hypotheses'][-20:], indent=2)}

RULES FOR GENERATING HYPOTHESES:
1. Each hypothesis MUST have a fundamental ICT reason for why it should work.
   "Because the backtest shows..." is NOT a valid reason.
   "Because institutional order flow creates..." IS a valid reason.

2. Each hypothesis should modify AT MOST 1-2 parameters or add 1 condition.
   NOT "change 5 things at once." ONE thing at a time.

3. Focus on the WEAKEST areas first (highest loss patterns).

4. Think about TIME (when), STRUCTURE (what setup), and CONTEXT (what environment).

5. Each hypothesis must be specific enough to code as a boolean condition.

Generate 3-5 hypotheses. For each one provide:
{{
  "id": "H-XXX",
  "name": "Short descriptive name",
  "ict_reasoning": "WHY this should work based on ICT theory (2-3 sentences)",
  "condition": "Exact boolean condition to add (pseudocode)",
  "parameters_added": 0-2,
  "expected_impact": "What metric should improve and by how much",
  "risk": "What could go wrong / why this might be overfitting"
}}

Respond ONLY with a JSON array."""
        
        response = await self.ai.messages.create(
            model=self.MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        hypotheses = json.loads(response.content[0].text)
        return [Hypothesis(**h) for h in hypotheses]
```

### Ejemplo de Hipotesis Generadas

```json
[
  {
    "id": "H-001",
    "name": "FVG-inside-OB filter",
    "ict_reasoning": "ICT teaches that Order Blocks represent zones where 
     institutions placed large orders. A FVG that forms WITHIN an OB zone 
     has double institutional backing — the OB shows where they bought, 
     and the FVG shows where they left an imbalance. This confluence 
     should produce higher hold rates than isolated FVGs.",
    "condition": "IF entry_fvg.overlaps(active_ob_zone) THEN bonus_score += 1",
    "parameters_added": 0,
    "expected_impact": "Win rate on FVG entries improves 3-5%",
    "risk": "Reduces total trades significantly if OB+FVG overlap is rare"
  },
  {
    "id": "H-002", 
    "name": "Tuesday-Thursday MNQ filter",
    "ict_reasoning": "ICT discusses weekly price delivery cycles. Monday 
     often sets the range (manipulation), Tuesday-Thursday deliver the 
     real move (distribution). Fridays are prone to profit-taking. 
     The NY AM Reversal should have higher probability Tue-Thu when 
     institutional algorithms are most active in price delivery.",
    "condition": "IF day_of_week in [TUESDAY, WEDNESDAY, THURSDAY] THEN allow_trade ELSE skip",
    "parameters_added": 0,
    "expected_impact": "Win rate improves 2-4%, fewer trades but higher quality",
    "risk": "Could be calendar overfitting — need walk-forward to verify"
  },
  {
    "id": "H-003",
    "name": "Negative gamma regime momentum boost",
    "ict_reasoning": "In negative gamma environments, dealer hedging 
     AMPLIFIES directional moves. If the ICT setup direction aligns 
     with the GEX regime pressure, the move should extend further. 
     Increase target from 1:3 to 1:4 in negative gamma + aligned bias.",
    "condition": "IF gamma_regime == NEGATIVE AND trade_direction == gex_pressure_direction THEN target_rr = 4.0",
    "parameters_added": 1,
    "expected_impact": "Average win size increases 15-20% on qualifying trades",
    "risk": "Wider target means more trades hit stop before reaching TP"
  }
]
```

---

## Anti-Overfitting Gates — Los 9 Filtros

```python
# strategy_lab/anti_overfit_gates.py

@dataclass
class GateResult:
    gate_name: str
    passed: bool
    metric: float
    threshold: float
    reason: str

class AntiOverfitGates:
    """
    9 gates that a hypothesis must pass before becoming a candidate.
    Each gate is designed to catch a specific type of false positive.
    """
    
    # Paso 2: Training Set Performance
    MIN_SHARPE_IMPROVEMENT = 0.1        # Gate 1
    MAX_WINRATE_DEGRADATION = 0.02      # Gate 2 (2%)
    MAX_DRAWDOWN_INCREASE = 0.10        # Gate 3 (10%)
    
    # Paso 3: Walk-Forward
    MIN_POSITIVE_WINDOWS = 0.70         # Gate 4 (70% of windows)
    
    # Paso 4: Cross-Instrument
    MIN_INSTRUMENTS_PASSING = 2         # Gate 5 (2 of 3)
    
    # Paso 5: Stress Test
    MAX_NOISE_DEGRADATION = 0.30        # Gate 6 (30% max degradation)
    INVERSION_MUST_LOSE = True          # Gate 7
    
    # Paso 6: Occam's Razor
    MAX_NEW_PARAMETERS = 2              # Gate 8
    
    # Paso 7: Validation Set
    VALIDATION_MUST_IMPROVE = True      # Gate 9
    
    def run_all_gates(self, hypothesis, results) -> list[GateResult]:
        """Run all 9 gates. Returns list of results. ALL must pass."""
        gates = [
            self._gate_1_sharpe(results),
            self._gate_2_winrate(results),
            self._gate_3_drawdown(results),
            self._gate_4_walk_forward(results),
            self._gate_5_cross_instrument(results),
            self._gate_6_noise_resilience(results),
            self._gate_7_inversion(results),
            self._gate_8_complexity(hypothesis),
            self._gate_9_validation(results),
        ]
        return gates
    
    def all_passed(self, gates: list[GateResult]) -> bool:
        return all(g.passed for g in gates)
```

---

## Stress Tester

```python
# strategy_lab/stress_tester.py

class StressTester:
    """
    Intentionally breaks the strategy to see if the edge survives.
    If it doesn't survive noise, it was never real.
    """
    
    def run_all_tests(self, strategy_fn, data, baseline_sharpe):
        results = {}
        
        # a) Gaussian noise on prices (±0.1%)
        noisy_data = self._add_price_noise(data, std=0.001)
        results['noise'] = self._run_and_compare(strategy_fn, noisy_data, baseline_sharpe)
        
        # b) Shift signals ±1 bar (timing sensitivity)
        shifted_fwd = self._shift_signals(data, bars=1)
        shifted_bwd = self._shift_signals(data, bars=-1)
        results['shift_fwd'] = self._run_and_compare(strategy_fn, shifted_fwd, baseline_sharpe)
        results['shift_bwd'] = self._run_and_compare(strategy_fn, shifted_bwd, baseline_sharpe)
        
        # c) Remove 10% of random candles (data gaps)
        sparse_data = self._remove_random(data, pct=0.10)
        results['sparse'] = self._run_and_compare(strategy_fn, sparse_data, baseline_sharpe)
        
        # d) Double the spread (slippage simulation)
        results['slippage'] = self._run_with_extra_slippage(strategy_fn, data, multiplier=2.0)
        
        # e) Inversion test — flip long↔short. Must LOSE money.
        results['inversion'] = self._run_inverted(strategy_fn, data)
        
        return results
```

---

## Walk-Forward Validator

```python
# strategy_lab/walk_forward.py

class WalkForwardValidator:
    """
    Rolling window validation within the Training Set.
    If the hypothesis only works in specific time periods,
    walk-forward kills it.
    """
    
    TRAIN_MONTHS = 6
    TEST_MONTHS = 2
    STEP_MONTHS = 2
    
    def validate(self, strategy_fn, training_data) -> WalkForwardResult:
        windows = self._generate_windows(training_data)
        results = []
        
        for window in windows:
            train_slice = training_data[window.train_start:window.train_end]
            test_slice = training_data[window.test_start:window.test_end]
            
            # "Train" = run baseline on this slice
            baseline = self._run_strategy(strategy_fn, train_slice, use_hypothesis=False)
            
            # "Test" = run with hypothesis on unseen slice
            with_hypothesis = self._run_strategy(strategy_fn, test_slice, use_hypothesis=True)
            
            results.append({
                'window': window,
                'baseline_sharpe': baseline.sharpe,
                'hypothesis_sharpe': with_hypothesis.sharpe,
                'improvement': with_hypothesis.sharpe - baseline.sharpe,
                'positive': with_hypothesis.sharpe > baseline.sharpe,
            })
        
        positive_pct = sum(1 for r in results if r['positive']) / len(results)
        
        return WalkForwardResult(
            windows_tested=len(results),
            windows_positive=sum(1 for r in results if r['positive']),
            positive_percentage=positive_pct,
            passed=positive_pct >= 0.70,  # Gate 4: 70% minimum
            details=results,
        )
```

---

## Data Splitter — Con Test Set Lock

```python
# strategy_lab/data_splitter.py

class DataSplitter:
    """
    Splits data into Train/Validation/Test with a HARD LOCK on Test Set.
    The Test Set cannot be accessed during hypothesis generation/validation.
    """
    
    TRAIN_END = '2022-12-31'
    VALIDATION_END = '2023-12-31'
    # Everything after = Test Set (2024-2025)
    
    def __init__(self, data: pd.DataFrame):
        self.train = data[data.index <= self.TRAIN_END]
        self.validation = data[(data.index > self.TRAIN_END) & (data.index <= self.VALIDATION_END)]
        self._test = data[data.index > self.VALIDATION_END]  # Private!
        self._test_accessed = False
        self._test_lock = True
    
    def get_training(self) -> pd.DataFrame:
        return self.train.copy()
    
    def get_validation(self) -> pd.DataFrame:
        return self.validation.copy()
    
    def get_test(self, authorization_code: str) -> pd.DataFrame:
        """
        Test Set requires explicit authorization.
        Can only be accessed ONCE per hypothesis.
        Logs the access permanently.
        """
        if authorization_code != "JUAN_APPROVED_FINAL_TEST":
            raise PermissionError(
                "TEST SET IS LOCKED. Only Juan can unlock with explicit approval. "
                "This is by design to prevent overfitting."
            )
        if self._test_accessed:
            raise RuntimeError(
                "TEST SET ALREADY ACCESSED FOR THIS HYPOTHESIS. "
                "Cannot access twice — data is now contaminated for this test."
            )
        self._test_accessed = True
        logger.warning("⚠️ TEST SET ACCESSED — This is a one-time event.")
        return self._test.copy()
```

---

## Candidate Manager

```python
# strategy_lab/candidate_manager.py

@dataclass  
class StrategyCandidate:
    hypothesis_id: str
    name: str
    ict_reasoning: str
    condition: str
    parameters_added: int
    
    # Training results
    training_sharpe_improvement: float
    training_winrate_delta: float
    training_drawdown_delta: float
    
    # Walk-forward results
    wf_positive_pct: float
    wf_windows_tested: int
    
    # Cross-instrument results
    instruments_passing: int  # out of 3
    
    # Stress test results
    noise_resilience: float
    inversion_loses: bool
    
    # Validation results (2023)
    validation_sharpe_improvement: float
    validation_passed: bool
    
    # Test Set (only if Juan approved)
    test_result: Optional[float] = None
    
    # Status
    status: str = 'candidate'  # candidate | approved | rejected | integrated
    created_at: str = ''
    
    def summary(self) -> str:
        return (
            f"📊 Candidate: {self.name}\n"
            f"ICT Logic: {self.ict_reasoning[:100]}...\n"
            f"Training Sharpe: +{self.training_sharpe_improvement:.2f}\n"
            f"Walk-Forward: {self.wf_positive_pct:.0%} positive\n"
            f"Cross-Instrument: {self.instruments_passing}/3\n"
            f"Noise Resilience: {self.noise_resilience:.0%}\n"
            f"Validation (2023): {'✅ PASSED' if self.validation_passed else '❌ FAILED'}\n"
            f"Parameters Added: {self.parameters_added}\n"
            f"Status: {self.status}"
        )
```

---

## Lab Session Flow

### Manual: Juan pide "Strategy Lab, genera hipotesis"
```bash
python -m strategy_lab.lab_engine --mode generate --count 5
```
1. Claude genera 5 hipotesis
2. Cada una pasa por los 8 pasos automaticamente
3. Reporte final muestra cuantas sobrevivieron
4. Candidatas se guardan en memoria

### Overnight Batch: Corre mientras Juan duerme
```bash
python -m strategy_lab.lab_engine --mode overnight --count 20
```
1. Genera 20 hipotesis
2. Las valida todas (puede tardar horas)
3. Al amanecer: Telegram con resumen
4. "Lab Session #12: 20 hipotesis → 3 pasaron Gate 1-3 → 1 paso Walk-Forward → 0 candidatas finales"
5. O: "🎯 1 CANDIDATA encontrada: 'FVG-inside-OB filter' — revisa en dashboard"

### Comandos

```bash
# Generar y validar hipotesis
python -m strategy_lab.lab_engine --mode generate --count 5

# Overnight batch
python -m strategy_lab.lab_engine --mode overnight --count 20

# Ver candidatas actuales
python -m strategy_lab.candidate_manager --list

# Ver detalle de una candidata
python -m strategy_lab.candidate_manager --detail H-001

# Aprobar candidata para Test Set (IRREVERSIBLE)
python -m strategy_lab.lab_engine --approve H-001 --auth JUAN_APPROVED_FINAL_TEST

# Ver historial de sesiones
python -m strategy_lab.lab_report --history
```

---

## Metricas de una Sesion Tipica

Expectativa realista de una sesion de Strategy Lab:

| Etapa | Hipotesis que sobreviven |
|-------|--------------------------|
| Generadas por Claude | 10 |
| Pasan Gate 1-3 (Training) | 3-4 |
| Pasan Gate 4 (Walk-Forward) | 1-2 |
| Pasan Gate 5 (Cross-Instrument) | 1 |
| Pasan Gate 6-7 (Stress Test) | 0-1 |
| Pasan Gate 8 (Occam) | 0-1 |
| Pasan Gate 9 (Validation 2023) | 0-1 |
| **Candidatas finales** | **0-1** |

**Encontrar 1 candidata valida en 10-20 hipotesis es un EXITO.** La mayoria de las sesiones produciran 0 candidatas — y eso esta BIEN. Significa que los filtros funcionan. Prefiero 0 candidatas falsas que 10 candidatas que son overfitting.

---

## Data Adicional Necesaria

| Data | Source | Cost | Para que |
|------|--------|------|----------|
| ES 1min (S&P 500 futures) | FirstRateData | ~$30-50 once | Cross-instrument Gate 5 |
| YM 1min (Dow futures) | FirstRateData | ~$30-50 once | Cross-instrument Gate 5 |
| NQ ya lo tenemos | — | — | — |

**Total adicional: ~$60-100 one-time para data de ES + YM.**

---

## Integracion con Memoria

Despues de cada sesion, el lab guarda en `.claude/memory/project/`:

```markdown
## Strategy Lab Session #XX — YYYY-MM-DD

### Hipotesis generadas: N
### Candidatas encontradas: N

### Hipotesis que fallaron (y por que):
- H-001: "Nombre" — Failed Gate 4 (walk-forward 45%, needed 70%)
- H-002: "Nombre" — Failed Gate 5 (only worked on NQ, not ES/YM)

### Candidatas:
- H-003: "FVG-inside-OB filter" — PASSED all 9 gates
  - Training Sharpe: +0.15
  - Walk-Forward: 78% positive
  - Cross-Instrument: 3/3
  - Validation (2023): +0.12 Sharpe
  - Status: Awaiting Juan's review

### Insights:
- Most hypotheses fail at Walk-Forward (temporal overfitting is the #1 killer)
- Cross-instrument validation is surprisingly effective at catching NQ-specific noise
```

---

## Fase de Implementacion

El Strategy Lab se implementa DESPUES de que el bot base funcione (Fase 4+):

| Cuando | Que |
|--------|-----|
| Week 10 | Build `data_splitter.py`, `walk_forward.py`, `stress_tester.py` |
| Week 11 | Build `hypothesis_generator.py`, `anti_overfit_gates.py`, `lab_engine.py` |
| Week 12 | Buy ES + YM data. Build `cross_instrument.py`. Run first lab session. |
| Ongoing | Run 1-2 lab sessions per week. Review candidates on Sundays. |

**Costo adicional:** ~$60-100 (data) + ~$2-4/sesion (Claude API). Total ~$10-15/mes.

---

## La Filosofia Final

> *"Un investigador que no encuentra nada util en 100 experimentos no fracaso.*
> *Un investigador que reporta 100 descubrimientos falsos si fracaso."*
>
> *El Strategy Lab esta disenado para RECHAZAR, no para APROBAR.*
> *Cada hipotesis es culpable hasta que 9 jurados la declaren inocente.*
> *Y al final, el juez (Juan) tiene la ultima palabra.*

---

*Strategy Lab — AlgoICT | "No busca la mejor curva. Busca la verdad."*
