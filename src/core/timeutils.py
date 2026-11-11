"""Time rules shared by every module. All stored times are timezone-aware UTC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.contracts import IngestionMode, SocialPost


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC. Naive datetimes are rejected, never guessed."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime: a timezone is required")
    return value.astimezone(UTC)


def parse_timestamp(value: object) -> datetime | None:
    """Parse a source timestamp into UTC.

    Returns None when the value is missing, unparseable, or has no timezone. A timestamp
    without a timezone is treated as unusable rather than assumed to be UTC.
    """
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def availability_time(post: SocialPost, assumed_latency: timedelta) -> datetime:
    """Earliest time the system could have known about a post.

    A live post is available when it was actually collected. A backfilled post has a
    retrieval time long after publication, so its availability is modelled as publication
    time plus an assumed collection latency.
    """
    if post.ingestion_mode is IngestionMode.LIVE:
        return max(post.retrieved_at, post.published_at)
    return post.published_at + assumed_latency
