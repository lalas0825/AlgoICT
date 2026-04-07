---
name: ICT Pattern Reference
description: Placeholder for NotebookLM transcripts and ICT rule extraction
type: reference
---

## ICT Detector Patterns

_To be populated with findings from NotebookLM analysis of ICT education transcripts._

### Swing Points
- Lookback varies by timeframe (2 for 5min, 3 for 15min, 5 for daily/weekly)
- Source: CLAUDE.md, detectors/swing_points.py

### Fair Value Gap (FVG)
- Bullish: `candle[0].high < candle[2].low` (gap up)
- Bearish: `candle[0].low > candle[2].high` (gap down)
- Mitigation: When price fills 50%+ of the gap
- Source: CLAUDE.md, detectors/fair_value_gap.py

### Order Block (OB)
- Validation: Must have sweep + FVG + BOS + unmitigated
- Source: CLAUDE.md, detectors/order_block.py

### Liquidity (BSL/SSL/PDH/PDL)
- BSL/SSL: Buy-side / sell-side liquidity clusters
- PDH/PDL/PWH/PWL: Previous day/week high/low
- Source: CLAUDE.md, detectors/liquidity.py

### Market Structure
- BOS (Break of Structure)
- CHoCH (Change of Character)
- MSS (Market Structure Shift)
- Source: CLAUDE.md, detectors/market_structure.py

## Task: ICT Transcripts Analysis

_Not yet completed. Scheduled for post-Milestone 2._

- [ ] Upload ICT education transcripts to NotebookLM
- [ ] Extract detector rules
- [ ] Update this reference
- [ ] Validate against existing detector logic
