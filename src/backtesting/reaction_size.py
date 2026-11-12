"""Reaction-size test: do prices move more than usual after a post, in either direction?

The event study averages signed abnormal returns, so a rise after one post and a fall after
another cancel. This test ignores direction. For every measured event window it takes the
absolute abnormal return and compares it with the same symbol's absolute abnormal return
over the same window, at the same time of day, on nearby sessions where that symbol had no
event (the controls).

- `excess` is the event's absolute move minus the mean absolute move of its controls.
- Excess values are averaged per session before testing, because events in one session
  share one market move and are not independent.
- Posts published outside trading hours are measured from the next open. Their reaction, if
  any, is mostly in the overnight gap, which these windows do not contain. They are reported
  separately from posts published during a session.
- Volume is compared for intraday windows as the event's volume over the geometric mean of
  its controls, tested on the log of that ratio.

A control session can still contain news unrelated to posts, and a session with a post
about other symbols counts as a control. Both push the result toward "no difference".
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

from pydantic import BaseModel

from src.backtesting.event_study import _t_test
from src.contracts import DataQuality, EventWindow, MarketFeature
from src.core.storage import DataPaths, write_json_atomic
from src.core.timeutils import utc_now
from src.market_data.calendar import Session, TradingCalendar
from src.market_data.windows import INTRADAY_INTERVALS, WindowCalculator

CONTROL_SESSIONS_EACH_SIDE = 10
MIN_CONTROLS = 5
WINDOWS = [w for w in EventWindow if w is not EventWindow.CLOSE_TO_CLOSE]
GROUPS = ("all", "during_session", "outside_hours")


class ReactionStats(BaseModel):
    window: EventWindow
    group: str
    n_measurements: int
    n_sessions: int
    mean_abs_event: float | None = None
    mean_abs_control: float | None = None
    ratio: float | None = None
    session_clustered_excess: float | None = None
    session_clustered_t_stat: float | None = None
    session_clustered_p_value: float | None = None
    share_above_control_median: float | None = None
    n_volume: int = 0
    median_volume_ratio: float | None = None
    session_clustered_volume_log_ratio: float | None = None
    volume_log_ratio_t_stat: float | None = None
    volume_log_ratio_p_value: float | None = None


class ReactionSizeReport(BaseModel):
    report_id: str
    created_at: datetime
    content_hash: str
    benchmark_symbol: str
    control_sessions_each_side: int
    min_controls: int
    measurements_total: int
    measurements_without_enough_controls: int
    stats: list[ReactionStats]
    data_quality: DataQuality
    caveats: list[str]


class _Row(BaseModel):
    window: EventWindow
    session: date
    outside_hours: bool
    abs_event: float
    abs_controls: list[float]
    volume_ratio: float | None


def _entry_session(calendar: TradingCalendar, feature: MarketFeature) -> Session | None:
    assert feature.entry_ts is not None
    if feature.window.is_intraday:
        return calendar.session_at(feature.entry_ts)
    return calendar.session_at(feature.entry_ts) or calendar.session_on(feature.entry_ts.date())


def _nearby_sessions(calendar: TradingCalendar, session: Session, each_side: int) -> list[Session]:
    before = calendar.previous_sessions(session, each_side)
    after: list[Session] = []
    current = session
    for _ in range(each_side):
        following = calendar.session_after(current)
        if following is None:
            break
        after.append(following)
        current = following
    return before + after


class _Volume:
    """Traded volume of a symbol between two times, from the finest stored intraday bars."""

    def __init__(self, calculator: WindowCalculator) -> None:
        self._calculator = calculator

    def between(self, symbol: str, start: datetime, end: datetime) -> float | None:
        for interval in INTRADAY_INTERVALS:
            bars = self._calculator.series(symbol, interval)
            if len(bars) == 0:
                continue
            index = bars.index_of(start)
            if index is None:
                return None
            total = 0.0
            while index < len(bars) and bars.ts[index] < end:
                total += bars.volume[index]
                index += 1
            return total
        return None


def _collect_rows(
    features: list[MarketFeature],
    calculator: WindowCalculator,
    calendar: TradingCalendar,
    each_side: int,
    min_controls: int,
) -> tuple[list[_Row], int]:
    measured = [
        f
        for f in features
        if f.available and f.window in WINDOWS and f.entry_ts and f.abnormal_ret is not None
    ]
    event_sessions: set[tuple[str, date]] = set()
    sessions: dict[int, Session] = {}
    for index, feature in enumerate(measured):
        session = _entry_session(calendar, feature)
        if session is not None:
            sessions[index] = session
            event_sessions.add((feature.symbol, session.date))

    volume = _Volume(calculator)
    cache: dict[tuple[str, EventWindow, datetime], tuple[float, float | None] | None] = {}

    def control(
        symbol: str, window: EventWindow, anchor: datetime
    ) -> tuple[float, float | None] | None:
        key = (symbol, window, anchor)
        if key not in cache:
            result = calculator.feature("control", symbol, anchor, window)
            if not result.available or result.abnormal_ret is None:
                cache[key] = None
            else:
                traded = None
                if window.is_intraday and result.entry_ts and result.exit_ts:
                    traded = volume.between(symbol, result.entry_ts, result.exit_ts)
                cache[key] = (abs(result.abnormal_ret), traded)
        return cache[key]

    rows: list[_Row] = []
    skipped = 0
    for index, feature in enumerate(measured):
        session = sessions.get(index)
        if session is None or feature.entry_ts is None or feature.abnormal_ret is None:
            skipped += 1
            continue
        offset = feature.entry_ts - session.open if feature.window.is_intraday else timedelta(0)
        abs_controls: list[float] = []
        control_volumes: list[float] = []
        for other in _nearby_sessions(calendar, session, each_side):
            if (feature.symbol, other.date) in event_sessions:
                continue
            outcome = control(feature.symbol, feature.window, other.open + offset)
            if outcome is None:
                continue
            abs_controls.append(outcome[0])
            if outcome[1] is not None and outcome[1] > 0:
                control_volumes.append(outcome[1])
        if len(abs_controls) < min_controls:
            skipped += 1
            continue

        volume_ratio = None
        if feature.window.is_intraday and feature.exit_ts and len(control_volumes) >= min_controls:
            traded = volume.between(feature.symbol, feature.entry_ts, feature.exit_ts)
            if traded is not None and traded > 0:
                # Geometric mean: volume is right-skewed, so an arithmetic mean of the
                # controls would sit above a typical session and bias the ratio below 1.
                typical = math.exp(sum(math.log(v) for v in control_volumes) / len(control_volumes))
                volume_ratio = traded / typical
        rows.append(
            _Row(
                window=feature.window,
                session=session.date,
                outside_hours=feature.shifted_to_open,
                abs_event=abs(feature.abnormal_ret),
                abs_controls=abs_controls,
                volume_ratio=volume_ratio,
            )
        )
    return rows, skipped


def _clustered(
    values: list[tuple[date, float]],
) -> tuple[int, float | None, float | None, float | None]:
    """Mean per session, then mean, t-statistic, and p-value across sessions."""
    by_session: dict[date, list[float]] = defaultdict(list)
    for session, value in values:
        by_session[session].append(value)
    means = [sum(v) / len(v) for _, v in sorted(by_session.items())]
    if not means:
        return 0, None, None, None
    _, t_stat, p_value = _t_test(means)
    return len(means), sum(means) / len(means), t_stat, p_value


def _stats(window: EventWindow, group: str, rows: list[_Row]) -> ReactionStats:
    if not rows:
        return ReactionStats(window=window, group=group, n_measurements=0, n_sessions=0)
    control_means = [sum(r.abs_controls) / len(r.abs_controls) for r in rows]
    mean_event = sum(r.abs_event for r in rows) / len(rows)
    mean_control = sum(control_means) / len(rows)
    n_sessions, excess, t_stat, p_value = _clustered(
        [(r.session, r.abs_event - c) for r, c in zip(rows, control_means, strict=True)]
    )
    above = sum(1 for r in rows if r.abs_event > median(r.abs_controls)) / len(rows)

    volume_rows = [(r.session, r.volume_ratio) for r in rows if r.volume_ratio is not None]
    _, volume_mean, volume_t, volume_p = _clustered([(s, math.log(v)) for s, v in volume_rows])
    return ReactionStats(
        window=window,
        group=group,
        n_measurements=len(rows),
        n_sessions=n_sessions,
        mean_abs_event=mean_event,
        mean_abs_control=mean_control,
        ratio=mean_event / mean_control if mean_control > 0 else None,
        session_clustered_excess=excess,
        session_clustered_t_stat=t_stat,
        session_clustered_p_value=p_value,
        share_above_control_median=above,
        n_volume=len(volume_rows),
        median_volume_ratio=median(v for _, v in volume_rows) if volume_rows else None,
        session_clustered_volume_log_ratio=volume_mean,
        volume_log_ratio_t_stat=volume_t,
        volume_log_ratio_p_value=volume_p,
    )


def run_reaction_size(
    features: list[MarketFeature],
    calculator: WindowCalculator,
    calendar: TradingCalendar,
    benchmark: str,
    each_side: int = CONTROL_SESSIONS_EACH_SIDE,
    min_controls: int = MIN_CONTROLS,
) -> ReactionSizeReport:
    rows, skipped = _collect_rows(features, calculator, calendar, each_side, min_controls)
    stats: list[ReactionStats] = []
    for window in WINDOWS:
        members = [r for r in rows if r.window is window]
        stats.append(_stats(window, "all", members))
        stats.append(_stats(window, "during_session", [r for r in members if not r.outside_hours]))
        stats.append(_stats(window, "outside_hours", [r for r in members if r.outside_hours]))

    qualities = [f.quality for f in features if f.available]
    body = [s.model_dump(mode="json") for s in stats]
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    return ReactionSizeReport(
        report_id=f"rs_{digest[:12]}",
        created_at=utc_now(),
        content_hash=digest,
        benchmark_symbol=benchmark,
        control_sessions_each_side=each_side,
        min_controls=min_controls,
        measurements_total=len(rows) + skipped,
        measurements_without_enough_controls=skipped,
        stats=stats,
        data_quality=DataQuality.lowest(qualities) if qualities else DataQuality.DELAYED,
        caveats=[
            "Association, not causation: a larger move after a post does not show the post "
            "caused it.",
            "Controls are nearby sessions without an event for the same symbol. They can "
            "still contain unrelated news, or posts about other symbols.",
            "Posts published outside trading hours are measured from the next open, so the "
            "overnight gap, where most of any reaction would be, is not in the window.",
            "Each window and group is a separate test with no multiple-comparison correction.",
        ],
    )


def reaction_size_from_store(
    paths: DataPaths,
    calculator: WindowCalculator,
    calendar: TradingCalendar,
    benchmark: str,
    save: bool = True,
) -> ReactionSizeReport:
    from src.pipelines.features import load_features

    report = run_reaction_size(load_features(paths), calculator, calendar, benchmark)
    if save and report.measurements_total:
        path = paths.reports_dir("reaction_size") / f"{report.report_id}.json"
        if not path.exists():
            write_json_atomic(report.model_dump_json(indent=2), path)
    return report
