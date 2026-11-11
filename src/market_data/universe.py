"""The defined universe of liquid US stocks and ETFs.

The list is curated at the time of writing, so it favours names that exist today. That is a
survivorship bias and is stated in every report. `eligible_from` and `eligible_to` stop a
symbol from being studied or traded outside the period in which it was listed.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Literal

from src.contracts import EventCategory, UniverseMember

C = EventCategory

# Symbols listed well before the study period share this start date.
_LONG_LISTED = date(2015, 1, 1)


def _m(
    symbol: str,
    name: str,
    kind: Literal["stock", "etf"],
    sector: str,
    themes: list[EventCategory],
    eligible_from: date = _LONG_LISTED,
    eligible_to: date | None = None,
) -> UniverseMember:
    return UniverseMember(
        symbol=symbol,
        name=name,
        kind=kind,
        sector=sector,
        themes=themes,
        eligible_from=eligible_from,
        eligible_to=eligible_to,
    )


_MEMBERS: list[UniverseMember] = [
    # Broad market
    _m("SPY", "SPDR S&P 500 ETF", "etf", "Broad Market", []),
    _m("QQQ", "Invesco QQQ Trust", "etf", "Broad Market", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("IWM", "iShares Russell 2000 ETF", "etf", "Broad Market", []),
    _m("DIA", "SPDR Dow Jones Industrial Average ETF", "etf", "Broad Market", []),
    # Trade and industrials
    _m("CAT", "Caterpillar", "stock", "Industrials", [C.TARIFFS_TRADE, C.GOVERNMENT_SPENDING]),
    _m("DE", "Deere & Company", "stock", "Industrials", [C.TARIFFS_TRADE]),
    _m("BA", "Boeing", "stock", "Industrials", [C.TARIFFS_TRADE, C.DEFENCE]),
    _m("GM", "General Motors", "stock", "Autos", [C.TARIFFS_TRADE]),
    _m("F", "Ford Motor", "stock", "Autos", [C.TARIFFS_TRADE]),
    _m("TSLA", "Tesla", "stock", "Autos", [C.TARIFFS_TRADE]),
    _m("NKE", "Nike", "stock", "Consumer", [C.TARIFFS_TRADE]),
    _m("WMT", "Walmart", "stock", "Consumer", [C.TARIFFS_TRADE]),
    _m("TGT", "Target", "stock", "Consumer", [C.TARIFFS_TRADE]),
    _m("NUE", "Nucor", "stock", "Materials", [C.TARIFFS_TRADE]),
    _m("CLF", "Cleveland-Cliffs", "stock", "Materials", [C.TARIFFS_TRADE]),
    _m("AA", "Alcoa", "stock", "Materials", [C.TARIFFS_TRADE], date(2016, 11, 1)),
    _m("FCX", "Freeport-McMoRan", "stock", "Materials", [C.TARIFFS_TRADE]),
    _m("XLI", "Industrial Select Sector SPDR", "etf", "Industrials", [C.GOVERNMENT_SPENDING]),
    _m(
        "PAVE",
        "Global X US Infrastructure ETF",
        "etf",
        "Industrials",
        [C.GOVERNMENT_SPENDING],
        date(2017, 3, 8),
    ),
    # Countries and regions
    _m(
        "FXI",
        "iShares China Large-Cap ETF",
        "etf",
        "International",
        [C.TARIFFS_TRADE, C.SANCTIONS_INTERNATIONAL],
    ),
    _m("KWEB", "KraneShares CSI China Internet ETF", "etf", "International", [C.TARIFFS_TRADE]),
    _m("BABA", "Alibaba Group", "stock", "International", [C.TARIFFS_TRADE]),
    _m("EWW", "iShares MSCI Mexico ETF", "etf", "International", [C.TARIFFS_TRADE]),
    _m("EWC", "iShares MSCI Canada ETF", "etf", "International", [C.TARIFFS_TRADE]),
    _m("EWJ", "iShares MSCI Japan ETF", "etf", "International", [C.TARIFFS_TRADE]),
    _m("VGK", "Vanguard FTSE Europe ETF", "etf", "International", [C.TARIFFS_TRADE]),
    _m("INDA", "iShares MSCI India ETF", "etf", "International", [C.TARIFFS_TRADE]),
    _m("EWZ", "iShares MSCI Brazil ETF", "etf", "International", [C.TARIFFS_TRADE]),
    _m("EWY", "iShares MSCI South Korea ETF", "etf", "International", [C.TARIFFS_TRADE]),
    _m("EWT", "iShares MSCI Taiwan ETF", "etf", "International", [C.TARIFFS_TRADE]),
    # Energy
    _m("XLE", "Energy Select Sector SPDR", "etf", "Energy", [C.ENERGY_OIL]),
    _m("USO", "United States Oil Fund", "etf", "Energy", [C.ENERGY_OIL, C.SANCTIONS_INTERNATIONAL]),
    _m("XOM", "Exxon Mobil", "stock", "Energy", [C.ENERGY_OIL]),
    _m("CVX", "Chevron", "stock", "Energy", [C.ENERGY_OIL]),
    _m("COP", "ConocoPhillips", "stock", "Energy", [C.ENERGY_OIL]),
    _m("OXY", "Occidental Petroleum", "stock", "Energy", [C.ENERGY_OIL]),
    _m("SLB", "Schlumberger", "stock", "Energy", [C.ENERGY_OIL]),
    _m("LNG", "Cheniere Energy", "stock", "Energy", [C.ENERGY_OIL]),
    # Technology and semiconductors
    _m("XLK", "Technology Select Sector SPDR", "etf", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("SMH", "VanEck Semiconductor ETF", "etf", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("NVDA", "Nvidia", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("AMD", "Advanced Micro Devices", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("INTC", "Intel", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("TSM", "Taiwan Semiconductor", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("MU", "Micron Technology", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("AVGO", "Broadcom", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("AAPL", "Apple", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS, C.TARIFFS_TRADE]),
    _m("MSFT", "Microsoft", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("GOOGL", "Alphabet", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("META", "Meta Platforms", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS]),
    _m("AMZN", "Amazon", "stock", "Technology", [C.TECHNOLOGY_SEMICONDUCTORS, C.TARIFFS_TRADE]),
    # Defence
    _m("ITA", "iShares US Aerospace & Defense ETF", "etf", "Defence", [C.DEFENCE]),
    _m("LMT", "Lockheed Martin", "stock", "Defence", [C.DEFENCE, C.SANCTIONS_INTERNATIONAL]),
    _m("RTX", "RTX Corporation", "stock", "Defence", [C.DEFENCE]),
    _m("NOC", "Northrop Grumman", "stock", "Defence", [C.DEFENCE]),
    _m("GD", "General Dynamics", "stock", "Defence", [C.DEFENCE]),
    # Banking and rates
    _m("XLF", "Financial Select Sector SPDR", "etf", "Financials", [C.BANKING_MONETARY_POLICY]),
    _m("KRE", "SPDR S&P Regional Banking ETF", "etf", "Financials", [C.BANKING_MONETARY_POLICY]),
    _m("JPM", "JPMorgan Chase", "stock", "Financials", [C.BANKING_MONETARY_POLICY]),
    _m("BAC", "Bank of America", "stock", "Financials", [C.BANKING_MONETARY_POLICY]),
    _m("GS", "Goldman Sachs", "stock", "Financials", [C.BANKING_MONETARY_POLICY]),
    _m("WFC", "Wells Fargo", "stock", "Financials", [C.BANKING_MONETARY_POLICY]),
    _m("TLT", "iShares 20+ Year Treasury Bond ETF", "etf", "Rates", [C.BANKING_MONETARY_POLICY]),
    _m(
        "GLD",
        "SPDR Gold Shares",
        "etf",
        "Commodities",
        [C.BANKING_MONETARY_POLICY, C.SANCTIONS_INTERNATIONAL],
    ),
    # Immigration and employment
    _m("GEO", "GEO Group", "stock", "Services", [C.IMMIGRATION_EMPLOYMENT]),
    _m("CXW", "CoreCivic", "stock", "Services", [C.IMMIGRATION_EMPLOYMENT]),
    # Health care (mapped by company mention or the government spending theme)
    _m("XLV", "Health Care Select Sector SPDR", "etf", "Health Care", [C.GOVERNMENT_SPENDING]),
    _m("UNH", "UnitedHealth Group", "stock", "Health Care", [C.GOVERNMENT_SPENDING]),
    _m("PFE", "Pfizer", "stock", "Health Care", []),
    _m("LLY", "Eli Lilly", "stock", "Health Care", []),
    # Mapped by company mention only
    _m("DJT", "Trump Media & Technology Group", "stock", "Media", [], date(2024, 3, 26)),
    _m("COIN", "Coinbase Global", "stock", "Financials", [], date(2021, 4, 14)),
    _m("PLTR", "Palantir Technologies", "stock", "Technology", [C.DEFENCE], date(2020, 9, 30)),
    _m("DIS", "Walt Disney", "stock", "Media", []),
    _m("CMCSA", "Comcast", "stock", "Media", []),
    _m("HOG", "Harley-Davidson", "stock", "Consumer", [C.TARIFFS_TRADE]),
]

# The symbols studied for a category when a post names no specific company. Kept short so
# one post does not fan out into dozens of loosely related symbols.
CATEGORY_SYMBOLS: dict[EventCategory, list[str]] = {
    C.TARIFFS_TRADE: ["CAT", "NUE", "GM", "AAPL", "WMT", "FXI"],
    C.ENERGY_OIL: ["XLE", "XOM", "CVX", "USO"],
    C.TECHNOLOGY_SEMICONDUCTORS: ["SMH", "NVDA", "XLK", "AAPL"],
    C.DEFENCE: ["ITA", "LMT", "RTX"],
    C.BANKING_MONETARY_POLICY: ["XLF", "KRE", "TLT", "GLD"],
    C.IMMIGRATION_EMPLOYMENT: ["GEO", "CXW"],
    C.GOVERNMENT_SPENDING: ["XLI", "PAVE", "XLV", "TLT"],
    C.SANCTIONS_INTERNATIONAL: ["USO", "GLD", "FXI", "LMT"],
}


class Universe:
    def __init__(self, members: list[UniverseMember], benchmark: str) -> None:
        self._members = {m.symbol: m for m in members}
        if benchmark not in self._members:
            raise ValueError(f"benchmark {benchmark} must be in the universe")
        self.benchmark = benchmark

    @property
    def members(self) -> list[UniverseMember]:
        return list(self._members.values())

    @property
    def symbols(self) -> list[str]:
        return list(self._members)

    def get(self, symbol: str) -> UniverseMember | None:
        return self._members.get(symbol.upper())

    def __contains__(self, symbol: str) -> bool:
        return symbol.upper() in self._members

    def is_eligible(self, symbol: str, on: date) -> bool:
        member = self.get(symbol)
        return member is not None and member.is_eligible(on)

    def category_symbols(self, category: EventCategory) -> list[str]:
        return [s for s in CATEGORY_SYMBOLS.get(category, []) if s in self._members]

    def sector_of(self, symbol: str) -> str:
        member = self.get(symbol)
        return member.sector if member else "Unknown"


@lru_cache(maxsize=4)
def default_universe(benchmark: str = "SPY") -> Universe:
    return Universe(_MEMBERS, benchmark)
