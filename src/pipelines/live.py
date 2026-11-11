"""Live processing: new posts to events, predictions, signals, and paper orders.

One cycle fetches a source, rebuilds the event table, and handles each event that was not
there before. Only fresh events from live-collected posts may produce an order; anything
picked up as backfill is recorded but never traded.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import polars as pl
from pydantic import BaseModel

from src.contracts import (
    IngestionMode,
    MarketEvent,
    ModelPrediction,
    PaperOrder,
    SignalAction,
    SocialPost,
    TradingSignal,
)
from src.core.logging import get_logger
from src.core.settings import Settings
from src.core.storage import (
    DataPaths,
    from_frame,
    read_parquet,
    to_frame,
    write_parquet_atomic,
)
from src.core.timeutils import utc_now
from src.ingestion.sources import PostSource
from src.market_data.universe import Universe
from src.ml.inference import InferenceService, ModelUnavailable
from src.pipelines.events import build_events, load_events
from src.pipelines.posts import IngestReport, ingest_posts
from src.strategies import ImmediateReactionStrategy, StrategyConfig, StrategyContext
from src.strategies.base import make_signal
from src.trading.service import OrderService

log = get_logger(__name__)

Publisher = Callable[[str, Any], None]


class LiveCycleReport(BaseModel):
    ingest: IngestReport
    new_events: int
    predictions: int
    signals: int
    trade_signals: int
    orders: dict[str, int]
    model_version: str | None
    notes: list[str]


def _append(paths_file: Any, frame: pl.DataFrame, cls: type, key: str) -> None:
    existing = read_parquet(paths_file, cls)
    if existing.height:
        existing = existing.filter(~pl.col(key).is_in(frame[key].to_list()))
    write_parquet_atomic(pl.concat([existing, frame], how="vertical_relaxed"), paths_file)


def process_new_event(
    event: MarketEvent,
    live_post_ids: set[str],
    inference: InferenceService,
    strategy: ImmediateReactionStrategy,
    now: datetime,
    max_event_age: timedelta,
) -> tuple[list[ModelPrediction], list[TradingSignal], str | None]:
    """Predictions and signals for one new event. Returns a note when no model exists."""
    note: str | None = None
    is_live = event.post_ids[0] in live_post_ids
    predictions: list[ModelPrediction] = []
    if is_live:
        # Backfilled events may be part of the model's training data. Predicting them here
        # would store in-sample predictions next to the out-of-sample ones backtests rely on.
        try:
            predictions = inference.predict_event(event, predicted_at=now)
        except ModelUnavailable as exc:
            note = str(exc)
    by_symbol = {p.symbol: p for p in predictions}
    # A post collected just now may have been published long ago. Staleness is
    # measured from publication: the market has had that long to react.
    age = now - event.published_at
    signals: list[TradingSignal] = []
    for symbol in event.symbols:
        context = StrategyContext(
            event=event, symbol=symbol, decision_time=now, prediction=by_symbol.get(symbol)
        )
        if not is_live:
            signal = make_signal(
                strategy.name,
                strategy.config,
                context,
                SignalAction.NO_TRADE,
                "event comes from backfilled posts, not live collection",
            )
        elif age > max_event_age:
            signal = make_signal(
                strategy.name,
                strategy.config,
                context,
                SignalAction.NO_TRADE,
                f"event is stale (published {age.total_seconds():.0f}s ago)",
            )
        else:
            signal = strategy.decide(context)
        signals.append(signal)
    return predictions, signals, note


async def run_live_cycle(
    source: PostSource,
    paths: DataPaths,
    settings: Settings,
    universe: Universe,
    inference: InferenceService,
    orders: OrderService | None = None,
    publish: Publisher | None = None,
    mode: IngestionMode = IngestionMode.LIVE,
    max_event_age: timedelta = timedelta(minutes=30),
    strategy_config: StrategyConfig | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> LiveCycleReport:
    publish = publish or (lambda _type, _data: None)
    known_events = {e.event_id for e in load_events(paths)}

    ingest = await ingest_posts(source, mode, paths, settings)
    build_events(paths, settings, universe)
    new_events = [e for e in load_events(paths) if e.event_id not in known_events]

    posts = from_frame(read_parquet(paths.silver_posts, SocialPost), SocialPost)
    live_post_ids = {p.post_id for p in posts if p.ingestion_mode is IngestionMode.LIVE}
    strategy = ImmediateReactionStrategy(strategy_config)
    now = clock()

    all_predictions: list[ModelPrediction] = []
    all_signals: list[TradingSignal] = []
    order_counts: dict[str, int] = {}
    notes: list[str] = []
    for event in new_events:
        publish("event", event.model_dump(mode="json"))
        predictions, signals, note = process_new_event(
            event, live_post_ids, inference, strategy, now, max_event_age
        )
        if note and note not in notes:
            notes.append(note)
        for prediction in predictions:
            publish("prediction", prediction.model_dump(mode="json"))
        for signal in signals:
            publish("signal", signal.model_dump(mode="json"))
            if orders is not None and signal.action is not SignalAction.NO_TRADE:
                order: PaperOrder = orders.submit_signal(signal)
                order_counts[order.status.value] = order_counts.get(order.status.value, 0) + 1
        all_predictions.extend(predictions)
        all_signals.extend(signals)

    if all_predictions:
        _append(
            paths.gold_predictions,
            to_frame(all_predictions, ModelPrediction),
            ModelPrediction,
            "prediction_id",
        )
    if all_signals:
        _append(
            paths.gold_signals, to_frame(all_signals, TradingSignal), TradingSignal, "signal_id"
        )

    report = LiveCycleReport(
        ingest=ingest,
        new_events=len(new_events),
        predictions=len(all_predictions),
        signals=len(all_signals),
        trade_signals=sum(1 for s in all_signals if s.action is not SignalAction.NO_TRADE),
        orders=order_counts,
        model_version=inference.version,
        notes=notes,
    )
    log.info("live cycle finished", extra=report.model_dump(mode="json", exclude={"ingest"}))
    return report
