"""Backtest and paper-order contracts."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from src.contracts.base import Contract, UtcDatetime
from src.contracts.enums import (
    DataQuality,
    OrderSide,
    OrderStatus,
    StrategyName,
)

BrokerName = Literal["simulator", "alpaca-paper"]


class BacktestMetrics(Contract):
    """Performance summary. Ratios are null when they cannot be computed."""

    cumulative_return: float
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown: float
    win_rate: float | None = None
    profit_factor: float | None = None
    turnover: float
    trade_count: int = Field(ge=0)


class EquityPoint(Contract):
    ts: UtcDatetime
    equity: float


class BacktestTrade(Contract):
    """One round trip in a backtest."""

    signal_id: str
    event_id: str
    symbol: str
    side: OrderSide
    qty: float = Field(gt=0)
    signal_ts: UtcDatetime
    entry_ts: UtcDatetime
    entry_price: float = Field(gt=0)
    exit_ts: UtcDatetime
    exit_price: float = Field(gt=0)
    costs: float = Field(ge=0)
    pnl: float
    return_pct: float
    exit_reason: Literal["holding_period", "stop_loss", "end_of_data"]
    categories: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.entry_ts < self.signal_ts:
            raise ValueError("a trade cannot be entered before its signal time")
        if self.exit_ts < self.entry_ts:
            raise ValueError("a trade cannot exit before it is entered")
        return self


class BacktestResult(Contract):
    """Outcome of running one strategy configuration over a period."""

    run_id: str = Field(min_length=1)
    strategy: StrategyName
    config: dict[str, Any]
    created_at: UtcDatetime
    period_start: UtcDatetime
    period_end: UtcDatetime
    initial_equity: float = Field(gt=0)
    metrics: BacktestMetrics
    benchmark_symbol: str
    benchmark_metrics: BacktestMetrics | None = None
    by_category: dict[str, BacktestMetrics] = Field(default_factory=dict)
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    benchmark_curve: list[EquityPoint] = Field(default_factory=list)
    trades: list[BacktestTrade] = Field(default_factory=list)
    signal_count: int = Field(ge=0)
    no_trade_count: int = Field(ge=0)
    no_trade_reasons: dict[str, int] = Field(default_factory=dict)
    assumptions: list[str] = Field(min_length=1)
    data_quality: DataQuality


class OrderStatusChange(Contract):
    status: OrderStatus
    at: UtcDatetime
    note: str = ""


class PaperOrder(Contract):
    """A simulated order derived from a signal. Never a real-money order."""

    order_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    signal_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: OrderSide
    # Positive for any order sent to a broker. A blocked order may be 0 when it was
    # refused before it could be sized (for example, no price was available).
    qty: float = Field(ge=0)
    status: OrderStatus
    broker: BrokerName
    created_at: UtcDatetime
    submitted_at: UtcDatetime | None = None
    filled_at: UtcDatetime | None = None
    filled_price: float | None = Field(default=None, gt=0)
    reject_reason: str | None = None
    history: list[OrderStatusChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_state(self) -> Self:
        if self.qty <= 0 and self.status is not OrderStatus.BLOCKED:
            raise ValueError("qty must be positive unless the order is blocked")
        if self.status in {OrderStatus.REJECTED, OrderStatus.BLOCKED} and not self.reject_reason:
            raise ValueError("reject_reason is required for rejected and blocked orders")
        if self.status is OrderStatus.FILLED and (
            self.filled_price is None or self.filled_at is None
        ):
            raise ValueError("a filled order needs filled_price and filled_at")
        return self
