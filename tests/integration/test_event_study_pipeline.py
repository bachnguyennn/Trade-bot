"""From a synthetic archive and synthetic candles to a reproducible event study."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.backtesting.event_study import daily_baselines, run_event_study
from src.contracts import EventWindow, IngestionMode
from src.core.settings import Settings
from src.core.storage import DataPaths
from src.ingestion.sources import ArchiveFileSource
from src.market_data.calendar import TradingCalendar
from src.market_data.store import CandleStore
from src.market_data.universe import default_universe
from src.pipelines.events import build_events, load_events
from src.pipelines.features import build_features, load_features
from src.pipelines.posts import ingest_posts
from tests.helpers import daily_candles, intraday_candles, make_calendar


@pytest.fixture
def calendar() -> TradingCalendar:
    return make_calendar(start=date(2025, 2, 24), days=25)


async def populate(
    posts_fixture: Path, paths: DataPaths, settings: Settings, calendar: TradingCalendar
) -> None:
    await ingest_posts(ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings)
    universe = default_universe()
    build_events(paths, settings, universe)
    store = CandleStore(paths)
    for symbol in universe.symbols:
        bump = 0.02 if symbol == "NUE" else 0.01  # NUE beats the market by 1% each session
        store.upsert(daily_candles(symbol, calendar, lambda i, b=bump: (100.0, 100.0 * (1 + b))))
    session = calendar.session_on(date(2025, 3, 3))
    assert session is not None
    for symbol in ("NUE", "SPY"):
        slope = 0.2 if symbol == "NUE" else 0.1
        store.upsert(intraday_candles(symbol, session, "5m", lambda k, s=slope: 100.0 + s * k))


async def test_real_pipeline_shape_on_synthetic_data(
    posts_fixture: Path, paths: DataPaths, settings: Settings, calendar: TradingCalendar
) -> None:
    await populate(posts_fixture, paths, settings, calendar)
    universe = default_universe()
    report = build_features(paths, settings, universe, calendar)
    events = load_events(paths)
    features = load_features(paths)

    assert report.events == 3
    assert report.features_total == sum(len(e.symbols) for e in events) * len(EventWindow)
    assert report.available_by_window["1d"] == sum(len(e.symbols) for e in events)
    # Intraday bars exist only for NUE on 3 March, so only that pair has short windows.
    assert report.available_by_window["5m"] == 1

    tariff = events[0]
    nue = {f.window: f for f in features if f.event_id == tariff.event_id and f.symbol == "NUE"}
    daily = nue[EventWindow.D1]
    assert daily.available and daily.abnormal_ret == pytest.approx(0.01)
    assert daily.entry_ts is not None and daily.entry_ts >= daily.anchor_ts
    five = nue[EventWindow.M5]
    # Published 14:05:00, available 14:06:00, decided 14:06:30, but the session opens 14:30.
    assert five.available and five.shifted_to_open
    assert five.anchor_ts == tariff.available_at.replace(second=30)
    assert five.entry_ts == calendar.session_on(date(2025, 3, 3)).open  # type: ignore[union-attr]

    other = [f for f in features if f.symbol != "NUE" and f.window is EventWindow.M5]
    assert other and all(not f.available and f.unavailable_reason for f in other)

    # No tradable feature starts before the event was available to the system.
    by_id = {e.event_id: e for e in events}
    for f in features:
        if f.available and f.tradable:
            assert f.entry_ts is not None and f.entry_ts >= by_id[f.event_id].available_at


async def test_event_study_end_to_end_is_reproducible(
    posts_fixture: Path, paths: DataPaths, settings: Settings, calendar: TradingCalendar
) -> None:
    await populate(posts_fixture, paths, settings, calendar)
    universe = default_universe()
    build_features(paths, settings, universe, calendar)
    events, features = load_events(paths), load_features(paths)
    baselines = daily_baselines(
        CandleStore(paths),
        "SPY",
        universe.symbols,
        calendar.sessions[0].daily_ts,
        calendar.sessions[-1].daily_ts,
    )

    first = run_event_study(events, features, settings, baselines=baselines)
    build_features(paths, settings, universe, calendar)  # rebuild from the same stored data
    second = run_event_study(
        load_events(paths), load_features(paths), settings, baselines=baselines
    )

    assert first.content_hash == second.content_hash
    daily = {w.window: w for w in first.by_category["tariffs_trade"]}[EventWindow.D1]
    assert daily.n_events == 1
    assert daily.mean_abnormal_ret is not None and daily.mean_abnormal_ret > 0
    # NUE outperforms on every session, event or not, so the baseline absorbs the effect.
    assert daily.excess_mean_abnormal_ret == pytest.approx(0.0, abs=1e-9)
