---
name: sentiment
description: "Skill para el modulo Sentiment-Weighted Confluence (SWC). Integra analisis de sentimiento en tiempo real al Confluence Scorer. Escanea noticias, calendario economico, FedWatch, y social sentiment para ajustar dinamicamente el scoring del bot. Activa cuando el usuario menciona sentimiento, noticias, CPI, NFP, FOMC, fear/greed, o contexto fundamental."
argument-hint: "[scan | event | mood | calibrate]"
user-invocable: true
allowed-tools: Read, Write, Bash
---

# Sentiment-Weighted Confluence (SWC) — El Edge

> *"El bot ICT ve las velas. El SWC ve el MUNDO detras de las velas."*

## Por Que Existe Este Modulo

Los bots ICT son ciegos al contexto fundamental. Un FVG perfecto con confluencia 10/14 en dia de CPI puede ser una trampa mortal. NQ futures promedian 150 puntos de movimiento en los primeros 5 minutos post-CPI vs 20-30 puntos en dias normales. El SWC le da OJOS al bot para ver mas alla del price action.

**El edge:** Precision de ICT para entries + inteligencia de AI para contexto = algo que nadie mas tiene.

## Cuando Se Activa

- "Como esta el sentimiento hoy?", "Es dia de noticias?"
- "Hay CPI/NFP/FOMC hoy?", "Que dice el mercado?"
- "Calibra el sentimiento", "Que mood tiene el mercado?"
- Automaticamente en pre-market (6:00 AM) para daily mood scan
- Automaticamente cuando hay release economico programado

## Arquitectura

```
PRE-MARKET (6:00 AM EST — automatico)
│
├── Economic Calendar Scan
│   ├── Eventos del dia (CPI, NFP, FOMC, Retail Sales, PMI, GDP)
│   ├── Hora exacta del release
│   ├── Consenso esperado vs dato previo
│   └── OUTPUT: events_today[], event_risk_level (low|medium|high|extreme)
│
├── FedWatch Probability Scan
│   ├── Probabilidad de rate change en proximo FOMC
│   ├── Cambio en probabilidad vs dia anterior
│   └── OUTPUT: rate_expectation, hawkish_dovish_shift
│
├── News Sentiment Scan (Claude API)
│   ├── Top 10-20 headlines financieras (Alpha Vantage News API)
│   ├── Sentiment classification: bullish/bearish/neutral
│   ├── Relevancia para NQ/tech sector
│   └── OUTPUT: news_sentiment_score (-1.0 a +1.0)
│
├── Social Sentiment Scan (opcional)
│   ├── X/Reddit trending topics financieros
│   ├── Fear & Greed index
│   └── OUTPUT: crowd_sentiment (-1.0 a +1.0)
│
└── DAILY MOOD SYNTHESIS (Claude API)
    ├── Combina todos los inputs
    ├── Genera: market_mood (risk_on | risk_off | event_driven | choppy)
    ├── Genera: confidence_level (low | medium | high)
    ├── Genera: recommended_adjustments {}
    └── OUTPUT → config_overrides para el dia

DURING TRADING (real-time en event days)
│
├── Economic Release Monitor
│   ├── Detecta cuando sale el dato
│   ├── Compara actual vs consenso
│   ├── Calcula surprise_factor (z-score)
│   └── OUTPUT: surprise (positive|negative|inline), magnitude
│
├── Post-Release Analyzer (Claude API)
│   ├── "CPI salio 0.4% vs 0.3% esperado — que significa?"
│   ├── Determina impacto probable en NQ
│   ├── Determina si el spike + retrace crea setup ICT
│   └── OUTPUT: direction_bias, trade_or_wait, confidence
│
└── Dynamic Confluence Adjustment
    ├── Modifica min_confluence en real-time
    ├── Modifica position_size_multiplier
    └── OUTPUT → risk_manager.update(adjustments)
```

## Implementacion

### Estructura de archivos

```
algoict-engine/
├── sentiment/
│   ├── swc_engine.py           # Motor principal del SWC
│   ├── economic_calendar.py    # Escanea eventos economicos del dia
│   ├── news_scanner.py         # Lee headlines + sentiment via API
│   ├── fedwatch.py             # CME FedWatch probabilities
│   ├── social_scanner.py       # X/Reddit sentiment (opcional, fase 2)
│   ├── mood_synthesizer.py     # Claude API: combina todo en Daily Mood
│   ├── release_monitor.py      # Monitorea releases en real-time
│   └── confluence_adjuster.py  # Modifica scoring basado en sentiment
│
└── tests/
    ├── test_economic_calendar.py
    ├── test_news_scanner.py
    └── test_confluence_adjuster.py
```

### Data Sources

| Source | Data | Cost | API |
|--------|------|------|-----|
| Alpha Vantage | News sentiment + headlines | Free (25 req/dia) o $49/mes | REST |
| Investing.com Calendar | Economic events, consenso, actual | Free (scraping) | Scraping |
| CME FedWatch | Rate probabilities | Free (scraping) | Web |
| Fear & Greed Index | CNN Fear & Greed | Free | REST |
| Claude API (Sonnet) | Mood synthesis + release analysis | ~$0.10-0.20/dia | REST |

### SWC Engine — Core Logic

```python
# sentiment/swc_engine.py
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class MarketMood(Enum):
    RISK_ON = "risk_on"         # Bullish sentiment, trending day expected
    RISK_OFF = "risk_off"       # Bearish sentiment, defensive positioning
    EVENT_DRIVEN = "event_driven" # Major event today, high volatility expected
    CHOPPY = "choppy"           # Mixed signals, no clear direction

class EventRisk(Enum):
    NONE = "none"               # No events today
    LOW = "low"                 # Minor data (PMI, housing)
    MEDIUM = "medium"           # Retail sales, GDP
    HIGH = "high"               # CPI, NFP
    EXTREME = "extreme"         # FOMC decision day

@dataclass
class DailyMoodReport:
    """Generated pre-market, guides the bot all day."""
    mood: MarketMood
    event_risk: EventRisk
    events_today: List[dict]          # [{name, time, consensus, previous}]
    news_sentiment: float             # -1.0 to +1.0
    crowd_sentiment: float            # -1.0 to +1.0
    fedwatch_shift: float             # Change in rate probability vs yesterday
    confidence: str                   # low | medium | high
    
    # Dynamic adjustments for the trading engine
    min_confluence_override: int      # Normal=7, can go 6-10
    position_size_multiplier: float   # 1.0 normal, 0.5 on high event risk
    news_blackout_windows: List[dict] # [{start, end}] auto-calculated
    directional_bias_weight: float    # How much sentiment influences HTF bias
    
    # For post-release trading
    post_release_enabled: bool        # Can we trade the retrace after spike?
    post_release_delay_minutes: int   # Wait X min after release before scanning

class SWCEngine:
    """
    Sentiment-Weighted Confluence Engine.
    Runs pre-market to set daily mood.
    Runs real-time on event days to adjust dynamically.
    """
    
    def __init__(self, calendar, news, fedwatch, synthesizer, adjuster):
        self.calendar = calendar
        self.news = news
        self.fedwatch = fedwatch
        self.synthesizer = synthesizer
        self.adjuster = adjuster
        self.daily_mood: Optional[DailyMoodReport] = None
    
    async def pre_market_scan(self) -> DailyMoodReport:
        """
        Runs at 6:00 AM EST. Generates the daily mood report.
        This report guides all trading decisions for the day.
        """
        # 1. Scan economic calendar
        events = await self.calendar.get_today_events()
        event_risk = self._classify_event_risk(events)
        
        # 2. Scan news headlines + sentiment
        news_data = await self.news.scan_headlines(sector="technology")
        news_sentiment = news_data.aggregate_score  # -1.0 to +1.0
        
        # 3. Check FedWatch
        fedwatch = await self.fedwatch.get_current_probabilities()
        fed_shift = fedwatch.daily_change
        
        # 4. Synthesize with Claude API
        mood_report = await self.synthesizer.generate_mood(
            events=events,
            event_risk=event_risk,
            news_sentiment=news_sentiment,
            fedwatch=fedwatch,
        )
        
        # 5. Calculate dynamic adjustments
        adjustments = self.adjuster.calculate(
            mood=mood_report.mood,
            event_risk=event_risk,
            news_sentiment=news_sentiment,
        )
        
        self.daily_mood = DailyMoodReport(
            mood=mood_report.mood,
            event_risk=event_risk,
            events_today=events,
            news_sentiment=news_sentiment,
            crowd_sentiment=0.0,  # Optional, fase 2
            fedwatch_shift=fed_shift,
            confidence=mood_report.confidence,
            **adjustments,
        )
        
        return self.daily_mood
    
    def _classify_event_risk(self, events: List[dict]) -> EventRisk:
        """Classify today's event risk level."""
        extreme = {"FOMC", "FOMC Minutes"}
        high = {"CPI", "Core CPI", "NFP", "Non-Farm Payrolls"}
        medium = {"Retail Sales", "GDP", "Core PCE", "PPI"}
        
        event_names = {e['name'] for e in events}
        
        if event_names & extreme:
            return EventRisk.EXTREME
        if event_names & high:
            return EventRisk.HIGH
        if event_names & medium:
            return EventRisk.MEDIUM
        if events:
            return EventRisk.LOW
        return EventRisk.NONE
```

### Confluence Adjuster — Dynamic Rules

```python
# sentiment/confluence_adjuster.py

class ConfluenceAdjuster:
    """
    Modifies trading parameters based on daily sentiment.
    These overrides are applied to the risk manager and confluence scorer.
    """
    
    # Base values (from config.py)
    BASE_MIN_CONFLUENCE = 7
    BASE_POSITION_MULTIPLIER = 1.0
    BASE_NEWS_BLACKOUT_MINUTES = 15
    
    def calculate(self, mood, event_risk, news_sentiment) -> dict:
        
        min_conf = self.BASE_MIN_CONFLUENCE
        pos_mult = self.BASE_POSITION_MULTIPLIER
        blackout_windows = []
        post_release_enabled = False
        post_release_delay = 0
        bias_weight = 0.0
        
        # === EVENT RISK ADJUSTMENTS ===
        
        if event_risk == EventRisk.EXTREME:
            # FOMC day: max caution
            min_conf = 10              # Only trade A+ setups
            pos_mult = 0.5            # Half position size
            blackout_windows.append({
                'start': '13:45',     # 15 min before FOMC (2:00 PM ET)
                'end': '15:00',       # 1 hour after
            })
            post_release_enabled = True
            post_release_delay = 30    # Wait 30 min for dust to settle
            
        elif event_risk == EventRisk.HIGH:
            # CPI/NFP day
            min_conf = 9               # Higher bar
            pos_mult = 0.75           # 75% position
            blackout_windows.append({
                'start': '08:15',     # 15 min before 8:30 release
                'end': '08:45',       # 15 min after
            })
            post_release_enabled = True
            post_release_delay = 15    # Wait 15 min, then scan for ICT setups
            
        elif event_risk == EventRisk.MEDIUM:
            min_conf = 8
            pos_mult = 0.9
            blackout_windows.append({
                'start': '08:20',
                'end': '08:40',
            })
            
        elif event_risk == EventRisk.NONE:
            # Clean day, no events — best days for ICT
            min_conf = 7              # Standard
            pos_mult = 1.0            # Full size
        
        # === SENTIMENT ADJUSTMENTS ===
        
        if abs(news_sentiment) > 0.7:
            # Extreme sentiment — use as CONTRARIAN filter
            # When everyone is bullish, be more cautious on longs
            bias_weight = -0.3  # Slight contrarian tilt
            min_conf = max(min_conf, 8)  # Higher bar in extreme sentiment
            
        elif abs(news_sentiment) < 0.2:
            # Neutral/mixed sentiment — standard operation
            bias_weight = 0.0
            
        else:
            # Moderate sentiment — use as confirmation
            bias_weight = news_sentiment * 0.2  # Slight weight toward sentiment
        
        return {
            'min_confluence_override': min_conf,
            'position_size_multiplier': pos_mult,
            'news_blackout_windows': blackout_windows,
            'directional_bias_weight': bias_weight,
            'post_release_enabled': post_release_enabled,
            'post_release_delay_minutes': post_release_delay,
        }
```

### Post-Release ICT Scanner — THE REAL EDGE

```python
# sentiment/release_monitor.py

class ReleaseMonitor:
    """
    Monitors economic releases in real-time.
    After a surprise release, waits for the spike + retrace,
    then scans for ICT setups in the direction of the surprise.
    
    THIS IS THE EDGE:
    - Everyone else has a blackout and misses the move
    - We wait for the noise to settle, then use ICT precision
      to enter the post-release retrace with full context
    """
    
    async def on_release(self, event: dict, actual: float, consensus: float):
        """Called when an economic number is released."""
        
        # 1. Calculate surprise
        surprise = actual - consensus
        z_score = surprise / event['historical_std']
        
        # 2. Determine direction
        if event['name'] in ['CPI', 'Core CPI', 'PPI']:
            # Higher inflation = hawkish = bearish for NQ
            direction = 'bearish' if surprise > 0 else 'bullish'
        elif event['name'] in ['NFP', 'Retail Sales', 'GDP']:
            # Strong economy = hawkish = bearish for NQ (rate hike fear)
            # BUT can also be bullish (strong economy = earnings growth)
            # Use Claude to determine
            direction = await self._ai_determine_direction(event, surprise)
        else:
            direction = 'neutral'
        
        # 3. Wait for initial spike to complete
        await asyncio.sleep(self.daily_mood.post_release_delay_minutes * 60)
        
        # 4. NOW scan for ICT setups in the retrace
        # The spike created FVGs and displacement — perfect ICT territory
        return PostReleaseContext(
            event=event,
            surprise_direction=direction,
            surprise_magnitude=abs(z_score),
            ready_to_scan=True,
            # The strategy engine will now scan for:
            # - FVGs created by the spike
            # - OBs formed during the reversal
            # - MSS confirming the post-release direction
            # With the ADDED CONTEXT of knowing WHY price moved
        )
```

### Daily Mood Synthesis (Claude API)

```python
# sentiment/mood_synthesizer.py

class MoodSynthesizer:
    """Uses Claude API to generate a coherent daily market mood."""
    
    MODEL = "claude-sonnet-4-20250514"
    
    async def generate_mood(self, events, event_risk, news_sentiment, fedwatch):
        
        prompt = f"""You are a senior macro trader assessing today's market conditions for NQ/MNQ futures trading.

TODAY'S CONTEXT:
- Economic events: {json.dumps(events)}
- Event risk level: {event_risk.value}
- News sentiment (tech sector): {news_sentiment:.2f} (-1 bearish to +1 bullish)
- FedWatch rate probability shift: {fedwatch.daily_change:+.1f}%
- Current rate probability: {fedwatch.current_prob}% chance of cut at next meeting

DETERMINE:
1. market_mood: "risk_on" | "risk_off" | "event_driven" | "choppy"
2. confidence: "low" | "medium" | "high"
3. one_line_summary: Brief assessment for the trader
4. key_risk: Single biggest risk factor today
5. opportunity: Best potential opportunity today

Respond ONLY in JSON."""
        
        response = await self.ai.messages.create(
            model=self.MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return json.loads(response.content[0].text)
```

## Integration con AlgoICT

### En main.py — Pre-market
```python
# 6:00 AM EST — before anything else
daily_mood = await swc_engine.pre_market_scan()

# Log to Supabase
await supabase.table('daily_performance').update({
    'market_mood': daily_mood.mood.value,
    'event_risk': daily_mood.event_risk.value,
    'sentiment_score': daily_mood.news_sentiment,
}).eq('date', today).execute()

# Send Telegram daily briefing
await telegram.send(
    f"🌅 *AlgoICT Daily Mood*\n"
    f"Mood: {daily_mood.mood.value}\n"
    f"Event Risk: {daily_mood.event_risk.value}\n"
    f"Events: {', '.join(e['name'] for e in daily_mood.events_today) or 'None'}\n"
    f"News Sentiment: {daily_mood.news_sentiment:+.2f}\n"
    f"Min Confluence: {daily_mood.min_confluence_override}/14\n"
    f"Position Size: {daily_mood.position_size_multiplier:.0%}"
)

# Override risk manager params for the day
risk_manager.set_daily_overrides(
    min_confluence=daily_mood.min_confluence_override,
    position_multiplier=daily_mood.position_size_multiplier,
    blackout_windows=daily_mood.news_blackout_windows,
)
```

### En confluence.py — Scoring Adjustment
```python
# Add sentiment as 15th factor in confluence scoring
def score(self, ..., daily_mood: DailyMoodReport) -> int:
    base_score = self._calculate_base_score(...)  # 0-14 from ICT factors
    
    # Sentiment alignment bonus
    if daily_mood.mood == MarketMood.RISK_ON and direction == 'long':
        base_score += 1  # Sentiment confirms longs
    elif daily_mood.mood == MarketMood.RISK_OFF and direction == 'short':
        base_score += 1  # Sentiment confirms shorts
    
    # NEW MAX: 15 points (14 ICT + 1 sentiment)
    return min(base_score, 15)
```

### Updated Confluence Scoring Table

| Factor | Points | Source |
|--------|--------|--------|
| Liquidity grab | +2 | ICT (5min/15min) |
| Fair Value Gap | +2 | ICT (5min) |
| Order Block | +2 | ICT (5min/15min) |
| Market Structure Shift | +2 | ICT (15min) |
| Kill Zone | +1 | Time-based |
| OTE Fibonacci | +1 | ICT (5min) |
| HTF bias aligned | +1 | ICT (Daily/Weekly) |
| HTF OB/FVG alignment | +1 | ICT (HTF) |
| Target at PDH/PDL | +1 | ICT (15min/Daily) |
| **Sentiment alignment** | **+1** | **SWC (NEW)** |
| **Max total** | **15** | |

## Costos del Modulo SWC

| Servicio | Costo | Frecuencia |
|----------|-------|------------|
| Alpha Vantage News | Free (25/dia) o $49/mes | Per request |
| Claude API (mood + releases) | ~$0.10-0.20/dia | Daily + on events |
| Economic calendar scraping | Free | Daily |
| FedWatch scraping | Free | Daily |
| **Total adicional** | **~$3-6/mes** | |

## Fases de Implementacion

### Fase A (con backtest, Semana 3): Implementar economic_calendar.py y confluence_adjuster.py
- Backtest con data historica: en dias de CPI/NFP, usar min_confluence mas alto
- Medir: mejora el win rate? Reduce drawdown en event days?

### Fase B (con paper trading, Semana 6): Agregar news_scanner.py y mood_synthesizer.py
- Daily mood report real via Claude API
- Telegram briefing cada manana

### Fase C (Semana 8+): Post-release scanner
- release_monitor.py activo en dias de eventos
- El bot puede operar el retrace post-CPI/NFP con contexto
- ESTE es el edge principal — backtestear extensivamente primero

### Fase D (opcional): Social sentiment
- social_scanner.py con X/Reddit APIs
- Fear & Greed index como filtro contrarian
- Solo si Fases A-C prueban valor en backtest

## Backtest del SWC

Para validar el edge, el backtester debe comparar:

1. **ICT Pure (sin SWC):** Backtest normal con nuestras 3 estrategias
2. **ICT + Calendar Adjuster:** Mismo backtest pero con min_confluence ajustado en event days
3. **ICT + Full SWC:** Mismo pero con post-release scanner habilitado

Si el SWC mejora el Sharpe ratio Y reduce max drawdown en event days, es un edge valido. Si no, lo descartamos sin remordimiento. Data decides, not ego.

---

*"El mercado no se mueve por velas. Se mueve por MIEDO y CODICIA. El SWC cuantifica ambos."*
