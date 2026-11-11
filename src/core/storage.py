"""File layout and Parquet helpers for the Bronze, Silver, and Gold layers."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel

from src.contracts import (
    MarketEvent,
    MarketFeature,
    ModelPrediction,
    SocialPost,
    StockCandle,
    TradingSignal,
)

_TS = pl.Datetime("us", "UTC")

# Explicit schemas keep empty and single-row files readable and stable across versions.
SCHEMAS: dict[type[BaseModel], dict[str, Any]] = {
    SocialPost: {
        "post_id": pl.String,
        "source": pl.String,
        "account": pl.String,
        "text": pl.String,
        "url": pl.String,
        "published_at": _TS,
        "retrieved_at": _TS,
        "ingestion_mode": pl.String,
        "is_repost": pl.Boolean,
        "reposted_from": pl.String,
        "has_media": pl.Boolean,
        "media_urls": pl.List(pl.String),
        "content_hash": pl.String,
        "version": pl.Int64,
        "is_edited": pl.Boolean,
        "is_deleted": pl.Boolean,
    },
    MarketEvent: {
        "event_id": pl.String,
        "post_ids": pl.List(pl.String),
        "text": pl.String,
        "published_at": _TS,
        "available_at": _TS,
        "categories": pl.List(pl.String),
        "entities": pl.String,  # JSON
        "symbols": pl.List(pl.String),
        "relevance_score": pl.Float64,
        "classifier_version": pl.String,
    },
    StockCandle: {
        "symbol": pl.String,
        "interval": pl.String,
        "ts": _TS,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "volume": pl.Float64,
        "adjusted": pl.Boolean,
        "source": pl.String,
        "quality": pl.String,
    },
    MarketFeature: {
        "event_id": pl.String,
        "symbol": pl.String,
        "window": pl.String,
        "anchor_ts": _TS,
        "entry_ts": _TS,
        "exit_ts": _TS,
        "entry_price": pl.Float64,
        "exit_price": pl.Float64,
        "ret": pl.Float64,
        "benchmark_ret": pl.Float64,
        "abnormal_ret": pl.Float64,
        "realized_vol": pl.Float64,
        "volume_ratio": pl.Float64,
        "tradable": pl.Boolean,
        "shifted_to_open": pl.Boolean,
        "available": pl.Boolean,
        "unavailable_reason": pl.String,
        "quality": pl.String,
    },
    ModelPrediction: {
        "prediction_id": pl.String,
        "event_id": pl.String,
        "symbol": pl.String,
        "window": pl.String,
        "model_name": pl.String,
        "model_version": pl.String,
        "predicted_at": _TS,
        "direction": pl.String,
        "prob_up": pl.Float64,
        "expected_abnormal_return": pl.Float64,
        "prob_high_vol": pl.Float64,
        "confidence": pl.Float64,
    },
    TradingSignal: {
        "signal_id": pl.String,
        "event_id": pl.String,
        "symbol": pl.String,
        "strategy": pl.String,
        "action": pl.String,
        "generated_at": _TS,
        "target_weight": pl.Float64,
        "holding_window": pl.String,
        "stop_loss_pct": pl.Float64,
        "reason": pl.String,
        "prediction_id": pl.String,
    },
}

_JSON_FIELDS: dict[type[BaseModel], set[str]] = {MarketEvent: {"entities"}}


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def to_frame[T: BaseModel](models: Iterable[T], cls: type[T]) -> pl.DataFrame:
    """Convert contract instances to a DataFrame with the stored schema."""
    schema = SCHEMAS[cls]
    json_fields = _JSON_FIELDS.get(cls, set())
    rows: list[dict[str, Any]] = []
    for model in models:
        data = model.model_dump(mode="python")
        row: dict[str, Any] = {}
        for name in schema:
            if name in json_fields:
                row[name] = json.dumps(model.model_dump(mode="json")[name], sort_keys=True)
            else:
                row[name] = _plain(data[name])
        rows.append(row)
    return pl.DataFrame(rows, schema=schema, orient="row")


def from_frame[T: BaseModel](frame: pl.DataFrame, cls: type[T]) -> list[T]:
    """Convert stored rows back to validated contract instances."""
    json_fields = _JSON_FIELDS.get(cls, set())
    out: list[T] = []
    for row in frame.to_dicts():
        for name in json_fields:
            row[name] = json.loads(row[name]) if row.get(name) else []
        out.append(cls.model_validate(row))
    return out


def empty_frame(cls: type[BaseModel]) -> pl.DataFrame:
    return pl.DataFrame(schema=SCHEMAS[cls])


def write_parquet_atomic(frame: pl.DataFrame, path: Path) -> None:
    """Write to a temporary file and rename, so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.write_parquet(tmp)
    os.replace(tmp, path)


def read_parquet(path: Path, cls: type[BaseModel] | None = None) -> pl.DataFrame:
    """Read a Parquet file. A missing file yields an empty frame, never invented rows."""
    if not path.exists():
        return empty_frame(cls) if cls is not None else pl.DataFrame()
    return pl.read_parquet(path)


def write_json_atomic(payload: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


class DataPaths:
    """Locations of every stored artifact under one data directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # Bronze
    def bronze_posts_dir(self, source: str) -> Path:
        return self.root / "bronze" / "posts" / source

    def bronze_post_files(self) -> list[Path]:
        base = self.root / "bronze" / "posts"
        return sorted(base.glob("*/*.parquet")) if base.exists() else []

    # Silver
    @property
    def silver_posts(self) -> Path:
        return self.root / "silver" / "posts.parquet"

    @property
    def silver_rejections(self) -> Path:
        return self.root / "silver" / "post_rejections.parquet"

    def silver_candles(self, interval: str, symbol: str) -> Path:
        return self.root / "silver" / "candles" / interval / f"{symbol}.parquet"

    def silver_candle_symbols(self, interval: str) -> list[str]:
        base = self.root / "silver" / "candles" / interval
        return sorted(p.stem for p in base.glob("*.parquet")) if base.exists() else []

    # Gold
    @property
    def gold_events(self) -> Path:
        return self.root / "gold" / "events.parquet"

    @property
    def gold_features(self) -> Path:
        return self.root / "gold" / "features.parquet"

    @property
    def gold_predictions(self) -> Path:
        return self.root / "gold" / "predictions.parquet"

    @property
    def gold_signals(self) -> Path:
        return self.root / "gold" / "signals.parquet"

    # Reports, models, state
    def reports_dir(self, kind: str) -> Path:
        return self.root / "reports" / kind

    def report_files(self, kind: str) -> list[Path]:
        base = self.reports_dir(kind)
        return sorted(base.glob("*.json")) if base.exists() else []

    def models_dir(self, name: str) -> Path:
        return self.root / "models" / name

    @property
    def orders_db(self) -> Path:
        return self.root / "state" / "orders.sqlite"


def concat_frames(frames: Sequence[pl.DataFrame], cls: type[BaseModel]) -> pl.DataFrame:
    non_empty = [f for f in frames if f.height > 0]
    if not non_empty:
        return empty_frame(cls)
    return pl.concat(non_empty, how="vertical_relaxed")
