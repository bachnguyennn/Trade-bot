"""Turn raw archive records into clean post fields."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from src.core.timeutils import parse_timestamp

_WHITESPACE = re.compile(r"\s+")
# Two forms appear in the archive: "RT @account ..." and
# "RT: https://truthsocial.com/users/account/statuses/123...".
_REPOST = re.compile(
    r"^RT\s*:?\s*(?:@|https?://truthsocial\.com/users/)(?P<account>[A-Za-z0-9_.]+)",
    re.IGNORECASE,
)
_BLOCK_TAGS = {"p", "br", "div", "li", "blockquote"}


# The archive contains text whose UTF-8 bytes were once read as single-byte characters, so
# a curly apostrophe arrives as three characters ("â", then two from the 0x80-0xBF range).
# A candidate is a UTF-8 lead byte followed by its continuation bytes, each seen either as
# its Latin-1 character or as its Windows-1252 character.
_CP1252_SPECIALS = "".join(
    bytes([b]).decode("cp1252")
    for b in range(0x80, 0xA0)
    if b not in {0x81, 0x8D, 0x8F, 0x90, 0x9D}
)
_CONTINUATION = f"[\u0080-¿{re.escape(_CP1252_SPECIALS)}]"
_MOJIBAKE = re.compile(f"[Â-ß]{_CONTINUATION}|[à-ï]{_CONTINUATION}{{2}}|[ð-ô]{_CONTINUATION}{{3}}")


def _mojibake_bytes(segment: str) -> bytes | None:
    out = bytearray()
    for char in segment:
        if ord(char) < 256:
            out.append(ord(char))
            continue
        try:
            out.extend(char.encode("cp1252"))
        except UnicodeEncodeError:
            return None
    return bytes(out)


def repair_mojibake(text: str) -> str:
    """Restore characters whose UTF-8 bytes were mis-read as single-byte text.

    Only sequences that form valid UTF-8 are replaced; everything else is left as it is.
    """

    def fix(match: re.Match[str]) -> str:
        raw = _mojibake_bytes(match.group(0))
        if raw is None:
            return match.group(0)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return match.group(0)

    return _MOJIBAKE.sub(fix, text)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(content: str) -> str:
    """Remove markup, decode entities, and collapse whitespace."""
    if not content:
        return ""
    parser = _TextExtractor()
    parser.feed(content)
    parser.close()
    text = repair_mojibake(html.unescape("".join(parser.parts)))
    return _WHITESPACE.sub(" ", text).strip()


def content_hash(text: str) -> str:
    """Hash of the normalised text, used to detect edits."""
    normalised = _WHITESPACE.sub(" ", text).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def detect_repost(text: str) -> tuple[bool, str | None]:
    """A post that begins with `RT @account` is a repost of that account."""
    match = _REPOST.match(text)
    if match:
        return True, match.group("account")
    return False, None


@dataclass(frozen=True)
class NormalizedRecord:
    post_id: str
    text: str
    url: str
    published_at: datetime
    is_repost: bool
    reposted_from: str | None
    media_urls: list[str]
    content_hash: str


@dataclass(frozen=True)
class Rejection:
    reason: str


def normalize_record(raw: dict[str, Any], account: str) -> NormalizedRecord | Rejection:
    """Validate and clean one raw record. Bad records are rejected with a reason."""
    raw_id = raw.get("id")
    if raw_id is None or str(raw_id).strip() == "":
        return Rejection("missing post id")
    post_id = str(raw_id).strip()

    published_at = parse_timestamp(raw.get("created_at"))
    if published_at is None:
        return Rejection("missing or unparseable publication time")

    raw_content = raw.get("content")
    text = html_to_text(raw_content) if isinstance(raw_content, str) else ""

    media = raw.get("media")
    media_urls = [str(m) for m in media if m] if isinstance(media, list) else []

    raw_url = raw.get("url")
    url = (
        str(raw_url)
        if isinstance(raw_url, str) and raw_url
        else f"https://truthsocial.com/@{account}/{post_id}"
    )
    is_repost, reposted_from = detect_repost(text)

    return NormalizedRecord(
        post_id=post_id,
        text=text,
        url=url,
        published_at=published_at,
        is_repost=is_repost,
        reposted_from=reposted_from,
        media_urls=media_urls,
        content_hash=content_hash(text),
    )
