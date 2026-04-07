---
name: post-mortem
description: "Skill para analizar trades perdedores con Claude API. Genera insights sobre por que fallo el trade y recomendaciones para mejorar. Se activa automaticamente despues de cada loss en paper/live, o manualmente cuando el usuario pide analizar un trade."
argument-hint: "[trade_id | 'last' | 'today' | 'patterns']"
user-invocable: true
allowed-tools: Read, Write, Bash
---

# Post-Mortem Skill

## Cuando se activa

### Automaticamente (en paper/live trading)
- Despues de CADA trade perdedor, `risk_manager.py` llama a `post_mortem.py`
- No requiere intervencion del usuario
- Resultado se guarda en Supabase tabla `post_mortems`
- Resumen se envia a Telegram

### Manualmente (el usuario pide)
- "Analiza el ultimo trade", "Que paso con el trade de hoy?"
- "Analiza trade [ID]"
- "Muestra patrones de losses", "Por que pierdo tanto los lunes?"
- "Que recomienda el post-mortem?"

## Directorio de trabajo
```bash
cd algoict-engine/
```

## Arquitectura del Post-Mortem Agent

```
Trade perdedor ocurre
        │
        ▼
risk_manager.py detecta loss
        │
        ▼
post_mortem.py recopila contexto:
├── Trade data (entry, exit, pnl, confluence, ict_concepts)
├── HTF bias al momento del trade (weekly, daily)
├── Market structure en 15min al momento de entry
├── FVGs y OBs activos al momento de entry
├── Liquidity levels cercanos
├── Eventos de noticias del dia
├── Que paso con el precio DESPUES del stop
└── Trades anteriores del dia (contexto de sesion)
        │
        ▼
Claude API (Sonnet) analiza con prompt estructurado
        │
        ▼
Respuesta JSON estructurada:
├── reason: Por que fallo
├── htf_analysis: El HTF bias era correcto?
├── entry_analysis: El entry TF era apropiado?
├── stop_analysis: El stop estaba bien puesto?
├── pattern_to_avoid: Que patron evitar
├── recommendation: Ajuste de parametro especifico
├── severity: low | medium | high
└── category: htf_misread | premature_entry | stop_too_tight | news_event | false_signal
        │
        ├──▶ Supabase tabla `post_mortems`
        ├──▶ Telegram resumen
        └──▶ Si 3+ losses misma categoria → ALERTA PATRON RECURRENTE
```

## Implementacion del Agente

```python
# agents/post_mortem.py
import json
from datetime import datetime
from anthropic import Anthropic

class PostMortemAgent:
    """Analyzes losing trades using Claude API."""
    
    MODEL = "claude-sonnet-4-20250514"
    MAX_TOKENS = 1500
    
    def __init__(self, anthropic_client: Anthropic, supabase, telegram):
        self.ai = anthropic_client
        self.db = supabase
        self.tg = telegram
    
    async def analyze_loss(self, trade: dict, market_context: dict) -> dict:
        """
        Main analysis function. Called automatically after each loss.
        
        Args:
            trade: Dict with trade data from Supabase
            market_context: Dict with market state at time of trade
        
        Returns:
            Dict with structured analysis
        """
        prompt = self._build_prompt(trade, market_context)
        
        response = self.ai.messages.create(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}]
        )
        
        analysis = json.loads(response.content[0].text)
        
        # Save to Supabase
        await self.db.table('post_mortems').insert({
            'trade_id': trade['id'],
            'analysis': analysis,
            'category': analysis.get('category', 'unknown'),
            'severity': analysis.get('severity', 'medium'),
            'created_at': datetime.utcnow().isoformat()
        }).execute()
        
        # Alert to Telegram
        await self.tg.send(
            f"📊 *Post-Mortem*\n"
            f"Strategy: {trade['strategy']}\n"
            f"Loss: ${abs(trade['pnl_dollars']):.0f}\n"
            f"Reason: {analysis['reason']}\n"
            f"💡 {analysis['recommendation']}"
        )
        
        # Check for recurring patterns
        await self._check_patterns(analysis['category'])
        
        return analysis
    
    def _build_prompt(self, trade: dict, ctx: dict) -> str:
        return f"""You are an expert ICT trader analyzing a losing trade. 
Respond ONLY with a JSON object, no other text.

TRADE DATA:
- Strategy: {trade['strategy']}
- Direction: {trade['direction']}
- Entry: {trade['entry_price']} at {trade['entry_time']}
- Stop hit: {trade['exit_price']} at {trade['exit_time']}
- Loss: ${abs(trade['pnl_dollars']):.2f}
- Contracts: {trade['contracts']}
- Stop size: {trade.get('stop_points', 'N/A')} points
- Confluence score: {trade['confluence_score']}/14
- ICT concepts used: {json.dumps(trade['ict_concepts'])}
- Kill Zone: {trade['kill_zone']}

MARKET CONTEXT AT TIME OF TRADE:
- HTF Bias Weekly: {ctx.get('weekly_bias', 'N/A')}
- HTF Bias Daily: {ctx.get('daily_bias', 'N/A')}
- 15min structure: {ctx.get('structure_15min', 'N/A')}
- 5min structure: {ctx.get('structure_5min', 'N/A')}
- Active FVGs at entry: {json.dumps(ctx.get('active_fvgs', []))}
- Active OBs at entry: {json.dumps(ctx.get('active_obs', []))}
- Liquidity levels nearby: {json.dumps(ctx.get('liquidity_levels', []))}
- PDH/PDL: {ctx.get('pdh', 'N/A')}/{ctx.get('pdl', 'N/A')}
- News events today: {json.dumps(ctx.get('news_events', []))}
- Price action 30min after stop: {ctx.get('post_stop_action', 'N/A')}
- Session context (prior trades today): {json.dumps(ctx.get('prior_trades_today', []))}

ANALYZE AND RESPOND IN JSON:
{{
  "reason": "1-2 sentence explanation of why this trade failed",
  "htf_analysis": "Was the HTF bias correctly identified? Was there a HTF OB or FVG that should have prevented this trade?",
  "entry_analysis": "Was the entry timeframe and setup valid? Was the FVG/OB retrace clean or was it a marginal setup?",
  "stop_analysis": "Was the stop correctly placed per ICT rules? Too tight? Too loose? Was there a better level?",
  "pattern_to_avoid": "What specific pattern should the bot recognize and AVOID in the future?",
  "recommendation": "One specific, actionable parameter adjustment. Example: 'Increase min confluence from 7 to 8 when HTF bias is neutral'",
  "severity": "low | medium | high",
  "category": "htf_misread | premature_entry | stop_too_tight | stop_too_loose | news_event | false_signal | counter_trend | low_confluence | session_overtrading"
}}"""
    
    async def _check_patterns(self, category: str):
        """Check if same category appeared 3+ times recently."""
        recent = await self.db.table('post_mortems') \
            .select('category') \
            .order('created_at', desc=True) \
            .limit(10) \
            .execute()
        
        if recent.data:
            categories = [pm['category'] for pm in recent.data]
            count = categories.count(category)
            if count >= 3:
                await self.tg.send(
                    f"🚨 *PATRON RECURRENTE DETECTADO*\n"
                    f"Categoria: `{category}`\n"
                    f"Frecuencia: {count}/10 ultimos trades\n"
                    f"⚠️ Revisar detector/strategy relacionado"
                )
```

## Categorias de Loss

| Categoria | Significado | Accion |
|-----------|-------------|--------|
| `htf_misread` | El bias HTF era incorrecto o neutral | Revisar `htf_bias.py` |
| `premature_entry` | Entry antes de confirmacion completa | Revisar confluence minimo |
| `stop_too_tight` | Stop muy cerca, no dio espacio al trade | Revisar `position_sizer.py` expand logic |
| `stop_too_loose` | Stop muy lejos, perdida innecesariamente grande | Revisar OB/FVG placement |
| `news_event` | Movimiento por noticia inesperada | Verificar `news_blackout` en config |
| `false_signal` | Setup parecia valido pero el mercado no reacciono | Aumentar min confluence |
| `counter_trend` | Trade contra la tendencia principal | Forzar HTF alignment |
| `low_confluence` | Entro con confluence marginal (7-8) | Considerar subir minimo a 8 |
| `session_overtrading` | Demasiados trades en una sesion | Reducir max trades |

## Pattern Detection — Alertas Inteligentes

El agente no solo analiza trades individuales. Tambien busca patrones:

### Patron recurrente (3+ misma categoria en ultimos 10 trades)
→ Alerta Telegram urgente + guardar en `.claude/memory/feedback/`

### Patron temporal (losses se concentran en cierto horario)
→ Sugerir ajuste de Kill Zone timing

### Patron de confluencia (losses se concentran en score 7)
→ Sugerir subir minimo a 8

### Patron de dia de semana
→ Sugerir evitar ciertos dias

## Comandos

```bash
# Analizar un trade especifico
python -c "from agents.post_mortem import PostMortemAgent; agent.analyze_loss(trade_id='xxx')"

# Ver patrones recientes
python -c "from agents.post_mortem import PostMortemAgent; agent.show_patterns(last_n=20)"

# Generar reporte de patrones
python -m agents.post_mortem --report --last 50
```

## Uso manual en Claude Code

Cuando el usuario pide analisis:

```
"Analiza por que perdi el ultimo trade"
→ Leer ultimo trade de Supabase, correr post_mortem.analyze_loss()

"Muestra patrones de losses de esta semana"
→ Query post_mortems de los ultimos 7 dias, agrupar por categoria

"Que recomienda el post-mortem?"
→ Leer top 3 categorias mas frecuentes, presentar recomendaciones
```

## Costo
- Claude Sonnet: ~$0.05-0.10 por analisis
- Max 3 losses/dia (kill switch) = $0.15-0.30/dia
- ~$5-9/mes en el peor caso
- ROI: si un insight previene 1 loss de $250, el agente se paga solo en 1 dia

## Guardar Insights en Memoria

Despues de cada semana, guardar los patrones descubiertos en:
```
.claude/memory/feedback/post-mortem-patterns.md
```

Formato:
```markdown
## Week of YYYY-MM-DD
- **Top pattern:** [category] (X/Y trades)
- **Action taken:** [que se ajusto]
- **Result:** [mejoro o no]
```
