from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import polars as pl
import pytest

from src.contracts import DataQuality, EventCategory, StockCandle
from src.core.settings import Settings
from src.core.storage import DataPaths
from src.market_data.providers import (
    AlpacaProvider,
    ProviderError,
    build_provider,
    drop_unfinished_bars,
)
from src.market_data.store import CandleStore
from src.market_data.universe import default_universe
from tests.helpers import daily_candles, make_calendar


def test_upsert_is_idempotent_and_sorted(paths: DataPaths) -> None:
    calendar = make_calendar(days=5)
    frame = daily_candles("AAA", calendar, lambda i: (100.0 + i, 101.0 + i))
    store = CandleStore(paths)
    store.upsert(frame.reverse())
    store.upsert(frame)
    stored = store.read("AAA", "1d")
    assert stored.height == 5
    assert stored["ts"].is_sorted()
    assert store.symbols("1d") == ["AAA"] and store.intervals() == ["1d"]
    assert store.count() == 5
    assert store.quality_summary() == {"synthetic": 5}


def test_read_range_and_models(paths: DataPaths) -> None:
    calendar = make_calendar(days=5)
    store = CandleStore(paths)
    store.upsert(daily_candles("AAA", calendar, lambda i: (100.0 + i, 101.0 + i)))
    start = calendar.sessions[1].daily_ts
    end = calendar.sessions[3].daily_ts
    assert store.read("AAA", "1d", start, end).height == 3
    models = store.read_models("AAA", "1d", start, end)
    assert all(isinstance(m, StockCandle) for m in models) and models[0].open == 101.0
    assert store.read("ZZZ", "1d").height == 0


def test_lower_quality_never_replaces_higher(paths: DataPaths) -> None:
    calendar = make_calendar(days=2)
    store = CandleStore(paths)
    good = daily_candles("AAA", calendar, lambda i: (100.0, 101.0)).with_columns(
        pl.lit(DataQuality.CONSOLIDATED.value).alias("quality")
    )
    worse = daily_candles("AAA", calendar, lambda i: (200.0, 201.0)).with_columns(
        pl.lit(DataQuality.DELAYED.value).alias("quality")
    )
    store.upsert(good)
    store.upsert(worse)
    stored = store.read("AAA", "1d")
    assert stored["quality"].unique().to_list() == ["consolidated"]
    assert stored["open"].to_list() == [100.0, 100.0]
    # Better data does replace worse data.
    other = CandleStore(DataPaths(paths.root / "other"))
    other.upsert(worse)
    other.upsert(good)
    assert other.read("AAA", "1d")["open"].to_list() == [100.0, 100.0]


def test_invalid_rows_are_dropped(paths: DataPaths) -> None:
    calendar = make_calendar(days=3)
    frame = daily_candles("AAA", calendar, lambda i: (100.0, 101.0))
    frame = frame.with_columns(
        pl.when(pl.int_range(pl.len()) == 1).then(None).otherwise(pl.col("close")).alias("close")
    )
    store = CandleStore(paths)
    store.upsert(frame)
    assert store.read("AAA", "1d").height == 2


def test_unfinished_daily_bar_is_dropped() -> None:
    calendar = make_calendar(days=3)
    frame = daily_candles("AAA", calendar, lambda i: (100.0, 101.0))
    midday_second_session = calendar.sessions[1].open + timedelta(hours=2)
    kept = drop_unfinished_bars(frame, "1d", calendar, midday_second_session)
    assert kept["ts"].to_list() == [calendar.sessions[0].daily_ts]


def test_universe_definition() -> None:
    universe = default_universe()
    assert universe.benchmark == "SPY" and "SPY" in universe
    assert len(universe.symbols) == len(set(universe.symbols)) >= 60
    for category in EventCategory:
        symbols = universe.category_symbols(category)
        assert symbols, f"no symbols for {category}"
        assert all(s in universe for s in symbols)
    assert not universe.is_eligible("DJT", date(2024, 3, 25))
    assert universe.is_eligible("DJT", date(2024, 3, 26))
    assert not universe.is_eligible("NOPE", date(2024, 3, 26))


def test_alpaca_requires_keys(settings: Settings) -> None:
    with pytest.raises(ProviderError, match="keys are not set"):
        AlpacaProvider(settings, make_calendar())
    assert settings.resolved_market_provider() == "yfinance"
    assert build_provider(settings, make_calendar()).name == "yfinance"


def test_alpaca_bars_are_parsed_paged_and_labelled(settings: Settings) -> None:
    calendar = make_calendar(start=date(2025, 3, 3), days=5)
    keyed = settings.model_copy(update={"alpaca_api_key": "k", "alpaca_api_secret": "s"})
    keyed = Settings.model_validate(keyed.model_dump())
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["APCA-API-KEY-ID"] == "k"
        assert request.url.params["feed"] == "sip"
        if "page_token" not in request.url.params:
            bars = {
                "AAA": [
                    {"t": "2025-03-03T05:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 100}
                ]
            }
            return httpx.Response(200, json={"bars": bars, "next_page_token": "p2"})
        bars = {
            "AAA": [{"t": "2025-03-04T05:00:00Z", "o": 11, "h": 12, "l": 10, "c": 11.5, "v": 200}]
        }
        return httpx.Response(200, json={"bars": bars, "next_page_token": None})

    provider = AlpacaProvider(
        keyed, calendar, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = provider.fetch(["AAA", "BBB"], "1d", date(2025, 3, 3), date(2025, 3, 4))

    assert len(requests) == 2
    assert result.errors == {"BBB": "no data returned"}
    assert result.candles["ts"].to_list() == [
        datetime(2025, 3, 3, tzinfo=UTC),
        datetime(2025, 3, 4, tzinfo=UTC),
    ]
    assert result.candles["quality"].unique().to_list() == ["consolidated"]
    assert result.candles["source"].unique().to_list() == ["alpaca"]
