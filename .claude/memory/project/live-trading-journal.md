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
