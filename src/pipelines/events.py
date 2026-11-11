"""Silver posts to Gold events: classify, recognise entities, map symbols, cluster."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel

from src.contracts import Entity, EventCategory, MarketEvent, SocialPost
from src.core.logging import get_logger
from src.core.settings import Settings
from src.core.storage import DataPaths, from_frame, read_parquet, to_frame, write_parquet_atomic
from src.core.timeutils import availability_time
from src.market_data.universe import Universe
from src.ml.classifier import RuleBasedClassifier
from src.ml.entities import EntityRecognizer

log = get_logger(__name__)

MAX_SYMBOLS_PER_EVENT = 8
_COUNTRY_CATEGORIES = {EventCategory.TARIFFS_TRADE, EventCategory.SANCTIONS_INTERNATIONAL}


class EventBuildReport(BaseModel):
    posts_considered: int
    posts_skipped_repost: int
    posts_skipped_empty: int
    posts_skipped_deleted: int
    posts_relevant: int
    events: int
    events_by_category: dict[str, int]
    classifier_version: str


@dataclass
class _Candidate:
    post: SocialPost
    available_at: datetime
    categories: list[EventCategory]
    entities: list[Entity]
    symbols: list[str]
    relevance: float


def event_id_for(first_post_id: str, classifier_version: str) -> str:
    digest = hashlib.sha256(f"{first_post_id}:{classifier_version}".encode()).hexdigest()
    return f"evt_{digest[:16]}"


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


class EventBuilder:
    def __init__(
        self,
        universe: Universe,
        settings: Settings,
        classifier: RuleBasedClassifier | None = None,
        recognizer: EntityRecognizer | None = None,
        include_reposts: bool = False,
    ) -> None:
        self._universe = universe
        self._classifier = classifier or RuleBasedClassifier()
        self._recognizer = recognizer or EntityRecognizer(universe)
        self._assumed_latency = timedelta(seconds=settings.assumed_latency_seconds)
        self._cluster_gap = timedelta(minutes=settings.cluster_gap_minutes)
        self._include_reposts = include_reposts

    @property
    def classifier_version(self) -> str:
        return self._classifier.version

    def candidate(self, post: SocialPost) -> _Candidate | None:
        """Classify one post. Returns None when the post is not market-relevant."""
        classification = self._classifier.classify(post.text)
        recognition = self._recognizer.recognize(post.text)
        categories = list(classification.categories)
        relevance = classification.relevance_score

        if not categories and recognition.direct_symbols:
            # A named company with no policy keywords: use the company's own themes.
            themes: list[EventCategory] = []
            for symbol in recognition.direct_symbols:
                member = self._universe.get(symbol)
                themes.extend(member.themes if member else [])
            categories = [c for c in EventCategory if c in themes]
            relevance = 0.5
        if not categories:
            return None

        symbols = list(recognition.direct_symbols) + list(recognition.related_symbols)
        if _COUNTRY_CATEGORIES.intersection(categories):
            symbols += recognition.country_symbols
        for category in categories:
            symbols += self._universe.category_symbols(category)
        symbols = [s for s in _ordered_unique(symbols) if s != self._universe.benchmark]

        return _Candidate(
            post=post,
            available_at=availability_time(post, self._assumed_latency),
            categories=categories,
            entities=recognition.entities,
            symbols=symbols[:MAX_SYMBOLS_PER_EVENT],
            relevance=relevance,
        )

    def build(self, posts: list[SocialPost]) -> tuple[list[MarketEvent], EventBuildReport]:
        skipped_repost = skipped_empty = skipped_deleted = 0
        candidates: list[_Candidate] = []
        for post in posts:
            if post.is_deleted:
                skipped_deleted += 1
            elif post.is_repost and not self._include_reposts:
                skipped_repost += 1
            elif not post.text.strip():
                skipped_empty += 1
            else:
                candidate = self.candidate(post)
                if candidate is not None:
                    candidates.append(candidate)

        candidates.sort(key=lambda c: (c.available_at, c.post.post_id))
        events = [self._to_event(cluster) for cluster in self._cluster(candidates)]

        by_category: dict[str, int] = {}
        for event in events:
            for category in event.categories:
                by_category[category.value] = by_category.get(category.value, 0) + 1
        report = EventBuildReport(
            posts_considered=len(posts),
            posts_skipped_repost=skipped_repost,
            posts_skipped_empty=skipped_empty,
            posts_skipped_deleted=skipped_deleted,
            posts_relevant=len(candidates),
            events=len(events),
            events_by_category=dict(sorted(by_category.items())),
            classifier_version=self.classifier_version,
        )
        return events, report

    def _cluster(self, candidates: list[_Candidate]) -> list[list[_Candidate]]:
        """Group posts that share a category and fall within the gap of a cluster's first post.

        Overlapping posts on one theme describe one market event; counting each separately
        would count the same price move several times.
        """
        clusters: list[list[_Candidate]] = []
        open_clusters: list[list[_Candidate]] = []
        for candidate in candidates:
            open_clusters = [
                c
                for c in open_clusters
                if candidate.available_at - c[0].available_at <= self._cluster_gap
            ]
            target = next(
                (
                    c
                    for c in open_clusters
                    if set(c[0].categories).intersection(candidate.categories)
                ),
                None,
            )
            if target is None:
                target = []
                clusters.append(target)
                open_clusters.append(target)
            target.append(candidate)
        return clusters

    def _to_event(self, cluster: list[_Candidate]) -> MarketEvent:
        anchor = cluster[0]
        categories = [c for c in EventCategory if any(c in m.categories for m in cluster)]
        entities: list[Entity] = []
        seen: set[tuple[str, str]] = set()
        for member in cluster:
            for entity in member.entities:
                key = (entity.type.value, entity.text)
                if key not in seen:
                    seen.add(key)
                    entities.append(entity)
        symbols = _ordered_unique([s for m in cluster for s in m.symbols])[:MAX_SYMBOLS_PER_EVENT]
        return MarketEvent(
            event_id=event_id_for(anchor.post.post_id, self.classifier_version),
            post_ids=[m.post.post_id for m in cluster],
            text=anchor.post.text,
            published_at=anchor.post.published_at,
            available_at=anchor.available_at,
            categories=categories,
            entities=entities,
            symbols=symbols,
            relevance_score=max(m.relevance for m in cluster),
            classifier_version=self.classifier_version,
        )


def load_events(paths: DataPaths) -> list[MarketEvent]:
    return from_frame(read_parquet(paths.gold_events, MarketEvent), MarketEvent)


def build_events(
    paths: DataPaths, settings: Settings, universe: Universe, include_reposts: bool = False
) -> EventBuildReport:
    """Rebuild the Gold events table from Silver posts."""
    posts = from_frame(read_parquet(paths.silver_posts, SocialPost), SocialPost)
    builder = EventBuilder(universe, settings, include_reposts=include_reposts)
    events, report = builder.build(posts)
    write_parquet_atomic(to_frame(events, MarketEvent), paths.gold_events)
    log.info("events built", extra=report.model_dump())
    return report
