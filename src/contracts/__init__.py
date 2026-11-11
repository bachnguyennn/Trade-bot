"""Shared data contracts. Every module exchanges data through these models."""

from src.contracts.base import Contract, UtcDatetime
from src.contracts.enums import (
    DataQuality,
    Direction,
    EntityType,
    EventCategory,
    EventWindow,
    IngestionMode,
    OrderSide,
    OrderStatus,
    SignalAction,
    StrategyName,
)
from src.contracts.market import Interval, MarketFeature, StockCandle, UniverseMember
from src.contracts.posts import Entity, MarketEvent, SocialPost
from src.contracts.signals import ModelPrediction, TradingSignal
from src.contracts.trading import (
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    BrokerName,
    EquityPoint,
    OrderStatusChange,
    PaperOrder,
)

__all__ = [
    "BacktestMetrics",
    "BacktestResult",
    "BacktestTrade",
    "BrokerName",
    "Contract",
    "DataQuality",
    "Direction",
    "Entity",
    "EntityType",
    "EquityPoint",
    "EventCategory",
    "EventWindow",
    "IngestionMode",
    "Interval",
    "MarketEvent",
    "MarketFeature",
    "ModelPrediction",
    "OrderSide",
    "OrderStatus",
    "OrderStatusChange",
    "PaperOrder",
    "SignalAction",
    "SocialPost",
    "StockCandle",
    "StrategyName",
    "TradingSignal",
    "UniverseMember",
    "UtcDatetime",
]
