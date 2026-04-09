export type ToxicityLevel = 'calm' | 'normal' | 'elevated' | 'high' | 'extreme';
export type MarketMood = 'risk_on' | 'risk_off' | 'event_driven' | 'choppy';
export type GEXRegime = 'positive' | 'negative' | 'flip' | 'unknown';
export type TradeDirection = 'long' | 'short';
export type TradeStatus = 'open' | 'closed' | 'cancelled';

export interface BotState {
  id: string;
  is_running: boolean;
  last_heartbeat: string;
  vpin: number;
  toxicity_level: ToxicityLevel;
  shield_active: boolean;
  trades_today: number;
  pnl_today: number;
  daily_high_pnl: number;
  max_loss_threshold: number;
  profit_cap: number;
  position_count: number;
  wins_today: number;
  losses_today: number;
  swc_mood: MarketMood;
  swc_confidence: number;
  swc_summary: string;
  gex_regime: GEXRegime;
  gex_call_wall: number | null;
  gex_put_wall: number | null;
  gex_flip_point: number | null;
  updated_at: string;
}

export interface Trade {
  id: string;
  strategy: string;
  direction: TradeDirection;
  entry_price: number;
  entry_time: string;
  exit_price: number | null;
  exit_time: string | null;
  pnl: number | null;
  contracts: number;
  confluence_score: number;
  kill_zone: string;
  stop_loss: number;
  take_profit: number;
  status: TradeStatus;
}
