"""Event-window measurements: what a symbol did after a moment in time.

Rules (research R7):

- Intraday windows enter at the open of the first regular-session bar at or after the
  anchor and exit at the close of the last bar inside the window. A window is unavailable
  when bars are missing, too coarse, or the window would cross the session close.
- `1d` enters at the open of the first session opening at or after the anchor and exits at
  that session's close.
- `close_to_close` spans the last close before the anchor to the first close after it. It
  is descriptive only: it starts before the information existed, so it is not tradable.

Abnormal return is the symbol's return minus the benchmark's return over the same window.
Nothing is estimated: when data is missing the measurement is marked unavailable.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta

import polars as pl

from src.contracts import DataQuality, EventWindow, MarketFeature
from src.market_data.calendar import Session, TradingCalendar
from src.market_data.providers import INTERVAL_STEP
from src.market_data.store import CandleStore
from src.market_data.universe import Universe

# Finest first: the most precise stored bars are preferred.
INTRADAY_INTERVALS = ["1m", "5m", "15m", "30m", "1h"]
VOLUME_LOOKBACK_SESSIONS = 20
VOLUME_MIN_SESSIONS = 5


class BarSeries:
    """Column-wise view of one symbol's bars with fast lookup by time."""

    def __init__(self, frame: pl.DataFrame) -> None:
        self.ts: list[datetime] = frame["ts"].to_list()
        self.open: list[float] = frame["open"].to_list()
        self.high: list[float] = frame["high"].to_list()
        self.low: list[float] = frame["low"].to_list()
        self.close: list[float] = frame["close"].to_list()
        self.volume: list[float] = frame["volume"].to_list()
        self.quality: list[str] = frame["quality"].to_list()
        self._index = {ts: i for i, ts in enumerate(self.ts)}

    def __len__(self) -> int:
        return len(self.ts)

    def index_of(self, ts: datetime) -> int | None:
        return self._index.get(ts)

    def index_at_or_after(self, ts: datetime) -> int | None:
        index = bisect_left(self.ts, ts)
        return index if index < len(self.ts) else None


@dataclass(frozen=True)
class PathBar:
    """One bar on the path between entry and exit, used to check stop-losses."""

    start: datetime
    end: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Measurement:
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    realized_vol: float | None
    volume_ratio: float | None
    shifted_to_open: bool
    quality: DataQuality
    path: tuple[PathBar, ...] = ()

    @property
    def ret(self) -> float:
        return self.exit_price / self.entry_price - 1.0


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


class WindowCalculator:
    def __init__(
        self,
        store: CandleStore,
        calendar: TradingCalendar,
        universe: Universe,
        fallback_quality: DataQuality = DataQuality.DELAYED,
    ) -> None:
        self._store = store
        self._calendar = calendar
        self._universe = universe
        self._fallback_quality = fallback_quality
        self._series: dict[tuple[str, str], BarSeries] = {}

    def series(self, symbol: str, interval: str) -> BarSeries:
        key = (symbol, interval)
        if key not in self._series:
            self._series[key] = BarSeries(self._store.read(symbol, interval))
        return self._series[key]

    # -- raw measurements -------------------------------------------------------------

    def measure(self, symbol: str, anchor: datetime, window: EventWindow) -> Measurement | str:
        """Measure one symbol over one window, or return the reason it cannot be measured."""
        if window is EventWindow.CLOSE_TO_CLOSE:
            return self._measure_close_to_close(symbol, anchor)
        if window is EventWindow.D1:
            return self._measure_next_session(symbol, anchor)
        return self._measure_intraday(symbol, anchor, window)

    def _eligible(self, symbol: str, session: Session) -> bool:
        return self._universe.is_eligible(symbol, session.date)

    def _measure_next_session(self, symbol: str, anchor: datetime) -> Measurement | str:
        session = self._calendar.next_open_at_or_after(anchor)
        if session is None:
            return "no trading session after the anchor"
        if not self._eligible(symbol, session):
            return "symbol not eligible on the session date"
        daily = self.series(symbol, "1d")
        index = daily.index_of(session.daily_ts)
        if index is None:
            return "missing daily candle for the session"
        open_price = daily.open[index]
        return Measurement(
            entry_ts=session.open,
            exit_ts=session.close,
            entry_price=open_price,
            exit_price=daily.close[index],
            realized_vol=(daily.high[index] - daily.low[index]) / open_price,
            volume_ratio=self._volume_ratio(daily, session, index),
            shifted_to_open=not self._calendar.is_open(anchor),
            quality=DataQuality(daily.quality[index]),
            path=(
                PathBar(
                    session.open,
                    session.close,
                    open_price,
                    daily.high[index],
                    daily.low[index],
                    daily.close[index],
                ),
            ),
        )

    def _volume_ratio(self, daily: BarSeries, session: Session, index: int) -> float | None:
        previous = self._calendar.previous_sessions(session, VOLUME_LOOKBACK_SESSIONS)
        volumes = [
            daily.volume[i] for s in previous if (i := daily.index_of(s.daily_ts)) is not None
        ]
        if len(volumes) < VOLUME_MIN_SESSIONS:
            return None
        average = sum(volumes) / len(volumes)
        return daily.volume[index] / average if average > 0 else None

    def _measure_close_to_close(self, symbol: str, anchor: datetime) -> Measurement | str:
        before = self._calendar.last_close_at_or_before(anchor)
        after = self._calendar.first_close_after(anchor)
        if before is None or after is None:
            return "no trading session around the anchor"
        if not (self._eligible(symbol, before) and self._eligible(symbol, after)):
            return "symbol not eligible on the session date"
        daily = self.series(symbol, "1d")
        i, j = daily.index_of(before.daily_ts), daily.index_of(after.daily_ts)
        if i is None or j is None:
            return "missing daily candle for the session"
        return Measurement(
            entry_ts=before.close,
            exit_ts=after.close,
            entry_price=daily.close[i],
            exit_price=daily.close[j],
            realized_vol=(daily.high[j] - daily.low[j]) / daily.open[j],
            volume_ratio=self._volume_ratio(daily, after, j),
            shifted_to_open=not self._calendar.is_open(anchor),
            quality=DataQuality.lowest(
                [DataQuality(daily.quality[i]), DataQuality(daily.quality[j])]
            ),
        )

    def _measure_intraday(
        self, symbol: str, anchor: datetime, window: EventWindow
    ) -> Measurement | str:
        duration = window.duration
        session = self._calendar.session_at(anchor)
        shifted = session is None
        if session is None:
            session = self._calendar.next_open_at_or_after(anchor)
            if session is None:
                return "no trading session after the anchor"
            start = session.open
        else:
            start = anchor
        if not self._eligible(symbol, session):
            return "symbol not eligible on the session date"

        reason = "no intraday candles stored at or finer than the window"
        for interval in INTRADAY_INTERVALS:
            step = INTERVAL_STEP[interval]
            if step > duration:
                continue
            bars = self.series(symbol, interval)
            if len(bars) == 0:
                continue
            outcome = self._walk_bars(bars, step, session, start, duration, shifted)
            if isinstance(outcome, Measurement):
                return outcome
            reason = outcome
        return reason

    @staticmethod
    def _walk_bars(
        bars: BarSeries,
        step: timedelta,
        session: Session,
        start: datetime,
        duration: timedelta,
        shifted: bool,
    ) -> Measurement | str:
        first = bars.index_at_or_after(start)
        if first is None or bars.ts[first] >= session.close:
            return "missing candles after the anchor"
        entry_ts = bars.ts[first]
        if entry_ts >= start + step:
            return "missing candles at the entry time"
        target = entry_ts + duration
        if target > session.close:
            return "window crosses the session close"

        prices = [bars.open[first]]
        qualities: list[DataQuality] = []
        path: list[PathBar] = []
        expected = entry_ts
        index = first
        while index < len(bars) and bars.ts[index] < target:
            if bars.ts[index] != expected:
                return "missing candles inside the window"
            prices.append(bars.close[index])
            qualities.append(DataQuality(bars.quality[index]))
            expected = min(bars.ts[index] + step, session.close)
            path.append(
                PathBar(
                    bars.ts[index],
                    expected,
                    bars.open[index],
                    bars.high[index],
                    bars.low[index],
                    bars.close[index],
                )
            )
            index += 1
        if expected != target:
            return "candles do not cover the window exactly"

        log_returns = [math.log(b / a) for a, b in zip(prices, prices[1:], strict=False)]
        return Measurement(
            entry_ts=entry_ts,
            exit_ts=target,
            entry_price=prices[0],
            exit_price=prices[-1],
            realized_vol=_std(log_returns),
            volume_ratio=None,
            shifted_to_open=shifted,
            quality=DataQuality.lowest(qualities),
            path=tuple(path),
        )

    # -- features ---------------------------------------------------------------------

    def feature(
        self, event_id: str, symbol: str, anchor: datetime, window: EventWindow
    ) -> MarketFeature:
        """Abnormal-return feature for one event, symbol, and window."""

        def unavailable(reason: str) -> MarketFeature:
            return MarketFeature(
                event_id=event_id,
                symbol=symbol,
                window=window,
                anchor_ts=anchor,
                tradable=window.tradable,
                available=False,
                unavailable_reason=reason,
                quality=self._fallback_quality,
            )

        own = self.measure(symbol, anchor, window)
        if isinstance(own, str):
            return unavailable(own)
        benchmark = self.measure(self._universe.benchmark, anchor, window)
        if isinstance(benchmark, str):
            return unavailable(f"benchmark: {benchmark}")
        if (benchmark.entry_ts, benchmark.exit_ts) != (own.entry_ts, own.exit_ts):
            return unavailable("benchmark window does not match the symbol window")

        return MarketFeature(
            event_id=event_id,
            symbol=symbol,
            window=window,
            anchor_ts=anchor,
            entry_ts=own.entry_ts,
            exit_ts=own.exit_ts,
            entry_price=own.entry_price,
            exit_price=own.exit_price,
            ret=own.ret,
            benchmark_ret=benchmark.ret,
            abnormal_ret=own.ret - benchmark.ret,
            realized_vol=own.realized_vol,
            volume_ratio=own.volume_ratio,
            tradable=window.tradable,
            shifted_to_open=own.shifted_to_open,
            available=True,
            quality=DataQuality.lowest([own.quality, benchmark.quality]),
        )

    def features(
        self, event_id: str, symbol: str, anchor: datetime, windows: list[EventWindow]
    ) -> list[MarketFeature]:
        return [self.feature(event_id, symbol, anchor, w) for w in windows]
