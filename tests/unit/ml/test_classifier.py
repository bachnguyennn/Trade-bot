from __future__ import annotations

import pytest

from src.contracts import EventCategory as C
from src.ml.classifier import CLASSIFIER_VERSION, RuleBasedClassifier

classifier = RuleBasedClassifier()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("We will place a 25% TARIFF on all cars from Mexico.", C.TARIFFS_TRADE),
        ("DRILL, BABY, DRILL! Oil production will soar.", C.ENERGY_OIL),
        ("New export controls on advanced semiconductors.", C.TECHNOLOGY_SEMICONDUCTORS),
        ("NATO members must buy more missiles.", C.DEFENCE),
        ("The Fed must cut interest rates now.", C.BANKING_MONETARY_POLICY),
        ("The jobs report shows unemployment falling.", C.IMMIGRATION_EMPLOYMENT),
        ("We must not raise the debt ceiling without tax cuts.", C.GOVERNMENT_SPENDING),
        ("New sanctions on Iran take effect today.", C.SANCTIONS_INTERNATIONAL),
    ],
)
def test_each_category_is_detected(text: str, expected: C) -> None:
    result = classifier.classify(text)
    assert result.relevant
    assert expected in result.categories
    assert 0.5 <= result.relevance_score <= 1.0
    assert result.version == CLASSIFIER_VERSION


def test_multiple_labels() -> None:
    result = classifier.classify(
        "Tariffs on China will fund tax cuts, and the Federal Reserve should cut interest rates."
    )
    assert {C.TARIFFS_TRADE, C.GOVERNMENT_SPENDING, C.BANKING_MONETARY_POLICY} <= set(
        result.categories
    )
    # Categories are reported in a stable order.
    assert result.categories == [c for c in C if c in result.categories]


@pytest.mark.parametrize(
    "text",
    [
        "Happy birthday to a wonderful friend. Have a great day!",
        "Thank you to the great people of Iowa. See you tonight!",
        "",
        "https://example.invalid/oil-tariffs-inflation",
    ],
)
def test_unrelated_posts_are_not_relevant(text: str) -> None:
    result = classifier.classify(text)
    assert not result.relevant
    assert result.categories == []
    assert result.relevance_score < 0.5


def test_one_weak_term_is_not_enough_but_two_are() -> None:
    assert not classifier.classify("We love our military.").relevant
    assert classifier.classify("Our military needs more troops.").categories == [C.DEFENCE]


def test_political_phrases_are_not_mistaken_for_policy() -> None:
    assert not classifier.classify("The Russia, Russia, Russia hoax was a witch hunt!").relevant
    assert not classifier.classify("The Russian collusion story is fake.").relevant


def test_endorsements_are_excluded() -> None:
    text = (
        "Jane Doe will fight for Energy Independence, lower inflation, and our Military. "
        "She has my Complete and Total Endorsement!"
    )
    assert not classifier.classify(text).relevant


def test_case_sensitive_terms() -> None:
    assert C.BANKING_MONETARY_POLICY in classifier.classify("The Fed is too late.").categories
    assert not classifier.classify("I fed the dog.").relevant
    assert C.TECHNOLOGY_SEMICONDUCTORS in classifier.classify("AI will change America.").categories
    assert not classifier.classify("Ai Weiwei is an artist.").relevant
