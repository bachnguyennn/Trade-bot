from __future__ import annotations

from datetime import UTC, datetime

from src.ingestion.normalize import (
    NormalizedRecord,
    Rejection,
    content_hash,
    detect_repost,
    html_to_text,
    normalize_record,
)


def test_html_to_text_strips_markup_and_entities() -> None:
    raw = '<p>Tariffs &amp; trade</p><p>with <a href="https://x.invalid">@<span>Fox</span></a></p>'
    assert html_to_text(raw) == "Tariffs & trade with @Fox"
    assert html_to_text("") == ""


def test_content_hash_ignores_case_and_spacing() -> None:
    assert content_hash("Hello   World") == content_hash("hello world")
    assert content_hash("hello world") != content_hash("hello world!")


def test_detect_repost() -> None:
    assert detect_repost("RT @SomeAccount: thanks") == (True, "SomeAccount")
    assert detect_repost("RT: @other great") == (True, "other")
    assert detect_repost("Report on trade") == (False, None)


def test_normalize_valid_record() -> None:
    record = normalize_record(
        {
            "id": 123,
            "created_at": "2025-03-03T14:05:00.000Z",
            "content": "<p>Hello</p>",
            "url": "https://example.invalid/123",
            "media": ["https://example.invalid/a.jpg", ""],
        },
        account="acct",
    )
    assert isinstance(record, NormalizedRecord)
    assert record.post_id == "123"
    assert record.text == "Hello"
    assert record.published_at == datetime(2025, 3, 3, 14, 5, tzinfo=UTC)
    assert record.media_urls == ["https://example.invalid/a.jpg"]


def test_normalize_media_only_post_keeps_empty_text() -> None:
    record = normalize_record(
        {"id": "5", "created_at": "2025-03-06T12:00:00Z", "content": "", "media": ["m"]}, "acct"
    )
    assert isinstance(record, NormalizedRecord)
    assert record.text == ""
    assert record.url == "https://truthsocial.com/@acct/5"


def test_normalize_rejects_missing_id_and_time() -> None:
    assert normalize_record({"created_at": "2025-03-06T12:00:00Z"}, "a") == Rejection(
        "missing post id"
    )
    rejected = normalize_record({"id": "6", "created_at": None}, "a")
    assert isinstance(rejected, Rejection)
    assert "publication time" in rejected.reason
    assert isinstance(normalize_record({"id": "7", "created_at": "yesterday"}, "a"), Rejection)
