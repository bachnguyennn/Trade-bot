"""Universe, candles, and window features."""

from __future__ import annotations

from datetime import datetime

import polars as pl
from fastapi import APIRouter, HTTPException, Query

from src.api.deps import Limit, Offset, ServicesDep, page
from src.contracts import EventWindow, Interval, MarketFeature, StockCandle, UniverseMember
from src.core.storage import from_frame, read_parquet

router = APIRouter(prefix="/api/v1", tags=["market"])

MAX_CANDLES = 5000


@router.get("/universe", response_model=list[UniverseMember])
def universe(services: ServicesDep) -> list[UniverseMember]:
    return services.universe.members


@router.get("/market/candles", response_model=list[StockCandle])
def candles(
    services: ServicesDep,
    symbol: str,
    interval: Interval = "1d",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=1000, ge=1, le=MAX_CANDLES),
) -> list[StockCandle]:
    """Stored candles, oldest first. Returns the most recent `limit` bars in the range."""
    symbol = symbol.upper()
    if symbol not in services.universe:
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the universe")
    frame = services.candle_store().read(symbol, interval, start, end)
    return from_frame(frame.tail(limit), StockCandle)


@router.get("/market/features", response_model=list[MarketFeature])
def features(
    services: ServicesDep,
    limit: Limit = 200,
    offset: Offset = 0,
    event_id: str | None = None,
    symbol: str | None = None,
    window: EventWindow | None = None,
    available_only: bool = False,
) -> list[MarketFeature]:
    frame = read_parquet(services.paths.gold_features, MarketFeature)
    if event_id:
        frame = frame.filter(pl.col("event_id") == event_id)
    if symbol:
        frame = frame.filter(pl.col("symbol") == symbol.upper())
    if window is not None:
        frame = frame.filter(pl.col("window") == window.value)
    if available_only:
        frame = frame.filter(pl.col("available"))
    frame = frame.sort("anchor_ts", descending=True)
    return from_frame(page(frame, limit, offset), MarketFeature)
