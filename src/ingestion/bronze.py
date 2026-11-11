"""Bronze layer: raw records exactly as fetched, append-only, one file per fetch."""

from __future__ import annotations

import json
from typing import Any

import polars as pl

from src.contracts import IngestionMode
from src.core.storage import DataPaths, write_parquet_atomic
from src.ingestion.sources import RawFetch

BRONZE_SCHEMA: dict[str, Any] = {
    "fetch_id": pl.String,
    "source": pl.String,
    "origin": pl.String,
    "fetched_at": pl.Datetime("us", "UTC"),
    "ingestion_mode": pl.String,
    "is_full_snapshot": pl.Boolean,
    "payload_sha256": pl.String,
    "record_index": pl.Int64,
    "raw_json": pl.String,
}


def fetch_id(fetch: RawFetch) -> str:
    return f"{fetch.fetched_at.strftime('%Y%m%dT%H%M%S%fZ')}-{fetch.payload_sha256[:12]}"


def known_payload_hashes(paths: DataPaths, source: str) -> set[str]:
    """Payload hashes already stored for a source, used to skip identical re-fetches."""
    hashes: set[str] = set()
    directory = paths.bronze_posts_dir(source)
    if not directory.exists():
        return hashes
    for file in directory.glob("*.parquet"):
        frame = pl.read_parquet(file, columns=["payload_sha256"]).head(1)
        if frame.height:
            hashes.add(frame["payload_sha256"][0])
    return hashes


def write_bronze(paths: DataPaths, fetch: RawFetch, mode: IngestionMode) -> str | None:
    """Store a fetch unmodified. Returns the fetch id, or None if the payload is already stored."""
    if fetch.payload_sha256 in known_payload_hashes(paths, fetch.source):
        return None
    fid = fetch_id(fetch)
    rows = [
        {
            "fetch_id": fid,
            "source": fetch.source,
            "origin": fetch.origin,
            "fetched_at": fetch.fetched_at,
            "ingestion_mode": mode.value,
            "is_full_snapshot": fetch.is_full_snapshot,
            "payload_sha256": fetch.payload_sha256,
            "record_index": index,
            "raw_json": json.dumps(record, ensure_ascii=False, sort_keys=True),
        }
        for index, record in enumerate(fetch.records)
    ]
    frame = pl.DataFrame(rows, schema=BRONZE_SCHEMA, orient="row")
    write_parquet_atomic(frame, paths.bronze_posts_dir(fetch.source) / f"{fid}.parquet")
    return fid


def read_bronze(paths: DataPaths) -> pl.DataFrame:
    """All Bronze records in fetch order."""
    files = paths.bronze_post_files()
    if not files:
        return pl.DataFrame(schema=BRONZE_SCHEMA)
    frame = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")
    return frame.sort(["fetched_at", "fetch_id", "record_index"])
