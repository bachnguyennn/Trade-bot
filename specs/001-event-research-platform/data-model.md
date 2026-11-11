# Data Model: TradeBot Event Research and Paper-Trading Platform

All timestamps are timezone-aware UTC. All contracts live in `src/contracts/` as Pydantic v2
models with `extra="forbid"`. Enumerations are string enums.

## Enumerations

| Enum | Values |
|------|--------|
| `IngestionMode` | `historical`, `live` |
| `EventCategory` | `tariffs_trade`, `energy_oil`, `technology_semiconductors`, `defence`, `banking_monetary_policy`, `immigration_employment`, `government_spending`, `sanctions_international` |
| `EntityType` | `company`, `ticker`, `country`, `industry`, `commodity`, `government_body` |
| `DataQuality` | `consolidated`, `delayed`, `partial_venue`, `synthetic` |
| `EventWindow` | `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `close_to_close` |
| `Direction` | `up`, `down`, `flat` |
| `SignalAction` | `buy`, `sell`, `no_trade` |
| `StrategyName` | `immediate_reaction`, `momentum_continuation`, `mean_reversion` |
| `OrderSide` | `buy`, `sell` |
| `OrderStatus` | `pending`, `submitted`, `filled`, `rejected`, `cancelled`, `blocked` |

## SocialPost

One post from the monitored account (Silver layer).

| Field | Type | Rule |
|-------|------|------|
| `post_id` | str | Source ID; unique key |
| `source` | str | Name of the data source |
| `account` | str | Monitored account handle |
| `text` | str | Plain text with HTML removed; may be empty for media-only posts |
| `url` | str | Link to the original post |
| `published_at` | datetime | Required, UTC |
| `retrieved_at` | datetime | Required, UTC; time of the first fetch that saw this post |
| `ingestion_mode` | IngestionMode | `historical` for backfill, `live` for incremental |
| `is_repost` | bool | True when the post is a repost or quotes another account only |
| `reposted_from` | str or null | Original account when known |
| `has_media` | bool | |
| `media_urls` | list[str] | |
| `content_hash` | str | SHA-256 of normalised text |
| `version` | int | Starts at 1; increments when the text changes |
| `is_edited` | bool | True when `version > 1` |
| `is_deleted` | bool | True when a later fetch of a full archive no longer contains it |

Validation: `published_at` and `retrieved_at` must be timezone-aware. A raw record without a
parseable publication time stays in Bronze and is listed in the rejection report.

Availability rule (`src/core/timeutils.py`): `live` posts are available at `retrieved_at`;
`historical` posts at `published_at + assumed_latency`.

## MarketEvent

A market-relevant post or cluster of posts (Gold layer).

| Field | Type | Rule |
|-------|------|------|
| `event_id` | str | Deterministic hash of the first post ID and classifier version |
| `post_ids` | list[str] | One or more, in time order |
| `text` | str | Text of the anchor post |
| `published_at` | datetime | Of the anchor post |
| `available_at` | datetime | Availability time of the anchor post |
| `categories` | list[EventCategory] | At least one |
| `entities` | list[Entity] | `Entity{text, type, symbol?}` |
| `symbols` | list[str] | Affected symbols in the universe; may be empty |
| `relevance_score` | float | 0 to 1 |
| `classifier_version` | str | |

Relationships: one event to many posts; one event to many features, predictions, signals.

## StockCandle

| Field | Type | Rule |
|-------|------|------|
| `symbol` | str | Upper case |
| `interval` | str | `1d`, `1h`, `30m`, `15m`, `5m`, `1m` |
| `ts` | datetime | Bar start, UTC |
| `open`, `high`, `low`, `close` | float | Positive; `low <= open, close <= high` |
| `volume` | float | Non-negative |
| `adjusted` | bool | True when adjusted for splits and dividends |
| `source` | str | Provider name |
| `quality` | DataQuality | Never upgraded after storage |

Key: (`symbol`, `interval`, `ts`).

## UniverseMember

| Field | Type | Rule |
|-------|------|------|
| `symbol` | str | |
| `name` | str | |
| `kind` | str | `stock` or `etf` |
| `sector` | str | |
| `themes` | list[EventCategory] | Categories the symbol is exposed to |
| `eligible_from` | date | Not traded or studied before this date |
| `eligible_to` | date or null | Null when still listed |

## MarketFeature

A measured outcome for one event, symbol, and window (Gold layer).

| Field | Type | Rule |
|-------|------|------|
| `event_id`, `symbol`, `window` | | Composite key |
| `anchor_ts` | datetime | `available_at + decision_latency` |
| `entry_ts`, `exit_ts` | datetime or null | |
| `entry_price`, `exit_price` | float or null | |
| `ret`, `benchmark_ret`, `abnormal_ret` | float or null | |
| `realized_vol` | float or null | Standard deviation of bar returns in the window |
| `volume_ratio` | float or null | Window volume over trailing average |
| `tradable` | bool | False for `close_to_close` |
| `shifted_to_open` | bool | True when the anchor was outside the session |
| `available` | bool | False when data is incomplete |
| `unavailable_reason` | str or null | Required when `available` is false |
| `quality` | DataQuality | Lowest quality among bars used |

## ModelPrediction

| Field | Type | Rule |
|-------|------|------|
| `prediction_id` | str | |
| `event_id`, `symbol`, `window` | | |
| `model_name`, `model_version` | str | Version is required |
| `predicted_at` | datetime | Must be at or after the event's `available_at` |
| `direction` | Direction | |
| `prob_up` | float | 0 to 1 |
| `expected_abnormal_return` | float | |
| `prob_high_vol` | float or null | 0 to 1 |
| `confidence` | float | 0 to 1; `abs(prob_up - 0.5) * 2` for the baseline |

## TradingSignal

| Field | Type | Rule |
|-------|------|------|
| `signal_id` | str | Deterministic from strategy, event, symbol; used for idempotency |
| `event_id`, `symbol` | | |
| `strategy` | StrategyName | |
| `action` | SignalAction | `no_trade` is a first-class outcome |
| `generated_at` | datetime | Earliest time the decision could be made |
| `target_weight` | float | Fraction of equity; 0 for `no_trade` |
| `holding_window` | EventWindow | |
| `stop_loss_pct` | float or null | |
| `reason` | str | Required |
| `prediction_id` | str or null | |

## BacktestResult

| Field | Type | Rule |
|-------|------|------|
| `run_id` | str | |
| `strategy` | StrategyName | |
| `config` | dict | Full strategy and execution configuration |
| `created_at` | datetime | |
| `period_start`, `period_end` | datetime | |
| `initial_equity` | float | Positive |
| `metrics` | BacktestMetrics | cumulative return, Sharpe, Sortino, max drawdown, win rate, profit factor, turnover, trade count |
| `benchmark_symbol` | str | |
| `benchmark_metrics` | BacktestMetrics or null | Buy-and-hold of the benchmark over the same period |
| `by_category` | dict[str, BacktestMetrics] | |
| `equity_curve`, `benchmark_curve` | list[EquityPoint] | `{ts, equity}` |
| `trades` | list[BacktestTrade] | Entry, exit, costs, exit reason |
| `signal_count`, `no_trade_count` | int | |
| `no_trade_reasons` | dict[str, int] | Why signals were not traded |
| `assumptions` | list[str] | Costs, slippage, latency, data quality, known biases |
| `data_quality` | DataQuality | |

## PaperOrder

| Field | Type | Rule |
|-------|------|------|
| `order_id` | str | |
| `client_order_id` | str | Equal to `signal_id`; unique |
| `signal_id` | str | |
| `symbol`, `side`, `qty` | | `qty > 0`, except that a `blocked` order may be 0 when it was refused before sizing |
| `status` | OrderStatus | |
| `broker` | str | `simulator` or `alpaca-paper` |
| `created_at` | datetime | |
| `submitted_at`, `filled_at` | datetime or null | |
| `filled_price` | float or null | |
| `reject_reason` | str or null | Required for `rejected` and `blocked` |
| `history` | list[OrderStatusChange] | `{status, at, note}` |

State transitions: `pending -> submitted -> filled`; `pending -> blocked` (no-trade signal,
kill switch, market closed, loss limit, no price); `pending -> rejected` (broker refusal or
unreachable); `submitted -> rejected`; `submitted -> cancelled`.
No transition leaves `filled`, `rejected`, `cancelled`, or `blocked`.

## Storage Layout

| Layer | Path | Content |
|-------|------|---------|
| Bronze | `data/bronze/posts/<source>/<fetch_ts>.parquet` | Raw records as fetched, plus fetch metadata |
| Silver | `data/silver/posts.parquet` | `SocialPost` rows |
| Silver | `data/silver/candles/<interval>/<symbol>.parquet` | `StockCandle` rows |
| Gold | `data/gold/events.parquet` | `MarketEvent` rows |
| Gold | `data/gold/features.parquet` | `MarketFeature` rows |
| Gold | `data/gold/predictions.parquet` | Out-of-sample `ModelPrediction` rows |
| Gold | `data/gold/signals.parquet` | Latest `TradingSignal` rows per strategy |
| Silver | `data/silver/post_rejections.parquet` | Rejected raw records with reasons |
| Reports | `data/reports/event_study/*.json`, `data/reports/models/*.json`, `data/reports/backtests/*.json` | Reproducible outputs |
| Models | `data/models/<name>/<version>/` | Fitted model and metadata |
| State | `data/state/orders.sqlite` | Paper orders and risk state |
