# AlgoICT — TOKEN OPTIMIZATION PLAN
### Que modelo usar para cada task + estrategias de ahorro

---

## Modelo por Tarea

### Leyenda
- 🟢 **Haiku** — Boilerplate, scaffolding, tests, patrones repetitivos, formatting
- 🟡 **Sonnet** — Logica de negocio, implementacion, integracion, debugging normal
- 🔴 **Opus** — Arquitectura, decisiones complejas, debugging dificil, Strategy Lab AI

---

## MILESTONE 1: FOUNDATION

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 1 | Scaffold project (dirs, files) | 🟢 Haiku | Solo crear folders y archivos vacios |
| 2 | Config constants | 🟢 Haiku | Copiar constantes del CLAUDE.md a Python |
| 3 | Data loader | 🟡 Sonnet | Logica de parsing CSV + validacion |
| 4 | Timeframe manager | 🟡 Sonnet | Logica de OHLCV aggregation |
| 5 | Session manager | 🟢 Haiku | Comparaciones de timestamps simples |
| 6 | HTF bias | 🟡 Sonnet | Logica ICT de bias determination |
| 7 | Foundation tests | 🟢 Haiku | Tests siguen patrones predecibles |
| 8 | Init memory | 🟢 Haiku | Crear archivos markdown |

**M1 Total:** 4 Haiku, 3 Sonnet, 0 Opus

---

## MILESTONE 2: ICT DETECTORS

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 9 | Swing points | 🟡 Sonnet | Logica de lookback + detection |
| 10 | Market structure (BOS/CHoCH/MSS) | 🔴 Opus | Logica ICT compleja, multi-TF state machine |
| 11 | Fair Value Gap | 🟡 Sonnet | Logica clara pero necesita mitigation tracking |
| 12 | Order Block | 🟡 Sonnet | Validation rules multiples |
| 13 | Liquidity | 🟡 Sonnet | Multiple level types + sweep detection |
| 14 | Displacement | 🟢 Haiku | Comparacion simple: body > 2x ATR |
| 15 | Confluence scorer | 🔴 Opus | Integra TODO, multi-TF, scoring complejo |
| 16 | All detector tests | 🟢 Haiku | Tests siguen patron de Task 7 |
| 17 | Commit | 🟢 Haiku | Git command |

**M2 Total:** 3 Haiku, 4 Sonnet, 2 Opus

---

## MILESTONE 3: RISK + STRATEGIES

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 18 | Position sizer | 🟡 Sonnet | floor() + expand logic |
| 19 | Risk manager | 🟡 Sonnet | Multiple safety mechanisms |
| 20 | Topstep compliance | 🟢 Haiku | Comparaciones simples contra limites |
| 21 | NY AM Reversal strategy | 🔴 Opus | Estrategia completa, multi-TF, evaluation loop |
| 22 | Silver Bullet strategy | 🟡 Sonnet | Mas simple que NY AM, patron similar |
| 23 | Strategy tests | 🟢 Haiku | Tests con mock data |
| 24 | Commit | 🟢 Haiku | Git command |

**M3 Total:** 3 Haiku, 3 Sonnet, 1 Opus

---

## MILESTONE 4: BACKTESTER + COMBINE SIM

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 25 | Backtester core | 🔴 Opus | Engine complejo: candle-by-candle loop con todo integrado |
| 26 | Risk audit | 🟡 Sonnet | Validation checks contra reglas |
| 27 | Combine simulator | 🟡 Sonnet | Sigue logica del backtester + Topstep rules |
| 28 | Report generator | 🟢 Haiku | Calculos de metricas + formatting |
| 29 | Run backtests | 🟢 Haiku | Ejecutar comandos, leer output |
| 30 | SWC-A (calendar + adjuster) | 🟡 Sonnet | Parsing + logica de ajuste |
| 31 | GEX-A (calculator + regime) | 🔴 Opus | Black-Scholes math + regime detection |
| 32 | VPIN-A (buckets + calculator) | 🔴 Opus | BVC algorithm + VPIN rolling calc |

**M4 Total:** 2 Haiku, 3 Sonnet, 3 Opus

---

## MILESTONE 5: LIVE CONNECTION

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 33 | TopstepX auth | 🟡 Sonnet | JWT + token refresh logic |
| 34 | TopstepX WebSocket | 🟡 Sonnet | WS connection + parsing |
| 35 | TopstepX orders | 🟡 Sonnet | REST API calls + error handling |
| 36 | Heartbeat | 🟢 Haiku | Timer + Supabase write, simple |
| 37 | Main entry point | 🔴 Opus | Orchestrates EVERYTHING — critical |
| 38 | Supabase setup | 🟢 Haiku | SQL tables + RLS from spec |
| 39 | Telegram bot | 🟢 Haiku | Template messages + send |
| 40 | Paper validation | 🟡 Sonnet | Compare + debug |

**M5 Total:** 3 Haiku, 4 Sonnet, 1 Opus

---

## MILESTONE 6: EDGE MODULES LIVE

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 41 | SWC news scanner | 🟡 Sonnet | API integration |
| 42 | SWC mood synthesizer | 🟡 Sonnet | Claude API prompt + parsing |
| 43 | SWC engine integration | 🟡 Sonnet | Wire into main.py |
| 44 | GEX live scan | 🟡 Sonnet | Fetch + calculate |
| 45 | GEX confluence integration | 🟢 Haiku | Wire bonus into existing scorer |
| 46 | VPIN live engine | 🟡 Sonnet | WebSocket → buckets → calc |
| 47 | VPIN shield | 🟡 Sonnet | Shield actions + integration |
| 48 | Post-mortem agent | 🟡 Sonnet | Claude API prompt + save |
| 49 | Full pipeline test | 🟡 Sonnet | Run + debug |
| 50-52 | Review + document | 🟢 Haiku | Read results, write markdown |

**M6 Total:** 2 Haiku, 8 Sonnet, 0 Opus

---

## MILESTONE 7: DASHBOARD

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 53 | Dashboard scaffold | 🟢 Haiku | Next.js boilerplate |
| 54 | Main dashboard page | 🟡 Sonnet | Multiple components + Realtime |
| 55 | Candlestick chart | 🔴 Opus | Complex chart with ICT + GEX + VPIN annotations |
| 56 | Trades + signals pages | 🟢 Haiku | Table components, repetitive pattern |
| 57 | Backtest + post-mortem pages | 🟢 Haiku | Same pattern as 56 |
| 58 | Strategy Lab page | 🟡 Sonnet | Gate results visualization |
| 59 | Controls page | 🟢 Haiku | Buttons + status badges |
| 60 | Deploy + test | 🟢 Haiku | Vercel commands |

**M7 Total:** 5 Haiku, 2 Sonnet, 1 Opus

---

## MILESTONE 8: SWING

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 61 | Alpaca client | 🟡 Sonnet | API integration |
| 62 | Swing HTF strategy | 🔴 Opus | New strategy, different TF stack |
| 63-65 | Sector filter + backtest + paper | 🟢 Haiku | Config + run commands |

**M8 Total:** 1 Haiku, 1 Sonnet, 1 Opus

---

## MILESTONE 9: STRATEGY LAB

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 66 | Data splitter (LOCKED test set) | 🟡 Sonnet | Split logic + permission system |
| 67 | Walk-forward validator | 🔴 Opus | Rolling windows, complex validation |
| 68 | Stress tester | 🟡 Sonnet | Noise injection, shift, remove |
| 69 | Cross-instrument | 🟡 Sonnet | Run on multiple datasets |
| 70 | Anti-overfit gates | 🔴 Opus | 9 gates, threshold logic, integration |
| 71 | Hypothesis generator | 🔴 Opus | Claude API prompt engineering — the brain |
| 72 | Lab engine orchestrator | 🔴 Opus | Full pipeline orchestration |
| 73 | Candidate manager | 🟡 Sonnet | CRUD + ranking |
| 74-75 | Run sessions + review | 🟡 Sonnet | Execute + analyze |

**M9 Total:** 0 Haiku, 5 Sonnet, 4 Opus

---

## MILESTONE 10: GO LIVE

| Task | Descripcion | Modelo | Razon |
|------|------------|--------|-------|
| 76-78 | Validation runs | 🟢 Haiku | Run commands, read results |
| 79 | SWC post-release scanner | 🟡 Sonnet | Real-time detection logic |
| 80 | Final Combine sim | 🟢 Haiku | Run command |
| 81-82 | Go/No-Go + launch | 🟢 Haiku | Decision + config change |

**M10 Total:** 4 Haiku, 1 Sonnet, 0 Opus

---

## RESUMEN POR MODELO

| Modelo | Tasks | % del proyecto | Costo relativo |
|--------|-------|---------------|----------------|
| 🟢 **Haiku** | 27 | 33% | $1x (baseline) |
| 🟡 **Sonnet** | 34 | 41% | $12x |
| 🔴 **Opus** | 13 | 16% | $60x |

**Sin optimizacion:** 100% Opus = $$$$$
**Con optimizacion:** 33% Haiku + 41% Sonnet + 16% Opus = ~70% ahorro

---

## ESTRATEGIAS ADICIONALES DE AHORRO

### 1. Context Window Management
```
NO cargar CLAUDE.md completo en cada task.
- Haiku tasks: Solo cargar config.py + el archivo que va a editar
- Sonnet tasks: Cargar CLAUDE.md seccion relevante + skill file
- Opus tasks: Cargar CLAUDE.md completo + skill + related files
```

### 2. Skill Files como Contexto Minimo
```
En vez de cargar todo CLAUDE.md (largo), cargar solo el SKILL.md relevante:
- Task trabaja en detectors → cargar python-engine_SKILL.md
- Task trabaja en backtest → cargar backtest_SKILL.md
- Task trabaja en GEX → cargar gamma_SKILL.md
El SKILL.md tiene todo lo que el agente necesita para esa area.
```

### 3. Usar /primer Solo en Opus Tasks
```
/primer carga contexto completo = muchos tokens.
Para Haiku/Sonnet tasks, no correr /primer.
Solo dar instrucciones directas: "Edit file X, add function Y"
```

### 4. Batch Haiku Tasks
```
Haiku es tan barato que puedes hacer 3-4 tasks seguidas:
"Create these 4 test files following the pattern in test_fvg.py:
 test_ob.py, test_liquidity.py, test_displacement.py, test_confluence.py"
Un solo prompt = 4 tasks completadas.
```

### 5. Template-Driven Generation
```
Darle a Haiku UN ejemplo perfecto y pedirle que replique:
"Here is test_fvg.py (the gold standard). 
 Create test_ob.py following the EXACT same pattern."
Haiku es excelente replicando patrones.
```

### 6. Sonnet como Default, Opus Solo Cuando Se Atora
```
Empieza cada task compleja con Sonnet.
Si Sonnet se atora o produce algo incorrecto despues de 2 intentos,
ENTONCES escala a Opus para desatorar.
Muchas veces Sonnet resuelve lo que parece "Opus-level".
```

### 7. Code Review con Haiku
```
Despues de que Sonnet/Opus escribe codigo:
- Usa Haiku para: lint, format, type check, docstrings
- Haiku es perfecto para tareas mecanicas de limpieza
```

### 8. Memory Saves con Haiku
```
Actualizar .claude/memory/ siempre con Haiku.
Es escribir markdown, no necesita razonamiento.
```

### 9. Tests con Haiku (Siempre)
```
TODOS los tests se escriben con Haiku.
Tests siguen patrones predecibles:
- Arrange (setup data)
- Act (call function)
- Assert (check result)
Haiku los clava al 100%.
```

### 10. Debugging Escalation
```
Bug encontrado:
1. Intenta con Haiku (error obvio? typo? import?) → $0.01
2. Si no resuelve → Sonnet (logica incorrecta?) → $0.10
3. Si no resuelve → Opus (arquitectura? race condition?) → $1.00
La mayoria de bugs se resuelven en paso 1 o 2.
```

---

## FLUJO OPTIMO POR SESION

```
INICIO DE SESION:
├── Si es Haiku task → NO /primer, instruccion directa
├── Si es Sonnet task → Cargar SKILL.md relevante + archivo target
└── Si es Opus task → /primer + CLAUDE.md + SKILL.md + BUILD_TASKS.md

DURANTE:
├── Escribir codigo → Modelo asignado
├── Escribir tests → Siempre Haiku
├── Debugging → Escalation (Haiku → Sonnet → Opus)
├── Code review/cleanup → Haiku
└── Memory updates → Haiku

FIN DE SESION:
├── Commit → Haiku
└── Memory update → Haiku
```

---

## CUANDO ESCALAR A OPUS (Checklist)

Solo usar Opus cuando:
- [ ] El task requiere integrar 3+ sistemas que interactuan
- [ ] El task requiere razonamiento sobre la ARQUITECTURA (no solo implementacion)
- [ ] Sonnet fallo 2 veces en el mismo task
- [ ] El task involucra prompt engineering para Claude API (meta-AI)
- [ ] El task es main.py (orquestador de todo)
- [ ] El task es el Confluence Scorer (integra 20 factores)
- [ ] El task es el Backtester core (candle-by-candle loop)
- [ ] El task es el Strategy Lab (hypothesis generator, anti-overfit gates)

Si ninguna de estas es true → NO uses Opus.

---

*"Haiku para las manos. Sonnet para el cerebro. Opus para las decisiones que importan."*
