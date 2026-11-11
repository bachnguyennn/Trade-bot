"""Post and event contracts."""

from __future__ import annotations

from pydantic import Field

from src.contracts.base import Contract, UtcDatetime
from src.contracts.enums import EntityType, EventCategory, IngestionMode


class SocialPost(Contract):
    """One post from the monitored account (Silver layer)."""

    post_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    account: str = Field(min_length=1)
    text: str
    url: str
    published_at: UtcDatetime
    retrieved_at: UtcDatetime
    ingestion_mode: IngestionMode
    is_repost: bool = False
    reposted_from: str | None = None
    has_media: bool = False
    media_urls: list[str] = Field(default_factory=list)
    content_hash: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    is_edited: bool = False
    is_deleted: bool = False


class Entity(Contract):
    """Something named in a post, optionally mapped to a symbol in the universe."""

    text: str = Field(min_length=1)
    type: EntityType
    symbol: str | None = None


class MarketEvent(Contract):
    """A market-relevant post or cluster of posts (Gold layer)."""

    event_id: str = Field(min_length=1)
    post_ids: list[str] = Field(min_length=1)
    text: str
    published_at: UtcDatetime
    available_at: UtcDatetime
    categories: list[EventCategory] = Field(min_length=1)
    entities: list[Entity] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    relevance_score: float = Field(ge=0.0, le=1.0)
    classifier_version: str = Field(min_length=1)
