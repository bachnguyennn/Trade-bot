"""Event-window rules, checked against hand-computed values on synthetic bars."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.contracts import DataQuality, EventWindow, UniverseMember
from src.core.storage import DataPaths
from src.market_data.calendar import TradingCalendar
from src.market_data.store import CandleStore
from src.market_data.universe import Universe
from src.market_data.windows import Measurement, WindowCalculator
from tests.helpers import daily_candles, intraday_candles, make_calendar

MONDAY = date(2025, 3, 3)
TUESDAY = date(2025, 3, 4)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def member(symbol: str, eligible_from: date = date(2015, 1, 1)) -> UniverseMember:
    return UniverseMember(
        symbol=symbol, name=symbol, kind="stock", sector="Test", eligible_from=eligible_from
    )


@pytest.fixture
def calendar() -> TradingCalendar:
    return make_calendar()


@pytest.fixture
def universe() -> Universe:
    return Universe([member("SPY"), member("AAA"), member("NEW", date(2025, 3, 5))], "SPY")


@pytest.fixture
def store(paths: DataPaths, calendar: TradingCalendar) -> CandleStore:
    store = CandleStore(paths)
    # AAA: session i opens at 100 + i and closes 2% higher. SPY: opens at 400, closes 1% higher.
    store.upsert(daily_candles("AAA", calendar, lambda i: (100.0 + i, (100.0 + i) * 1.02)))
    store.upsert(daily_candles("SPY", calendar, lambda i: (400.0, 404.0)))
    store.upsert(daily_candles("NEW", calendar, lambda i: (50.0, 51.0)))
    for session in calendar.sessions[:3]:
        # 5-minute bars: AAA rises 0.10 per bar from 100, SPY rises 0.20 per bar from 400.
        store.upsert(intraday_candles("AAA", session, "5m", lambda k: 100.0 + 0.10 * k))
        store.upsert(intraday_candles("SPY", session, "5m", lambda k: 400.0 + 0.20 * k))
    return store


@pytest.fixture
def calc(store: CandleStore, calendar: TradingCalendar, universe: Universe) -> WindowCalculator:
    return WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)


def test_intraday_window_inside_session(calc: WindowCalculator) -> None:
    # Anchor 15:02 UTC. The first 5-minute bar at or after it starts at 15:05 (bar 7).
    feature = calc.feature("e", "AAA", utc(2025, 3, 3, 15, 2), EventWindow.M15)
    assert feature.available and feature.tradable and not feature.shifted_to_open
    assert feature.entry_ts == utc(2025, 3, 3, 15, 5)
    assert feature.exit_ts == utc(2025, 3, 3, 15, 20)
    assert feature.entry_price == pytest.approx(100.7)
    assert feature.exit_price == pytest.approx(101.0)
    assert feature.ret == pytest.approx(101.0 / 100.7 - 1)
    assert feature.benchmark_ret == pytest.approx(402.0 / 401.4 - 1)
    assert feature.abnormal_ret == pytest.approx(feature.ret - feature.benchmark_ret)
    assert feature.quality is DataQuality.SYNTHETIC
    assert feature.realized_vol is not None and feature.realized_vol >= 0


def test_anchor_exactly_on_a_bar_uses_that_bar(calc: WindowCalculator) -> None:
    feature = calc.feature("e", "AAA", utc(2025, 3, 3, 15, 5), EventWindow.M5)
    assert feature.entry_ts == utc(2025, 3, 3, 15, 5)
    assert feature.exit_ts == utc(2025, 3, 3, 15, 10)


def test_entry_is_never_before_the_anchor(calc: WindowCalculator) -> None:
    for minute in range(0, 60, 7):
        anchor = utc(2025, 3, 3, 16, minute, 13)
        for window in [EventWindow.M5, EventWindow.M30, EventWindow.H1, EventWindow.D1]:
            feature = calc.feature("e", "AAA", anchor, window)
            assert feature.available
            assert feature.entry_ts is not None and feature.entry_ts >= anchor


def test_overnight_anchor_shifts_to_next_open(calc: WindowCalculator) -> None:
    feature = calc.feature("e", "AAA", utc(2025, 3, 3, 23, 30), EventWindow.H1)
    assert feature.available and feature.shifted_to_open
    assert feature.entry_ts == utc(2025, 3, 4, 14, 30)
    assert feature.exit_ts == utc(2025, 3, 4, 15, 30)
    assert feature.entry_price == pytest.approx(100.0)
    assert feature.exit_price == pytest.approx(101.2)


def test_weekend_anchor_shifts_to_monday(calc: WindowCalculator) -> None:
    saturday = utc(2025, 3, 8, 12, 0)
    feature = calc.feature("e", "AAA", saturday, EventWindow.D1)
    assert feature.available and feature.shifted_to_open
    assert feature.entry_ts == utc(2025, 3, 10, 14, 30)


def test_window_crossing_the_close_is_unavailable(calc: WindowCalculator) -> None:
    feature = calc.feature("e", "AAA", utc(2025, 3, 3, 20, 0), EventWindow.H4)
    assert not feature.available
    assert feature.unavailable_reason == "window crosses the session close"
    assert feature.ret is None


def test_missing_bars_make_the_window_unavailable(
    paths: DataPaths, calendar: TradingCalendar, universe: Universe
) -> None:
    store = CandleStore(paths)
    session = calendar.sessions[0]
    store.upsert(intraday_candles("AAA", session, "5m", lambda k: 100.0 + k, skip_bars=(8,)))
    store.upsert(intraday_candles("SPY", session, "5m", lambda k: 400.0))
    calc = WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)
    feature = calc.feature("e", "AAA", utc(2025, 3, 3, 15, 2), EventWindow.M15)
    assert not feature.available
    assert feature.unavailable_reason == "missing candles inside the window"
    # A window that ends before the gap is unaffected.
    assert calc.feature("e", "AAA", utc(2025, 3, 3, 15, 2), EventWindow.M5).available


def test_missing_entry_bar_is_not_silently_skipped(
    paths: DataPaths, calendar: TradingCalendar, universe: Universe
) -> None:
    store = CandleStore(paths)
    session = calendar.sessions[0]
    store.upsert(intraday_candles("AAA", session, "5m", lambda k: 100.0, skip_bars=(7, 8, 9)))
    store.upsert(intraday_candles("SPY", session, "5m", lambda k: 400.0))
    calc = WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)
    feature = calc.feature("e", "AAA", utc(2025, 3, 3, 15, 2), EventWindow.M5)
    assert not feature.available
    assert feature.unavailable_reason == "missing candles at the entry time"


def test_bars_coarser_than_window_are_not_used(
    paths: DataPaths, calendar: TradingCalendar, universe: Universe
) -> None:
    store = CandleStore(paths)
    session = calendar.sessions[0]
    for symbol in ("AAA", "SPY"):
        store.upsert(intraday_candles(symbol, session, "1h", lambda k: 100.0 + k))
    calc = WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)
    anchor = utc(2025, 3, 3, 14, 40)
    fine = calc.feature("e", "AAA", anchor, EventWindow.M15)
    assert not fine.available
    assert fine.unavailable_reason == "no intraday candles stored at or finer than the window"
    hourly = calc.feature("e", "AAA", anchor, EventWindow.H1)
    assert hourly.available
    assert hourly.entry_ts == utc(2025, 3, 3, 15, 30) and hourly.exit_ts == utc(2025, 3, 3, 16, 30)
    four = calc.feature("e", "AAA", anchor, EventWindow.H4)
    assert four.available and four.exit_ts == utc(2025, 3, 3, 19, 30)


def test_next_day_window_uses_next_session_open_to_close(calc: WindowCalculator) -> None:
    # Anchor during Monday's session: the next session to open is Tuesday (index 1).
    feature = calc.feature("e", "AAA", utc(2025, 3, 3, 16, 0), EventWindow.D1)
    assert feature.available and not feature.shifted_to_open
    assert feature.entry_ts == utc(2025, 3, 4, 14, 30)
    assert feature.exit_ts == utc(2025, 3, 4, 21, 0)
    assert feature.entry_price == pytest.approx(101.0)
    assert feature.ret == pytest.approx(0.02)
    assert feature.benchmark_ret == pytest.approx(0.01)
    assert feature.abnormal_ret == pytest.approx(0.01)


def test_close_to_close_is_descriptive_only(calc: WindowCalculator) -> None:
    feature = calc.feature("e", "AAA", utc(2025, 3, 4, 16, 0), EventWindow.CLOSE_TO_CLOSE)
    assert feature.available and not feature.tradable
    assert feature.entry_ts == utc(2025, 3, 3, 21, 0)  # before the anchor, by design
    assert feature.exit_ts == utc(2025, 3, 4, 21, 0)
    assert feature.ret == pytest.approx((101.0 * 1.02) / (100.0 * 1.02) - 1)


def test_missing_daily_candle_is_unavailable(
    paths: DataPaths, calendar: TradingCalendar, universe: Universe
) -> None:
    store = CandleStore(paths)
    store.upsert(daily_candles("AAA", calendar, lambda i: (100.0, 101.0), skip=(TUESDAY,)))
    store.upsert(daily_candles("SPY", calendar, lambda i: (400.0, 404.0)))
    calc = WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)
    feature = calc.feature("e", "AAA", utc(2025, 3, 3, 16, 0), EventWindow.D1)
    assert not feature.available
    assert feature.unavailable_reason == "missing daily candle for the session"


def test_missing_benchmark_is_reported(
    paths: DataPaths, calendar: TradingCalendar, universe: Universe
) -> None:
    store = CandleStore(paths)
    store.upsert(daily_candles("AAA", calendar, lambda i: (100.0, 101.0)))
    calc = WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)
    feature = calc.feature("e", "AAA", utc(2025, 3, 3, 16, 0), EventWindow.D1)
    assert not feature.available
    assert feature.unavailable_reason is not None
    assert feature.unavailable_reason.startswith("benchmark:")


def test_symbol_not_yet_listed_is_unavailable(calc: WindowCalculator) -> None:
    early = calc.feature("e", "NEW", utc(2025, 3, 3, 16, 0), EventWindow.D1)  # enters 4 March
    assert not early.available
    assert early.unavailable_reason == "symbol not eligible on the session date"
    later = calc.feature("e", "NEW", utc(2025, 3, 4, 22, 0), EventWindow.D1)  # enters 5 March
    assert later.available


def test_volume_ratio_uses_only_earlier_sessions(
    paths: DataPaths, calendar: TradingCalendar, universe: Universe
) -> None:
    store = CandleStore(paths)
    volume = lambda i: 3_000_000.0 if i == 10 else 1_000_000.0  # noqa: E731
    store.upsert(daily_candles("AAA", calendar, lambda i: (100.0, 101.0), volume))
    store.upsert(daily_candles("SPY", calendar, lambda i: (400.0, 404.0)))
    calc = WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)
    session = calendar.sessions[10]
    spike = calc.measure("AAA", session.open - timedelta(hours=1), EventWindow.D1)
    assert isinstance(spike, Measurement)
    assert spike.volume_ratio == pytest.approx(3.0)
    # Too little history: no ratio rather than a guess.
    first = calc.measure("AAA", calendar.sessions[1].open - timedelta(hours=1), EventWindow.D1)
    assert isinstance(first, Measurement) and first.volume_ratio is None
