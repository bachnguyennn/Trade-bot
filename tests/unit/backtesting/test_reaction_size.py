"""Reaction-size test on synthetic bars with known moves."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from src.backtesting.reaction_size import ReactionSizeReport, ReactionStats, run_reaction_size
from src.contracts import DataQuality, EventWindow, MarketFeature, UniverseMember
from src.core.storage import DataPaths
from src.market_data.calendar import TradingCalendar
from src.market_data.store import CandleStore
from src.market_data.universe import Universe
from src.market_data.windows import WindowCalculator
from tests.helpers import intraday_candles, make_calendar

QUIET_STEP = 0.01
EVENT_STEP = 0.10


def member(symbol: str) -> UniverseMember:
    return UniverseMember(
        symbol=symbol, name=symbol, kind="stock", sector="Test", eligible_from=date(2015, 1, 1)
    )


def build(
    paths: DataPaths, calendar: TradingCalendar, event_sessions: set[int]
) -> WindowCalculator:
    """SPY is flat. AAA drifts slowly, and ten times faster on the event sessions."""
    store = CandleStore(paths)
    for index, session in enumerate(calendar.sessions):
        step = EVENT_STEP if index in event_sessions else QUIET_STEP
        store.upsert(intraday_candles("AAA", session, "5m", lambda k, s=step: 100.0 + s * k))
        store.upsert(intraday_candles("SPY", session, "5m", lambda k: 400.0))
    universe = Universe([member("SPY"), member("AAA")], "SPY")
    return WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)


def event_feature(calc: WindowCalculator, calendar: TradingCalendar, index: int) -> MarketFeature:
    anchor = datetime.combine(calendar.sessions[index].date, time(15, 0), tzinfo=UTC)
    return calc.feature(f"e{index}", "AAA", anchor, EventWindow.M15)


def stats_for(report: ReactionSizeReport, group: str) -> ReactionStats:
    return next(s for s in report.stats if s.window is EventWindow.M15 and s.group == group)


def test_event_move_is_compared_with_quiet_sessions(paths: DataPaths) -> None:
    calendar = make_calendar(days=20)
    calc = build(paths, calendar, {10})
    report = run_reaction_size([event_feature(calc, calendar, 10)], calc, calendar, "SPY")

    stats = stats_for(report, "during_session")
    assert stats.n_measurements == 1 and stats.n_sessions == 1
    # 15:00 is bar 6. Three bars later the price has moved three steps.
    assert stats.mean_abs_event == pytest.approx(3 * EVENT_STEP / (100.0 + 6 * EVENT_STEP))
    assert stats.mean_abs_control == pytest.approx(3 * QUIET_STEP / (100.0 + 6 * QUIET_STEP))
    assert stats.ratio == pytest.approx(10.0, rel=0.01)
    assert stats.share_above_control_median == 1.0
    assert stats.median_volume_ratio == pytest.approx(1.0)
    assert stats_for(report, "outside_hours").n_measurements == 0
    assert stats_for(report, "all").n_measurements == 1


def test_sessions_with_an_event_for_the_symbol_are_not_controls(paths: DataPaths) -> None:
    calendar = make_calendar(days=20)
    calc = build(paths, calendar, {10, 11})
    features = [event_feature(calc, calendar, 10), event_feature(calc, calendar, 11)]
    report = run_reaction_size(features, calc, calendar, "SPY")

    stats = stats_for(report, "all")
    assert stats.n_measurements == 2 and stats.n_sessions == 2
    # If either event session had been used as a control, this mean would be larger.
    assert stats.mean_abs_control == pytest.approx(3 * QUIET_STEP / (100.0 + 6 * QUIET_STEP))


def test_measurement_without_enough_controls_is_left_out(paths: DataPaths) -> None:
    calendar = make_calendar(days=4)
    calc = build(paths, calendar, {2})
    report = run_reaction_size([event_feature(calc, calendar, 2)], calc, calendar, "SPY")

    assert report.measurements_total == 1
    assert report.measurements_without_enough_controls == 1
    assert stats_for(report, "all").n_measurements == 0


def test_same_data_gives_the_same_report_id(paths: DataPaths) -> None:
    calendar = make_calendar(days=20)
    calc = build(paths, calendar, {10})
    features = [event_feature(calc, calendar, 10)]
    first = run_reaction_size(features, calc, calendar, "SPY")
    second = run_reaction_size(features, calc, calendar, "SPY")
    assert first.report_id == second.report_id
