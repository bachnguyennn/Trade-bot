"""Baseline model: TF-IDF text features with logistic and ridge regression.

Three heads share one feature space:

- direction: probability that the abnormal return is positive
- magnitude: expected abnormal return
- volatility: probability of an unusually large move (top fifth of training moves)

Everything that is fitted (vocabulary, encoders, thresholds, weights) is fitted on training
data only. The regularisation strength is chosen on the validation period, and the test
period is used once, for the reported metrics.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import joblib
from pydantic import BaseModel

from src.contracts import DataQuality, Direction, EventWindow, ModelPrediction
from src.core.logging import get_logger
from src.core.settings import Settings
from src.core.storage import DataPaths, to_frame, write_json_atomic, write_parquet_atomic
from src.core.timeutils import utc_now
from src.market_data.universe import Universe
from src.ml.classifier import CLASSIFIER_VERSION
from src.ml.dataset import (
    Sample,
    build_samples,
    chronological_split,
    walk_forward_folds,
)
from src.ml.evaluation import (
    CAVEATS,
    ModelReport,
    SplitInfo,
    direction_metrics,
    magnitude_metrics,
    naive_baselines,
    volatility_metrics,
)
from src.pipelines.events import load_events
from src.pipelines.features import load_features

log = get_logger(__name__)

MODEL_NAME = "baseline-tfidf-logreg"
C_GRID = [0.03, 0.1, 0.3, 1.0]
HIGH_VOL_QUANTILE = 0.80
DIRECTION_MARGIN = 0.02  # prob_up within 0.5 +/- margin is reported as flat


class InsufficientData(RuntimeError):
    """Raised when there is too little data to train or evaluate honestly."""


@dataclass
class Bundle:
    """A fitted model with everything needed to predict."""

    version: str
    window: EventWindow
    text_vectorizer: Any
    categorical_vectorizer: Any
    direction_model: Any
    magnitude_model: Any
    volatility_model: Any | None
    high_vol_threshold: float
    c_value: float

    def matrix(self, samples: list[Sample]) -> Any:
        from scipy.sparse import hstack

        text = self.text_vectorizer.transform([s.text for s in samples])
        categorical = self.categorical_vectorizer.transform([s.categorical for s in samples])
        return hstack([text, categorical]).tocsr()

    def predict(self, samples: list[Sample]) -> tuple[list[float], list[float], list[float | None]]:
        """Probability up, expected abnormal return, and probability of a large move."""
        if not samples:
            return [], [], []
        x = self.matrix(samples)
        prob_up = [float(p) for p in self.direction_model.predict_proba(x)[:, 1]]
        magnitude = [float(v) for v in self.magnitude_model.predict(x)]
        if self.volatility_model is None:
            vol: list[float | None] = [None] * len(samples)
        else:
            vol = [float(p) for p in self.volatility_model.predict_proba(x)[:, 1]]
        return prob_up, magnitude, vol


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def fit_bundle(train: list[Sample], window: EventWindow, c_value: float, version: str) -> Bundle:
    """Fit all three heads on `train` only."""
    from scipy.sparse import hstack
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression, Ridge

    text_vectorizer = TfidfVectorizer(
        lowercase=True, ngram_range=(1, 2), min_df=3, max_features=5000, sublinear_tf=True
    )
    try:
        text = text_vectorizer.fit_transform([s.text for s in train])
    except ValueError:
        # Vocabulary too small for min_df on a tiny training set.
        text_vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 1), min_df=1)
        text = text_vectorizer.fit_transform([s.text for s in train])
    categorical_vectorizer = DictVectorizer(sparse=True)
    categorical = categorical_vectorizer.fit_transform([s.categorical for s in train])
    x = hstack([text, categorical]).tocsr()

    up = [s.up for s in train]
    if len(set(up)) < 2:
        raise InsufficientData("training data has only one direction class")
    direction_model = LogisticRegression(C=c_value, max_iter=2000)
    direction_model.fit(x, up)

    magnitude_model = Ridge(alpha=1.0 / c_value)
    magnitude_model.fit(x, [s.abnormal_ret for s in train])

    threshold = _quantile([abs(s.abnormal_ret) for s in train], HIGH_VOL_QUANTILE)
    high_vol = [1 if abs(s.abnormal_ret) > threshold else 0 for s in train]
    volatility_model: Any | None = None
    if len(set(high_vol)) == 2:
        volatility_model = LogisticRegression(C=c_value, max_iter=2000)
        volatility_model.fit(x, high_vol)

    return Bundle(
        version=version,
        window=window,
        text_vectorizer=text_vectorizer,
        categorical_vectorizer=categorical_vectorizer,
        direction_model=direction_model,
        magnitude_model=magnitude_model,
        volatility_model=volatility_model,
        high_vol_threshold=threshold,
        c_value=c_value,
    )


def _split_info(samples: list[Sample]) -> SplitInfo:
    return SplitInfo(
        start=min((s.available_at for s in samples), default=None),
        end=max((s.available_at for s in samples), default=None),
        samples=len(samples),
        events=len({s.event_id for s in samples}),
    )


def _version(samples: list[Sample], window: EventWindow, created: datetime) -> str:
    digest = hashlib.sha256()
    digest.update(window.value.encode())
    for sample in samples:
        digest.update(f"{sample.event_id}:{sample.symbol}:{sample.abnormal_ret:.10f}".encode())
    return f"{created.strftime('%Y%m%dT%H%M%SZ')}-{digest.hexdigest()[:8]}"


def to_predictions(
    bundle: Bundle, samples: list[Sample], decision_latency: timedelta, version: str | None = None
) -> list[ModelPrediction]:
    prob_up, magnitude, vol = bundle.predict(samples)
    used_version = version or bundle.version
    predictions: list[ModelPrediction] = []
    for sample, p, m, v in zip(samples, prob_up, magnitude, vol, strict=True):
        if p > 0.5 + DIRECTION_MARGIN:
            direction = Direction.UP
        elif p < 0.5 - DIRECTION_MARGIN:
            direction = Direction.DOWN
        else:
            direction = Direction.FLAT
        key = f"{sample.event_id}:{sample.symbol}:{bundle.window.value}:{used_version}"
        predictions.append(
            ModelPrediction(
                prediction_id=f"pred_{hashlib.sha256(key.encode()).hexdigest()[:16]}",
                event_id=sample.event_id,
                symbol=sample.symbol,
                window=bundle.window,
                model_name=MODEL_NAME,
                model_version=used_version,
                predicted_at=sample.available_at + decision_latency,
                direction=direction,
                prob_up=min(1.0, max(0.0, p)),
                expected_abnormal_return=m,
                prob_high_vol=None if v is None else min(1.0, max(0.0, v)),
                confidence=min(1.0, abs(p - 0.5) * 2),
            )
        )
    return predictions


# -- registry --------------------------------------------------------------------------


def save_bundle(paths: DataPaths, bundle: Bundle, report: ModelReport) -> None:
    directory = paths.models_dir(MODEL_NAME) / bundle.version
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, directory / "model.joblib")
    write_json_atomic(report.model_dump_json(indent=2), directory / "report.json")
    write_json_atomic(
        report.model_dump_json(indent=2), paths.reports_dir("models") / f"{bundle.version}.json"
    )


def load_reports(paths: DataPaths) -> list[ModelReport]:
    reports = [
        ModelReport.model_validate(json.loads(f.read_text(encoding="utf-8")))
        for f in paths.report_files("models")
    ]
    return sorted(reports, key=lambda r: r.created_at)


def latest_version(paths: DataPaths) -> str | None:
    reports = load_reports(paths)
    return reports[-1].model_version if reports else None


def load_bundle(paths: DataPaths, version: str) -> Bundle | None:
    file = paths.models_dir(MODEL_NAME) / version / "model.joblib"
    if not file.exists():
        return None
    bundle = joblib.load(file)
    return bundle if isinstance(bundle, Bundle) else None


# -- training --------------------------------------------------------------------------


class TrainingOutcome(BaseModel):
    report: ModelReport
    out_of_sample_predictions: int


def train_on_samples(
    samples: list[Sample],
    window: EventWindow,
    min_samples: int,
    decision_latency: timedelta,
    data_quality: DataQuality,
) -> tuple[Bundle, ModelReport, list[ModelPrediction]]:
    """Select, fit, and evaluate. Returns the model, its report, and out-of-sample
    predictions (walk-forward) that are safe to use in a backtest."""
    if len(samples) < min_samples:
        raise InsufficientData(
            f"{len(samples)} samples available for window {window.value}; "
            f"at least {min_samples} are required to train"
        )
    try:
        split = chronological_split(samples)
    except ValueError as exc:
        raise InsufficientData(str(exc)) from exc
    if not split.train or not split.validation or not split.test:
        raise InsufficientData("one of the train, validation, or test periods is empty")

    created = utc_now()
    version = _version(samples, window, created)

    # Choose regularisation on the validation period.
    validation_up = [s.up for s in split.validation]
    scores: dict[float, float] = {}
    for c_value in C_GRID:
        candidate = fit_bundle(split.train, window, c_value, version)
        prob, _, _ = candidate.predict(split.validation)
        loss = direction_metrics(validation_up, prob)["log_loss"]
        scores[c_value] = loss if loss is not None else float("inf")
    best_c = min(scores, key=lambda c: (scores[c], c))
    selected = fit_bundle(split.train, window, best_c, version)
    validation_prob, _, _ = selected.predict(split.validation)

    # Final model: train plus validation, both strictly before the test period.
    final_train = split.train + split.validation
    bundle = fit_bundle(final_train, window, best_c, version)
    test_prob, test_mag, test_vol = bundle.predict(split.test)
    test_up = [s.up for s in split.test]
    train_up = [s.up for s in final_train]
    test_metrics = direction_metrics(test_up, test_prob)
    baselines = naive_baselines(train_up, test_up)
    train_mean = sum(s.abnormal_ret for s in final_train) / len(final_train)
    test_high_vol = [
        1 if abs(s.abnormal_ret) > bundle.high_vol_threshold else 0 for s in split.test
    ]

    # Walk-forward predictions: each made by a model that saw only earlier, purged data.
    oos_predictions: list[ModelPrediction] = []
    wf_true: list[int] = []
    wf_prob: list[float] = []
    for index, (fold_train, fold_predict, _) in enumerate(walk_forward_folds(samples)):
        try:
            fold_bundle = fit_bundle(fold_train, window, best_c, version)
        except InsufficientData:
            continue
        fold_prob, _, _ = fold_bundle.predict(fold_predict)
        wf_true.extend(s.up for s in fold_predict)
        wf_prob.extend(fold_prob)
        oos_predictions.extend(
            to_predictions(fold_bundle, fold_predict, decision_latency, f"{version}-wf{index}")
        )

    # A model "beats the baseline" only if the lower bound of its accuracy interval is
    # above every naive accuracy and its probabilities beat a constant rate. Anything
    # less is reported as no demonstrated skill.
    ci_low = test_metrics.get("accuracy_ci_low")
    naive_accuracies = [
        baselines.get("majority_class_accuracy"),
        baselines.get("always_up_accuracy"),
        baselines.get("coin_flip_accuracy"),
    ]
    best_naive = max((a for a in naive_accuracies if a is not None), default=None)
    log_loss_value = test_metrics.get("log_loss")
    constant_loss = baselines.get("constant_rate_log_loss")
    beats = bool(
        ci_low is not None
        and best_naive is not None
        and log_loss_value is not None
        and constant_loss is not None
        and ci_low > best_naive
        and log_loss_value < constant_loss
    )
    report = ModelReport(
        model_name=MODEL_NAME,
        model_version=version,
        created_at=created,
        window=window,
        classifier_version=CLASSIFIER_VERSION,
        samples_total=len(samples),
        events_total=len({s.event_id for s in samples}),
        splits={
            "train": _split_info(split.train),
            "validation": _split_info(split.validation),
            "test": _split_info(split.test),
        },
        selected_params={
            "C": best_c,
            "validation_log_loss_by_C": {str(c): v for c, v in scores.items()},
            "text": "tfidf 1-2 grams, min_df 3, max 5000 features",
            "final_fit": "train + validation",
            "purged": "samples whose label window reaches the next period are dropped",
        },
        validation_metrics=direction_metrics(validation_up, validation_prob),
        test_metrics=test_metrics,
        baselines=baselines,
        magnitude_metrics=magnitude_metrics(
            [s.abnormal_ret for s in split.test], test_mag, train_mean
        ),
        volatility_metrics=volatility_metrics(test_high_vol, [v for v in test_vol if v is not None])
        if bundle.volatility_model is not None
        else {"samples": 0.0},
        walk_forward_metrics=direction_metrics(wf_true, wf_prob),
        high_vol_threshold=bundle.high_vol_threshold,
        beats_baseline=beats,
        data_quality=data_quality,
        caveats=CAVEATS,
    )
    return bundle, report, oos_predictions


def train_baseline(
    paths: DataPaths,
    settings: Settings,
    universe: Universe,
    window: EventWindow = EventWindow.D1,
    min_samples: int = 200,
) -> ModelReport:
    """Train on stored events and features, save the model, its report, and its
    out-of-sample predictions."""
    events = load_events(paths)
    features = load_features(paths)
    samples = build_samples(events, features, universe, window)
    qualities = {f.quality for f in features if f.available and f.window is window}
    quality = DataQuality.lowest(list(qualities)) if qualities else DataQuality.DELAYED
    bundle, report, predictions = train_on_samples(
        samples,
        window,
        min_samples,
        timedelta(seconds=settings.decision_latency_seconds),
        quality,
    )
    save_bundle(paths, bundle, report)
    write_parquet_atomic(to_frame(predictions, ModelPrediction), paths.gold_predictions)
    log.info(
        "model trained",
        extra={
            "version": report.model_version,
            "test": report.test_metrics,
            "oos": len(predictions),
        },
    )
    return report
