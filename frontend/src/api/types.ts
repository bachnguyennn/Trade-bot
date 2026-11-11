// Mirrors the backend contracts in src/contracts. Field names match the OpenAPI schema;
// tests/contract/test_frontend_types.py checks that they stay in step.

export type EventCategory =
  | "tariffs_trade"
  | "energy_oil"
  | "technology_semiconductors"
  | "defence"
  | "banking_monetary_policy"
  | "immigration_employment"
  | "government_spending"
  | "sanctions_international";

export type EventWindow = "5m" | "15m" | "30m" | "1h" | "4h" | "1d" | "close_to_close";
export type DataQuality = "consolidated" | "delayed" | "partial_venue" | "synthetic";
export type Direction = "up" | "down" | "flat";
export type SignalAction = "buy" | "sell" | "no_trade";
export type StrategyName = "immediate_reaction" | "momentum_continuation" | "mean_reversion";
export type OrderSide = "buy" | "sell";
export type OrderStatus = "pending" | "submitted" | "filled" | "rejected" | "cancelled" | "blocked";
export type Interval = "1d" | "1h" | "30m" | "15m" | "5m" | "1m";

export interface SocialPost {
  post_id: string;
  source: string;
  account: string;
  text: string;
  url: string;
  published_at: string;
  retrieved_at: string;
  ingestion_mode: "historical" | "live";
  is_repost: boolean;
  reposted_from: string | null;
  has_media: boolean;
  media_urls: string[];
  content_hash: string;
  version: number;
  is_edited: boolean;
  is_deleted: boolean;
}

export interface Entity {
  text: string;
  type: "company" | "ticker" | "country" | "industry" | "commodity" | "government_body";
  symbol: string | null;
}

export interface MarketEvent {
  event_id: string;
  post_ids: string[];
  text: string;
  published_at: string;
  available_at: string;
  categories: EventCategory[];
  entities: Entity[];
  symbols: string[];
  relevance_score: number;
  classifier_version: string;
}

export interface StockCandle {
  symbol: string;
  interval: Interval;
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  adjusted: boolean;
  source: string;
  quality: DataQuality;
}

export interface UniverseMember {
  symbol: string;
  name: string;
  kind: "stock" | "etf";
  sector: string;
  themes: EventCategory[];
  eligible_from: string;
  eligible_to: string | null;
}

export interface MarketFeature {
  event_id: string;
  symbol: string;
  window: EventWindow;
  anchor_ts: string;
  entry_ts: string | null;
  exit_ts: string | null;
  entry_price: number | null;
  exit_price: number | null;
  ret: number | null;
  benchmark_ret: number | null;
  abnormal_ret: number | null;
  realized_vol: number | null;
  volume_ratio: number | null;
  tradable: boolean;
  shifted_to_open: boolean;
  available: boolean;
  unavailable_reason: string | null;
  quality: DataQuality;
}

export interface ModelPrediction {
  prediction_id: string;
  event_id: string;
  symbol: string;
  window: EventWindow;
  model_name: string;
  model_version: string;
  predicted_at: string;
  direction: Direction;
  prob_up: number;
  expected_abnormal_return: number;
  prob_high_vol: number | null;
  confidence: number;
}

export interface TradingSignal {
  signal_id: string;
  event_id: string;
  symbol: string;
  strategy: StrategyName;
  action: SignalAction;
  generated_at: string;
  target_weight: number;
  holding_window: EventWindow;
  stop_loss_pct: number | null;
  reason: string;
  prediction_id: string | null;
}

export interface BacktestMetrics {
  cumulative_return: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown: number;
  win_rate: number | null;
  profit_factor: number | null;
  turnover: number;
  trade_count: number;
}

export interface EquityPoint {
  ts: string;
  equity: number;
}

export interface BacktestTrade {
  signal_id: string;
  event_id: string;
  symbol: string;
  side: OrderSide;
  qty: number;
  signal_ts: string;
  entry_ts: string;
  entry_price: number;
  exit_ts: string;
  exit_price: number;
  costs: number;
  pnl: number;
  return_pct: number;
  exit_reason: "holding_period" | "stop_loss" | "end_of_data";
  categories: string[];
}

export interface BacktestSummary {
  run_id: string;
  strategy: StrategyName;
  created_at: string;
  period_start: string;
  period_end: string;
  metrics: BacktestMetrics;
  benchmark_symbol: string;
  benchmark_metrics: BacktestMetrics | null;
  signal_count: number;
  no_trade_count: number;
  data_quality: DataQuality;
}

export interface BacktestResult extends BacktestSummary {
  config: Record<string, unknown>;
  initial_equity: number;
  by_category: Record<string, BacktestMetrics>;
  equity_curve: EquityPoint[];
  benchmark_curve: EquityPoint[];
  trades: BacktestTrade[];
  no_trade_reasons: Record<string, number>;
  assumptions: string[];
}

export interface OrderStatusChange {
  status: OrderStatus;
  at: string;
  note: string;
}

export interface PaperOrder {
  order_id: string;
  client_order_id: string;
  signal_id: string;
  symbol: string;
  side: OrderSide;
  qty: number;
  status: OrderStatus;
  broker: "simulator" | "alpaca-paper";
  created_at: string;
  submitted_at: string | null;
  filled_at: string | null;
  filled_price: number | null;
  reject_reason: string | null;
  history: OrderStatusChange[];
}

export interface Position {
  symbol: string;
  qty: number;
  avg_price: number;
  market_value: number | null;
}

export interface Portfolio {
  broker: string;
  cash: number;
  equity: number;
  day_pnl: number;
  gross_exposure: number;
  positions: Position[];
}

export interface RiskState {
  kill_switch: boolean;
  daily_loss_limit_pct: number;
  day: string;
  day_start_equity: number;
  equity: number;
  day_pnl: number;
  loss_limit_breached: boolean;
  market_open: boolean;
  enforce_market_hours: boolean;
}

export interface SystemStatus {
  posts: number;
  latest_post_at: string | null;
  events: number;
  features: number;
  candles: number;
  candle_intervals: string[];
  candle_quality: Record<string, number>;
  market_data_provider: string;
  market_data_quality: DataQuality | null;
  model_version: string | null;
  broker: string;
  kill_switch: boolean;
  market_open: boolean;
  paper_trading_only: boolean;
}

export interface EventDetail {
  event: MarketEvent;
  posts: SocialPost[];
  features: MarketFeature[];
  predictions: ModelPrediction[];
}

export interface WindowStats {
  window: EventWindow;
  tradable: boolean;
  n_events: number;
  mean_abnormal_ret: number | null;
  median_abnormal_ret: number | null;
  std_abnormal_ret: number | null;
  t_stat: number | null;
  p_value: number | null;
  share_positive: number | null;
  mean_abs_abnormal_ret: number | null;
  baseline_mean_abnormal_ret: number | null;
  excess_mean_abnormal_ret: number | null;
  excess_t_stat: number | null;
  excess_p_value: number | null;
  n_sessions: number | null;
  session_clustered_mean: number | null;
  session_clustered_t_stat: number | null;
  session_clustered_p_value: number | null;
}

export interface EventStudyReport {
  report_id: string;
  created_at: string;
  content_hash: string;
  classifier_version: string;
  benchmark_symbol: string;
  assumed_latency_seconds: number;
  decision_latency_seconds: number;
  period_start: string | null;
  period_end: string | null;
  events_total: number;
  events_measured: number;
  windows: EventWindow[];
  overall: WindowStats[];
  by_category: Record<string, WindowStats[]>;
  unavailable_by_window: Record<string, Record<string, number>>;
  data_quality: DataQuality;
  caveats: string[];
}

export interface SplitInfo {
  start: string | null;
  end: string | null;
  samples: number;
  events: number;
}

export type MetricMap = Record<string, number | null>;

export interface ModelReport {
  model_name: string;
  model_version: string;
  created_at: string;
  window: EventWindow;
  classifier_version: string;
  samples_total: number;
  events_total: number;
  splits: Record<string, SplitInfo>;
  selected_params: Record<string, unknown>;
  validation_metrics: MetricMap;
  test_metrics: MetricMap;
  baselines: MetricMap;
  magnitude_metrics: MetricMap;
  volatility_metrics: MetricMap;
  walk_forward_metrics: MetricMap;
  high_vol_threshold: number;
  beats_baseline: boolean;
  data_quality: DataQuality;
  caveats: string[];
}

export interface StreamMessage {
  type: "event" | "prediction" | "signal" | "order" | "status";
  data: unknown;
  ts: string;
}
