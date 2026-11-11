"""Candle storage: one Parquet file per symbol and interval, keyed by bar start time."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from src.contracts import DataQuality, StockCandle
from src.core.storage import SCHEMAS, DataPaths, empty_frame, from_frame, write_parquet_atomic

CANDLE_COLUMNS = list(SCHEMAS[StockCandle])
_QUALITY_RANK = {q.value: q.rank for q in DataQuality}


def validate_candle_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Coerce to the stored schema and drop rows that break the candle rules."""
    if frame.height == 0:
        return empty_frame(StockCandle)
    frame = frame.select(CANDLE_COLUMNS).cast(SCHEMAS[StockCandle])  # type: ignore[arg-type]
    price_cols = ["open", "high", "low", "close"]
    frame = frame.drop_nulls(subset=[*price_cols, "volume", "ts"])
    frame = frame.filter(
        pl.all_horizontal(pl.col(c) > 0 for c in price_cols) & (pl.col("volume") >= 0)
    )
    # Providers occasionally return a high or low that misses open or close by float noise.
    frame = frame.with_columns(
        pl.max_horizontal("open", "high", "close").alias("high"),
        pl.min_horizontal("open", "low", "close").alias("low"),
    )
    return frame


class CandleStore:
    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths
        self._cache: dict[tuple[str, str], pl.DataFrame] = {}

    def upsert(self, frame: pl.DataFrame) -> int:
        """Merge candles into the store. Returns the number of new or replaced rows.

        A stored bar is never replaced by a lower-quality bar for the same time.
        """
        frame = validate_candle_frame(frame)
        written = 0
        for (symbol, interval), group in frame.group_by(["symbol", "interval"]):
            key = (str(symbol), str(interval))
            existing = self.read(key[0], key[1])
            incoming = group.unique(subset=["ts"], keep="last")
            if existing.height:
                merged = pl.concat(
                    [
                        existing.with_columns(pl.lit(0).alias("_order")),
                        incoming.with_columns(pl.lit(1).alias("_order")),
                    ]
                )
                merged = (
                    merged.with_columns(
                        pl.col("quality")
                        .replace_strict(_QUALITY_RANK, return_dtype=pl.Int64)
                        .alias("_rank")
                    )
                    .sort(["ts", "_rank", "_order"])
                    .unique(subset=["ts"], keep="last", maintain_order=True)
                    .drop(["_rank", "_order"])
                )
            else:
                merged = incoming
            merged = merged.sort("ts")
            write_parquet_atomic(merged, self._paths.silver_candles(key[1], key[0]))
            self._cache[key] = merged
            written += incoming.height
        return written

    def read(
        self,
        symbol: str,
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Candles for one symbol and interval, sorted by time. Empty when nothing is stored."""
        key = (symbol, interval)
        if key not in self._cache:
            path = self._paths.silver_candles(interval, symbol)
            self._cache[key] = (
                pl.read_parquet(path).sort("ts") if path.exists() else empty_frame(StockCandle)
            )
        frame = self._cache[key]
        if start is not None:
            frame = frame.filter(pl.col("ts") >= start)
        if end is not None:
            frame = frame.filter(pl.col("ts") <= end)
        return frame

    def read_models(
        self,
        symbol: str,
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[StockCandle]:
        return from_frame(self.read(symbol, interval, start, end), StockCandle)

    def symbols(self, interval: str) -> list[str]:
        return self._paths.silver_candle_symbols(interval)

    def intervals(self) -> list[str]:
        base = self._paths.root / "silver" / "candles"
        return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []

    def count(self) -> int:
        total = 0
        for interval in self.intervals():
            for symbol in self.symbols(interval):
                total += self.read(symbol, interval).height
        return total

    def quality_summary(self) -> dict[str, int]:
        """Number of stored bars per quality label."""
        summary: dict[str, int] = {}
        for interval in self.intervals():
            for symbol in self.symbols(interval):
                counts = self.read(symbol, interval)["quality"].value_counts()
                for quality, count in counts.iter_rows():
                    summary[quality] = summary.get(quality, 0) + int(count)
        return summary

    def clear_cache(self) -> None:
        self._cache.clear()
