"""Post sources. Each returns raw records exactly as published by the source.

Only published datasets are read. Nothing here contacts the social platform itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from src.core.settings import Settings
from src.core.timeutils import utc_now
from src.ingestion.http import fetch_bytes


class SourceNotPermitted(RuntimeError):
    """Raised when a source needs an acknowledgement that has not been given."""


@dataclass(frozen=True)
class RawFetch:
    """One fetch of one source: the raw records plus where and when they came from."""

    source: str
    origin: str
    fetched_at: datetime
    records: list[dict[str, Any]]
    payload_sha256: str
    is_full_snapshot: bool


class PostSource(Protocol):
    name: str

    async def fetch(self) -> RawFetch: ...


def parse_archive_payload(payload: bytes) -> list[dict[str, Any]]:
    """Parse an archive file: a JSON array of post objects."""
    data = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("archive payload must be a JSON array")
    return [r for r in data if isinstance(r, dict)]


def _raw_fetch(source: str, origin: str, payload: bytes) -> RawFetch:
    return RawFetch(
        source=source,
        origin=origin,
        fetched_at=utc_now(),
        records=parse_archive_payload(payload),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        is_full_snapshot=True,
    )


class ArchiveFileSource:
    """A local archive file in the published archive format."""

    def __init__(self, path: Path, name: str = "file") -> None:
        self.path = Path(path)
        self.name = name

    async def fetch(self) -> RawFetch:
        return _raw_fetch(self.name, str(self.path), self.path.read_bytes())


class HttpArchiveSource:
    """A published archive file fetched over HTTP."""

    def __init__(self, name: str, url: str, settings: Settings) -> None:
        self.name = name
        self.url = url
        self._settings = settings

    async def fetch(self) -> RawFetch:
        headers = {"User-Agent": self._settings.http_user_agent}
        timeout = httpx.Timeout(self._settings.http_timeout_seconds)
        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=True
        ) as client:
            payload = await fetch_bytes(
                self.url, client=client, max_retries=self._settings.http_max_retries
            )
        return _raw_fetch(self.name, self.url, payload)


def stiles_source(settings: Settings) -> HttpArchiveSource:
    """CC0-1.0 archive from the stiles/trump-truth-social-archive project. Frozen 2025-10-26."""
    return HttpArchiveSource("stiles", settings.stiles_archive_url, settings)


def cnn_source(settings: Settings) -> HttpArchiveSource:
    """Continuation of the same archive. Reuse terms not confirmed, so it is opt-in."""
    if not settings.allow_unverified_sources:
        raise SourceNotPermitted(
            "The 'cnn' source has unverified reuse terms. Review docs/DATA_SOURCES.md, then set "
            "TRADEBOT_ALLOW_UNVERIFIED_SOURCES=true to use it."
        )
    return HttpArchiveSource("cnn", settings.cnn_archive_url, settings)


def build_source(name: str, settings: Settings, path: Path | None = None) -> PostSource:
    if name == "stiles":
        return stiles_source(settings)
    if name == "cnn":
        return cnn_source(settings)
    if name == "file":
        if path is None:
            raise ValueError("--path is required for the 'file' source")
        return ArchiveFileSource(path)
    raise ValueError(f"unknown post source: {name}")
