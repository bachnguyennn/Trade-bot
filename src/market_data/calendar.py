"""Trading sessions for US equities (NYSE calendar), including holidays and early closes."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from functools import lru_cache


@dataclass(frozen=True)
class Session:
    """One regular trading session. `open` and `close` are UTC."""

    date: date
    open: datetime
    close: datetime

    @property
    def daily_ts(self) -> datetime:
        """Timestamp used as the key of this session's daily candle: midnight UTC of the date."""
        return datetime.combine(self.date, time(0, 0), tzinfo=UTC)

    def contains(self, ts: datetime) -> bool:
        return self.open <= ts < self.close


class TradingCalendar:
    """Lookup of regular sessions. Built from an explicit list so tests need no data files."""

    def __init__(self, sessions: list[Session]) -> None:
        self._sessions = sorted(sessions, key=lambda s: s.open)
        self._opens = [s.open for s in self._sessions]
        self._closes = [s.close for s in self._sessions]
        self._by_date = {s.date: i for i, s in enumerate(self._sessions)}

    @property
    def sessions(self) -> list[Session]:
        return self._sessions

    def session_on(self, day: date) -> Session | None:
        index = self._by_date.get(day)
        return None if index is None else self._sessions[index]

    def session_at(self, ts: datetime) -> Session | None:
        """The session that is open at `ts`, if any."""
        index = bisect_right(self._opens, ts) - 1
        if index >= 0 and self._sessions[index].contains(ts):
            return self._sessions[index]
        return None

    def is_open(self, ts: datetime) -> bool:
        return self.session_at(ts) is not None

    def next_open_at_or_after(self, ts: datetime) -> Session | None:
        """First session whose open is at or after `ts`."""
        index = bisect_left(self._opens, ts)
        return self._sessions[index] if index < len(self._sessions) else None

    def first_close_after(self, ts: datetime) -> Session | None:
        """First session whose close is strictly after `ts`."""
        index = bisect_right(self._closes, ts)
        return self._sessions[index] if index < len(self._sessions) else None

    def last_close_at_or_before(self, ts: datetime) -> Session | None:
        """Last session that had fully closed by `ts`."""
        index = bisect_right(self._closes, ts) - 1
        return self._sessions[index] if index >= 0 else None

    def session_after(self, session: Session) -> Session | None:
        index = self._by_date[session.date] + 1
        return self._sessions[index] if index < len(self._sessions) else None

    def previous_sessions(self, session: Session, count: int) -> list[Session]:
        """Up to `count` sessions immediately before `session`, oldest first."""
        index = self._by_date[session.date]
        return self._sessions[max(0, index - count) : index]


@lru_cache(maxsize=4)
def xnys_calendar(start: str = "2015-01-01", end: str | None = None) -> TradingCalendar:
    """NYSE regular sessions from `exchange-calendars`."""
    import exchange_calendars as xcals

    if end is None:
        end = f"{datetime.now(UTC).year + 1}-12-31"
    schedule = xcals.get_calendar("XNYS", start=start, end=end).schedule
    sessions = [
        Session(
            date=index.date(),
            open=row.open.to_pydatetime().astimezone(UTC),
            close=row.close.to_pydatetime().astimezone(UTC),
        )
        for index, row in zip(schedule.index, schedule.itertuples(index=False), strict=True)
    ]
    return TradingCalendar(sessions)
