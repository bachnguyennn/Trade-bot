from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.contracts import (
    Entity,
    EntityType,
    EventCategory,
    IngestionMode,
    MarketEvent,
    SocialPost,
)
from src.core.storage import (
    DataPaths,
    empty_frame,
    from_frame,
    read_parquet,
    to_frame,
    write_parquet_atomic,
)

T0 = datetime(2025, 3, 3, 14, 5, tzinfo=UTC)


def test_missing_file_reads_as_empty_frame(tmp_path: Path) -> None:
    frame = read_parquet(tmp_path / "nope.parquet", SocialPost)
    assert frame.height == 0
    assert frame.columns == empty_frame(SocialPost).columns


def test_post_round_trip(tmp_path: Path) -> None:
    post = SocialPost(
        post_id="1",
        source="file",
        account="acct",
        text="hello",
        url="https://example.invalid/1",
        published_at=T0,
        retrieved_at=T0,
        ingestion_mode=IngestionMode.HISTORICAL,
        media_urls=["https://example.invalid/a.jpg"],
        content_hash="h",
    )
    path = tmp_path / "silver" / "posts.parquet"
    write_parquet_atomic(to_frame([post], SocialPost), path)
    assert from_frame(read_parquet(path, SocialPost), SocialPost) == [post]
    assert not path.with_suffix(".parquet.tmp").exists()


def test_event_round_trip_keeps_entities_and_categories(tmp_path: Path) -> None:
    event = MarketEvent(
        event_id="e1",
        post_ids=["1", "2"],
        text="tariffs on China",
        published_at=T0,
        available_at=T0,
        categories=[EventCategory.TARIFFS_TRADE, EventCategory.SANCTIONS_INTERNATIONAL],
        entities=[Entity(text="China", type=EntityType.COUNTRY, symbol="FXI")],
        symbols=["FXI"],
        relevance_score=0.8,
        classifier_version="rules-v1",
    )
    path = tmp_path / "gold" / "events.parquet"
    write_parquet_atomic(to_frame([event], MarketEvent), path)
    assert from_frame(read_parquet(path, MarketEvent), MarketEvent) == [event]


def test_empty_list_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "posts.parquet"
    write_parquet_atomic(to_frame([], SocialPost), path)
    assert from_frame(read_parquet(path, SocialPost), SocialPost) == []


def test_paths_layout(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    assert (
        paths.silver_candles("1d", "SPY") == tmp_path / "silver" / "candles" / "1d" / "SPY.parquet"
    )
    assert paths.bronze_post_files() == []
    assert paths.report_files("event_study") == []
