"""Shared strategy configuration, context, and signal construction."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field

from src.contracts import (
    EventWindow,
    MarketEvent,
    MarketFeature,
    ModelPrediction,
    SignalAction,
    StrategyName,
    TradingSignal,
)


class StrategyConfig(BaseModel):
    """Everything a strategy may be tuned with. Unused fields are ignored by a strategy."""

    holding_window: EventWindow = EventWindow.D1
    position_weight: float = Field(default=0.05, gt=0, le=1)
    stop_loss_pct: float | None = Field(default=0.03, gt=0, lt=1)
    allow_short: bool = True
    # Strategy A
    min_confidence: float = Field(default=0.10, ge=0, le=1)
    # Strategies B and C: the initial move that is observed before deciding
    trigger_window: EventWindow = EventWindow.D1
    momentum_threshold: float = Field(default=0.005, gt=0)
    reversion_threshold: float = Field(default=0.015, gt=0)


@dataclass(frozen=True)
class StrategyContext:
    """What a strategy is allowed to know when it decides."""

    event: MarketEvent
    symbol: str
    decision_time: datetime
    prediction: ModelPrediction | None = None
    trigger: MarketFeature | None = None


class Strategy(Protocol):
    name: StrategyName
    config: StrategyConfig

    def decide(self, context: StrategyContext) -> TradingSignal: ...


def signal_id(strategy: StrategyName, event_id: str, symbol: str) -> str:
    """Deterministic, so the same decision is never turned into two orders."""
    digest = hashlib.sha256(f"{strategy.value}:{event_id}:{symbol}".encode()).hexdigest()
    return f"sig_{digest[:20]}"


def make_signal(
    strategy: StrategyName,
    config: StrategyConfig,
    context: StrategyContext,
    action: SignalAction,
    reason: str,
    generated_at: datetime | None = None,
) -> TradingSignal:
    if action is SignalAction.SELL and not config.allow_short:
        action, reason = SignalAction.NO_TRADE, f"short selling disabled ({reason})"
    trade = action is not SignalAction.NO_TRADE
    return TradingSignal(
        signal_id=signal_id(strategy, context.event.event_id, context.symbol),
        event_id=context.event.event_id,
        symbol=context.symbol,
        strategy=strategy,
        action=action,
        generated_at=generated_at or context.decision_time,
        target_weight=config.position_weight if trade else 0.0,
        holding_window=config.holding_window,
        stop_loss_pct=config.stop_loss_pct if trade else None,
        reason=reason,
        prediction_id=context.prediction.prediction_id if context.prediction else None,
    )
