"""Label sheet: blind stratified sample, reading filled-in labels, and scoring the rules."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.contracts import IngestionMode, SocialPost
from src.core.settings import Settings
from src.market_data.universe import Universe, default_universe
from src.ml.labels import (
    RULE_OTHER,
    RULE_RELEVANT,
    SHEET_COLUMNS,
    PostLabel,
    SampleMeta,
    Specificity,
    build_sample,
    evaluate_relevance,
    evaluate_symbols,
    read_meta,
    read_sheet,
    write_sheet,
)
from src.pipelines.events import EventBuilder

RELEVANT_TEXT = "We are putting a 25% Tariff on all Steel imports from China, effective Monday!"
OTHER_TEXT = "Great rally tonight in Ohio. Thank you to everyone who came!"


def post(post_id: str, text: str, **kwargs: object) -> SocialPost:
    published = datetime(2025, 3, 3, 15, 0, tzinfo=UTC)
    return SocialPost(
        post_id=post_id,
        source="synthetic-test",
        account="test",
        text=text,
        url=f"https://example.test/{post_id}",
        published_at=published,
        retrieved_at=published,
        ingestion_mode=IngestionMode.HISTORICAL,
        content_hash=post_id,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture
def universe() -> Universe:
    return default_universe("SPY")


@pytest.fixture
def builder(universe: Universe, settings: Settings) -> EventBuilder:
    return EventBuilder(universe, settings)


def sample_posts() -> list[SocialPost]:
    posts = [post(f"r{i}", RELEVANT_TEXT) for i in range(6)]
    posts += [post(f"o{i}", OTHER_TEXT) for i in range(10)]
    posts.append(post("rt", "RT @someone " + RELEVANT_TEXT, is_repost=True))
    posts.append(post("del", RELEVANT_TEXT, is_deleted=True))
    posts.append(post("empty", "   "))
    return posts


def test_sample_is_stratified_reproducible_and_skips_unlabelable_posts(
    builder: EventBuilder,
) -> None:
    chosen, meta = build_sample(sample_posts(), builder, n_relevant=4, n_other=3, seed=1)
    again, _ = build_sample(sample_posts(), builder, n_relevant=4, n_other=3, seed=1)

    assert [p.post_id for p in chosen] == [p.post_id for p in again]
    assert meta.population == {RULE_RELEVANT: 6, RULE_OTHER: 10}
    assert meta.sampled == {RULE_RELEVANT: 4, RULE_OTHER: 3}
    assert {"rt", "del", "empty"}.isdisjoint(meta.strata)
    for post_id, stratum in meta.strata.items():
        assert stratum == (RULE_RELEVANT if post_id.startswith("r") else RULE_OTHER)
    assert set(meta.rule_symbols) == {pid for pid in meta.strata if pid.startswith("r")}


def test_sheet_is_blind_and_is_never_overwritten(builder: EventBuilder, tmp_path: Path) -> None:
    chosen, meta = build_sample(sample_posts(), builder, n_relevant=2, n_other=2)
    sheet = tmp_path / "labels" / "sheet.csv"
    write_sheet(chosen, meta, sheet, force=False)

    with sheet.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == SHEET_COLUMNS
    assert all(row[0].startswith("p") for row in rows[1:])
    assert read_meta(sheet).strata == meta.strata
    with pytest.raises(FileExistsError):
        write_sheet(chosen, meta, sheet, force=False)


def write_rows(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHEET_COLUMNS)
        writer.writerows(rows)


def test_read_sheet_validates_labels(universe: Universe, tmp_path: Path) -> None:
    sheet = tmp_path / "sheet.csv"
    write_rows(
        sheet,
        [
            ["p1", "", "text", "y", "company", "nue, $clf nue", ""],
            ["p2", "", "text", "N", "", "XOM", ""],
            ["p3", "", "text", "", "", "", ""],
            ["p4", "", "text", "maybe", "", "", ""],
            ["p5", "", "text", "y", "", "NUE", ""],
            ["p6", "", "text", "y", "action", "NOTREAL", ""],
        ],
    )
    result = read_sheet(sheet, universe)

    assert result.labels == [
        PostLabel("1", True, Specificity.COMPANY, ["NUE", "CLF"]),
        PostLabel("2", False, None, []),
    ]
    assert result.unlabelled == 1
    assert len(result.errors) == 3
    assert any("line 5" in e and "relevant" in e for e in result.errors)
    assert any("line 6" in e and "specificity" in e for e in result.errors)
    assert any("line 7" in e and "NOTREAL" in e for e in result.errors)


def meta(strata: dict[str, str], rule_symbols: dict[str, list[str]]) -> SampleMeta:
    return SampleMeta(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        seed=1,
        classifier_version="rules-test",
        population={RULE_RELEVANT: 100, RULE_OTHER: 900},
        sampled={},
        strata=strata,
        rule_symbols=rule_symbols,
    )


def test_relevance_precision_and_population_weighted_recall() -> None:
    strata = {f"r{i}": RULE_RELEVANT for i in range(4)} | {f"o{i}": RULE_OTHER for i in range(10)}
    labels = [
        PostLabel(f"r{i}", i < 3, Specificity.ACTION if i < 3 else None, []) for i in range(4)
    ]
    labels += [
        PostLabel(f"o{i}", i == 0, Specificity.GENERAL if i == 0 else None, []) for i in range(10)
    ]

    result = evaluate_relevance(labels, meta(strata, {}))

    assert result.precision == pytest.approx(0.75)
    assert result.share_relevant_among_rejected == pytest.approx(0.1)
    # Found: 0.75 * 100 = 75. Missed: 0.1 * 900 = 90.
    assert result.estimated_recall == pytest.approx(75 / 165)
    assert result.specificity_counts == {"company": 0, "action": 3, "general": 1}


def test_symbol_agreement_is_micro_averaged() -> None:
    labels = [
        PostLabel("a", True, Specificity.COMPANY, ["NUE", "CLF"]),
        PostLabel("b", True, Specificity.ACTION, ["XOM"]),
        PostLabel("c", False, None, []),
    ]
    rule = {"a": ["NUE", "AA", "FCX"], "b": ["XOM"], "c": ["GLD"]}
    result = evaluate_symbols(labels, meta({}, rule))

    assert result.posts == 2
    assert result.precision == pytest.approx(2 / 4)
    assert result.recall == pytest.approx(2 / 3)
