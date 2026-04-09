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

export interface ChartAnnotations {
  fvgZones: FVGZone[];
  obZones: OBZone[];
  liquidity: LiquidityLevel[];
  gexLevels: GEXLevel[];
  trades: TradeMarker[];
}
