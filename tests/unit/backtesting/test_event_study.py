from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from src.backtesting.event_study import (
    daily_baselines,
    event_window_returns,
    latest_event_study,
    load_event_studies,
    run_event_study,
    save_event_study,
    window_stats,
)
from src.contracts import DataQuality, EventCategory, EventWindow, MarketEvent, MarketFeature
from src.core.settings import Settings
from src.core.storage import DataPaths
from src.market_data.store import CandleStore
from tests.helpers import daily_candles, make_calendar

T0 = datetime(2025, 3, 3, 15, 0, tzinfo=UTC)


def event(event_id: str, category: EventCategory, day: int = 0) -> MarketEvent:
    ts = T0 + timedelta(days=day)
    return MarketEvent(
        event_id=event_id,
        post_ids=[event_id],
        text="synthetic",
        published_at=ts,
        available_at=ts,
        categories=[category],
        symbols=["AAA", "BBB"],
        relevance_score=0.5,
        classifier_version="rules-v1",
    )


def feature(
    event_id: str,
    symbol: str,
    abnormal: float | None,
    window: EventWindow = EventWindow.D1,
    day: int = 0,
) -> MarketFeature:
    anchor = T0 + timedelta(days=day)
    if abnormal is None:
        return MarketFeature(
            event_id=event_id,
            symbol=symbol,
            window=window,
            anchor_ts=anchor,
            tradable=window.tradable,
            available=False,
            unavailable_reason="missing candles",
            quality=DataQuality.SYNTHETIC,
        )
    return MarketFeature(
        event_id=event_id,
        symbol=symbol,
        window=window,
        anchor_ts=anchor,
        entry_ts=anchor + timedelta(hours=1),
        exit_ts=anchor + timedelta(hours=6),
        entry_price=100.0,
        exit_price=100.0 * (1 + abnormal),
        ret=abnormal,
        benchmark_ret=0.0,
        abnormal_ret=abnormal,
        tradable=window.tradable,
        available=True,
        quality=DataQuality.SYNTHETIC,
    )


def test_window_stats_matches_hand_calculation() -> None:
    values = [0.01, 0.02, -0.01, 0.03, 0.00]
    stats = window_stats(EventWindow.D1, values)
    mean = 0.01
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / 4)
    assert stats.n_events == 5
    assert stats.mean_abnormal_ret == pytest.approx(mean)
    assert stats.median_abnormal_ret == pytest.approx(0.01)
    assert stats.std_abnormal_ret == pytest.approx(std)
    assert stats.t_stat == pytest.approx(mean / (std / math.sqrt(5)))
    assert stats.share_positive == pytest.approx(0.6)
    assert stats.mean_abs_abnormal_ret == pytest.approx(0.014)
    assert stats.p_value is not None and 0 < stats.p_value < 1


def test_no_test_statistic_on_tiny_samples() -> None:
    stats = window_stats(EventWindow.D1, [0.01, 0.02])
    assert stats.mean_abnormal_ret == pytest.approx(0.015)
    assert stats.t_stat is None and stats.p_value is None
    empty = window_stats(EventWindow.H1, [])
    assert empty.n_events == 0 and empty.mean_abnormal_ret is None


def test_baseline_and_session_clustering() -> None:
    values = [0.02, 0.02, 0.02, 0.01, 0.00, -0.01]
    baseline = [0.01] * 6
    # The first three events enter on the same session and count once when clustered.
    sessions = [date(2025, 3, 3)] * 3 + [date(2025, 3, 4), date(2025, 3, 5), date(2025, 3, 6)]
    stats = window_stats(EventWindow.D1, values, baseline, sessions)
    assert stats.baseline_mean_abnormal_ret == pytest.approx(0.01)
    assert stats.excess_mean_abnormal_ret == pytest.approx(0.0)
    assert stats.n_sessions == 4
    assert stats.session_clustered_mean == pytest.approx((0.01 + 0.0 - 0.01 - 0.02) / 4)


def test_event_with_many_symbols_counts_once() -> None:
    features = [
        feature("e1", "AAA", 0.02),
        feature("e1", "BBB", 0.04),
        feature("e1", "CCC", None),
        feature("e2", "AAA", -0.01),
    ]
    per_event = event_window_returns(features)
    assert per_event[("e1", EventWindow.D1)] == pytest.approx(0.03)
    assert per_event[("e2", EventWindow.D1)] == pytest.approx(-0.01)
    assert len(per_event) == 2


def test_study_report_structure_and_unavailable_counts(settings: Settings) -> None:
    events = [event(f"e{i}", EventCategory.TARIFFS_TRADE, i) for i in range(6)]
    events.append(event("x1", EventCategory.ENERGY_OIL, 7))
    features = [feature(f"e{i}", "AAA", 0.01 * (i - 2), day=i) for i in range(6)]
    features.append(feature("x1", "AAA", 0.05, day=7))
    features.append(feature("x1", "AAA", None, EventWindow.H1, day=7))

    report = run_event_study(events, features, settings)

    assert report.events_total == 7 and report.events_measured == 7
    assert set(report.by_category) == {"energy_oil", "tariffs_trade"}
    daily = {w.window: w for w in report.by_category["tariffs_trade"]}[EventWindow.D1]
    assert daily.n_events == 6 and daily.mean_abnormal_ret == pytest.approx(0.005)
    hourly = {w.window: w for w in report.overall}[EventWindow.H1]
    assert hourly.n_events == 0 and hourly.mean_abnormal_ret is None
    assert report.unavailable_by_window == {"1h": {"missing candles": 1}}
    assert report.data_quality is DataQuality.SYNTHETIC
    assert any("Association only" in c for c in report.caveats)
    close = {w.window: w for w in report.overall}[EventWindow.CLOSE_TO_CLOSE]
    assert not close.tradable


def test_study_is_reproducible_and_saved_once(settings: Settings, paths: DataPaths) -> None:
    events = [event(f"e{i}", EventCategory.TARIFFS_TRADE, i) for i in range(6)]
    features = [feature(f"e{i}", "AAA", 0.01 * i, day=i) for i in range(6)]

    first = run_event_study(events, features, settings)
    second = run_event_study(list(reversed(events)), list(reversed(features)), settings)
    assert first.content_hash == second.content_hash
    assert first.report_id == second.report_id
    assert first.overall == second.overall

    save_event_study(paths, first)
    save_event_study(paths, second)
    assert len(load_event_studies(paths)) == 1
    latest = latest_event_study(paths)
    assert latest is not None and latest.report_id == first.report_id

    changed = run_event_study(events, features[:-1], settings)
    assert changed.content_hash != first.content_hash


def test_empty_study_has_no_numbers(settings: Settings, paths: DataPaths) -> None:
    report = run_event_study([], [], settings)
    assert report.events_total == 0
    assert all(w.n_events == 0 and w.mean_abnormal_ret is None for w in report.overall)
    assert report.by_category == {}
    assert latest_event_study(paths) is None


def test_daily_baselines_average_all_sessions(paths: DataPaths) -> None:
    calendar = make_calendar(days=10)
    store = CandleStore(paths)
    # AAA gains 2% open to close every session; SPY gains 1%.
    store.upsert(daily_candles("AAA", calendar, lambda i: (100.0, 102.0)))
    store.upsert(daily_candles("SPY", calendar, lambda i: (400.0, 404.0)))
    start = calendar.sessions[0].daily_ts
    end = calendar.sessions[-1].daily_ts
    baselines = daily_baselines(store, "SPY", ["AAA", "MISSING"], start, end)
    assert baselines[EventWindow.D1]["AAA"] == pytest.approx(0.01)
    # Close to close is flat for both, so the abnormal return is zero.
    assert baselines[EventWindow.CLOSE_TO_CLOSE]["AAA"] == pytest.approx(0.0)
    assert "MISSING" not in baselines[EventWindow.D1]
