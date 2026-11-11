import type {
  BacktestResult,
  BacktestSummary,
  EventCategory,
  EventDetail,
  EventStudyReport,
  Interval,
  MarketEvent,
  MarketFeature,
  ModelPrediction,
  ModelReport,
  PaperOrder,
  Portfolio,
  RiskState,
  SocialPost,
  StockCandle,
  StrategyName,
  SystemStatus,
  TradingSignal,
  UniverseMember,
} from "./types";

const BASE = (import.meta.env?.VITE_API_BASE as string | undefined) ?? "";

/** An HTTP error from the API. `status` 404 means "nothing there yet", not a failure. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

function buildUrl(path: string, params?: Params): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  const suffix = query.toString();
  return `${BASE}${path}${suffix ? `?${suffix}` : ""}`;
}

async function request<T>(path: string, init?: RequestInit, params?: Params): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, params), {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the TradeBot API. Is the backend running?");
  }
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // The body was not JSON; keep the generic message.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

const get = <T>(path: string, params?: Params) => request<T>(path, undefined, params);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  status: () => get<SystemStatus>("/api/v1/status"),
  posts: (params?: { limit?: number; q?: string }) => get<SocialPost[]>("/api/v1/posts", params),
  events: (params?: { limit?: number; category?: EventCategory | ""; symbol?: string }) =>
    get<MarketEvent[]>("/api/v1/events", params),
  event: (eventId: string) => get<EventDetail>(`/api/v1/events/${encodeURIComponent(eventId)}`),
  universe: () => get<UniverseMember[]>("/api/v1/universe"),
  candles: (symbol: string, interval: Interval, limit = 500) =>
    get<StockCandle[]>("/api/v1/market/candles", { symbol, interval, limit }),
  features: (params: { symbol?: string; event_id?: string; limit?: number }) =>
    get<MarketFeature[]>("/api/v1/market/features", params),
  eventStudy: () => get<EventStudyReport>("/api/v1/research/event-study"),
  backtests: () => get<BacktestSummary[]>("/api/v1/backtests"),
  backtest: (runId: string) =>
    get<BacktestResult>(`/api/v1/backtests/${encodeURIComponent(runId)}`),
  runBacktest: (strategy: StrategyName) =>
    post<BacktestResult>("/api/v1/backtests/run", { strategy }),
  models: () => get<ModelReport[]>("/api/v1/models"),
  predictions: (params?: { limit?: number; symbol?: string }) =>
    get<ModelPrediction[]>("/api/v1/predictions", params),
  signals: (params?: { limit?: number; trades_only?: boolean; strategy?: StrategyName }) =>
    get<TradingSignal[]>("/api/v1/signals", params),
  orders: () => get<PaperOrder[]>("/api/v1/trading/orders"),
  portfolio: () => get<Portfolio>("/api/v1/trading/portfolio"),
  risk: () => get<RiskState>("/api/v1/trading/risk"),
  setKillSwitch: (enabled: boolean) =>
    post<RiskState>("/api/v1/trading/kill-switch", { enabled }),
};

export function streamUrl(): string {
  if (BASE) return `${BASE.replace(/^http/, "ws")}/api/v1/stream`;
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/v1/stream`;
}
