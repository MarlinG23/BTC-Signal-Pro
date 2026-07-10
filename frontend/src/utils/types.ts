// ─── Domain types shared across the frontend ─────────────────────────────────

export type SignalType =
  | "STRONG_BUY"
  | "BUY"
  | "HOLD"
  | "SELL"
  | "STRONG_SELL";

export type AlertType =
  | "PRICE_LEVEL"
  | "NEW_SIGNAL"
  | "BREAKING_NEWS"
  | "LIQUIDATION";

export type Sentiment = "BULLISH" | "BEARISH" | "NEUTRAL";

export interface IndicatorSnapshot {
  timestamp: string | null;
  close_price: number | null;
  rsi_14: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  ema_20: number | null;
  ema_50: number | null;
  ema_200: number | null;
  bb_upper: number | null;
  bb_middle: number | null;
  bb_lower: number | null;
  bb_percent_b: number | null;
  volume_sma_20: number | null;
  volume_ratio: number | null;
  atr_14: number | null;
}

export interface Signal {
  id?: number;
  signal_type: SignalType;
  confidence: number;
  entry_price: number;
  take_profit: number | null;
  stop_loss: number | null;
  risk_reward_ratio: number | null;
  indicators_agreed: number;
  generated_at: string;
  outcome?: "WIN" | "LOSS" | "OPEN" | null;
  pnl_percent?: number | null;
}

/** Blocked 1M entry broadcast over WebSocket — not persisted to DB. */
export interface WaitSignal {
  signal_type: SignalType;
  confidence: number;
  entry_price: number;
  take_profit: number | null;
  stop_loss: number | null;
  risk_reward_ratio: number | null;
  indicators_agreed: number;
  generated_at: string;
  display_state: "WAIT";
  block_reason: string;
  trend_4h?: number;
  fear_greed?: number | null;
}

export interface NewsItem {
  id: number;
  source: string;
  title: string;
  url: string;
  published_at: string | null;
  sentiment: Sentiment | null;
  sentiment_score: number | null;
  is_geopolitical: boolean;
  geo_keywords: string | null;
}

export interface AlertItem {
  id: number;
  alert_type: AlertType;
  message: string;
  triggered_at: string;
  is_sent: boolean;
}

export interface FearGreedData {
  value: number;
  classification: string;
  timestamp: string;
  /** When our backend last fetched the index (ISO). Prefer for "Updated …" display. */
  updated_at?: string;
}

export interface SystemStatus {
  candles_1m: number;
  candles_4h: number;
  last_news_fetch: string | null;
  news_count: number;
  fear_greed: number | null;
  fear_greed_updated: string | null;
  fear_greed_poll_alive: boolean;
  ws_connected: boolean;
  ws_last_message_seconds: number | null;
  last_signal: string | null;
  db_connected: boolean;
  uptime_seconds: number;
  startup_ready: boolean;
}

export interface TrendSignal {
  direction: 1 | -1 | 0;        // +1 bullish, -1 bearish, 0 neutral
  label: "BULLISH" | "BEARISH" | "NEUTRAL" | "LOADING";
  ema_20: number | null;
  ema_50: number | null;
  ema_200: number | null;
  rsi_14: number | null;
  close_price: number | null;
  candles_buffered: number;
}

export interface BacktestResult {
  total_signals: number;
  total_trades: number;
  win_rate_pct: number;
  avg_profit_pct: number;
  avg_loss_pct: number;
  profit_factor: number;
  max_drawdown_pct: number;
  sharpe_proxy: number;
  total_return_pct: number;
  candles_used: number;
}

// WebSocket message types
export interface WsMessage {
  type:
    | "price_tick"
    | "indicators"
    | "signal"
    | "signal_wait"
    | "alert"
    | "news"
    | "fear_greed"
    | "ping";
  [key: string]: unknown;
}
