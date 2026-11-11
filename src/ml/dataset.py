"""Training samples and leak-free chronological splits.

A sample is one (event, symbol) pair. Its inputs use only what was known when the event
became available: the anchor post's text and the symbol. Its label is the abnormal return
over a tradable window that starts after that time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.contracts import EventWindow, MarketEvent, MarketFeature
from src.market_data.universe import Universe
from src.ml.classifier import RuleBasedClassifier


class LeakageError(RuntimeError):
    """Raised when a split would let a model see information from its evaluation period."""


@dataclass(frozen=True)
class Sample:
    event_id: str
    symbol: str
    available_at: datetime
    label_end: datetime
    text: str
    categorical: dict[str, float]
    abnormal_ret: float

    @property
    def up(self) -> int:
        return 1 if self.abnormal_ret > 0 else 0


@dataclass(frozen=True)
class Split:
    train: list[Sample]
    validation: list[Sample]
    test: list[Sample]
    validation_start: datetime
    test_start: datetime


def categorical_inputs(
    text: str, symbol: str, universe: Universe, classifier: RuleBasedClassifier
) -> dict[str, float]:
    """Non-text inputs. Categories come from the anchor text only, never from later posts."""
    inputs: dict[str, float] = {
        f"symbol={symbol}": 1.0,
        f"sector={universe.sector_of(symbol)}": 1.0,
    }
    for category in classifier.classify(text).categories:
        inputs[f"category={category.value}"] = 1.0
    return inputs


def build_samples(
    events: list[MarketEvent],
    features: list[MarketFeature],
    universe: Universe,
    window: EventWindow,
    classifier: RuleBasedClassifier | None = None,
) -> list[Sample]:
    """Join events with their outcome for one tradable window."""
    if not window.tradable:
        raise ValueError(f"{window.value} is not tradable and cannot be a prediction target")
    classifier = classifier or RuleBasedClassifier()
    by_event = {e.event_id: e for e in events}
    samples: list[Sample] = []
    for feature in features:
        if feature.window is not window or not feature.available:
            continue
        event = by_event.get(feature.event_id)
        if event is None or feature.abnormal_ret is None or feature.exit_ts is None:
            continue
        samples.append(
            Sample(
                event_id=event.event_id,
                symbol=feature.symbol,
                available_at=event.available_at,
                label_end=feature.exit_ts,
                text=event.text,
                categorical=categorical_inputs(event.text, feature.symbol, universe, classifier),
                abnormal_ret=feature.abnormal_ret,
            )
        )
    samples.sort(key=lambda s: (s.available_at, s.event_id, s.symbol))
    return samples


def _boundary(event_times: list[datetime], fraction: float) -> datetime:
    index = min(len(event_times) - 1, max(1, int(len(event_times) * fraction)))
    return event_times[index]


def purge(samples: list[Sample], before: datetime) -> list[Sample]:
    """Keep samples whose input and label are both fully known before `before`."""
    return [s for s in samples if s.available_at < before and s.label_end < before]


def chronological_split(
    samples: list[Sample], train_fraction: float = 0.70, validation_fraction: float = 0.15
) -> Split:
    """Split by event time. Earlier samples whose label window reaches into the next
    period are dropped (purged), so no label overlaps the data it is evaluated against."""
    event_times = sorted({s.available_at for s in samples})
    if len(event_times) < 3:
        raise ValueError("at least three distinct event times are needed to split")
    validation_start = _boundary(event_times, train_fraction)
    test_start = _boundary(event_times, train_fraction + validation_fraction)
    if test_start <= validation_start:
        raise ValueError("not enough distinct event times for three periods")

    train = purge(samples, validation_start)
    validation = [s for s in purge(samples, test_start) if s.available_at >= validation_start]
    test = [s for s in samples if s.available_at >= test_start]
    split = Split(train, validation, test, validation_start, test_start)
    assert_no_leakage(split)
    return split


def assert_no_leakage(split: Split) -> None:
    """Fail loudly if any earlier period knows something from a later one."""

    def latest(samples: list[Sample]) -> datetime | None:
        return max((max(s.available_at, s.label_end) for s in samples), default=None)

    def earliest(samples: list[Sample]) -> datetime | None:
        return min((s.available_at for s in samples), default=None)

    pairs = [
        ("train", split.train, "validation", split.validation),
        ("train", split.train, "test", split.test),
        ("validation", split.validation, "test", split.test),
    ]
    for early_name, early, late_name, late in pairs:
        end, start = latest(early), earliest(late)
        if end is not None and start is not None and end >= start:
            raise LeakageError(
                f"{early_name} data extends to {end.isoformat()}, which is not before the "
                f"start of {late_name} at {start.isoformat()}"
            )
    train_events = {s.event_id for s in split.train}
    for name, part in (("validation", split.validation), ("test", split.test)):
        shared = train_events.intersection(s.event_id for s in part)
        if shared:
            raise LeakageError(f"{len(shared)} events appear in both train and {name}")


def walk_forward_folds(
    samples: list[Sample], initial_fraction: float = 0.4, n_folds: int = 4
) -> list[tuple[list[Sample], list[Sample], datetime]]:
    """Expanding-window folds: (train, predict, fold_start). Each fold is predicted by a
    model that saw only purged samples from before the fold started."""
    event_times = sorted({s.available_at for s in samples})
    if len(event_times) < n_folds + 2:
        return []
    starts = [
        _boundary(event_times, initial_fraction + (1 - initial_fraction) * k / n_folds)
        for k in range(n_folds)
    ]
    folds: list[tuple[list[Sample], list[Sample], datetime]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else None
        train = purge(samples, start)
        predict = [
            s for s in samples if s.available_at >= start and (end is None or s.available_at < end)
        ]
        if train and predict:
            folds.append((train, predict, start))
    return folds
