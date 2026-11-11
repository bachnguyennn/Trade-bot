import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "../App";
import { EventFeed } from "../pages/EventFeed";
import { MarketAnalysis } from "../pages/MarketAnalysis";
import { ModelAnalytics } from "../pages/ModelAnalytics";
import { Overview } from "../pages/Overview";
import { PaperTrading } from "../pages/PaperTrading";
import { StrategyResearch } from "../pages/StrategyResearch";

type Routes = Record<string, unknown>;

const EMPTY_STATUS = {
  posts: 0,
  latest_post_at: null,
  events: 0,
  features: 0,
  candles: 0,
  candle_intervals: [],
  candle_quality: {},
  market_data_provider: "yfinance",
  market_data_quality: null,
  model_version: null,
  broker: "simulator",
  kill_switch: false,
  market_open: false,
  paper_trading_only: true,
};

/** What the API returns when nothing has been ingested or computed. */
const EMPTY_API: Routes = {
  "/api/v1/status": EMPTY_STATUS,
  "/api/v1/posts": [],
  "/api/v1/events": [],
  "/api/v1/universe": [],
  "/api/v1/market/candles": [],
  "/api/v1/market/features": [],
  "/api/v1/research/event-study": 404,
  "/api/v1/backtests": [],
  "/api/v1/models": [],
  "/api/v1/predictions": [],
  "/api/v1/signals": [],
  "/api/v1/trading/orders": [],
};

function mockApi(routes: Routes) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname;
    const body = routes[path];
    if (body === undefined || body === 404) {
      return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    }
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mockApiDown() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }),
  );
}

async function settled() {
  await waitFor(() => expect(screen.queryAllByTestId("loading")).toHaveLength(0));
}

/** Percentages, currency amounts, and basis points: anything that reads as a result. */
const FINANCIAL_VALUE = /-?\d[\d,]*(\.\d+)?\s?%|\$\s?\d|\d\s?bps/;

const PAGES = [
  ["Overview", Overview],
  ["Political Event Feed", EventFeed],
  ["Stock Market Analysis", MarketAnalysis],
  ["Strategy Research", StrategyResearch],
  ["Model Analytics", ModelAnalytics],
] as const;

describe("empty data store", () => {
  it.each(PAGES)("%s shows empty states and no financial values", async (_name, Page) => {
    mockApi(EMPTY_API);
    const { container } = render(<Page refreshKey={0} />);
    await settled();
    expect(screen.getAllByTestId("empty-state").length).toBeGreaterThan(0);
    expect(screen.queryAllByTestId("error-state")).toHaveLength(0);
    expect(container.textContent ?? "").not.toMatch(FINANCIAL_VALUE);
  });

  it("Overview says none rather than showing zero counts", async () => {
    mockApi({
      ...EMPTY_API,
      "/api/v1/trading/portfolio": 404,
    });
    render(<Overview refreshKey={0} />);
    await settled();
    expect(screen.getAllByText("None").length).toBe(3);
    expect(screen.getByText("No model trained")).toBeInTheDocument();
    expect(screen.getByText("No posts collected yet")).toBeInTheDocument();
    expect(screen.getByText("No backtests have been run")).toBeInTheDocument();
    expect(screen.getByText("No trade signals")).toBeInTheDocument();
  });

  it("Paper Trading shows the real starting account and no positions or orders", async () => {
    mockApi({
      ...EMPTY_API,
      "/api/v1/trading/portfolio": {
        broker: "simulator",
        cash: 100000,
        equity: 100000,
        day_pnl: 0,
        gross_exposure: 0,
        positions: [],
      },
      "/api/v1/trading/risk": {
        kill_switch: false,
        daily_loss_limit_pct: 0.02,
        day: "2025-03-03",
        day_start_equity: 100000,
        equity: 100000,
        day_pnl: 0,
        loss_limit_breached: false,
        market_open: false,
        enforce_market_hours: true,
      },
    });
    render(<PaperTrading refreshKey={0} />);
    await settled();
    expect(screen.getByText("No open positions")).toBeInTheDocument();
    expect(screen.getByText("No paper orders yet")).toBeInTheDocument();
    expect(screen.getByText(/Paper trading only/)).toBeInTheDocument();
    expect(screen.getByText("Stop all new orders")).toBeInTheDocument();
  });
});

describe("backend unreachable", () => {
  it.each([...PAGES, ["Paper Trading", PaperTrading] as const])(
    "%s reports the connection problem",
    async (_name, Page) => {
      mockApiDown();
      const { container } = render(<Page refreshKey={0} />);
      await settled();
      const errors = screen.getAllByTestId("error-state");
      expect(errors.length).toBeGreaterThan(0);
      expect(within(errors[0]!).getByText(/Cannot reach the TradeBot API/)).toBeInTheDocument();
      expect(container.textContent ?? "").not.toMatch(FINANCIAL_VALUE);
    },
  );
});

describe("with data", () => {
  it("renders values exactly as the API returned them", async () => {
    mockApi({
      ...EMPTY_API,
      "/api/v1/backtests": [
        {
          run_id: "bt_1",
          strategy: "mean_reversion",
          created_at: "2025-03-03T00:00:00Z",
          period_start: "2024-01-02T14:30:00Z",
          period_end: "2024-12-31T21:00:00Z",
          metrics: {
            cumulative_return: -0.0323,
            sharpe_ratio: null,
            sortino_ratio: -0.81,
            max_drawdown: -0.0442,
            win_rate: 0.468,
            profit_factor: 0.874,
            turnover: 71.8,
            trade_count: 735,
          },
          benchmark_symbol: "SPY",
          benchmark_metrics: null,
          signal_count: 6868,
          no_trade_count: 6133,
          data_quality: "delayed",
        },
      ],
    });
    render(<Overview refreshKey={0} />);
    await settled();
    expect(screen.getByText("-3.23%")).toBeInTheDocument();
    expect(screen.getByText("-4.42%")).toBeInTheDocument();
    expect(screen.getByText("735")).toBeInTheDocument();
    // A missing ratio and a missing benchmark are dashes, not zeros.
    const row = screen.getByText("mean reversion").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row!).getAllByText("—")).toHaveLength(2);
  });
});

describe("app shell", () => {
  it("has the six sections and states the paper-trading limit", async () => {
    mockApi(EMPTY_API);
    render(<App />);
    await settled();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    for (const name of [
      "Overview",
      "Political Event Feed",
      "Stock Market Analysis",
      "Strategy Research",
      "Paper Trading",
      "Model Analytics",
    ]) {
      expect(within(nav).getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByText(/paper trading only/)).toBeInTheDocument();
  });
});
