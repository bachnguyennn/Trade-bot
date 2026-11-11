"""Performance metrics. A ratio that cannot be computed is reported as null, not zero."""

from __future__ import annotations

import math
from datetime import datetime

from src.contracts import BacktestMetrics, BacktestTrade, EquityPoint
from src.market_data.calendar import TradingCalendar

TRADING_DAYS_PER_YEAR = 252


def max_drawdown(equity: list[float]) -> float:
    """Largest peak-to-trough fall, as a negative fraction (0.0 when equity never falls)."""
    peak = -math.inf
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def daily_equity(
    curve: list[EquityPoint], calendar: TradingCalendar, start: datetime, end: datetime
) -> list[float]:
    """Equity at each session close between `start` and `end`, carrying the last value."""
    points = sorted(curve, key=lambda p: p.ts)
    values: list[float] = []
    index = 0
    current: float | None = None
    for session in calendar.sessions:
        if session.close < start:
            continue
        if session.close > end:
            break
        while index < len(points) and points[index].ts <= session.close:
            current = points[index].equity
            index += 1
        if current is not None:
            values.append(current)
    return values


def _returns(values: list[float]) -> list[float]:
    return [b / a - 1.0 for a, b in zip(values, values[1:], strict=False) if a > 0]


def sharpe_ratio(daily_returns: list[float]) -> float | None:
    """Annualised mean over standard deviation of daily returns (zero risk-free rate)."""
    if len(daily_returns) < 2:
        return None
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std = math.sqrt(variance)
    # A spread this small is float noise, not risk; a ratio over it would be meaningless.
    if std <= 1e-12:
        return None
    return mean / std * math.sqrt(TRADING_DAYS_PER_YEAR)


def sortino_ratio(daily_returns: list[float]) -> float | None:
    """Annualised mean over downside deviation of daily returns."""
    if len(daily_returns) < 2:
        return None
    mean = sum(daily_returns) / len(daily_returns)
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in daily_returns) / len(daily_returns))
    if downside <= 1e-12:
        return None
    return mean / downside * math.sqrt(TRADING_DAYS_PER_YEAR)


def trade_statistics(trades: list[BacktestTrade]) -> tuple[float | None, float | None]:
    """Win rate and profit factor. Both are null when they are undefined."""
    if not trades:
        return None, None
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [-t.pnl for t in trades if t.pnl < 0]
    win_rate = len(wins) / len(trades)
    profit_factor = sum(wins) / sum(losses) if losses else None
    return win_rate, profit_factor


def turnover(trades: list[BacktestTrade], initial_equity: float) -> float:
    """Total traded value (entries plus exits) as a multiple of starting capital."""
    traded = sum(t.qty * (t.entry_price + t.exit_price) for t in trades)
    return traded / initial_equity


def compute_metrics(
    curve: list[EquityPoint],
    trades: list[BacktestTrade],
    initial_equity: float,
    calendar: TradingCalendar,
    start: datetime,
    end: datetime,
) -> BacktestMetrics:
    final = curve[-1].equity if curve else initial_equity
    daily = daily_equity(curve, calendar, start, end)
    returns = _returns(daily)
    win_rate, profit_factor = trade_statistics(trades)
    return BacktestMetrics(
        cumulative_return=final / initial_equity - 1.0,
        sharpe_ratio=sharpe_ratio(returns),
        sortino_ratio=sortino_ratio(returns),
        max_drawdown=max_drawdown([p.equity for p in curve] or [initial_equity]),
        win_rate=win_rate,
        profit_factor=profit_factor,
        turnover=turnover(trades, initial_equity),
        trade_count=len(trades),
    )


def category_metrics(
    trades: list[BacktestTrade], initial_equity: float
) -> dict[str, BacktestMetrics]:
    """Trade-level metrics per event category. A trade counts in each of its categories.

    Sharpe and Sortino are not reported per category: a subset of trades has no equity
    curve of its own.
    """
    grouped: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        for category in trade.categories:
            grouped.setdefault(category, []).append(trade)
    out: dict[str, BacktestMetrics] = {}
    for category, members in sorted(grouped.items()):
        members = sorted(members, key=lambda t: t.exit_ts)
        equity = [initial_equity]
        for trade in members:
            equity.append(equity[-1] + trade.pnl)
        win_rate, profit_factor = trade_statistics(members)
        out[category] = BacktestMetrics(
            cumulative_return=equity[-1] / initial_equity - 1.0,
            max_drawdown=max_drawdown(equity),
            win_rate=win_rate,
            profit_factor=profit_factor,
            turnover=turnover(members, initial_equity),
            trade_count=len(members),
        )
    return out
