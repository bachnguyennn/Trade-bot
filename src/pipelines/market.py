"""Download candles for the universe and store them in Silver."""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from src.core.logging import get_logger
from src.core.timeutils import utc_now
from src.market_data.providers import MarketDataProvider
from src.market_data.store import CandleStore
from src.market_data.universe import Universe

log = get_logger(__name__)

# How far back each provider serves an interval. Requests are clamped so that a short
# history is reported rather than silently returning nothing.
YFINANCE_HISTORY_DAYS: dict[str, int] = {"1h": 729, "30m": 59, "15m": 59, "5m": 59, "1m": 7}


class MarketIngestReport(BaseModel):
    provider: str
    interval: str
    start: date
    end: date
    symbols_requested: int
    symbols_stored: int
    candles_written: int
    errors: dict[str, str]
    note: str | None = None


def ingest_market(
    provider: MarketDataProvider,
    store: CandleStore,
    universe: Universe,
    interval: str,
    start: date,
    end: date | None = None,
    symbols: list[str] | None = None,
) -> MarketIngestReport:
    end = end or utc_now().date()
    note: str | None = None
    if provider.name == "yfinance" and interval in YFINANCE_HISTORY_DAYS:
        earliest = utc_now().date() - timedelta(days=YFINANCE_HISTORY_DAYS[interval])
        if start < earliest:
            note = (
                f"{interval} history from this provider starts {earliest.isoformat()}; "
                f"requested start {start.isoformat()} was moved forward"
            )
            start = earliest

    requested = symbols or universe.symbols
    result = provider.fetch(requested, interval, start, end)
    written = store.upsert(result.candles)
    stored = result.candles["symbol"].n_unique() if result.candles.height else 0
    report = MarketIngestReport(
        provider=provider.name,
        interval=interval,
        start=start,
        end=end,
        symbols_requested=len(requested),
        symbols_stored=stored,
        candles_written=written,
        errors=result.errors,
        note=note,
    )
    log.info("market data ingested", extra=report.model_dump(mode="json"))
    return report
