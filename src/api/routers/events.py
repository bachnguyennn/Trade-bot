"""Posts, events, and ingestion."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal

import polars as pl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.deps import Limit, Offset, ServicesDep, page
from src.contracts import (
    EventCategory,
    IngestionMode,
    MarketEvent,
    MarketFeature,
    ModelPrediction,
    SocialPost,
)
from src.core.storage import from_frame, read_parquet
from src.ingestion.http import FetchError
from src.ingestion.sources import SourceNotPermitted, build_source
from src.pipelines.live import LiveCycleReport, run_live_cycle

router = APIRouter(prefix="/api/v1", tags=["events"])


class EventDetail(BaseModel):
    event: MarketEvent
    posts: list[SocialPost]
    features: list[MarketFeature]
    predictions: list[ModelPrediction]


class IngestRequest(BaseModel):
    source: Literal["stiles", "cnn"] = "stiles"
    mode: IngestionMode = IngestionMode.LIVE
    submit_orders: bool = True


@router.get("/posts", response_model=list[SocialPost])
def list_posts(
    services: ServicesDep,
    limit: Limit = 50,
    offset: Offset = 0,
    since: datetime | None = None,
    until: datetime | None = None,
    q: str | None = None,
) -> list[SocialPost]:
    frame = read_parquet(services.paths.silver_posts, SocialPost)
    if since is not None:
        frame = frame.filter(pl.col("published_at") >= since)
    if until is not None:
        frame = frame.filter(pl.col("published_at") <= until)
    if q:
        frame = frame.filter(
            pl.col("text").str.to_lowercase().str.contains(q.lower(), literal=True)
        )
    frame = frame.sort("published_at", descending=True)
    return from_frame(page(frame, limit, offset), SocialPost)


@router.get("/events", response_model=list[MarketEvent])
def list_events(
    services: ServicesDep,
    limit: Limit = 50,
    offset: Offset = 0,
    category: EventCategory | None = None,
    symbol: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[MarketEvent]:
    frame = read_parquet(services.paths.gold_events, MarketEvent)
    if category is not None:
        frame = frame.filter(pl.col("categories").list.contains(category.value))
    if symbol:
        frame = frame.filter(pl.col("symbols").list.contains(symbol.upper()))
    if since is not None:
        frame = frame.filter(pl.col("available_at") >= since)
    if until is not None:
        frame = frame.filter(pl.col("available_at") <= until)
    frame = frame.sort("available_at", descending=True)
    return from_frame(page(frame, limit, offset), MarketEvent)


@router.get("/events/{event_id}", response_model=EventDetail)
def get_event(event_id: str, services: ServicesDep) -> EventDetail:
    paths = services.paths
    events = read_parquet(paths.gold_events, MarketEvent).filter(pl.col("event_id") == event_id)
    if events.height == 0:
        raise HTTPException(status_code=404, detail=f"event {event_id} not found")
    event = from_frame(events, MarketEvent)[0]
    posts = read_parquet(paths.silver_posts, SocialPost).filter(
        pl.col("post_id").is_in(event.post_ids)
    )
    features = read_parquet(paths.gold_features, MarketFeature).filter(
        pl.col("event_id") == event_id
    )
    predictions = read_parquet(paths.gold_predictions, ModelPrediction).filter(
        pl.col("event_id") == event_id
    )
    return EventDetail(
        event=event,
        posts=from_frame(posts.sort("published_at"), SocialPost),
        features=from_frame(features, MarketFeature),
        predictions=from_frame(predictions, ModelPrediction),
    )


@router.post("/ingest/run", response_model=LiveCycleReport)
def run_ingest(request: IngestRequest, services: ServicesDep) -> LiveCycleReport:
    """Fetch new posts and run them through events, predictions, signals, and paper orders."""
    try:
        source = build_source(request.source, services.settings)
    except SourceNotPermitted as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not services.pipeline_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="an ingestion run is already in progress")
    try:
        return asyncio.run(
            run_live_cycle(
                source,
                services.paths,
                services.settings,
                services.universe,
                services.inference,
                services.orders if request.submit_orders else None,
                services.broadcaster.publish,
                request.mode,
            )
        )
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        services.pipeline_lock.release()
