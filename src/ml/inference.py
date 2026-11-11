"""Inference: predictions for stored events or new text, always tagged with a model version."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from src.contracts import MarketEvent, ModelPrediction
from src.core.settings import Settings
from src.core.storage import DataPaths
from src.core.timeutils import utc_now
from src.market_data.universe import Universe
from src.ml.baseline import Bundle, latest_version, load_bundle, to_predictions
from src.ml.classifier import RuleBasedClassifier
from src.ml.dataset import Sample, categorical_inputs
from src.ml.entities import EntityRecognizer


class ModelUnavailable(RuntimeError):
    """Raised when no trained model exists."""


class ModelVersionMismatch(RuntimeError):
    """Raised when the caller expects a different model version than the one loaded."""


class InferenceService:
    def __init__(self, paths: DataPaths, settings: Settings, universe: Universe) -> None:
        self._paths = paths
        self._universe = universe
        self._latency = timedelta(seconds=settings.decision_latency_seconds)
        self._classifier = RuleBasedClassifier()
        self._recognizer = EntityRecognizer(universe)
        self._bundle: Bundle | None = None

    def bundle(self, expected_version: str | None = None) -> Bundle:
        """Load the latest model. Fails rather than guessing when none exists."""
        version = latest_version(self._paths)
        if version is None:
            raise ModelUnavailable("no trained model found; run `tradebot model train` first")
        if self._bundle is None or self._bundle.version != version:
            loaded = load_bundle(self._paths, version)
            if loaded is None:
                raise ModelUnavailable(f"model files for version {version} are missing")
            self._bundle = loaded
        if expected_version is not None and expected_version != self._bundle.version:
            raise ModelVersionMismatch(
                f"requested model version {expected_version}, but the loaded version is "
                f"{self._bundle.version}"
            )
        return self._bundle

    @property
    def version(self) -> str | None:
        return latest_version(self._paths)

    def predict_event(
        self, event: MarketEvent, expected_version: str | None = None
    ) -> list[ModelPrediction]:
        """Predictions for every affected symbol of an event."""
        bundle = self.bundle(expected_version)
        samples = [
            Sample(
                event_id=event.event_id,
                symbol=symbol,
                available_at=event.available_at,
                label_end=event.available_at,
                text=event.text,
                categorical=categorical_inputs(
                    event.text, symbol, self._universe, self._classifier
                ),
                abnormal_ret=0.0,
            )
            for symbol in event.symbols
        ]
        return to_predictions(bundle, samples, self._latency)

    def predict_text(
        self,
        text: str,
        symbols: list[str] | None = None,
        expected_version: str | None = None,
    ) -> list[ModelPrediction]:
        """Predictions for arbitrary text. Symbols default to those the rules map it to."""
        bundle = self.bundle(expected_version)
        if symbols:
            chosen = [s.upper() for s in symbols if s.upper() in self._universe]
        else:
            recognition = self._recognizer.recognize(text)
            chosen = list(recognition.direct_symbols) + list(recognition.related_symbols)
            for category in self._classifier.classify(text).categories:
                chosen += self._universe.category_symbols(category)
            chosen = list(dict.fromkeys(s for s in chosen if s != self._universe.benchmark))
        now = utc_now()
        event_id = f"adhoc_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
        samples = [
            Sample(
                event_id=event_id,
                symbol=symbol,
                available_at=now,
                label_end=now,
                text=text,
                categorical=categorical_inputs(text, symbol, self._universe, self._classifier),
                abnormal_ret=0.0,
            )
            for symbol in chosen
        ]
        return to_predictions(bundle, samples, timedelta(0))
