"""Shared enumerations. Values are part of the public contract; do not rename."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum


class IngestionMode(StrEnum):
    HISTORICAL = "historical"
    LIVE = "live"


class EventCategory(StrEnum):
    TARIFFS_TRADE = "tariffs_trade"
    ENERGY_OIL = "energy_oil"
    TECHNOLOGY_SEMICONDUCTORS = "technology_semiconductors"
    DEFENCE = "defence"
    BANKING_MONETARY_POLICY = "banking_monetary_policy"
    IMMIGRATION_EMPLOYMENT = "immigration_employment"
    GOVERNMENT_SPENDING = "government_spending"
    SANCTIONS_INTERNATIONAL = "sanctions_international"


class EntityType(StrEnum):
    COMPANY = "company"
    TICKER = "ticker"
    COUNTRY = "country"
    INDUSTRY = "industry"
    COMMODITY = "commodity"
    GOVERNMENT_BODY = "government_body"


class DataQuality(StrEnum):
    """How far market data can be trusted as a full, timely picture of the market."""

    CONSOLIDATED = "consolidated"
    DELAYED = "delayed"
    PARTIAL_VENUE = "partial_venue"
    SYNTHETIC = "synthetic"

    @property
    def rank(self) -> int:
        """Higher is better. Used to report the lowest quality among inputs."""
        order = {
            DataQuality.SYNTHETIC: 0,
            DataQuality.PARTIAL_VENUE: 1,
            DataQuality.DELAYED: 2,
            DataQuality.CONSOLIDATED: 3,
        }
        return order[self]

    @staticmethod
    def lowest(values: list[DataQuality]) -> DataQuality:
        return min(values, key=lambda q: q.rank)


class EventWindow(StrEnum):
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    CLOSE_TO_CLOSE = "close_to_close"

    @property
    def is_intraday(self) -> bool:
        return self in _INTRADAY_DURATIONS

    @property
    def duration(self) -> timedelta:
        """Length of an intraday window. Daily windows are defined by sessions instead."""
        if self not in _INTRADAY_DURATIONS:
            raise ValueError(f"{self.value} is session-based and has no fixed duration")
        return _INTRADAY_DURATIONS[self]

    @property
    def tradable(self) -> bool:
        """False for windows that start before the information was available."""
        return self is not EventWindow.CLOSE_TO_CLOSE


_INTRADAY_DURATIONS: dict[EventWindow, timedelta] = {
    EventWindow.M5: timedelta(minutes=5),
    EventWindow.M15: timedelta(minutes=15),
    EventWindow.M30: timedelta(minutes=30),
    EventWindow.H1: timedelta(hours=1),
    EventWindow.H4: timedelta(hours=4),
}


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class SignalAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    NO_TRADE = "no_trade"


class StrategyName(StrEnum):
    IMMEDIATE_REACTION = "immediate_reaction"
    MOMENTUM_CONTINUATION = "momentum_continuation"
    MEAN_REVERSION = "mean_reversion"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
            OrderStatus.BLOCKED,
        }
