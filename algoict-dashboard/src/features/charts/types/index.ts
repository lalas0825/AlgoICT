export type Timeframe = '1m' | '5m' | '15m' | '1H' | '4H' | 'D';

export type VPINLevel = 'calm' | 'normal' | 'elevated' | 'high' | 'extreme';

export interface Candle {
  time: number; // Unix ms
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vpin_level?: VPINLevel;
}

export type ZoneDirection = 'bullish' | 'bearish';

export interface FVGZone {
  id: string;
  time_start: number;
  time_end: number;
  price_low: number;
  price_high: number;
  direction: ZoneDirection;
  mitigated: boolean;
}

export interface OBZone {
  id: string;
  time_start: number;
  time_end: number;
  price_low: number;
  price_high: number;
  direction: ZoneDirection;
}

export type LiquidityType = 'BSL' | 'SSL' | 'PDH' | 'PDL' | 'EQH' | 'EQL';

export interface LiquidityLevel {
  id: string;
  price: number;
  type: LiquidityType;
  time_detected: number;
  swept: boolean;
}

export type GEXLevelType = 'call_wall' | 'put_wall' | 'gamma_flip';

export interface GEXLevel {
  type: GEXLevelType;
  price: number;
  label?: string;
}

export interface TradeMarker {
  id: string;
  time: number;
  price: number;
  direction: 'long' | 'short';
  type: 'entry' | 'exit';
  pnl?: number | null;
}

// ──────────────────────────────────────────────────────────────────────
// New in Phase 2 (migration 0003) — overlays derived from bot_state.
// ──────────────────────────────────────────────────────────────────────

export type TrackedLevelType =
  | 'PDH' | 'PDL' | 'PWH' | 'PWL'
  | 'EQH' | 'EQL' | 'BSL' | 'SSL'
  | (string & {});

export interface TrackedLevel {
  type: TrackedLevelType;
  price: number;
  /** True → the level was breached by the engine's sweep check. Render
   *  with a muted stroke + strikethrough on the label. */
  swept: boolean;
}

export type StructureEventType = 'MSS' | 'BOS' | 'CHoCH';

export interface StructureEvent {
  type: StructureEventType;
  direction: 'bullish' | 'bearish';
  /** Unix ms. The chart maps this to the nearest bar on the current TF. */
  time: number;
  price: number;
}

export interface Displacement {
  direction: 'bullish' | 'bearish';
  points: number;
  /** Unix ms. Chart highlights the containing bar. */
  time: number;
}

export interface SignalMarker {
  id: string;
  time: number;
  price: number;
  direction: 'long' | 'short';
  confluence_score: number;
  strategy: string;
}

export interface ChartAnnotations {
  fvgZones: FVGZone[];
  ifvgZones: FVGZone[];
  obZones: OBZone[];
  liquidity: LiquidityLevel[];
  gexLevels: GEXLevel[];
  trades: TradeMarker[];
  trackedLevels: TrackedLevel[];
  structureEvents: StructureEvent[];
  signals: SignalMarker[];
  displacement: Displacement | null;
}
