# Live Trading Journal — Combine $50K (real eval money)

> Resultados del bot en VIVO (cuenta TopstepX Combine 21551969).
> Distinto de `backtest-final-results.md` (eso es backtest histórico).
> Baseline semanal — cada viernes se agrega una entrada. Net = gross − fees
> (MNQ $1.24 round-trip/contrato, $2/punto).

---

## Semana 1 — 06/01 → 06/05/2026 (week ending Fri 06/05)

### 🟢 NET +$949.54  ·  11 trades · 6W/5L · WR 54.5% · PF 2.16
Gross $1,016.50 − fees $66.96. avg win $295 / avg loss $164.

**Por día (CT):**
| Día | T | W/L | WR | Neto |
|-----|:-:|:---:|:--:|----:|
| Lun 06/01 | 3 | 2/1 | 67% | +$1,010.16 🔥 |
| Mar 06/02 | 2 | 1/1 | 50% | −$3.66 |
| Mié 06/03 | 2 | 0/2 | 0% | −$227.16 |
| Jue 06/04 | 2 | 1/1 | 50% | −$45.88 |
| Vie 06/05 | 2 | 2/0 | 100% | +$216.08 |

**Por Kill Zone:**
| KZ | T | W/L | WR | Neto |
|----|:-:|:---:|:--:|----:|
| NY AM | 4 | 3/1 | 75% | +$1,140.68 |
| London | 5 | 3/2 | 60% | +$36.02 |
| NY PM | 2 | 0/2 | 0% | −$227.16 |

**Notas de la semana:**
- Lunes hizo la semana (+$1,010). NY AM cargó todo (+$1,141).
- **NY PM fue la sangría** (0/2, −$227) — ambos LONG en estructura
  alcista agotada. Patrón documentado: NY PM = la KZ débil.
- El bot tiró 10 LONGS y 1 SHORT. El único short que se llenó GANÓ.
  El mercado se dio vuelta bajista; los shorts eran el edge de la semana.

### ⚠️ LECCIÓN CLAVE — "Override Emocional" cobró matrícula (barata)
El viernes 06/05 el usuario canceló MANUALMENTE 2 shorts ("no me gustaba
la entrada"). **Ambos eran ganadores:**
- SHORT #1 @29922.50 (x2) → bajó a 29801 = **+121 pts / +3.2R MFE**
- SHORT #2 @29893.75 (x1) → bajó a 29801 = **+93 pts / +2.1R MFE**

Impacto cuantificado de intervenir a mano:
- **WR real 54.5% (6W/5L) → sin intervenir 61.5% (8W/5L)** ≈ backtest ~63%
- **Costo: ~7 puntos de WR + ~$300–500** (captura realista con trailing).

→ Decisión del usuario: **"set and forget from now on"**. La disciplina
sistemática ES el edge. Veta-discrecional = apostar corazonada contra
7 años de backtest. Regla del proyecto: *Bot se detiene → NO intervenir.*

### Bugs/infra destapados esta semana
- **Cancel externo deja fantasma**: `_on_order_update` (topstepx.py:1019)
  solo procesa status=2 (fill), ignora status=3 (cancel). Un límite
  cancelado a mano queda `local_count=1` en estado local, bloquea entradas
  hasta restart. Fix pendiente (chip task_c1ae9813).
- **Auto-restart watchdog SHIPPED** (06/05): relanza el bot tras muerte
  limpia, session-independent. Ya se probó solo en un reboot real (booteó
  06:13 → relanzó 06:15, sin intervención).

### Combine progress
**+$949.54 = ~32% del target $3,000 en 1 semana.** MLL normal, 0 violaciones.

---

## Semana 2 — notas

### London 06/08 — give-back contra-tendencia (−$204 neto)
4 LONGs, todos conf=1 (sentiment), en régimen DIARIO BAJISTA. T1 ganó +$427
(MFE +3.0R), después T2/T3/T4 fadearon el downtrend y perdieron (T4 fue a
+1.9R y reversó full). Bot siguió sus reglas (SB bias-agnostic). Es variance +
el gap de regime-detection. NO se intervino (set & forget). Frenos: $900 DD +
cap 15 trades, ninguno cerca.

### 🔬 Camino C4 Vision overlay — DISABLED (06/08)
Contrafactual sobre 15 trades live: **obedecer visión = +$745 → −$254 (−$1,000).**
SKIP calls 62% WR, FIRE calls 33% WR — anti-correlada. Separabilidad: da el
MISMO rationale ("chop, FVG marginal") a ganadores y perdedores → la info que
los distingue no está en el chart al fire. **No es problema de prompt, es
fundamental.** 6º filtro throw-out-winner. `VISION_VALIDATOR_ENABLED=False`,
código retenido. Scripts: `analysis/vision_counterfactual.py`, `vision_separability.py`.

### Bugs fixed Semana 2
- **status='open' en trades cerrados** (regresión) → write_trade deriva status
  de exit_time + backfill de 11 filas. Dashboard "Open Positions" ya no muestra
  fantasmas. (commit f328eea)
- **Cancel-fantasma** (Friday's chip) → cancel callback limpia entry pendiente
  no-llena en status=3, self-vs-external aware. (commit f328eea)
- **Race en el self-cancel tag** → se registraba después del await; 8 alertas
  falsas "cancelled externally" hoy (todas eran opportunity-replace del bot).
  Fix: pre-registrar antes del await. (commit fd94bd5)

### Lunes 06/08 día completo — 1W/5L, −$508 neto (todos longs)
Régimen diario bajista, el bot fadeó/chopeó. Seguís VERDE en el Combine
(+$441 neto wk1+wk2). No se intervino — kill-switch $900 es el freno.

### 🛑 Camino B (regime circuit-breaker) — TESTEADO y RECHAZADO (06/08)
Backtest 3-año post-hoc de TODAS las variantes (halt por N pérdidas
consecutivas/totales, instant-adverse quick-stop, cross-KZ cascade).
**Todas throw-out-winner, 0 sobrevive.** Los trades que saltaría tras una
racha de pérdidas son net-GANADORES (N=2: 263 skipped = +$39,020). Cross-KZ:
los trades de una KZ que sigue a una KZ net-negativa son net-positivos cada
año. **Después de pérdidas, el bot RECUPERA — las rachas no predicen más
pérdidas.** Cierra la investigación "regime detection / darle ojos al bot":
ningún circuit-breaker de performance-reciente sobrevive. La protección que SÍ
sirve = los caps por MONTO que ya tenemos ($900 kill-switch + $2000 MLL).
7º throw-out-winner. Scripts: analysis/camino_b_crossperiod.py + camino_b_extra.py.
