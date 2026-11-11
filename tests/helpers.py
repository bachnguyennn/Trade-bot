"""Builders for synthetic test data. Nothing here is real market data."""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

import polars as pl

from src.contracts import DataQuality, EventWindow, StockCandle
from src.core.storage import SCHEMAS, DataPaths
from src.market_data.calendar import Session, TradingCalendar
from src.market_data.providers import INTERVAL_STEP
from src.ml.baseline import save_bundle, train_on_samples
from src.ml.dataset import Sample

OPEN_UTC = time(14, 30)
CLOSE_UTC = time(21, 0)


def make_calendar(
    start: date = date(2025, 3, 3),
    days: int = 20,
    holidays: tuple[date, ...] = (),
    early_closes: dict[date, time] | None = None,
) -> TradingCalendar:
    """Weekday sessions from 14:30 to 21:00 UTC, with optional holidays and early closes."""
    early_closes = early_closes or {}
    sessions: list[Session] = []
    day = start
    while len(sessions) < days:
        if day.weekday() < 5 and day not in holidays:
            close = early_closes.get(day, CLOSE_UTC)
            sessions.append(
                Session(
                    date=day,
                    open=datetime.combine(day, OPEN_UTC, tzinfo=UTC),
                    close=datetime.combine(day, close, tzinfo=UTC),
                )
            )
        day += timedelta(days=1)
    return TradingCalendar(sessions)


def _row(
    symbol: str, interval: str, ts: datetime, open_: float, close: float, volume: float
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "interval": interval,
        "ts": ts,
        "open": open_,
        "high": max(open_, close) * 1.001,
        "low": min(open_, close) * 0.999,
        "close": close,
        "volume": volume,
        "adjusted": True,
        "source": "synthetic-test",
        "quality": DataQuality.SYNTHETIC.value,
    }


def daily_candles(
    symbol: str,
    calendar: TradingCalendar,
    open_close: Callable[[int], tuple[float, float]],
    volume: Callable[[int], float] = lambda i: 1_000_000.0,
    skip: tuple[date, ...] = (),
) -> pl.DataFrame:
    """One daily bar per session. `open_close(i)` gives the open and close of session i."""
    rows = []
    for index, session in enumerate(calendar.sessions):
        if session.date in skip:
            continue
        open_, close = open_close(index)
        rows.append(_row(symbol, "1d", session.daily_ts, open_, close, volume(index)))
    return pl.DataFrame(rows, schema=SCHEMAS[StockCandle], orient="row")


def intraday_candles(
    symbol: str,
    session: Session,
    interval: str,
    price: Callable[[int], float],
    skip_bars: tuple[int, ...] = (),
) -> pl.DataFrame:
    """Bars covering one session. Bar k opens at `price(k)` and closes at `price(k + 1)`."""
    step = INTERVAL_STEP[interval]
    rows = []
    ts = session.open
    index = 0
    while ts < session.close:
        if index not in skip_bars:
            rows.append(_row(symbol, interval, ts, price(index), price(index + 1), 1_000.0))
        ts += step
        index += 1
    return pl.DataFrame(rows, schema=SCHEMAS[StockCandle], orient="row")


def signal_samples(n: int = 400, seed: int = 7) -> list[Sample]:
    """Synthetic training samples in which the word "boom" or "bust" decides the direction."""
    rng = random.Random(seed)
    start = datetime(2024, 1, 1, 15, 0, tzinfo=UTC)
    samples = []
    for index in range(n):
        positive = rng.random() < 0.5
        word = "boom" if positive else "bust"
        available = start + timedelta(days=index)
        samples.append(
            Sample(
                event_id=f"e{index}",
                symbol="NUE",
                available_at=available,
                label_end=available + timedelta(hours=7),
                text=f"synthetic post about tariffs and steel {word} today",
                categorical={"symbol=NUE": 1.0, "category=tariffs_trade": 1.0},
                abnormal_ret=(0.01 if positive else -0.01) * (1 + rng.random()),
            )
        )
    return samples


def save_synthetic_model(paths: DataPaths) -> str:
    """Train a model on `signal_samples` and store it. Returns its version."""
    bundle, report, _ = train_on_samples(
        signal_samples(), EventWindow.D1, 200, timedelta(seconds=30), DataQuality.SYNTHETIC
    )
    save_bundle(paths, bundle, report)
    return report.model_version
