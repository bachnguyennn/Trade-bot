from __future__ import annotations

from datetime import UTC, date, datetime, time

from src.market_data.calendar import xnys_calendar
from tests.helpers import make_calendar


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_session_lookup() -> None:
    cal = make_calendar()
    monday = cal.session_on(date(2025, 3, 3))
    assert monday is not None
    assert cal.session_at(utc(2025, 3, 3, 14, 30)) == monday
    assert cal.session_at(utc(2025, 3, 3, 20, 59)) == monday
    assert cal.session_at(utc(2025, 3, 3, 21, 0)) is None  # close is exclusive
    assert cal.session_at(utc(2025, 3, 3, 14, 29)) is None
    assert not cal.is_open(utc(2025, 3, 8, 16, 0))  # Saturday


def test_next_open_skips_weekend_and_holiday() -> None:
    cal = make_calendar(holidays=(date(2025, 3, 10),))
    friday_evening = utc(2025, 3, 7, 23, 0)
    nxt = cal.next_open_at_or_after(friday_evening)
    assert nxt is not None and nxt.date == date(2025, 3, 11)
    # Exactly at the open counts as that session.
    at_open = cal.next_open_at_or_after(utc(2025, 3, 4, 14, 30))
    assert at_open is not None and at_open.date == date(2025, 3, 4)
    # One second later, the next session is the following day.
    later = cal.next_open_at_or_after(utc(2025, 3, 4, 14, 30, 1))
    assert later is not None and later.date == date(2025, 3, 5)


def test_closes_around_a_time() -> None:
    cal = make_calendar()
    during = utc(2025, 3, 4, 16, 0)
    before = cal.last_close_at_or_before(during)
    after = cal.first_close_after(during)
    assert before is not None and before.date == date(2025, 3, 3)
    assert after is not None and after.date == date(2025, 3, 4)
    overnight = utc(2025, 3, 4, 23, 0)
    assert cal.last_close_at_or_before(overnight).date == date(2025, 3, 4)  # type: ignore[union-attr]
    assert cal.first_close_after(overnight).date == date(2025, 3, 5)  # type: ignore[union-attr]


def test_early_close_shortens_the_session() -> None:
    cal = make_calendar(early_closes={date(2025, 3, 5): time(18, 0)})
    assert cal.session_at(utc(2025, 3, 5, 17, 59)) is not None
    assert cal.session_at(utc(2025, 3, 5, 18, 0)) is None


def test_edges_of_the_calendar_return_none() -> None:
    cal = make_calendar(days=3)
    assert cal.next_open_at_or_after(utc(2026, 1, 1)) is None
    assert cal.last_close_at_or_before(utc(2020, 1, 1)) is None
    last = cal.sessions[-1]
    assert cal.session_after(last) is None
    assert [s.date for s in cal.previous_sessions(last, 5)] == [date(2025, 3, 3), date(2025, 3, 4)]


def test_real_nyse_calendar_knows_holidays_and_early_closes() -> None:
    cal = xnys_calendar("2024-01-01", "2025-12-31")
    assert cal.session_on(date(2024, 12, 25)) is None  # Christmas
    assert cal.session_on(date(2024, 7, 4)) is None  # Independence Day
    black_friday = cal.session_on(date(2024, 11, 29))
    assert black_friday is not None
    assert black_friday.close == utc(2024, 11, 29, 18, 0)  # 13:00 New York
    summer = cal.session_on(date(2024, 7, 1))
    assert summer is not None and summer.open == utc(2024, 7, 1, 13, 30)  # daylight time
