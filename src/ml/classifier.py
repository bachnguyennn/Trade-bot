"""Rule-based market-relevance and category classifier (`rules-v1`).

There is no labelled dataset for this task yet, so the first classifier is a transparent
lexicon: each category has strong phrases (enough on their own) and weak terms (need
company). It is auditable, deterministic, and provides the weak labels a later model can
learn from. It is a baseline, not a claim of accuracy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.contracts import EventCategory

CLASSIFIER_VERSION = "rules-v1"
STRONG = 1.0
WEAK = 0.5
FAINT = 0.3
CATEGORY_THRESHOLD = 1.0

C = EventCategory

# Phrases that use a market-sounding word in a purely political sense. Removed before matching.
_NOISE = re.compile(
    r"Russia,?\s+Russia,?\s+Russia|Russian?\s+(?:hoax|collusion|witch\s*hunt|disinformation)"
    r"|witch\s*hunt|war\s+on\s+(?:christmas|women|coal\s+miners)|culture\s+war",
    re.IGNORECASE,
)

# Campaign endorsements repeat stock phrases ("Energy Independence", "our Military") for
# every candidate. They carry no policy news, so they are excluded outright.
_EXCLUDED = re.compile(
    r"Complete\s+(?:and|&)\s+Total\s+Endorsement|has\s+my\s+(?:full\s+)?endorsement",
    re.IGNORECASE,
)


def _rx(pattern: str, case_sensitive: bool = False) -> re.Pattern[str]:
    return re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)


@dataclass(frozen=True)
class Term:
    pattern: re.Pattern[str]
    weight: float


def _terms(
    strong: list[str],
    weak: list[str],
    faint: list[str] | None = None,
    cased: list[str] | None = None,
) -> list[Term]:
    terms = [Term(_rx(p), STRONG) for p in strong]
    terms += [Term(_rx(p), WEAK) for p in weak]
    terms += [Term(_rx(p), FAINT) for p in (faint or [])]
    terms += [Term(_rx(p, case_sensitive=True), STRONG) for p in (cased or [])]
    return terms


LEXICON: dict[EventCategory, list[Term]] = {
    C.TARIFFS_TRADE: _terms(
        strong=[
            r"\btariff(?:s|ed)?\b",
            r"\btrade\s+(?:war|deal|deals|deficit|deficits|agreement|agreements|barriers?|imbalance)\b",
            r"\breciprocal\b",
            r"\bimport\s+(?:tax|taxes|duty|duties)\b",
            r"\bUSMCA\b",
            r"\bNAFTA\b",
            r"\bWTO\b|\bWorld\s+Trade\s+Organization\b",
            r"\btrading\s+partners?\b",
        ],
        weak=[
            r"\btrade\b",
            r"\bimports?\b",
            r"\bexports?\b",
            r"\bmanufactur(?:ing|ers?|ed)\b",
            r"\bsteel\b",
            r"\balumin(?:um|ium)\b",
            r"\bauto(?:s|mobiles?|makers?)\b",
            r"\bdumping\b",
            r"\bduties\b",
            r"\bsupply\s+chains?\b",
        ],
    ),
    C.ENERGY_OIL: _terms(
        strong=[
            r"\boil\b",
            r"\bgasoline\b|\bgas\s+prices?\b",
            r"\bOPEC\b",
            r"\bdrill(?:ing|ed)?\b",
            r"\bnatural\s+gas\b|\bLNG\b",
            r"\bpipelines?\b",
            r"\benergy\s+(?:dominance|independen(?:t|ce)|prices?|costs?|production|emergency)\b",
            r"\bStrategic\s+Petroleum\s+Reserve\b",
            r"\bfracking\b",
            r"\bnuclear\s+(?:power|energy|plants?|reactors?)\b",
            r"\bcoal\b",
            r"\brefiner(?:y|ies)\b",
        ],
        weak=[
            r"\benergy\b",
            r"\bwind(?:mills?|\s+turbines?|\s+farms?)\b",
            r"\bsolar\b",
            r"\belectric\s+(?:vehicles?|cars?)\b|\bEV\s+mandate\b",
            r"\bGreen\s+New\s+(?:Deal|Scam)\b",
            r"\belectricity\b",
        ],
    ),
    C.TECHNOLOGY_SEMICONDUCTORS: _terms(
        strong=[
            r"\bsemiconductors?\b",
            r"\b(?:micro)?chips\b",
            r"\bartificial\s+intelligence\b",
            r"\bBig\s+Tech\b",
            r"\bdata\s+cent(?:er|re)s?\b",
            r"\bTikTok\b",
            r"\bexport\s+controls?\b",
            r"\bSection\s+230\b",
            r"\bquantum\s+computing\b",
        ],
        weak=[
            r"\btechnology\b",
            r"\btech\b",
            r"\bantitrust\b",
            r"\bsocial\s+media\s+compan(?:y|ies)\b",
            r"\brare\s+earths?\b",
        ],
        cased=[r"\bA\.?I\.?(?=[\s,.!?:;)]|$)", r"\bCHIPS\s+Act\b"],
    ),
    C.DEFENCE: _terms(
        strong=[
            r"\bmilitary\s+(?:spending|budget|aid|equipment|build-?up)\b",
            r"\bdefen[cs]e\s+(?:spending|budget|contractors?|industry|production)\b",
            r"\bPentagon\b",
            r"\bmissiles?\b",
            r"\bfighter\s+jets?\b|\bF-?(?:35|47|22|16)s?\b",
            r"\b(?:Golden|Iron)\s+Dome\b",
            r"\bNATO\b",
            r"\bweapons?\b",
            r"\bwarships?\b|\bshipbuilding\b|\bsubmarines?\b",
            r"\bSpace\s+Force\b",
            r"\bmunitions\b",
            r"\bDepartment\s+of\s+(?:Defense|War)\b",
            r"\bdrones?\b",
        ],
        weak=[
            r"\bmilitary\b",
            r"\btroops\b",
            r"\bnavy\b|\bair\s+force\b|\barmy\b",
            r"\bdefen[cs]e\b",
        ],
    ),
    C.BANKING_MONETARY_POLICY: _terms(
        strong=[
            r"\bFederal\s+Reserve\b",
            r"\bPowell\b",
            r"\binterest\s+rates?\b",
            r"\brate\s+(?:cuts?|hikes?)\b|\b(?:cut|lower|raise)\s+(?:interest\s+)?rates\b",
            r"\binflation\b",
            r"\bFOMC\b",
            r"\bstock\s+markets?\b",
            r"\bTreasury\s+(?:yields?|bonds?|bills?|market)\b",
            r"\bmortgage\s+rates?\b",
            r"\bFannie\s+Mae\b|\bFreddie\s+Mac\b",
            r"\bbanking\b|\bde-?banking\b",
            r"\brecession\b",
            r"\bcrypto(?:currency|currencies)?\b|\bBitcoin\b|\bstablecoins?\b|\bdigital\s+assets?\b",
        ],
        weak=[
            r"\bbanks?\b",
            r"\bdollar\b",
            r"\bWall\s+Street\b",
            r"\bmarkets?\b",
            r"\bstocks?\b",
            r"\b401\(?k\)?s?\b",
            r"\bprices\b",
            r"\beconomy\b",
        ],
        cased=[r"\b[Tt]he\s+Fed\b"],
    ),
    C.IMMIGRATION_EMPLOYMENT: _terms(
        strong=[
            r"\bjobs?\s+(?:report|numbers|growth|creation)\b",
            r"\bunemployment\b",
            r"\bH-?1B\b",
            r"\bmass\s+deportations?\b",
            r"\bdetention\s+(?:cent(?:er|re)s?|facilit(?:y|ies))\b",
            r"\bminimum\s+wage\b",
            r"\blabor\s+(?:market|force|shortage)\b",
            r"\btax\s+on\s+tips\b",
            r"\bfarm\s*workers?\b",
        ],
        weak=[
            r"\bjobs\b",
            r"\bworkers\b",
            r"\bimmigra(?:tion|nts?)\b",
            r"\bdeport(?:ation|ations|ed|ing)?\b",
            r"\bwages?\b",
            r"\bemployment\b",
            r"\bvisas?\b",
            r"\bovertime\b",
        ],
        faint=[r"\bborder\b", r"\billegal\s+aliens?\b", r"\bunions?\b"],
    ),
    C.GOVERNMENT_SPENDING: _terms(
        strong=[
            r"\b(?:government|federal)\s+(?:spending|shutdown|budget|debt)\b",
            r"\bdebt\s+(?:ceiling|limit)\b",
            r"\bnational\s+debt\b",
            r"\btax\s+cuts?\b",
            r"\bBig,?\s+Beautiful\s+Bill\b",
            r"\binfrastructure\b",
            r"\bMedicare\b|\bMedicaid\b",
            r"\bSocial\s+Security\b",
            r"\bappropriations\b|\bcontinuing\s+resolution\b",
            r"\bstimulus\b",
            r"\bsubsid(?:y|ies|ize|ized)\b",
            r"\bdrug\s+prices?\b|\bprescription\s+drugs?\b|\bmost\s+favored\s+nation\b",
        ],
        weak=[
            r"\btax(?:es)?\b",
            r"\bspending\b",
            r"\bbudget\b",
            r"\bshutdown\b",
            r"\bdeficit\b",
            r"\breconciliation\b",
        ],
        cased=[r"\bDOGE\b"],
    ),
    C.SANCTIONS_INTERNATIONAL: _terms(
        strong=[
            r"\bsanction(?:s|ed|ing)?\b",
            r"\bembargo\b",
            r"\bcease-?fire\b",
            r"\bpeace\s+(?:deal|agreement|talks|plan)\b",
            r"\bUkrain(?:e|ian)\b",
            r"\bPutin\b",
            r"\bIran(?:ian|ians)?\b",
            r"\bNorth\s+Korea\b",
            r"\bTaiwan\b",
            r"\bVenezuela\b",
            r"\bBRICS\b",
            r"\bStrait\s+of\s+Hormuz\b",
            r"\bPresident\s+Xi\b|\bXi\s+Jinping\b",
        ],
        weak=[
            r"\bRussian?\b",
            r"\bChin(?:a|ese)\b",
            r"\bIsraeli?\b",
            r"\bGaza\b|\bHamas\b",
            r"\bMiddle\s+East\b",
            r"\bSaudi\s+Arabia\b",
            r"\bforeign\s+(?:policy|countries|nations)\b",
        ],
    ),
}


@dataclass(frozen=True)
class Classification:
    relevant: bool
    categories: list[EventCategory]
    scores: dict[EventCategory, float]
    relevance_score: float
    version: str = CLASSIFIER_VERSION


def clean_for_matching(text: str) -> str:
    """Drop links and known political phrases that would otherwise look market-related."""
    without_links = re.sub(r"https?://\S+", " ", text)
    return _NOISE.sub(" ", without_links)


class RuleBasedClassifier:
    version = CLASSIFIER_VERSION

    def classify(self, text: str) -> Classification:
        if _EXCLUDED.search(text):
            return Classification(relevant=False, categories=[], scores={}, relevance_score=0.0)
        cleaned = clean_for_matching(text)
        scores: dict[EventCategory, float] = {}
        for category, terms in LEXICON.items():
            score = sum(term.weight for term in terms if term.pattern.search(cleaned))
            if score > 0:
                scores[category] = round(score, 3)
        categories = [c for c in EventCategory if scores.get(c, 0.0) >= CATEGORY_THRESHOLD]
        top = max(scores.values(), default=0.0)
        relevance = min(1.0, top / 2.0) if categories else min(0.49, top / 2.0)
        return Classification(
            relevant=bool(categories),
            categories=categories,
            scores=scores,
            relevance_score=round(relevance, 3),
        )
