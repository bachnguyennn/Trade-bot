from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from src.backtesting.metrics import (
    category_metrics,
    compute_metrics,
    daily_equity,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    trade_statistics,
    turnover,
)
from src.contracts import BacktestTrade, EquityPoint, OrderSide
from tests.helpers import make_calendar

T0 = datetime(2025, 3, 3, 14, 30, tzinfo=UTC)


def trade(pnl: float, category: str = "tariffs_trade", day: int = 0) -> BacktestTrade:
    entry = T0 + timedelta(days=day)
    return BacktestTrade(
        signal_id=f"s{day}{pnl}",
        event_id="e",
        symbol="AAA",
        side=OrderSide.BUY,
        qty=10.0,
        signal_ts=entry,
        entry_ts=entry,
        entry_price=100.0,
        exit_ts=entry + timedelta(hours=6),
        exit_price=100.0 + pnl / 10.0,
        costs=0.0,
        pnl=pnl,
        return_pct=pnl / 1000.0,
        exit_reason="holding_period",
        categories=[category],
    )


def test_max_drawdown() -> None:
    assert max_drawdown([100, 110, 99, 105, 120]) == pytest.approx(99 / 110 - 1)
    assert max_drawdown([100, 101, 102]) == 0.0
    assert max_drawdown([]) == 0.0


def test_sharpe_and_sortino_by_hand() -> None:
    returns = [0.01, -0.005, 0.02, 0.0]
    mean = sum(returns) / 4
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / 3)
    assert sharpe_ratio(returns) == pytest.approx(mean / std * math.sqrt(252))
    downside = math.sqrt((0.005**2) / 4)
    assert sortino_ratio(returns) == pytest.approx(mean / downside * math.sqrt(252))


def test_ratios_are_null_when_undefined() -> None:
    assert sharpe_ratio([]) is None and sharpe_ratio([0.01]) is None
    assert sharpe_ratio([0.01, 0.01, 0.01]) is None  # no variation
    assert sortino_ratio([0.01, 0.02]) is None  # no losing day


def test_trade_statistics() -> None:
    win_rate, profit_factor = trade_statistics([trade(100), trade(50), trade(-75)])
    assert win_rate == pytest.approx(2 / 3)
    assert profit_factor == pytest.approx(150 / 75)
    assert trade_statistics([]) == (None, None)
    assert trade_statistics([trade(10)]) == (1.0, None)  # no losses: undefined, not infinite


def test_turnover_counts_both_sides() -> None:
    assert turnover([trade(0.0)], 10_000.0) == pytest.approx(10 * (100 + 100) / 10_000)


def test_daily_equity_carries_last_value() -> None:
    calendar = make_calendar(days=5)
    sessions = calendar.sessions
    curve = [
        EquityPoint(ts=sessions[0].open, equity=100.0),
        EquityPoint(ts=sessions[2].close, equity=110.0),
    ]
    values = daily_equity(curve, calendar, sessions[0].open, sessions[4].close)
    assert values == [100.0, 100.0, 110.0, 110.0, 110.0]


def test_compute_metrics_end_to_end() -> None:
    calendar = make_calendar(days=5)
    sessions = calendar.sessions
    trades = [trade(1000.0, day=0), trade(-500.0, day=1)]
    curve = [
        EquityPoint(ts=sessions[0].open, equity=100_000.0),
        EquityPoint(ts=sessions[0].close, equity=101_000.0),
        EquityPoint(ts=sessions[1].close, equity=100_500.0),
    ]
    metrics = compute_metrics(
        curve, trades, 100_000.0, calendar, sessions[0].open, sessions[4].close
    )
    assert metrics.cumulative_return == pytest.approx(0.005)
    assert metrics.max_drawdown == pytest.approx(100_500 / 101_000 - 1)
    assert metrics.win_rate == 0.5 and metrics.profit_factor == pytest.approx(2.0)
    assert metrics.trade_count == 2
    assert metrics.sharpe_ratio is not None and metrics.sortino_ratio is not None


def test_no_trades_gives_flat_metrics_without_fake_ratios() -> None:
    calendar = make_calendar(days=5)
    start, end = calendar.sessions[0].open, calendar.sessions[4].close
    metrics = compute_metrics(
        [EquityPoint(ts=start, equity=100_000.0)], [], 100_000.0, calendar, start, end
    )
    assert metrics.cumulative_return == 0.0 and metrics.trade_count == 0
    assert metrics.sharpe_ratio is None and metrics.win_rate is None
    assert metrics.profit_factor is None


def test_category_metrics() -> None:
    trades = [
        trade(100.0, "tariffs_trade", 0),
        trade(-40.0, "tariffs_trade", 1),
        trade(30.0, "energy_oil", 2),
    ]
    by_category = category_metrics(trades, 10_000.0)
    assert set(by_category) == {"energy_oil", "tariffs_trade"}
    tariffs = by_category["tariffs_trade"]
    assert tariffs.trade_count == 2
    assert tariffs.cumulative_return == pytest.approx(0.006)
    assert tariffs.max_drawdown == pytest.approx(10_060 / 10_100 - 1)
    assert tariffs.sharpe_ratio is None
