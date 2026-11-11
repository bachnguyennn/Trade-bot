"""Entity recognition with a gazetteer, and mapping to symbols in the universe.

Names that are also ordinary words (Apple, Target, Ford, Amazon, Meta, Intel) are only
accepted when the post also contains business context. When context is missing, no symbol
is assigned: a missed mapping is better than a wrong one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.contracts import Entity, EntityType
from src.market_data.universe import Universe

_BUSINESS_CONTEXT = re.compile(
    r"\b(?:compan(?:y|ies)|stocks?|shares?|shareholders?|CEO|invest(?:s|ed|ing|ment|ments)?"
    r"|billions?|plants?|factor(?:y|ies)|manufactur\w*|tariffs?|jobs|build(?:s|ing)?"
    r"|announc\w*|deal|merger|acquisition|earnings|products?|customers?|sales|prices?"
    r"|iPhones?|chips?|cars?|trucks?|vehicles?|stores?|retailers?|boycott|antitrust|monopoly)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GazetteerEntry:
    pattern: re.Pattern[str]
    type: EntityType
    canonical: str
    symbols: tuple[str, ...] = ()
    needs_context: bool = False


def _e(
    pattern: str,
    type_: EntityType,
    canonical: str,
    symbols: tuple[str, ...] = (),
    needs_context: bool = False,
    cased: bool = True,
) -> GazetteerEntry:
    flags = 0 if cased else re.IGNORECASE
    return GazetteerEntry(re.compile(pattern, flags), type_, canonical, symbols, needs_context)


CO = EntityType.COMPANY
CN = EntityType.COUNTRY
CM = EntityType.COMMODITY
IN = EntityType.INDUSTRY
GB = EntityType.GOVERNMENT_BODY

GAZETTEER: list[GazetteerEntry] = [
    # Companies. Case-sensitive so that ordinary lower-case words do not match.
    _e(r"\bApple\b(?!\s+pie)", CO, "Apple", ("AAPL",), needs_context=True),
    _e(r"\bTim\s+Cook\b", CO, "Apple", ("AAPL",)),
    _e(r"\bNvidia\b|\bNVIDIA\b", CO, "Nvidia", ("NVDA",)),
    _e(
        r"\bIntel\b(?!\s+(?:community|agencies|report|chief|officials?))",
        CO,
        "Intel",
        ("INTC",),
        needs_context=True,
    ),
    _e(r"\bMicron\b", CO, "Micron", ("MU",)),
    _e(r"\bAMD\b", CO, "AMD", ("AMD",)),
    _e(r"\bTSMC\b|\bTaiwan\s+Semiconductor\b", CO, "TSMC", ("TSM",)),
    _e(r"\bBroadcom\b", CO, "Broadcom", ("AVGO",)),
    _e(r"\bMicrosoft\b", CO, "Microsoft", ("MSFT",)),
    _e(r"\bGoogle\b|\bAlphabet\b", CO, "Alphabet", ("GOOGL",)),
    _e(r"\bFacebook\b|\bMeta\s+Platforms\b|\bInstagram\b", CO, "Meta", ("META",)),
    _e(r"\bMeta\b", CO, "Meta", ("META",), needs_context=True),
    _e(
        r"\bAmazon\b(?!\s+(?:rain\s*forest|river|basin))",
        CO,
        "Amazon",
        ("AMZN",),
        needs_context=True,
    ),
    _e(r"\bTesla\b", CO, "Tesla", ("TSLA",)),
    _e(r"\bGeneral\s+Motors\b|\bGM\b", CO, "General Motors", ("GM",)),
    _e(r"\bFord\b(?!\s+(?:Foundation|administration))", CO, "Ford", ("F",), needs_context=True),
    _e(r"\bBoeing\b", CO, "Boeing", ("BA",)),
    _e(r"\bCaterpillar\b", CO, "Caterpillar", ("CAT",), needs_context=True),
    _e(r"\bJohn\s+Deere\b|\bDeere\b", CO, "Deere", ("DE",)),
    _e(r"\bHarley-?\s?Davidson\b", CO, "Harley-Davidson", ("HOG",)),
    _e(r"\bNike\b", CO, "Nike", ("NKE",)),
    _e(r"\bWalmart\b|\bWal-Mart\b", CO, "Walmart", ("WMT",)),
    _e(r"\bTarget\s+(?:stores?|Corporation|Corp)\b|\bboycott\s+Target\b", CO, "Target", ("TGT",)),
    _e(r"\bNucor\b", CO, "Nucor", ("NUE",)),
    _e(r"\bCleveland-?\s?Cliffs\b", CO, "Cleveland-Cliffs", ("CLF",)),
    _e(r"\bAlcoa\b", CO, "Alcoa", ("AA",)),
    _e(r"\bExxon(?:\s?Mobil)?\b", CO, "Exxon Mobil", ("XOM",)),
    _e(r"\bChevron\b", CO, "Chevron", ("CVX",)),
    _e(r"\bConocoPhillips\b", CO, "ConocoPhillips", ("COP",)),
    _e(r"\bOccidental\s+Petroleum\b", CO, "Occidental Petroleum", ("OXY",)),
    _e(r"\bCheniere\b", CO, "Cheniere", ("LNG",)),
    _e(r"\bLockheed(?:\s+Martin)?\b", CO, "Lockheed Martin", ("LMT",)),
    _e(r"\bRaytheon\b|\bRTX\b", CO, "RTX", ("RTX",)),
    _e(r"\bNorthrop(?:\s+Grumman)?\b", CO, "Northrop Grumman", ("NOC",)),
    _e(r"\bGeneral\s+Dynamics\b", CO, "General Dynamics", ("GD",)),
    _e(r"\bPalantir\b", CO, "Palantir", ("PLTR",)),
    _e(r"\bJ\.?P\.?\s?Morgan(?:\s+Chase)?\b|\bJamie\s+Dimon\b", CO, "JPMorgan Chase", ("JPM",)),
    _e(r"\bBank\s+of\s+America\b", CO, "Bank of America", ("BAC",)),
    _e(r"\bGoldman(?:\s+Sachs)?\b", CO, "Goldman Sachs", ("GS",)),
    _e(r"\bWells\s+Fargo\b", CO, "Wells Fargo", ("WFC",)),
    _e(r"\bPfizer\b", CO, "Pfizer", ("PFE",)),
    _e(r"\bEli\s+Lilly\b", CO, "Eli Lilly", ("LLY",)),
    _e(r"\bUnitedHealth(?:care)?\b|\bUnited\s+Health(?:care)?\b", CO, "UnitedHealth", ("UNH",)),
    _e(r"\bTrump\s+Media\b|\bTMTG\b", CO, "Trump Media", ("DJT",)),
    _e(r"\bCoinbase\b", CO, "Coinbase", ("COIN",)),
    _e(r"\bDisney\b", CO, "Disney", ("DIS",)),
    _e(r"\bComcast\b|\bConcast\b", CO, "Comcast", ("CMCSA",)),
    _e(r"\bAlibaba\b", CO, "Alibaba", ("BABA",)),
    _e(r"\bGEO\s+Group\b", CO, "GEO Group", ("GEO",)),
    _e(r"\bCoreCivic\b", CO, "CoreCivic", ("CXW",)),
    _e(r"\bFreeport(?:-McMoRan)?\b", CO, "Freeport-McMoRan", ("FCX",), needs_context=True),
    # Countries and regions
    _e(r"\bChin(?:a|ese)\b", CN, "China", ("FXI",)),
    _e(r"\bMexic(?:o|an)\b", CN, "Mexico", ("EWW",)),
    _e(r"\bCanad(?:a|ian)\b", CN, "Canada", ("EWC",)),
    _e(r"\bJapan(?:ese)?\b", CN, "Japan", ("EWJ",)),
    _e(
        r"\bEuropean\s+Union\b|\bEurope(?:an)?\b|\bthe\s+EU\b|\bE\.U\.",
        CN,
        "European Union",
        ("VGK",),
    ),
    _e(r"\bIndia\b", CN, "India", ("INDA",)),
    _e(r"\bBrazil(?:ian)?\b", CN, "Brazil", ("EWZ",)),
    _e(r"\bSouth\s+Korea(?:n)?\b", CN, "South Korea", ("EWY",)),
    _e(r"\bTaiwan(?:ese)?\b", CN, "Taiwan", ("EWT",)),
    _e(r"\bRussia(?:n)?\b", CN, "Russia"),
    _e(r"\bUkrain(?:e|ian)\b", CN, "Ukraine"),
    _e(r"\bIran(?:ian)?\b", CN, "Iran"),
    _e(r"\bIsrael(?:i)?\b", CN, "Israel"),
    _e(r"\bVenezuela\b", CN, "Venezuela"),
    _e(r"\bNorth\s+Korea\b", CN, "North Korea"),
    _e(r"\bSaudi\s+Arabia\b", CN, "Saudi Arabia"),
    _e(r"\bVietnam\b", CN, "Vietnam"),
    _e(r"\bGermany\b", CN, "Germany"),
    _e(r"\bUnited\s+Kingdom\b|\bU\.K\.|\bBritain\b", CN, "United Kingdom"),
    # Commodities
    _e(r"\b(?:crude\s+)?oil\b", CM, "oil", ("USO",), cased=False),
    _e(r"\bnatural\s+gas\b|\bLNG\b", CM, "natural gas", ("LNG",), cased=False),
    _e(r"\bsteel\b", CM, "steel", ("NUE", "CLF"), cased=False),
    _e(r"\balumin(?:um|ium)\b", CM, "aluminum", ("AA",), cased=False),
    _e(r"\bcopper\b", CM, "copper", ("FCX",), cased=False),
    _e(
        r"\bgold\s+(?:prices?|reserves?)\b|\bprice\s+of\s+gold\b", CM, "gold", ("GLD",), cased=False
    ),
    _e(r"\bBitcoin\b|\bcrypto(?:currency|currencies)?\b", CM, "crypto", ("COIN",), cased=False),
    _e(r"\blumber\b", CM, "lumber", cased=False),
    _e(r"\bsoybeans?\b", CM, "soybeans", ("DE",), cased=False),
    # Industries
    _e(r"\bsemiconductors?\b|\b(?:micro)?chips\b", IN, "semiconductors", ("SMH",), cased=False),
    _e(
        r"\bauto(?:makers?|mobiles?|\s+industry)\b|\bcar\s+companies\b",
        IN,
        "autos",
        ("GM", "F"),
        cased=False,
    ),
    _e(r"\bbanks\b|\bbanking\b", IN, "banks", ("XLF", "KRE"), cased=False),
    _e(
        r"\bdefen[cs]e\s+(?:contractors?|industry|companies)\b",
        IN,
        "defence contractors",
        ("ITA",),
        cased=False,
    ),
    _e(
        r"\bpharma(?:ceuticals?)?\b|\bdrug\s+(?:companies|makers|prices?)\b",
        IN,
        "pharmaceuticals",
        ("XLV", "PFE", "LLY"),
        cased=False,
    ),
    _e(r"\bfarmers\b|\bagricultur(?:e|al)\b", IN, "agriculture", ("DE",), cased=False),
    _e(r"\boil\s+(?:companies|industry)\b|\bBig\s+Oil\b", IN, "oil and gas", ("XLE",), cased=False),
    _e(
        r"\bprivate\s+prisons?\b|\bdetention\s+(?:cent(?:er|re)s?|facilit(?:y|ies))\b",
        IN,
        "detention services",
        ("GEO", "CXW"),
        cased=False,
    ),
    # Government and international bodies
    _e(r"\bFederal\s+Reserve\b|\b[Tt]he\s+Fed\b", GB, "Federal Reserve"),
    _e(r"\bTreasury\b", GB, "Treasury"),
    _e(r"\bCommerce\s+Department\b|\bDepartment\s+of\s+Commerce\b", GB, "Commerce Department"),
    _e(r"\bPentagon\b|\bDepartment\s+of\s+(?:Defense|War)\b", GB, "Department of Defense"),
    _e(r"\bCongress\b", GB, "Congress"),
    _e(r"\bSupreme\s+Court\b", GB, "Supreme Court"),
    _e(r"\bSEC\b|\bSecurities\s+and\s+Exchange\s+Commission\b", GB, "SEC"),
    _e(r"\bFTC\b|\bFederal\s+Trade\s+Commission\b", GB, "FTC"),
    _e(r"\bEPA\b", GB, "EPA"),
    _e(r"\bOPEC\b", GB, "OPEC"),
    _e(r"\bNATO\b", GB, "NATO"),
    _e(r"\bWTO\b|\bWorld\s+Trade\s+Organization\b", GB, "WTO"),
]

_CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")


@dataclass
class RecognitionResult:
    entities: list[Entity] = field(default_factory=list)
    # Symbols named directly (company or cashtag). These are the strongest mappings.
    direct_symbols: list[str] = field(default_factory=list)
    # Symbols implied by a commodity or industry.
    related_symbols: list[str] = field(default_factory=list)
    # Symbols for a named country or region. Used only for trade and sanctions events.
    country_symbols: list[str] = field(default_factory=list)
    # Names seen without enough context to map them.
    unresolved: list[str] = field(default_factory=list)


def _add(target: list[str], symbols: tuple[str, ...] | list[str]) -> None:
    for symbol in symbols:
        if symbol not in target:
            target.append(symbol)


class EntityRecognizer:
    def __init__(self, universe: Universe) -> None:
        self._universe = universe

    def recognize(self, text: str) -> RecognitionResult:
        result = RecognitionResult()
        cleaned = re.sub(r"https?://\S+", " ", text)
        has_context = bool(_BUSINESS_CONTEXT.search(cleaned))
        seen: set[tuple[EntityType, str]] = set()

        for entry in GAZETTEER:
            if not entry.pattern.search(cleaned):
                continue
            key = (entry.type, entry.canonical)
            if key in seen:
                continue
            if entry.needs_context and not has_context:
                if entry.canonical not in result.unresolved:
                    result.unresolved.append(entry.canonical)
                continue
            seen.add(key)
            symbols = tuple(s for s in entry.symbols if s in self._universe)
            result.entities.append(
                Entity(
                    text=entry.canonical, type=entry.type, symbol=symbols[0] if symbols else None
                )
            )
            if entry.type is EntityType.COMPANY:
                _add(result.direct_symbols, symbols)
            elif entry.type is EntityType.COUNTRY:
                _add(result.country_symbols, symbols)
            else:
                _add(result.related_symbols, symbols)

        for match in _CASHTAG.finditer(cleaned):
            symbol = match.group(1)
            if symbol in self._universe and (EntityType.TICKER, symbol) not in seen:
                seen.add((EntityType.TICKER, symbol))
                result.entities.append(
                    Entity(text=f"${symbol}", type=EntityType.TICKER, symbol=symbol)
                )
                _add(result.direct_symbols, [symbol])
        return result
