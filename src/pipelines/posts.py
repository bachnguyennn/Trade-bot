"""Bronze to Silver for posts: deduplicate, track edits and deletions, report rejections."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import polars as pl
from pydantic import BaseModel

from src.contracts import IngestionMode, SocialPost
from src.core.logging import get_logger
from src.core.settings import Settings
from src.core.storage import (
    DataPaths,
    from_frame,
    read_parquet,
    to_frame,
    write_parquet_atomic,
)
from src.ingestion.bronze import read_bronze, write_bronze
from src.ingestion.normalize import Rejection, normalize_record
from src.ingestion.sources import PostSource

log = get_logger(__name__)

# A post first seen by a live fetch counts as live only if it was collected soon after
# publication. Older posts picked up by a live fetch are backfill.
LIVE_MAX_LAG = timedelta(hours=24)

REJECTION_SCHEMA: dict[str, Any] = {
    "fetch_id": pl.String,
    "source": pl.String,
    "record_index": pl.Int64,
    "reason": pl.String,
    "raw_json": pl.String,
}


class IngestReport(BaseModel):
    """Summary of one ingestion run."""

    source: str
    fetch_id: str | None
    payload_unchanged: bool
    records_fetched: int
    posts_total: int
    posts_new: int
    posts_edited: int
    posts_deleted: int
    rejected: int
    rejection_reasons: dict[str, int]
    new_post_ids: list[str] = []


def build_silver_posts(
    paths: DataPaths, settings: Settings
) -> tuple[list[SocialPost], pl.DataFrame]:
    """Rebuild the clean post table from every Bronze record, in fetch order.

    The build is deterministic: the same Bronze files always give the same Silver table.
    """
    bronze = read_bronze(paths)
    state: dict[str, dict[str, Any]] = {}
    rejections: list[dict[str, Any]] = []
    seen_in_source: dict[str, set[str]] = {}
    latest_snapshot: dict[str, set[str]] = {}

    for (fid,), group in bronze.group_by(["fetch_id"], maintain_order=True):
        first = group.row(0, named=True)
        source: str = first["source"]
        fetched_at: datetime = first["fetched_at"]
        fetch_mode = IngestionMode(first["ingestion_mode"])
        ids_in_fetch: set[str] = set()

        for row in group.iter_rows(named=True):
            normalised = normalize_record(json.loads(row["raw_json"]), settings.account)
            if isinstance(normalised, Rejection):
                rejections.append(
                    {
                        "fetch_id": str(fid),
                        "source": source,
                        "record_index": row["record_index"],
                        "reason": normalised.reason,
                        "raw_json": row["raw_json"],
                    }
                )
                continue

            ids_in_fetch.add(normalised.post_id)
            existing = state.get(normalised.post_id)
            if existing is None:
                is_live = (
                    fetch_mode is IngestionMode.LIVE
                    and fetched_at - normalised.published_at <= LIVE_MAX_LAG
                )
                state[normalised.post_id] = {
                    "post_id": normalised.post_id,
                    "source": source,
                    "account": settings.account,
                    "text": normalised.text,
                    "url": normalised.url,
                    "published_at": normalised.published_at,
                    "retrieved_at": fetched_at,
                    "ingestion_mode": IngestionMode.LIVE if is_live else IngestionMode.HISTORICAL,
                    "is_repost": normalised.is_repost,
                    "reposted_from": normalised.reposted_from,
                    "has_media": bool(normalised.media_urls),
                    "media_urls": normalised.media_urls,
                    "content_hash": normalised.content_hash,
                    "version": 1,
                    "is_edited": False,
                    "is_deleted": False,
                }
            elif existing["content_hash"] != normalised.content_hash:
                # The text changed: keep one row, bump the version. Earlier text stays in Bronze.
                existing.update(
                    text=normalised.text,
                    content_hash=normalised.content_hash,
                    is_repost=normalised.is_repost,
                    reposted_from=normalised.reposted_from,
                    has_media=bool(normalised.media_urls),
                    media_urls=normalised.media_urls,
                    version=existing["version"] + 1,
                    is_edited=True,
                )

        seen_in_source.setdefault(source, set()).update(ids_in_fetch)
        if first["is_full_snapshot"]:
            latest_snapshot[source] = ids_in_fetch

    # A post is deleted when every source that once carried it has dropped it from its
    # latest full snapshot.
    for post_id, record in state.items():
        carriers = [
            s for s, ids in seen_in_source.items() if post_id in ids and s in latest_snapshot
        ]
        if carriers and all(post_id not in latest_snapshot[s] for s in carriers):
            record["is_deleted"] = True

    posts = [SocialPost.model_validate(r) for r in state.values()]
    posts.sort(key=lambda p: (p.published_at, p.post_id))
    rejection_frame = pl.DataFrame(rejections, schema=REJECTION_SCHEMA, orient="row")
    return posts, rejection_frame


def load_posts(paths: DataPaths) -> list[SocialPost]:
    return from_frame(read_parquet(paths.silver_posts, SocialPost), SocialPost)


async def ingest_posts(
    source: PostSource, mode: IngestionMode, paths: DataPaths, settings: Settings
) -> IngestReport:
    """Fetch a source, store it in Bronze, and rebuild Silver. Safe to run repeatedly."""
    before = read_parquet(paths.silver_posts, SocialPost)
    before_versions = dict(zip(before["post_id"], before["version"], strict=True))
    before_deleted = int(before["is_deleted"].sum()) if before.height else 0

    fetch = await source.fetch()
    fid = write_bronze(paths, fetch, mode)

    posts, rejections = build_silver_posts(paths, settings)
    write_parquet_atomic(to_frame(posts, SocialPost), paths.silver_posts)
    write_parquet_atomic(rejections, paths.silver_rejections)

    new_ids = [p.post_id for p in posts if p.post_id not in before_versions]
    edited = sum(
        1 for p in posts if p.post_id in before_versions and p.version > before_versions[p.post_id]
    )
    reasons: dict[str, int] = {}
    for reason in rejections["reason"]:
        reasons[reason] = reasons.get(reason, 0) + 1

    report = IngestReport(
        source=fetch.source,
        fetch_id=fid,
        payload_unchanged=fid is None,
        records_fetched=len(fetch.records),
        posts_total=len(posts),
        posts_new=len(new_ids),
        posts_edited=edited,
        posts_deleted=sum(1 for p in posts if p.is_deleted) - before_deleted,
        rejected=rejections.height,
        rejection_reasons=reasons,
        new_post_ids=new_ids if len(new_ids) <= 200 else [],
    )
    log.info("posts ingested", extra=report.model_dump(exclude={"new_post_ids"}))
    return report
