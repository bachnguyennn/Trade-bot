"""Silver posts to Gold events on the synthetic fixture."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.contracts import EntityType, EventCategory, IngestionMode, SocialPost
from src.core.settings import Settings
from src.core.storage import DataPaths
from src.ingestion.normalize import content_hash
from src.ingestion.sources import ArchiveFileSource
from src.market_data.universe import default_universe
from src.pipelines.events import EventBuilder, build_events, event_id_for, load_events
from src.pipelines.posts import ingest_posts

T0 = datetime(2025, 3, 3, 14, 0, tzinfo=UTC)


def post(post_id: str, text: str, minutes: int, **overrides: object) -> SocialPost:
    data: dict[str, object] = {
        "post_id": post_id,
        "source": "test",
        "account": "acct",
        "text": text,
        "url": f"https://example.invalid/{post_id}",
        "published_at": T0 + timedelta(minutes=minutes),
        "retrieved_at": T0 + timedelta(days=30),
        "ingestion_mode": IngestionMode.HISTORICAL,
        "content_hash": content_hash(text),
    }
    data.update(overrides)
    return SocialPost.model_validate(data)


async def test_fixture_posts_become_events(
    posts_fixture: Path, paths: DataPaths, settings: Settings
) -> None:
    await ingest_posts(ArchiveFileSource(posts_fixture), IngestionMode.HISTORICAL, paths, settings)
    report = build_events(paths, settings, default_universe())
    events = load_events(paths)

    assert report.posts_considered == 7
    assert report.posts_skipped_repost == 1 and report.posts_skipped_empty == 1
    assert report.posts_relevant == 4  # two tariff posts, oil, Fed and chips
    assert report.events == 3  # the two tariff posts 35 minutes apart form one event
    assert [e.published_at for e in events] == sorted(e.published_at for e in events)

    tariff = events[0]
    assert tariff.post_ids == ["900000000000000001", "900000000000000002"]
    assert EventCategory.TARIFFS_TRADE in tariff.categories
    assert tariff.available_at == tariff.published_at + timedelta(seconds=60)
    assert {"NUE", "FXI"} <= set(tariff.symbols)
    assert "SPY" not in tariff.symbols  # the benchmark is never an affected symbol
    countries = [e.text for e in tariff.entities if e.type is EntityType.COUNTRY]
    assert countries == ["China"]

    oil = events[1]
    assert oil.categories == [EventCategory.ENERGY_OIL]
    assert oil.symbols[:2] == ["XOM", "CVX"]  # named companies come first

    mixed = events[2]
    assert set(mixed.categories) >= {
        EventCategory.BANKING_MONETARY_POLICY,
        EventCategory.TECHNOLOGY_SEMICONDUCTORS,
    }
    assert "NVDA" in mixed.symbols


def test_clustering_respects_gap_and_category(settings: Settings) -> None:
    builder = EventBuilder(default_universe(), settings)
    posts = [
        post("1", "Tariffs on China start Monday.", 0),
        post("2", "More tariffs on Mexico too.", 30),
        post("3", "The Fed must cut interest rates.", 40),  # other theme: its own event
        post("4", "Tariffs on Canada as well.", 61),  # outside 60 minutes of post 1
    ]
    events, _ = builder.build(posts)
    assert [e.post_ids for e in events] == [["1", "2"], ["3"], ["4"]]
    assert events[0].event_id == event_id_for("1", builder.classifier_version)


def test_event_ids_are_stable_across_runs(settings: Settings) -> None:
    builder = EventBuilder(default_universe(), settings)
    posts = [post("1", "Tariffs on China start Monday.", 0)]
    first, _ = builder.build(posts)
    second, _ = builder.build(posts)
    assert first == second


def test_deleted_reposted_and_empty_posts_are_skipped(settings: Settings) -> None:
    builder = EventBuilder(default_universe(), settings)
    posts = [
        post("1", "Tariffs on China start Monday.", 0, is_deleted=True),
        post("2", "RT @x: Tariffs on China start Monday.", 5, is_repost=True, reposted_from="x"),
        post("3", "", 10),
    ]
    events, report = builder.build(posts)
    assert events == []
    assert (report.posts_skipped_deleted, report.posts_skipped_repost) == (1, 1)
    assert report.posts_skipped_empty == 1


def test_company_mention_without_policy_words_uses_company_themes(settings: Settings) -> None:
    builder = EventBuilder(default_universe(), settings)
    events, _ = builder.build([post("1", "Boeing just called me. Great company, great CEO!", 0)])
    assert len(events) == 1
    assert events[0].symbols[0] == "BA"
    assert set(events[0].categories) == {EventCategory.TARIFFS_TRADE, EventCategory.DEFENCE}


def test_live_post_uses_collection_time(settings: Settings) -> None:
    builder = EventBuilder(default_universe(), settings)
    collected = T0 + timedelta(minutes=9)
    live = post(
        "1",
        "Tariffs on China start Monday.",
        0,
        retrieved_at=collected,
        ingestion_mode=IngestionMode.LIVE,
    )
    events, _ = builder.build([live])
    assert events[0].available_at == collected
