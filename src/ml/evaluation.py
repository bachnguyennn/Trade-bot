"""Model evaluation. Every metric is computed from held-out data and reported with baselines."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from src.contracts import DataQuality, EventWindow

CAVEATS = [
    "Metrics describe past data. They are not evidence of future performance.",
    "Samples from the same event or the same day are correlated, so intervals are too narrow.",
    "Labels are abnormal returns versus the benchmark, with no beta adjustment.",
    "Event selection and symbol mapping come from keyword rules (rules-v1).",
    "The symbol universe was chosen today, which introduces survivorship bias.",
    "A model is useful only if it beats the naive baselines listed next to it.",
    "The volatility head can score well simply by knowing which symbols are volatile; that "
    "is not evidence that it understands the posts.",
]


class SplitInfo(BaseModel):
    start: datetime | None
    end: datetime | None
    samples: int
    events: int


class ModelReport(BaseModel):
    model_name: str
    model_version: str
    created_at: datetime
    window: EventWindow
    classifier_version: str
    samples_total: int
    events_total: int
    splits: dict[str, SplitInfo]
    selected_params: dict[str, Any]
    validation_metrics: dict[str, float | None]
    test_metrics: dict[str, float | None]
    baselines: dict[str, float | None]
    magnitude_metrics: dict[str, float | None]
    volatility_metrics: dict[str, float | None]
    walk_forward_metrics: dict[str, float | None]
    high_vol_threshold: float
    beats_baseline: bool
    data_quality: DataQuality
    caveats: list[str]


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """95% confidence interval for a proportion."""
    if n == 0:
        return None, None
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return centre - half, centre + half


def direction_metrics(y_true: list[int], prob_up: list[float]) -> dict[str, float | None]:
    """Accuracy, balanced accuracy, AUC, Brier score, and log loss for up/down prediction."""
    from sklearn.metrics import balanced_accuracy_score, brier_score_loss, log_loss, roc_auc_score

    n = len(y_true)
    if n == 0:
        return {"samples": 0.0}
    predicted = [1 if p > 0.5 else 0 for p in prob_up]
    correct = sum(1 for t, p in zip(y_true, predicted, strict=True) if t == p)
    low, high = wilson_interval(correct, n)
    both_classes = len(set(y_true)) == 2
    clipped = [min(1 - 1e-6, max(1e-6, p)) for p in prob_up]
    return {
        "samples": float(n),
        "accuracy": correct / n,
        "accuracy_ci_low": low,
        "accuracy_ci_high": high,
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predicted))
        if both_classes
        else None,
        "roc_auc": float(roc_auc_score(y_true, prob_up)) if both_classes else None,
        "brier": float(brier_score_loss(y_true, clipped)),
        "log_loss": float(log_loss(y_true, clipped, labels=[0, 1])),
        "share_up": sum(y_true) / n,
    }


def naive_baselines(train_up: list[int], test_up: list[int]) -> dict[str, float | None]:
    """What a model with no skill would score on the test period."""
    if not test_up:
        return {}
    majority = 1 if sum(train_up) * 2 >= len(train_up) else 0
    share_up = sum(test_up) / len(test_up)
    train_rate = sum(train_up) / len(train_up) if train_up else 0.5
    rate = min(1 - 1e-6, max(1e-6, train_rate))
    constant_log_loss = -sum(
        math.log(rate) if y == 1 else math.log(1 - rate) for y in test_up
    ) / len(test_up)
    return {
        "majority_class_accuracy": share_up if majority == 1 else 1 - share_up,
        "always_up_accuracy": share_up,
        "coin_flip_accuracy": 0.5,
        "constant_rate_log_loss": constant_log_loss,
        "constant_rate_brier": sum((rate - y) ** 2 for y in test_up) / len(test_up),
    }


def magnitude_metrics(
    y_true: list[float], y_pred: list[float], train_mean: float
) -> dict[str, float | None]:
    """Error of the predicted abnormal return, against predicting zero or the training mean."""
    n = len(y_true)
    if n == 0:
        return {"samples": 0.0}

    def mae(pred: list[float]) -> float:
        return sum(abs(t - p) for t, p in zip(y_true, pred, strict=True)) / n

    rank_ic: float | None = None
    if n >= 3 and len(set(y_pred)) > 1 and len(set(y_true)) > 1:
        from scipy.stats import spearmanr

        value = float(spearmanr(y_true, y_pred).statistic)
        rank_ic = None if math.isnan(value) else value
    return {
        "samples": float(n),
        "mae": mae(y_pred),
        "mae_predict_zero": mae([0.0] * n),
        "mae_predict_train_mean": mae([train_mean] * n),
        "rank_ic": rank_ic,
    }


def volatility_metrics(y_true: list[int], prob: list[float]) -> dict[str, float | None]:
    from sklearn.metrics import roc_auc_score

    n = len(y_true)
    if n == 0:
        return {"samples": 0.0}
    both = len(set(y_true)) == 2
    return {
        "samples": float(n),
        "roc_auc": float(roc_auc_score(y_true, prob)) if both else None,
        "base_rate": sum(y_true) / n,
    }
