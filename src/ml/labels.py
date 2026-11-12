"""Hand labels for posts: a blind sample to label, and evaluation against the rules.

The sample is stratified. Most posts are ones the rules call market-relevant, which measures
precision and gives enough posts to test. The rest are posts the rules reject, which is the
only way to estimate what the rules miss. The sheet does not show the rules' output or the
stratum, so the labels are not anchored on them; both are kept in a sidecar file.

Post IDs are written with a `p` prefix so that spreadsheet programs keep them as text.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from src.backtesting.reaction_size import ReactionSizeReport, run_reaction_size
from src.contracts import EventWindow, MarketFeature, SocialPost
from src.core.storage import write_json_atomic
from src.core.timeutils import availability_time, utc_now
from src.market_data.calendar import TradingCalendar
from src.market_data.universe import Universe
from src.market_data.windows import WindowCalculator
from src.pipelines.events import EventBuilder

SHEET_COLUMNS = [
    "post_id",
    "published_at_utc",
    "text",
    "relevant",
    "specificity",
    "symbols",
    "notes",
]
LABEL_COLUMNS = ["relevant", "specificity", "symbols", "notes"]
RULE_RELEVANT = "rule_relevant"
RULE_OTHER = "rule_other"
DEFAULT_SEED = 20261112
_YES = {"y", "yes", "1", "true"}
_NO = {"n", "no", "0", "false"}


class Specificity(StrEnum):
    COMPANY = "company"
    ACTION = "action"
    GENERAL = "general"


SPECIFIC = {Specificity.COMPANY, Specificity.ACTION}


class SampleMeta(BaseModel):
    created_at: datetime
    seed: int
    classifier_version: str
    population: dict[str, int]
    sampled: dict[str, int]
    strata: dict[str, str]
    rule_symbols: dict[str, list[str]]


@dataclass(frozen=True)
class PostLabel:
    post_id: str
    relevant: bool
    specificity: Specificity | None
    symbols: list[str]


@dataclass
class SheetReadResult:
    labels: list[PostLabel] = field(default_factory=list)
    unlabelled: int = 0
    errors: list[str] = field(default_factory=list)


def labelable(post: SocialPost) -> bool:
    return not post.is_deleted and not post.is_repost and bool(post.text.strip())


def sheet_id(post_id: str) -> str:
    return f"p{post_id}"


def _post_id(value: str) -> str:
    value = value.strip()
    return value[1:] if value.startswith("p") else value


def build_sample(
    posts: list[SocialPost],
    builder: EventBuilder,
    n_relevant: int,
    n_other: int,
    seed: int = DEFAULT_SEED,
) -> tuple[list[SocialPost], SampleMeta]:
    """Draw a reproducible stratified sample and return it in shuffled order."""
    strata: dict[str, list[SocialPost]] = {RULE_RELEVANT: [], RULE_OTHER: []}
    rule_symbols: dict[str, list[str]] = {}
    for post in sorted((p for p in posts if labelable(p)), key=lambda p: p.post_id):
        candidate = builder.candidate(post)
        if candidate is None:
            strata[RULE_OTHER].append(post)
        else:
            strata[RULE_RELEVANT].append(post)
            rule_symbols[post.post_id] = candidate.symbols

    rng = random.Random(seed)
    wanted = {RULE_RELEVANT: n_relevant, RULE_OTHER: n_other}
    chosen: list[SocialPost] = []
    stratum_of: dict[str, str] = {}
    for name, members in strata.items():
        picked = rng.sample(members, min(wanted[name], len(members)))
        chosen.extend(picked)
        stratum_of.update({p.post_id: name for p in picked})
    rng.shuffle(chosen)

    meta = SampleMeta(
        created_at=utc_now(),
        seed=seed,
        classifier_version=builder.classifier_version,
        population={name: len(members) for name, members in strata.items()},
        sampled={name: sum(1 for s in stratum_of.values() if s == name) for name in strata},
        strata=stratum_of,
        rule_symbols={
            p.post_id: rule_symbols[p.post_id] for p in chosen if p.post_id in rule_symbols
        },
    )
    return chosen, meta


def write_sheet(posts: list[SocialPost], meta: SampleMeta, sheet: Path, force: bool) -> None:
    """Write the label sheet and its sidecar. Never overwrites labels unless forced."""
    if sheet.exists() and not force:
        raise FileExistsError(f"{sheet} already exists; it may contain labels")
    sheet.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so that spreadsheet programs detect the encoding.
    with sheet.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHEET_COLUMNS)
        for post in posts:
            published = post.published_at.strftime("%Y-%m-%d %H:%M")
            writer.writerow([sheet_id(post.post_id), published, post.text, "", "", "", ""])
    write_json_atomic(meta.model_dump_json(indent=2), meta_path(sheet))


def meta_path(sheet: Path) -> Path:
    return sheet.with_suffix(".meta.json")


def read_meta(sheet: Path) -> SampleMeta:
    return SampleMeta.model_validate(json.loads(meta_path(sheet).read_text(encoding="utf-8")))


def read_sheet(sheet: Path, universe: Universe) -> SheetReadResult:
    """Read filled-in labels. Rows with an empty `relevant` cell are not labelled yet."""
    result = SheetReadResult()
    with sheet.open(newline="", encoding="utf-8-sig") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            post_id = _post_id(row.get("post_id") or "")
            relevant_cell = (row.get("relevant") or "").strip().lower()
            if not relevant_cell:
                result.unlabelled += 1
                continue
            if relevant_cell not in _YES | _NO:
                result.errors.append(f"line {line}: relevant must be y or n, got {relevant_cell!r}")
                continue
            relevant = relevant_cell in _YES

            specificity: Specificity | None = None
            spec_cell = (row.get("specificity") or "").strip().lower()
            if relevant:
                try:
                    specificity = Specificity(spec_cell)
                except ValueError:
                    allowed = ", ".join(s.value for s in Specificity)
                    result.errors.append(
                        f"line {line}: specificity must be one of {allowed}, got {spec_cell!r}"
                    )
                    continue

            symbols: list[str] = []
            unknown: list[str] = []
            for token in (row.get("symbols") or "").replace(",", " ").split():
                symbol = token.strip().upper().lstrip("$")
                if symbol in universe:
                    if symbol not in symbols:
                        symbols.append(symbol)
                else:
                    unknown.append(symbol)
            if unknown:
                result.errors.append(
                    f"line {line}: symbols not in the universe: {', '.join(unknown)}"
                )
                continue
            if not relevant:
                symbols = []
            result.labels.append(PostLabel(post_id, relevant, specificity, symbols))
    return result


class SymbolAgreement(BaseModel):
    posts: int
    precision: float | None
    recall: float | None


class RelevanceEvaluation(BaseModel):
    labelled: dict[str, int]
    labelled_relevant: dict[str, int]
    precision: float | None
    share_relevant_among_rejected: float | None
    estimated_recall: float | None
    specificity_counts: dict[str, int]


class LabelEvaluation(BaseModel):
    classifier_version: str
    labelled: int
    unlabelled: int
    errors: list[str]
    relevance: RelevanceEvaluation
    symbols: SymbolAgreement
    reaction_specific: ReactionSizeReport | None
    reaction_general: ReactionSizeReport | None
    caveats: list[str]


def _share(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate_relevance(labels: list[PostLabel], meta: SampleMeta) -> RelevanceEvaluation:
    labelled = {RULE_RELEVANT: 0, RULE_OTHER: 0}
    positive = {RULE_RELEVANT: 0, RULE_OTHER: 0}
    for label in labels:
        stratum = meta.strata.get(label.post_id)
        if stratum is None:
            continue
        labelled[stratum] += 1
        positive[stratum] += int(label.relevant)

    precision = _share(positive[RULE_RELEVANT], labelled[RULE_RELEVANT])
    missed_rate = _share(positive[RULE_OTHER], labelled[RULE_OTHER])
    recall = None
    if precision is not None and missed_rate is not None:
        # Weight each stratum's labelled share by its size in the whole population.
        found = precision * meta.population[RULE_RELEVANT]
        missed = missed_rate * meta.population[RULE_OTHER]
        recall = found / (found + missed) if found + missed > 0 else None

    counts = {s.value: 0 for s in Specificity}
    for label in labels:
        if label.specificity is not None:
            counts[label.specificity.value] += 1
    return RelevanceEvaluation(
        labelled=labelled,
        labelled_relevant=positive,
        precision=precision,
        share_relevant_among_rejected=missed_rate,
        estimated_recall=recall,
        specificity_counts=counts,
    )


def evaluate_symbols(labels: list[PostLabel], meta: SampleMeta) -> SymbolAgreement:
    """Micro-averaged agreement between rule symbols and hand symbols, where both exist."""
    matched = rule_total = human_total = posts = 0
    for label in labels:
        rule = set(meta.rule_symbols.get(label.post_id, []))
        human = set(label.symbols)
        if not label.relevant or not rule or not human:
            continue
        posts += 1
        matched += len(rule & human)
        rule_total += len(rule)
        human_total += len(human)
    return SymbolAgreement(
        posts=posts, precision=_share(matched, rule_total), recall=_share(matched, human_total)
    )


def labelled_features(
    labels: list[PostLabel],
    posts: dict[str, SocialPost],
    calculator: WindowCalculator,
    assumed_latency: timedelta,
    decision_latency: timedelta,
    windows: list[EventWindow],
) -> list[MarketFeature]:
    """Measure every window for each labelled post and its hand-labelled symbols."""
    features: list[MarketFeature] = []
    for label in labels:
        post = posts.get(label.post_id)
        if post is None or not label.symbols:
            continue
        anchor = availability_time(post, assumed_latency) + decision_latency
        for symbol in label.symbols:
            for window in windows:
                features.append(calculator.feature(post.post_id, symbol, anchor, window))
    return features


def evaluate_labels(
    read: SheetReadResult,
    meta: SampleMeta,
    posts: dict[str, SocialPost],
    calculator: WindowCalculator,
    calendar: TradingCalendar,
    benchmark: str,
    assumed_latency: timedelta,
    decision_latency: timedelta,
) -> LabelEvaluation:
    windows: list[EventWindow] = [w for w in EventWindow if w is not EventWindow.CLOSE_TO_CLOSE]

    def reaction(group: list[PostLabel]) -> ReactionSizeReport | None:
        features = labelled_features(
            group, posts, calculator, assumed_latency, decision_latency, windows
        )
        if not any(f.available for f in features):
            return None
        return run_reaction_size(features, calculator, calendar, benchmark)

    relevant = [label for label in read.labels if label.relevant]
    specific = [label for label in relevant if label.specificity in SPECIFIC]
    general = [label for label in relevant if label.specificity is Specificity.GENERAL]
    return LabelEvaluation(
        classifier_version=meta.classifier_version,
        labelled=len(read.labels),
        unlabelled=read.unlabelled,
        errors=read.errors,
        relevance=evaluate_relevance(read.labels, meta),
        symbols=evaluate_symbols(read.labels, meta),
        reaction_specific=reaction(specific),
        reaction_general=reaction(general),
        caveats=[
            "Labels come from one person and have not been checked for agreement.",
            "Recall is estimated from the rejected stratum and is imprecise when few rejected "
            "posts turn out to be relevant.",
            "A few hundred posts give a test with little power: no difference here does not "
            "rule out a small effect.",
            "Several windows and two groups are tested, with no multiple-comparison correction.",
        ],
    )
