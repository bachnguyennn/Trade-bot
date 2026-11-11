"""Event study: how affected symbols moved, relative to the market, after posts.

Method:

1. For each event and window, average the abnormal returns of its affected symbols. One
   event contributes one observation, so an event with eight symbols does not count eight
   times.
2. Across events, report the mean, median, share positive, and a one-sample t-test of the
   mean against zero, overall and per category.
3. For the daily windows, compare against a baseline: the same symbols' average abnormal
   return over every session in the study period, event or not. Some symbols drift against
   the benchmark between open and close regardless of news; without the baseline that
   drift would look like an event effect.

The study reports association only. It does not show that a post caused a move: events
cluster around news that moves markets on its own, the symbol mapping is rule-based, and
events close in time are not independent, which overstates significance.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime
from statistics import median
from typing import Any

import polars as pl
from pydantic import BaseModel

from src.contracts import DataQuality, EventWindow, MarketEvent, MarketFeature
from src.core.settings import Settings
from src.core.storage import DataPaths, write_json_atomic
from src.core.timeutils import utc_now
from src.market_data.store import CandleStore

MIN_OBSERVATIONS_FOR_TEST = 5

CAVEATS = [
    "Association only: these figures do not show that a post caused a price move.",
    "Events near each other in time are not independent, so the per-event t-statistics are "
    "overstated. Prefer the session-clustered figures.",
    "Affected symbols are chosen by keyword rules (rules-v1), not by a validated model.",
    "The symbol universe was chosen today, which introduces survivorship bias.",
    "Abnormal return is the symbol return minus the benchmark return, with no beta adjustment.",
    "close_to_close includes the overnight gap and starts before the post: it is not tradable.",
    "No multiple-comparison correction is applied across categories and windows.",
    "The baseline is the full-period average for the same symbols. It uses the whole sample, "
    "so it is a descriptive control and not something known at the time of each event.",
    "Intraday windows have no baseline comparison yet.",
]

BASELINE_WINDOWS = (EventWindow.D1, EventWindow.CLOSE_TO_CLOSE)
Baselines = dict[EventWindow, dict[str, float]]


class WindowStats(BaseModel):
    window: EventWindow
    tradable: bool
    n_events: int
    mean_abnormal_ret: float | None = None
    median_abnormal_ret: float | None = None
    std_abnormal_ret: float | None = None
    t_stat: float | None = None
    p_value: float | None = None
    share_positive: float | None = None
    mean_abs_abnormal_ret: float | None = None
    # Baseline comparison (daily windows only): the same symbols on all sessions.
    baseline_mean_abnormal_ret: float | None = None
    excess_mean_abnormal_ret: float | None = None
    excess_t_stat: float | None = None
    excess_p_value: float | None = None
    # Events entering on the same session share one market move. These figures average
    # events per entry session first, then test across sessions (excess when a baseline
    # exists, raw otherwise). They are the more conservative significance measure.
    n_sessions: int | None = None
    session_clustered_mean: float | None = None
    session_clustered_t_stat: float | None = None
    session_clustered_p_value: float | None = None


class EventStudyReport(BaseModel):
    report_id: str
    created_at: datetime
    content_hash: str
    classifier_version: str
    benchmark_symbol: str
    assumed_latency_seconds: int
    decision_latency_seconds: int
    period_start: datetime | None
    period_end: datetime | None
    events_total: int
    events_measured: int
    windows: list[EventWindow]
    overall: list[WindowStats]
    by_category: dict[str, list[WindowStats]]
    unavailable_by_window: dict[str, dict[str, int]]
    data_quality: DataQuality
    caveats: list[str]


def _two_sided_p(t_stat: float, dof: int) -> float:
    from scipy import stats

    return float(2.0 * stats.t.sf(abs(t_stat), dof))


def _t_test(values: list[float]) -> tuple[float | None, float | None, float | None]:
    """Standard deviation, t-statistic, and two-sided p-value of the mean against zero."""
    n = len(values)
    if n < 2:
        return None, None, None
    mean = sum(values) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    if n < MIN_OBSERVATIONS_FOR_TEST or std == 0:
        return std, None, None
    t_stat = mean / (std / math.sqrt(n))
    return std, t_stat, _two_sided_p(t_stat, n - 1)


def window_stats(
    window: EventWindow,
    values: list[float],
    baseline: list[float] | None = None,
    sessions: list[date] | None = None,
) -> WindowStats:
    """Summary statistics for one window.

    `values` are per-event mean abnormal returns. `baseline` and `sessions`, when given,
    hold the matching per-event baseline values and entry session dates in the same order.
    """
    n = len(values)
    stats = WindowStats(window=window, tradable=window.tradable, n_events=n)
    if n == 0:
        return stats
    mean = sum(values) / n
    stats.mean_abnormal_ret = mean
    stats.median_abnormal_ret = float(median(values))
    stats.share_positive = sum(1 for v in values if v > 0) / n
    stats.mean_abs_abnormal_ret = sum(abs(v) for v in values) / n
    stats.std_abnormal_ret, stats.t_stat, stats.p_value = _t_test(values)
    if baseline is not None and len(baseline) == n:
        excess = [v - b for v, b in zip(values, baseline, strict=True)]
        stats.baseline_mean_abnormal_ret = sum(baseline) / n
        stats.excess_mean_abnormal_ret = sum(excess) / n
        _, stats.excess_t_stat, stats.excess_p_value = _t_test(excess)
    else:
        excess = values
    if sessions is not None and len(sessions) == n:
        by_session: dict[date, list[float]] = {}
        for day, value in zip(sessions, excess, strict=True):
            by_session.setdefault(day, []).append(value)
        session_means = [sum(v) / len(v) for _, v in sorted(by_session.items())]
        stats.n_sessions = len(session_means)
        stats.session_clustered_mean = sum(session_means) / len(session_means)
        _, stats.session_clustered_t_stat, stats.session_clustered_p_value = _t_test(session_means)
    return stats


def daily_baselines(
    store: CandleStore, benchmark: str, symbols: list[str], start: datetime, end: datetime
) -> Baselines:
    """Average abnormal return of each symbol over every stored session in the period.

    `1d` uses open to close; `close_to_close` uses close to close. These are the returns an
    event would show if posts had no relation to prices at all.
    """

    def returns(symbol: str) -> pl.DataFrame:
        frame = store.read(symbol, "1d").sort("ts")
        return frame.select(
            "ts",
            (pl.col("close") / pl.col("open") - 1).alias("oc"),
            (pl.col("close") / pl.col("close").shift(1) - 1).alias("cc"),
        )

    out: Baselines = {EventWindow.D1: {}, EventWindow.CLOSE_TO_CLOSE: {}}
    bench = returns(benchmark).rename({"oc": "b_oc", "cc": "b_cc"})
    if bench.height == 0:
        return out
    for symbol in sorted(set(symbols)):
        joined = returns(symbol).join(bench, on="ts", how="inner")
        joined = joined.filter((pl.col("ts") >= start) & (pl.col("ts") <= end)).drop_nulls()
        if joined.height == 0:
            continue
        means = joined.select(
            (pl.col("oc") - pl.col("b_oc")).mean().alias("oc"),
            (pl.col("cc") - pl.col("b_cc")).mean().alias("cc"),
        ).row(0)
        out[EventWindow.D1][symbol] = float(means[0])
        out[EventWindow.CLOSE_TO_CLOSE][symbol] = float(means[1])
    return out


def event_window_returns(features: list[MarketFeature]) -> dict[tuple[str, EventWindow], float]:
    """Mean abnormal return across an event's symbols, per event and window."""
    grouped: dict[tuple[str, EventWindow], list[float]] = {}
    for feature in features:
        if feature.available and feature.abnormal_ret is not None:
            grouped.setdefault((feature.event_id, feature.window), []).append(feature.abnormal_ret)
    return {key: sum(vals) / len(vals) for key, vals in grouped.items()}


def event_window_sessions(features: list[MarketFeature]) -> dict[tuple[str, EventWindow], date]:
    """Entry session date of each event and window (the exit date for close_to_close)."""
    out: dict[tuple[str, EventWindow], date] = {}
    for feature in features:
        if not feature.available or feature.entry_ts is None or feature.exit_ts is None:
            continue
        stamp = feature.entry_ts if feature.tradable else feature.exit_ts
        out.setdefault((feature.event_id, feature.window), stamp.date())
    return out


def event_window_baselines(
    features: list[MarketFeature], baselines: Baselines
) -> dict[tuple[str, EventWindow], float]:
    """Per event and window: the baseline averaged over the same symbols that were measured."""
    grouped: dict[tuple[str, EventWindow], list[float]] = {}
    incomplete: set[tuple[str, EventWindow]] = set()
    for feature in features:
        if not feature.available or feature.window not in baselines:
            continue
        key = (feature.event_id, feature.window)
        value = baselines[feature.window].get(feature.symbol)
        if value is None:
            incomplete.add(key)
        else:
            grouped.setdefault(key, []).append(value)
    return {k: sum(v) / len(v) for k, v in grouped.items() if k not in incomplete}


def run_event_study(
    events: list[MarketEvent],
    features: list[MarketFeature],
    settings: Settings,
    windows: list[EventWindow] | None = None,
    baselines: Baselines | None = None,
) -> EventStudyReport:
    """Compute the study. Pure function of its inputs: the same data gives the same result."""
    windows = windows or list(EventWindow)
    per_event = event_window_returns(features)
    per_event_baseline = event_window_baselines(features, baselines or {})
    per_event_session = event_window_sessions(features)
    events = sorted(events, key=lambda e: (e.available_at, e.event_id))

    def stats_for(window: EventWindow, members: list[MarketEvent]) -> WindowStats:
        keys = [(e.event_id, window) for e in members if (e.event_id, window) in per_event]
        values = [per_event[k] for k in keys]
        sessions = [per_event_session[k] for k in keys]
        if keys and all(k in per_event_baseline for k in keys):
            return window_stats(window, values, [per_event_baseline[k] for k in keys], sessions)
        return window_stats(window, values, None, sessions)

    overall = [stats_for(window, events) for window in windows]
    by_category: dict[str, list[WindowStats]] = {}
    for category in sorted({c.value for e in events for c in e.categories}):
        members = [e for e in events if category in {c.value for c in e.categories}]
        by_category[category] = [stats_for(window, members) for window in windows]

    unavailable: dict[str, dict[str, int]] = {}
    qualities: set[DataQuality] = set()
    for feature in features:
        if feature.window not in windows:
            continue
        if feature.available:
            qualities.add(feature.quality)
        else:
            bucket = unavailable.setdefault(feature.window.value, {})
            reason = feature.unavailable_reason or "unknown"
            bucket[reason] = bucket.get(reason, 0) + 1
    unavailable = {w: dict(sorted(r.items())) for w, r in sorted(unavailable.items())}

    body: dict[str, Any] = {
        "classifier_version": events[0].classifier_version if events else "none",
        "benchmark_symbol": settings.benchmark_symbol,
        "assumed_latency_seconds": settings.assumed_latency_seconds,
        "decision_latency_seconds": settings.decision_latency_seconds,
        "period_start": events[0].available_at if events else None,
        "period_end": events[-1].available_at if events else None,
        "events_total": len(events),
        "events_measured": len({event_id for event_id, _ in per_event}),
        "windows": windows,
        "overall": overall,
        "by_category": by_category,
        "unavailable_by_window": unavailable,
        "data_quality": DataQuality.lowest(list(qualities)) if qualities else DataQuality.DELAYED,
        "caveats": CAVEATS,
    }
    # The hash covers results only, so two runs on the same data are provably identical.
    placeholder = EventStudyReport(
        report_id="-", created_at=datetime.fromtimestamp(0, tz=UTC), content_hash="-", **body
    )
    canonical = placeholder.model_dump_json(exclude={"report_id", "created_at", "content_hash"})
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return EventStudyReport(
        report_id=f"es_{digest[:12]}", created_at=utc_now(), content_hash=digest, **body
    )


def study_from_store(
    paths: DataPaths,
    settings: Settings,
    store: CandleStore,
    benchmark: str,
    windows: list[EventWindow] | None = None,
    save: bool = True,
) -> EventStudyReport:
    """Run the study on stored events and features, with baselines from stored candles.

    Every caller (CLI, API, tests) goes through here, so they all produce the same report
    for the same data.
    """
    from src.pipelines.events import load_events
    from src.pipelines.features import load_features

    events = load_events(paths)
    features = load_features(paths)
    baselines: Baselines | None = None
    if events:
        baselines = daily_baselines(
            store,
            benchmark,
            sorted({f.symbol for f in features}),
            min(e.available_at for e in events),
            max(e.available_at for e in events),
        )
    report = run_event_study(events, features, settings, windows, baselines)
    if save and events:
        save_event_study(paths, report)
    return report


def save_event_study(paths: DataPaths, report: EventStudyReport) -> None:
    """Store the report. A report with identical results keeps its first file."""
    path = paths.reports_dir("event_study") / f"{report.report_id}.json"
    if not path.exists():
        write_json_atomic(report.model_dump_json(indent=2), path)


def load_event_studies(paths: DataPaths) -> list[EventStudyReport]:
    reports = [
        EventStudyReport.model_validate(json.loads(f.read_text(encoding="utf-8")))
        for f in paths.report_files("event_study")
    ]
    return sorted(reports, key=lambda r: r.created_at)


def latest_event_study(paths: DataPaths) -> EventStudyReport | None:
    reports = load_event_studies(paths)
    return reports[-1] if reports else None
