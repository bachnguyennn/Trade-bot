"""Gold features: window measurements for every event and affected symbol."""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel

from src.contracts import DataQuality, EventWindow, MarketFeature
from src.core.logging import get_logger
from src.core.settings import Settings
from src.core.storage import DataPaths, from_frame, read_parquet, to_frame, write_parquet_atomic
from src.market_data.calendar import TradingCalendar
from src.market_data.store import CandleStore
from src.market_data.universe import Universe
from src.market_data.windows import WindowCalculator
from src.pipelines.events import load_events

log = get_logger(__name__)


class FeatureBuildReport(BaseModel):
    events: int
    features_total: int
    features_available: int
    available_by_window: dict[str, int]
    unavailable_by_reason: dict[str, int]
    decision_latency_seconds: int
    data_quality: DataQuality


def stored_quality(store: CandleStore, fallback: DataQuality = DataQuality.DELAYED) -> DataQuality:
    """Lowest quality label among stored candles, or the fallback when the store is empty."""
    labels = [DataQuality(q) for q in store.quality_summary()]
    return DataQuality.lowest(labels) if labels else fallback


def load_features(paths: DataPaths) -> list[MarketFeature]:
    return from_frame(read_parquet(paths.gold_features, MarketFeature), MarketFeature)


def build_features(
    paths: DataPaths,
    settings: Settings,
    universe: Universe,
    calendar: TradingCalendar,
    windows: list[EventWindow] | None = None,
) -> FeatureBuildReport:
    """Measure every window for every event and symbol.

    The anchor is the event's availability time plus the decision latency, so no tradable
    measurement starts before the system could have acted.
    """
    windows = windows or list(EventWindow)
    store = CandleStore(paths)
    quality = stored_quality(store)
    calculator = WindowCalculator(store, calendar, universe, quality)
    latency = timedelta(seconds=settings.decision_latency_seconds)

    events = load_events(paths)
    features: list[MarketFeature] = []
    for event in events:
        anchor = event.available_at + latency
        for symbol in event.symbols:
            features.extend(calculator.features(event.event_id, symbol, anchor, windows))

    write_parquet_atomic(to_frame(features, MarketFeature), paths.gold_features)

    by_window: dict[str, int] = {w.value: 0 for w in windows}
    reasons: dict[str, int] = {}
    for feature in features:
        if feature.available:
            by_window[feature.window.value] += 1
        else:
            reason = feature.unavailable_reason or "unknown"
            reasons[reason] = reasons.get(reason, 0) + 1
    report = FeatureBuildReport(
        events=len(events),
        features_total=len(features),
        features_available=sum(by_window.values()),
        available_by_window=by_window,
        unavailable_by_reason=dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        decision_latency_seconds=settings.decision_latency_seconds,
        data_quality=quality,
    )
    log.info("features built", extra=report.model_dump(mode="json"))
    return report
