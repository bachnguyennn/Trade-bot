from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.contracts import IngestionMode, SocialPost
from src.core.timeutils import availability_time, ensure_utc, parse_timestamp

PUBLISHED = datetime(2025, 3, 3, 14, 5, tzinfo=UTC)


def post(mode: IngestionMode, retrieved_at: datetime) -> SocialPost:
    return SocialPost(
        post_id="1",
        source="file",
        account="acct",
        text="x",
        url="https://example.invalid/1",
        published_at=PUBLISHED,
        retrieved_at=retrieved_at,
        ingestion_mode=mode,
        content_hash="h",
    )


def test_parse_timestamp_variants() -> None:
    assert parse_timestamp("2025-03-03T14:05:00.000Z") == PUBLISHED
    assert parse_timestamp("2025-03-03T09:05:00-05:00") == PUBLISHED
    assert parse_timestamp(PUBLISHED) == PUBLISHED


@pytest.mark.parametrize("value", [None, "", "   ", "not a date", 12345, "2025-03-03T14:05:00"])
def test_parse_timestamp_rejects_unusable_values(value: object) -> None:
    # A timestamp without a timezone is unusable: it is never assumed to be UTC.
    assert parse_timestamp(value) is None


def test_ensure_utc_rejects_naive() -> None:
    with pytest.raises(ValueError):
        ensure_utc(datetime(2025, 3, 3))  # noqa: DTZ001


def test_historical_post_available_after_assumed_latency() -> None:
    backfilled = post(IngestionMode.HISTORICAL, PUBLISHED + timedelta(days=400))
    assert availability_time(backfilled, timedelta(seconds=60)) == PUBLISHED + timedelta(seconds=60)


def test_live_post_available_when_collected() -> None:
    collected = PUBLISHED + timedelta(minutes=7)
    live = post(IngestionMode.LIVE, collected)
    assert availability_time(live, timedelta(seconds=60)) == collected


def test_availability_is_never_before_publication() -> None:
    odd = post(IngestionMode.LIVE, PUBLISHED - timedelta(minutes=1))
    assert availability_time(odd, timedelta(0)) == PUBLISHED
