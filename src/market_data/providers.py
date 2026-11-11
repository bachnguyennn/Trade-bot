"""Market data providers. Each labels its bars with a source and an honest quality level."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx
import polars as pl

from src.contracts import DataQuality, StockCandle
from src.core.logging import get_logger
from src.core.settings import Settings
from src.core.storage import SCHEMAS, empty_frame
from src.core.timeutils import utc_now
from src.market_data.calendar import TradingCalendar

log = get_logger(__name__)

NEW_YORK = ZoneInfo("America/New_York")
INTERVAL_STEP: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
}


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderResult:
    candles: pl.DataFrame
    errors: dict[str, str] = field(default_factory=dict)


class MarketDataProvider(Protocol):
    name: str

    def fetch(
        self, symbols: list[str], interval: str, start: date, end: date
    ) -> ProviderResult: ...


def _rows_to_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        return empty_frame(StockCandle)
    return pl.DataFrame(rows, schema=SCHEMAS[StockCandle], orient="row")


def drop_unfinished_bars(
    frame: pl.DataFrame, interval: str, calendar: TradingCalendar, now: datetime
) -> pl.DataFrame:
    """Remove bars that are still forming, so a partial bar is never stored as final."""
    if frame.height == 0:
        return frame
    if interval == "1d":
        open_session = calendar.first_close_after(now)
        if open_session is None:
            return frame
        return frame.filter(pl.col("ts") < open_session.daily_ts)
    return frame.filter(pl.col("ts") + INTERVAL_STEP[interval] <= now)


def keep_regular_session(
    frame: pl.DataFrame, interval: str, calendar: TradingCalendar
) -> pl.DataFrame:
    """Keep intraday bars that start inside a regular session."""
    if frame.height == 0 or interval == "1d":
        return frame
    keep = [calendar.session_at(ts) is not None for ts in frame["ts"].to_list()]
    return frame.filter(pl.Series(keep))


class YFinanceProvider:
    """Keyless fallback using the unofficial Yahoo Finance client.

    Bars are labelled `delayed`. Yahoo's terms limit this data to personal, non-commercial
    use; it is stored locally and never redistributed. Intraday history is short: about
    730 days of 1-hour bars and 60 days of 5-minute bars.
    """

    name = "yfinance"
    quality = DataQuality.DELAYED

    def __init__(self, calendar: TradingCalendar, batch_size: int = 20) -> None:
        self._calendar = calendar
        self._batch_size = batch_size

    def fetch(self, symbols: list[str], interval: str, start: date, end: date) -> ProviderResult:
        import yfinance as yf

        rows: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for offset in range(0, len(symbols), self._batch_size):
            batch = symbols[offset : offset + self._batch_size]
            try:
                data = yf.download(
                    tickers=batch,
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),
                    interval=interval,
                    auto_adjust=True,
                    prepost=False,
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )
            except Exception as exc:  # noqa: BLE001 - provider failures are reported per symbol
                for symbol in batch:
                    errors[symbol] = f"download failed: {exc!r}"
                continue
            for symbol in batch:
                try:
                    frame = data[symbol] if symbol in data.columns.get_level_values(0) else None
                except (KeyError, AttributeError):
                    frame = None
                if frame is None or frame.dropna(how="all").empty:
                    errors[symbol] = "no data returned"
                    continue
                rows.extend(self._rows(symbol, interval, frame.dropna(how="any")))
        candles = _rows_to_frame(rows)
        candles = drop_unfinished_bars(candles, interval, self._calendar, utc_now())
        return ProviderResult(candles=candles, errors=errors)

    def _rows(self, symbol: str, interval: str, frame: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, record in zip(frame.index, frame.itertuples(index=False), strict=True):
            stamp = index.to_pydatetime()
            if interval == "1d":
                ts = datetime.combine(stamp.date(), time(0, 0), tzinfo=UTC)
            else:
                if stamp.tzinfo is None:
                    continue
                ts = stamp.astimezone(UTC)
            rows.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "ts": ts,
                    "open": float(record.Open),
                    "high": float(record.High),
                    "low": float(record.Low),
                    "close": float(record.Close),
                    "volume": float(record.Volume),
                    # Yahoo adjusts daily bars for splits and dividends; intraday bars for
                    # splits only.
                    "adjusted": interval == "1d",
                    "source": self.name,
                    "quality": self.quality.value,
                }
            )
        return rows


_ALPACA_TIMEFRAME = {
    "1d": "1Day",
    "1h": "1Hour",
    "30m": "30Min",
    "15m": "15Min",
    "5m": "5Min",
    "1m": "1Min",
}


class AlpacaProvider:
    """Alpaca market data. Historical bars use the consolidated (SIP) feed.

    The free plan does not serve SIP data from the last 15 minutes, so requests end 16
    minutes ago at the latest. Those historical bars are labelled `consolidated`. Real-time
    bars on the free plan come from one venue (IEX) and would be labelled `partial_venue`;
    this provider does not request them.
    """

    name = "alpaca"
    quality = DataQuality.CONSOLIDATED
    SIP_EMBARGO = timedelta(minutes=16)

    def __init__(
        self,
        settings: Settings,
        calendar: TradingCalendar,
        client: httpx.Client | None = None,
    ) -> None:
        if not settings.has_alpaca_keys:
            raise ProviderError(
                "Alpaca API keys are not set. Set TRADEBOT_ALPACA_API_KEY and "
                "TRADEBOT_ALPACA_API_SECRET, or use --provider yfinance."
            )
        assert settings.alpaca_api_key is not None and settings.alpaca_api_secret is not None
        self._base = settings.alpaca_data_url.rstrip("/")
        self._calendar = calendar
        self._client = client or httpx.Client(timeout=60.0)
        self._headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key.get_secret_value(),
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret.get_secret_value(),
        }

    def fetch(self, symbols: list[str], interval: str, start: date, end: date) -> ProviderResult:
        latest = utc_now() - self.SIP_EMBARGO
        start_ts = datetime.combine(start, time(0, 0), tzinfo=UTC)
        end_ts = min(datetime.combine(end + timedelta(days=1), time(0, 0), tzinfo=UTC), latest)
        rows: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for offset in range(0, len(symbols), 25):
            batch = symbols[offset : offset + 25]
            try:
                rows.extend(self._fetch_batch(batch, interval, start_ts, end_ts))
            except (httpx.HTTPError, ProviderError) as exc:
                for symbol in batch:
                    errors[symbol] = f"request failed: {exc}"
        candles = _rows_to_frame(rows)
        candles = keep_regular_session(candles, interval, self._calendar)
        candles = drop_unfinished_bars(candles, interval, self._calendar, utc_now())
        seen = set(candles["symbol"].unique().to_list()) if candles.height else set()
        for symbol in symbols:
            if symbol not in seen and symbol not in errors:
                errors[symbol] = "no data returned"
        return ProviderResult(candles=candles, errors=errors)

    def _fetch_batch(
        self, symbols: list[str], interval: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "symbols": ",".join(symbols),
            "timeframe": _ALPACA_TIMEFRAME[interval],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": "all",
            "feed": "sip",
            "limit": "10000",
        }
        rows: list[dict[str, Any]] = []
        while True:
            response = self._client.get(
                f"{self._base}/v2/stocks/bars", params=params, headers=self._headers
            )
            if response.status_code >= 400:
                raise ProviderError(f"HTTP {response.status_code}: {response.text[:200]}")
            payload = response.json()
            for symbol, bars in (payload.get("bars") or {}).items():
                for bar in bars:
                    stamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                    if interval == "1d":
                        session_date = stamp.astimezone(NEW_YORK).date()
                        ts = datetime.combine(session_date, time(0, 0), tzinfo=UTC)
                    else:
                        ts = stamp.astimezone(UTC)
                    rows.append(
                        {
                            "symbol": symbol,
                            "interval": interval,
                            "ts": ts,
                            "open": float(bar["o"]),
                            "high": float(bar["h"]),
                            "low": float(bar["l"]),
                            "close": float(bar["c"]),
                            "volume": float(bar["v"]),
                            "adjusted": True,
                            "source": self.name,
                            "quality": self.quality.value,
                        }
                    )
            token = payload.get("next_page_token")
            if not token:
                return rows
            params["page_token"] = token


def build_provider(
    settings: Settings, calendar: TradingCalendar, name: str | None = None
) -> MarketDataProvider:
    chosen = name or settings.resolved_market_provider()
    if chosen == "alpaca":
        return AlpacaProvider(settings, calendar)
    if chosen == "yfinance":
        return YFinanceProvider(calendar)
    raise ProviderError(f"unknown market data provider: {chosen}")
