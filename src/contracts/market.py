"""Market data contracts."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from src.contracts.base import Contract, UtcDatetime
from src.contracts.enums import DataQuality, EventCategory, EventWindow

Interval = Literal["1d", "1h", "30m", "15m", "5m", "1m"]


class StockCandle(Contract):
    """Price and volume for one symbol over one interval."""

    symbol: str = Field(min_length=1)
    interval: Interval
    ts: UtcDatetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    adjusted: bool
    source: str = Field(min_length=1)
    quality: DataQuality

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.symbol != self.symbol.upper():
            raise ValueError("symbol must be upper case")
        # A small tolerance absorbs float noise from adjusted prices.
        tol = 1e-6 * self.high
        if self.low - tol > min(self.open, self.close) or self.high + tol < max(
            self.open, self.close
        ):
            raise ValueError("candle must satisfy low <= open, close <= high")
        return self


class UniverseMember(Contract):
    """A symbol the platform is allowed to study and trade."""

    symbol: str = Field(min_length=1)
    name: str
    kind: Literal["stock", "etf"]
    sector: str
    themes: list[EventCategory] = Field(default_factory=list)
    eligible_from: date
    eligible_to: date | None = None

    def is_eligible(self, on: date) -> bool:
        if on < self.eligible_from:
            return False
        return self.eligible_to is None or on <= self.eligible_to


class MarketFeature(Contract):
    """A measured outcome for one event, symbol, and window (Gold layer)."""

    event_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    window: EventWindow
    anchor_ts: UtcDatetime
    entry_ts: UtcDatetime | None = None
    exit_ts: UtcDatetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    ret: float | None = None
    benchmark_ret: float | None = None
    abnormal_ret: float | None = None
    realized_vol: float | None = None
    volume_ratio: float | None = None
    tradable: bool
    shifted_to_open: bool = False
    available: bool
    unavailable_reason: str | None = None
    quality: DataQuality

    @model_validator(mode="after")
    def _check_availability(self) -> Self:
        if not self.available and not self.unavailable_reason:
            raise ValueError("unavailable_reason is required when available is false")
        if self.available and (self.ret is None or self.entry_ts is None or self.exit_ts is None):
            raise ValueError("an available feature needs ret, entry_ts, and exit_ts")
        if (
            self.available
            and self.tradable
            and self.entry_ts is not None
            and self.entry_ts < self.anchor_ts
        ):
            raise ValueError("a tradable window cannot be entered before its anchor")
        return self
