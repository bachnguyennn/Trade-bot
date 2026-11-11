"""Post ingestion from a synthetic archive file through Bronze to Silver."""

from __future__ import annotations

import json
from datetime import UTC, timedelta
from pathlib import Path

import pytest

from src.contracts import IngestionMode
from src.core.settings import Settings
from src.core.storage import DataPaths, read_parquet
from src.core.timeutils import utc_now
from src.ingestion.bronze import read_bronze
from src.ingestion.sources import ArchiveFileSource, SourceNotPermitted, build_source
from src.pipelines.posts import ingest_posts, load_posts


async def run(path: Path, paths: DataPaths, settings: Settings, mode: IngestionMode) -> object:
    return await ingest_posts(ArchiveFileSource(path), mode, paths, settings)


async def test_import_stores_clean_posts(
    posts_fixture: Path, paths: DataPaths, settings: Settings
) -> None:
    report = await ingest_posts(
        ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings
    )
    posts = load_posts(paths)

    assert report.records_fetched == 9
    assert report.posts_total == 7  # one duplicate, one rejected
    assert report.posts_new == 7
    assert report.rejected == 1
    assert report.rejection_reasons == {"missing or unparseable publication time": 1}

    assert [p.post_id for p in posts] == sorted(p.post_id for p in posts)
    for post in posts:
        assert post.published_at.utcoffset() == timedelta(0)
        assert post.retrieved_at.utcoffset() == timedelta(0)
        assert post.ingestion_mode is IngestionMode.HISTORICAL

    by_id = {p.post_id: p for p in posts}
    assert by_id["900000000000000004"].is_repost
    assert by_id["900000000000000004"].reposted_from == "SomeAccount"
    assert by_id["900000000000000005"].text == "" and by_id["900000000000000005"].has_media
    assert "<p>" not in by_id["900000000000000001"].text


async def test_raw_records_are_preserved(
    posts_fixture: Path, paths: DataPaths, settings: Settings
) -> None:
    await ingest_posts(ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings)
    bronze = read_bronze(paths)
    original = json.loads(posts_fixture.read_text(encoding="utf-8"))
    assert bronze.height == len(original)
    assert [json.loads(r) for r in bronze["raw_json"]] == original
    rejections = read_parquet(paths.silver_rejections)
    assert rejections.height == 1
    assert "900000000000000006" in rejections["raw_json"][0]


async def test_import_is_idempotent(
    posts_fixture: Path, paths: DataPaths, settings: Settings
) -> None:
    first = await ingest_posts(
        ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings
    )
    before = load_posts(paths)
    second = await ingest_posts(
        ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings
    )

    assert second.payload_unchanged and second.fetch_id is None
    assert second.posts_new == 0 and second.posts_edited == 0
    assert second.posts_total == first.posts_total
    assert load_posts(paths) == before
    assert len(paths.bronze_post_files()) == 1


def rewrite(source: Path, target: Path, mutate: object) -> Path:
    records = json.loads(source.read_text(encoding="utf-8"))
    records = mutate(records)  # type: ignore[operator]
    target.write_text(json.dumps(records), encoding="utf-8")
    return target


async def test_edit_bumps_version_and_keeps_history(
    posts_fixture: Path, paths: DataPaths, settings: Settings, tmp_path: Path
) -> None:
    await ingest_posts(ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings)

    def edit(records: list[dict[str, object]]) -> list[dict[str, object]]:
        for record in records:
            if record["id"] == "900000000000000003":
                record["content"] = "<p>SYNTHETIC TEST FIXTURE. Edited text about oil.</p>"
        return records

    edited_file = rewrite(posts_fixture, tmp_path / "edited.json", edit)
    report = await ingest_posts(
        ArchiveFileSource(edited_file), IngestionMode.HISTORICAL, paths, settings
    )

    post = {p.post_id: p for p in load_posts(paths)}["900000000000000003"]
    assert report.posts_edited == 1 and report.posts_new == 0
    assert post.version == 2 and post.is_edited
    assert post.text.endswith("Edited text about oil.")
    # The original wording is still in the raw layer.
    assert any("DRILL, BABY, DRILL" in raw for raw in read_bronze(paths)["raw_json"])


async def test_deleted_post_is_marked_not_removed(
    posts_fixture: Path, paths: DataPaths, settings: Settings, tmp_path: Path
) -> None:
    await ingest_posts(ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings)
    smaller = rewrite(
        posts_fixture,
        tmp_path / "smaller.json",
        lambda records: [r for r in records if r["id"] != "900000000000000007"],
    )
    report = await ingest_posts(
        ArchiveFileSource(smaller), IngestionMode.HISTORICAL, paths, settings
    )
    by_id = {p.post_id: p for p in load_posts(paths)}
    assert report.posts_deleted == 1
    assert by_id["900000000000000007"].is_deleted
    assert sum(p.is_deleted for p in by_id.values()) == 1


async def test_incremental_fetch_adds_only_new_posts_as_live(
    posts_fixture: Path, paths: DataPaths, settings: Settings, tmp_path: Path
) -> None:
    await ingest_posts(ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings)
    fresh_time = (utc_now() - timedelta(minutes=3)).astimezone(UTC)

    def add(records: list[dict[str, object]]) -> list[dict[str, object]]:
        records.append(
            {
                "id": "900000000000000099",
                "created_at": fresh_time.isoformat(),
                "content": "<p>SYNTHETIC TEST FIXTURE. Fresh post about tariffs.</p>",
                "media": [],
            }
        )
        return records

    grown = rewrite(posts_fixture, tmp_path / "grown.json", add)
    report = await ingest_posts(ArchiveFileSource(grown), IngestionMode.LIVE, paths, settings)

    by_id = {p.post_id: p for p in load_posts(paths)}
    assert report.posts_new == 1 and report.new_post_ids == ["900000000000000099"]
    assert by_id["900000000000000099"].ingestion_mode is IngestionMode.LIVE
    # Posts already known keep their first retrieval time and historical mode.
    assert by_id["900000000000000001"].ingestion_mode is IngestionMode.HISTORICAL
    assert by_id["900000000000000001"].retrieved_at < by_id["900000000000000099"].retrieved_at


async def test_old_post_seen_by_live_fetch_is_backfill(
    posts_fixture: Path, paths: DataPaths, settings: Settings
) -> None:
    await ingest_posts(ArchiveFileSource(posts_fixture), IngestionMode.LIVE, paths, settings)
    assert all(p.ingestion_mode is IngestionMode.HISTORICAL for p in load_posts(paths))


def test_unverified_source_is_refused_by_default(settings: Settings) -> None:
    with pytest.raises(SourceNotPermitted):
        build_source("cnn", settings)
    allowed = settings.model_copy(update={"allow_unverified_sources": True})
    assert build_source("cnn", allowed).name == "cnn"
    assert build_source("stiles", settings).name == "stiles"
