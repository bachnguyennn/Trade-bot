"""Baseline training, evaluation, versioning, and inference on synthetic samples."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from src.contracts import DataQuality, Direction, EventWindow
from src.core.settings import Settings
from src.core.storage import DataPaths
from src.market_data.universe import default_universe
from src.ml.baseline import (
    InsufficientData,
    latest_version,
    load_bundle,
    load_reports,
    save_bundle,
    train_on_samples,
)
from src.ml.dataset import Sample
from src.ml.evaluation import (
    direction_metrics,
    magnitude_metrics,
    naive_baselines,
    wilson_interval,
)
from src.ml.inference import InferenceService, ModelUnavailable, ModelVersionMismatch

T0 = datetime(2024, 1, 1, 15, 0, tzinfo=UTC)
LATENCY = timedelta(seconds=30)


def synthetic_samples(n: int, signal: bool, seed: int = 7) -> list[Sample]:
    """Samples whose direction either follows a word in the text or is pure noise."""
    rng = random.Random(seed)
    samples = []
    for index in range(n):
        positive = rng.random() < 0.5
        word = ("boom" if positive else "bust") if signal else rng.choice(["boom", "bust"])
        available = T0 + timedelta(days=index)
        samples.append(
            Sample(
                event_id=f"e{index}",
                symbol="NUE",
                available_at=available,
                label_end=available + timedelta(hours=7),
                text=f"synthetic post about tariffs and steel {word} today",
                categorical={"symbol=NUE": 1.0, "category=tariffs_trade": 1.0},
                abnormal_ret=(0.01 if positive else -0.01) * (1 + rng.random()),
            )
        )
    return samples


def test_learns_a_real_signal_and_reports_baselines() -> None:
    samples = synthetic_samples(400, signal=True)
    bundle, report, predictions = train_on_samples(
        samples, EventWindow.D1, 200, LATENCY, DataQuality.SYNTHETIC
    )
    assert report.test_metrics["accuracy"] == pytest.approx(1.0)
    assert report.beats_baseline
    assert set(report.baselines) >= {
        "majority_class_accuracy",
        "always_up_accuracy",
        "coin_flip_accuracy",
        "constant_rate_log_loss",
    }
    # Periods are in time order with no overlap.
    splits = report.splits
    assert splits["train"].end < splits["validation"].start  # type: ignore[operator]
    assert splits["validation"].end < splits["test"].start  # type: ignore[operator]
    assert report.data_quality is DataQuality.SYNTHETIC
    assert bundle.version == report.model_version

    # Walk-forward predictions cover only later samples and never precede availability.
    by_id = {s.event_id: s for s in samples}
    assert predictions
    for prediction in predictions:
        source = by_id[prediction.event_id]
        assert prediction.predicted_at == source.available_at + LATENCY
        assert prediction.model_version.startswith(report.model_version)
        assert 0 <= prediction.prob_up <= 1 and 0 <= prediction.confidence <= 1
    assert min(by_id[p.event_id].available_at for p in predictions) > samples[100].available_at


def test_noise_is_not_reported_as_skill() -> None:
    samples = synthetic_samples(400, signal=False)
    _, report, _ = train_on_samples(samples, EventWindow.D1, 200, LATENCY, DataQuality.SYNTHETIC)
    assert not report.beats_baseline
    accuracy = report.test_metrics["accuracy"]
    assert accuracy is not None and 0.3 < accuracy < 0.7


def test_refuses_to_train_on_too_little_data() -> None:
    with pytest.raises(InsufficientData, match="at least 200 are required"):
        train_on_samples(
            synthetic_samples(50, signal=True),
            EventWindow.D1,
            200,
            LATENCY,
            DataQuality.SYNTHETIC,
        )


def test_refuses_single_class_training_data() -> None:
    samples = [
        Sample(s.event_id, s.symbol, s.available_at, s.label_end, s.text, s.categorical, 0.01)
        for s in synthetic_samples(300, signal=True)
    ]
    with pytest.raises(InsufficientData, match="one direction class"):
        train_on_samples(samples, EventWindow.D1, 200, LATENCY, DataQuality.SYNTHETIC)


def test_registry_and_inference(paths: DataPaths, settings: Settings) -> None:
    universe = default_universe()
    service = InferenceService(paths, settings, universe)
    with pytest.raises(ModelUnavailable):
        service.predict_text("Tariffs on steel boom today")
    assert latest_version(paths) is None and load_reports(paths) == []

    bundle, report, _ = train_on_samples(
        synthetic_samples(400, signal=True), EventWindow.D1, 200, LATENCY, DataQuality.SYNTHETIC
    )
    save_bundle(paths, bundle, report)
    assert latest_version(paths) == report.model_version
    assert load_bundle(paths, report.model_version) is not None
    assert load_bundle(paths, "missing") is None

    up = service.predict_text("Tariffs on steel boom today", ["NUE"])
    down = service.predict_text("Tariffs on steel bust today", ["NUE"])
    assert [p.symbol for p in up] == ["NUE"]
    assert up[0].direction is Direction.UP and down[0].direction is Direction.DOWN
    assert up[0].model_version == report.model_version
    assert up[0].expected_abnormal_return > down[0].expected_abnormal_return
    assert up[0].prob_high_vol is None or 0 <= up[0].prob_high_vol <= 1

    # Symbols default to the rule-based mapping and exclude anything outside the universe.
    mapped = service.predict_text("Tariffs on China steel boom")
    assert "NUE" in {p.symbol for p in mapped} and "SPY" not in {p.symbol for p in mapped}
    assert service.predict_text("boom", ["NOT_A_SYMBOL"]) == []

    with pytest.raises(ModelVersionMismatch):
        service.predict_text("boom", ["NUE"], expected_version="some-other-version")


def test_metric_helpers() -> None:
    low, high = wilson_interval(50, 100)
    assert low is not None and high is not None and low < 0.5 < high
    assert wilson_interval(0, 0) == (None, None)

    perfect = direction_metrics([1, 0, 1, 0], [0.9, 0.1, 0.8, 0.2])
    assert perfect["accuracy"] == 1.0 and perfect["roc_auc"] == 1.0
    one_class = direction_metrics([1, 1], [0.6, 0.7])
    assert one_class["roc_auc"] is None and one_class["accuracy"] == 1.0
    assert direction_metrics([], []) == {"samples": 0.0}

    naive = naive_baselines([1, 1, 0], [1, 0, 0, 0])
    assert naive["majority_class_accuracy"] == 0.25  # train majority is "up"
    assert naive["always_up_accuracy"] == 0.25 and naive["coin_flip_accuracy"] == 0.5

    magnitude = magnitude_metrics([0.01, -0.01, 0.02], [0.01, -0.01, 0.02], 0.0)
    assert magnitude["mae"] == pytest.approx(0.0)
    assert magnitude["mae_predict_zero"] == pytest.approx(0.04 / 3)
    assert magnitude["rank_ic"] == pytest.approx(1.0)
