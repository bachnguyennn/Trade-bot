"""Fixtures for API and pipeline integration tests. All data is synthetic."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.backtesting.event_study import study_from_store
from src.backtesting.runner import run_backtest
from src.contracts import IngestionMode, StrategyName
from src.core.settings import Settings
from src.core.storage import DataPaths
from src.ingestion.sources import ArchiveFileSource
from src.market_data.calendar import TradingCalendar
from src.market_data.store import CandleStore
from src.market_data.universe import default_universe
from src.pipelines.events import build_events
from src.pipelines.features import build_features
from src.pipelines.posts import ingest_posts
from tests.helpers import daily_candles, make_calendar


@pytest.fixture
def api_calendar() -> TradingCalendar:
    return make_calendar(start=date(2025, 2, 24), days=25)


@pytest.fixture
def open_settings(settings: Settings) -> Settings:
    """Settings that allow simulated orders at any time of day."""
    return settings.model_copy(update={"enforce_market_hours": False})


def populate(
    posts_fixture: Path, paths: DataPaths, settings: Settings, calendar: TradingCalendar
) -> None:
    """Run the whole historical pipeline on the synthetic fixture."""
    universe = default_universe()
    asyncio.run(
        ingest_posts(ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings)
    )
    build_events(paths, settings, universe)
    store = CandleStore(paths)
    for index, symbol in enumerate(universe.symbols):
        # Every symbol moves a little differently so strategies have something to act on.
        bump = 0.01 + 0.004 * (index % 5)
        store.upsert(daily_candles(symbol, calendar, lambda i, b=bump: (100.0, 100.0 * (1 + b))))
    store.upsert(daily_candles("SPY", calendar, lambda i: (100.0, 101.0)))
    build_features(paths, settings, universe, calendar)
    study_from_store(paths, settings, store, universe.benchmark)
    for strategy in (StrategyName.MOMENTUM_CONTINUATION, StrategyName.MEAN_REVERSION):
        run_backtest(paths, settings, universe, calendar, strategy)


@pytest.fixture
def empty_client(settings: Settings, api_calendar: TradingCalendar) -> Iterator[TestClient]:
    with TestClient(create_app(settings, api_calendar)) as client:
        yield client


@pytest.fixture
def populated_client(
    posts_fixture: Path, paths: DataPaths, open_settings: Settings, api_calendar: TradingCalendar
) -> Iterator[TestClient]:
    populate(posts_fixture, paths, open_settings, api_calendar)
    with TestClient(create_app(open_settings, api_calendar)) as client:
        yield client
