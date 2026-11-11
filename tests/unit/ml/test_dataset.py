"""Chronological splits must never let a model see its evaluation period."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.contracts import DataQuality, EventCategory, EventWindow, MarketEvent, MarketFeature
from src.market_data.universe import default_universe
from src.ml.dataset import (
    LeakageError,
    Sample,
    Split,
    assert_no_leakage,
    build_samples,
    chronological_split,
    purge,
    walk_forward_folds,
)

T0 = datetime(2025, 1, 1, 15, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def sample(index: int, symbol: str = "NUE", label_days: float = 0.5) -> Sample:
    available = T0 + index * DAY
    return Sample(
        event_id=f"e{index}",
        symbol=symbol,
        available_at=available,
        label_end=available + label_days * DAY,
        text=f"tariffs on steel number {index}",
        categorical={f"symbol={symbol}": 1.0},
        abnormal_ret=0.01 if index % 2 == 0 else -0.01,
    )


def test_split_is_chronological_and_disjoint() -> None:
    samples = [sample(i, s) for i in range(100) for s in ("NUE", "CAT")]
    split = chronological_split(samples)

    assert max(s.available_at for s in split.train) < split.validation_start
    assert min(s.available_at for s in split.validation) >= split.validation_start
    assert max(s.available_at for s in split.validation) < split.test_start
    assert min(s.available_at for s in split.test) >= split.test_start
    ids = [{s.event_id for s in part} for part in (split.train, split.validation, split.test)]
    assert not ids[0] & ids[1] and not ids[0] & ids[2] and not ids[1] & ids[2]
    # Roughly 70 / 15 / 15 by event, and both symbols of an event stay together.
    assert [len(i) for i in ids] == [70, 15, 15]
    assert len(split.train) == 140


def test_labels_reaching_into_the_next_period_are_purged() -> None:
    samples = [sample(i, label_days=3.0) for i in range(100)]
    split = chronological_split(samples)
    assert max(s.label_end for s in split.train) < split.validation_start
    assert max(s.label_end for s in split.validation) < split.test_start
    # Three days of labels are dropped before each boundary.
    assert len(split.train) == 67 and len(split.validation) == 12 and len(split.test) == 15


def test_leakage_guard_rejects_overlap() -> None:
    samples = [sample(i) for i in range(100)]
    good = chronological_split(samples)
    assert_no_leakage(good)

    late_train = Split(
        good.train + [good.test[0]],
        good.validation,
        good.test,
        good.validation_start,
        good.test_start,
    )
    with pytest.raises(LeakageError):
        assert_no_leakage(late_train)

    overlapping_label = sample(10, label_days=200)
    with pytest.raises(LeakageError, match="not before the start"):
        assert_no_leakage(
            Split(
                [overlapping_label],
                good.validation,
                good.test,
                good.validation_start,
                good.test_start,
            )
        )


def test_random_shuffling_of_input_does_not_change_the_split() -> None:
    samples = [sample(i) for i in range(60)]
    forward = chronological_split(samples)
    backward = chronological_split(list(reversed(samples)))
    assert {s.event_id for s in forward.test} == {s.event_id for s in backward.test}


def test_too_few_events_cannot_be_split() -> None:
    with pytest.raises(ValueError):
        chronological_split([sample(0), sample(1)])


def test_purge_drops_unfinished_labels() -> None:
    samples = [sample(0), sample(1, label_days=5)]
    kept = purge(samples, T0 + 3 * DAY)
    assert [s.event_id for s in kept] == ["e0"]


def test_walk_forward_models_only_see_the_past() -> None:
    samples = [sample(i, label_days=2.0) for i in range(100)]
    folds = walk_forward_folds(samples, initial_fraction=0.4, n_folds=4)
    assert len(folds) == 4
    predicted: list[str] = []
    for train, predict, start in folds:
        assert max(max(s.available_at, s.label_end) for s in train) < start
        assert min(s.available_at for s in predict) >= start
        predicted.extend(s.event_id for s in predict)
    # Folds cover the last 60% exactly once.
    assert predicted == [f"e{i}" for i in range(40, 100)]


def test_samples_use_anchor_text_and_tradable_windows_only() -> None:
    universe = default_universe()
    event = MarketEvent(
        event_id="e1",
        post_ids=["1", "2"],
        text="Tariffs on China start Monday.",
        published_at=T0,
        available_at=T0,
        # A later post in the cluster added a category the anchor text does not have.
        categories=[EventCategory.TARIFFS_TRADE, EventCategory.ENERGY_OIL],
        symbols=["NUE"],
        relevance_score=0.5,
        classifier_version="rules-v1",
    )
    feature = MarketFeature(
        event_id="e1",
        symbol="NUE",
        window=EventWindow.D1,
        anchor_ts=T0,
        entry_ts=T0 + timedelta(hours=1),
        exit_ts=T0 + timedelta(hours=7),
        entry_price=100.0,
        exit_price=101.0,
        ret=0.01,
        benchmark_ret=0.0,
        abnormal_ret=0.01,
        tradable=True,
        available=True,
        quality=DataQuality.SYNTHETIC,
    )
    unavailable = feature.model_copy(
        update={"symbol": "CAT", "available": False, "unavailable_reason": "missing"}
    )
    samples = build_samples([event], [feature, unavailable], universe, EventWindow.D1)
    assert len(samples) == 1
    assert samples[0].up == 1 and samples[0].label_end == feature.exit_ts
    assert "category=tariffs_trade" in samples[0].categorical
    assert "category=energy_oil" not in samples[0].categorical  # not knowable at anchor time
    assert samples[0].categorical["sector=Materials"] == 1.0

    with pytest.raises(ValueError, match="not tradable"):
        build_samples([event], [feature], universe, EventWindow.CLOSE_TO_CLOSE)
