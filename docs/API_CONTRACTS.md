# API contracts

The shared contracts are Pydantic models in `src/contracts`. The OpenAPI document served at
`/openapi.json` is generated from them and is the authoritative schema. Field-level detail is
in [the data model](../specs/001-event-research-platform/data-model.md).

## Shared contracts

| Contract | Module | Produced by | Consumed by |
|----------|--------|-------------|-------------|
| `SocialPost` | `contracts/posts.py` | pipelines.posts | pipelines.events, api |
| `MarketEvent` | `contracts/posts.py` | pipelines.events | features, ml, strategies, api |
| `StockCandle` | `contracts/market.py` | market_data.providers | market_data.store, api |
| `MarketFeature` | `contracts/market.py` | market_data.windows | event study, ml, strategies, api |
| `ModelPrediction` | `contracts/signals.py` | ml.baseline, ml.inference | strategies, api |
| `TradingSignal` | `contracts/signals.py` | strategies | backtesting, trading, api |
| `BacktestResult` | `contracts/trading.py` | backtesting.runner | api |
| `PaperOrder` | `contracts/trading.py` | trading.service | api |

Supporting models: `Entity`, `UniverseMember`, `BacktestMetrics`, `BacktestTrade`,
`EquityPoint`, `OrderStatusChange`. Enumerations: `IngestionMode`, `EventCategory`,
`EntityType`, `DataQuality`, `EventWindow`, `Direction`, `SignalAction`, `StrategyName`,
`OrderSide`, `OrderStatus`.

Rules built into the contracts:

- Unknown fields are rejected (`extra="forbid"`).
- Every datetime must carry a timezone and is normalised to UTC.
- `MarketEvent` needs at least one category.
- `StockCandle` must satisfy `low <= open, close <= high`, with an upper-case symbol.
- An unavailable `MarketFeature` must state why. A tradable one cannot be entered before
  its anchor.
- A `no_trade` `TradingSignal` has zero weight; a trade has a positive weight; every signal
  has a reason; the holding window must be tradable.
- A `BacktestTrade` cannot be entered before its signal or exit before its entry.
- A `PaperOrder` broker is `simulator` or `alpaca-paper`. A rejected or blocked order must
  give a reason. Quantity is positive, except that a blocked order may be zero when it was
  refused before it could be sized.

## HTTP endpoints

| Method | Path | Returns |
|--------|------|---------|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/ready` | Readiness with per-check detail |
| GET | `/api/v1/status` | Store counts, data quality, model version, broker, kill switch |
| GET | `/api/v1/posts` | `SocialPost[]` (filters `since`, `until`, `q`) |
| GET | `/api/v1/events` | `MarketEvent[]` (filters `category`, `symbol`, `since`, `until`) |
| GET | `/api/v1/events/{event_id}` | `EventDetail` |
| POST | `/api/v1/ingest/run` | `LiveCycleReport` |
| GET | `/api/v1/universe` | `UniverseMember[]` |
| GET | `/api/v1/market/candles` | `StockCandle[]` |
| GET | `/api/v1/market/features` | `MarketFeature[]` |
| GET | `/api/v1/research/event-study` | Latest `EventStudyReport`, or 404 |
| POST | `/api/v1/research/event-study/run` | `EventStudyReport` |
| GET | `/api/v1/backtests` | `BacktestSummary[]` |
| GET | `/api/v1/backtests/{run_id}` | `BacktestResult` |
| POST | `/api/v1/backtests/run` | `BacktestResult` |
| GET | `/api/v1/models` | `ModelReport[]` |
| POST | `/api/v1/models/predict` | `ModelPrediction[]`; 409 with no model or a version mismatch |
| GET | `/api/v1/predictions` | `ModelPrediction[]` |
| GET | `/api/v1/signals` | `TradingSignal[]` |
| GET, POST | `/api/v1/trading/orders` | `PaperOrder[]`; submit a `TradingSignal`, get a `PaperOrder` |
| GET | `/api/v1/trading/positions` | `Position[]` |
| GET | `/api/v1/trading/portfolio` | `Portfolio` |
| GET | `/api/v1/trading/risk` | `RiskState` |
| POST | `/api/v1/trading/kill-switch` | `RiskState` |
| POST | `/api/v1/trading/reconcile` | `ReconcileReport` |
| WS | `/api/v1/stream` | `{type, data, ts}` with type `event`, `prediction`, `signal`, `order`, `status` |

Conventions: list endpoints take `limit` (1 to 500) and `offset`; an empty store returns an
empty list; a missing resource returns 404; invalid input returns 422.

## How drift is caught

| Check | Test |
|-------|------|
| Contract validation rules | `tests/contract/test_contracts.py` |
| Every documented path is served, and no undocumented one | `tests/contract/test_openapi.py` |
| Schema fields equal model fields | `tests/contract/test_openapi.py` |
| TypeScript interfaces and unions equal the models and enums | `tests/contract/test_frontend_types.py` |

## Change log

| Date | Change | Reason |
|------|--------|--------|
| 2026-11-11 | Initial contracts | Phase 1 |
| 2026-11-11 | `EventWindow` gained `close_to_close` (descriptive, not tradable) | Measure the full reaction including the overnight gap without presenting it as tradable |
| 2026-11-11 | `MarketFeature` gained `tradable` and `shifted_to_open` | Make the two facts above explicit to consumers |
| 2026-11-11 | `PaperOrder.qty` may be 0 for a blocked order | An order refused before sizing has no meaningful quantity |
| 2026-11-11 | `BacktestResult` gained `benchmark_curve`, `no_trade_reasons`, `signal_count`, `initial_equity`, `created_at` | Needed by the dashboard and for auditability |
| 2026-11-11 | Added `POST /api/v1/trading/reconcile` | Expose reconciliation |
