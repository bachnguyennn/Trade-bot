"""Prediction and signal contracts."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from src.contracts.base import Contract, UtcDatetime
from src.contracts.enums import Direction, EventWindow, SignalAction, StrategyName


class ModelPrediction(Contract):
    """A model's forecast for one event and symbol."""

    prediction_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    window: EventWindow
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    predicted_at: UtcDatetime
    direction: Direction
    prob_up: float = Field(ge=0.0, le=1.0)
    expected_abnormal_return: float
    prob_high_vol: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class TradingSignal(Contract):
    """A strategy's decision for one event and symbol. `no_trade` is a real outcome."""

    signal_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    strategy: StrategyName
    action: SignalAction
    generated_at: UtcDatetime
    target_weight: float = Field(ge=0.0, le=1.0)
    holding_window: EventWindow
    stop_loss_pct: float | None = Field(default=None, gt=0.0, lt=1.0)
    reason: str = Field(min_length=1)
    prediction_id: str | None = None

    @model_validator(mode="after")
    def _check_weight(self) -> Self:
        if self.action is SignalAction.NO_TRADE and self.target_weight != 0.0:
            raise ValueError("target_weight must be 0 for no_trade")
        if self.action is not SignalAction.NO_TRADE and self.target_weight <= 0.0:
            raise ValueError("target_weight must be positive for buy and sell")
        if not self.holding_window.tradable:
            raise ValueError("holding_window must be a tradable window")
        return self
