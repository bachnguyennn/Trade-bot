from __future__ import annotations

from src.contracts import EntityType
from src.market_data.universe import default_universe
from src.ml.entities import EntityRecognizer

recognizer = EntityRecognizer(default_universe())


def by_type(text: str) -> dict[EntityType, dict[str, str | None]]:
    out: dict[EntityType, dict[str, str | None]] = {}
    for entity in recognizer.recognize(text).entities:
        out.setdefault(entity.type, {})[entity.text] = entity.symbol
    return out


def test_company_country_commodity_and_body() -> None:
    text = "Nvidia will not sell chips to China. The Federal Reserve is watching oil prices."
    found = by_type(text)
    assert found[EntityType.COMPANY] == {"Nvidia": "NVDA"}
    assert found[EntityType.COUNTRY] == {"China": "FXI"}
    assert found[EntityType.COMMODITY] == {"oil": "USO"}
    assert found[EntityType.INDUSTRY] == {"semiconductors": "SMH"}
    assert found[EntityType.GOVERNMENT_BODY] == {"Federal Reserve": None}


def test_symbol_groups_are_kept_apart() -> None:
    result = recognizer.recognize(
        "Boeing and Lockheed will build jets with American steel in Canada."
    )
    assert result.direct_symbols == ["BA", "LMT"]
    assert result.related_symbols == ["NUE", "CLF"]
    assert result.country_symbols == ["EWC"]


def test_ambiguous_name_needs_business_context() -> None:
    no_context = recognizer.recognize("I ate an Apple today and it was great.")
    assert no_context.direct_symbols == []
    assert "Apple" in no_context.unresolved
    with_context = recognizer.recognize("Apple must build its iPhones in America, not India.")
    assert with_context.direct_symbols == ["AAPL"]
    assert with_context.unresolved == []


def test_ordinary_words_do_not_match_companies() -> None:
    result = recognizer.recognize(
        "The intel community missed the target. We ford the river at dawn."
    )
    assert result.direct_symbols == []
    assert recognizer.recognize("The Intel community report is out.").direct_symbols == []
    assert recognizer.recognize("The Amazon rainforest is burning.").direct_symbols == []


def test_cashtag_maps_only_to_universe_symbols() -> None:
    result = recognizer.recognize("Buy $TSLA and $ZZZZ now.")
    assert result.direct_symbols == ["TSLA"]
    tickers = [e for e in result.entities if e.type is EntityType.TICKER]
    assert [(e.text, e.symbol) for e in tickers] == [("$TSLA", "TSLA")]


def test_country_without_etf_has_no_symbol() -> None:
    found = by_type("Russia and Ukraine must make peace.")
    assert found[EntityType.COUNTRY] == {"Russia": None, "Ukraine": None}


def test_each_entity_is_reported_once() -> None:
    result = recognizer.recognize("China, China, China. Chinese steel and more steel.")
    names = [e.text for e in result.entities]
    assert names.count("China") == 1 and names.count("steel") == 1


def test_links_are_ignored() -> None:
    assert recognizer.recognize("https://example.invalid/Boeing-news").entities == []
