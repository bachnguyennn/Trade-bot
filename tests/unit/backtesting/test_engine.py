"""Engine rules: timing, costs, slippage, stop-loss, and risk limits, on synthetic bars."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from src.backtesting.engine import BacktestEngine, ExecutionConfig
from src.contracts import (
    DataQuality,
    EventWindow,
    OrderSide,
    SignalAction,
    StrategyName,
    TradingSignal,
    UniverseMember,
)
from src.core.storage import DataPaths
from src.market_data.calendar import TradingCalendar
from src.market_data.store import CandleStore
from src.market_data.universe import Universe
from src.market_data.windows import WindowCalculator
from tests.helpers import daily_candles, intraday_candles, make_calendar

FREE = ExecutionConfig(cost_bps=0.0, slippage_bps=0.0)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def member(symbol: str) -> UniverseMember:
    return UniverseMember(
        symbol=symbol, name=symbol, kind="stock", sector="Test", eligible_from=date(2015, 1, 1)
    )


@pytest.fixture
def calendar() -> TradingCalendar:
    return make_calendar()


@pytest.fixture
def calculator(paths: DataPaths, calendar: TradingCalendar) -> WindowCalculator:
    store = CandleStore(paths)
    # Every session: UP opens 100 and closes 102; DOWN opens 100 and closes 95; SPY is flat.
    store.upsert(daily_candles("UP", calendar, lambda i: (100.0, 102.0)))
    store.upsert(daily_candles("OTHER", calendar, lambda i: (50.0, 51.0)))
    store.upsert(daily_candles("SPY", calendar, lambda i: (400.0, 400.0)))
    down = daily_candles("DOWN", calendar, lambda i: (100.0, 95.0))
    store.upsert(down)
    universe = Universe([member(s) for s in ("SPY", "UP", "DOWN", "OTHER", "GAP")], "SPY")
    return WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)


def signal(
    symbol: str,
    generated_at: datetime,
    action: SignalAction = SignalAction.BUY,
    weight: float = 0.10,
    stop: float | None = None,
    window: EventWindow = EventWindow.D1,
    event_id: str = "e1",
) -> TradingSignal:
    trade = action is not SignalAction.NO_TRADE
    return TradingSignal(
        signal_id=f"sig-{symbol}-{generated_at.isoformat()}-{action.value}",
        event_id=event_id,
        symbol=symbol,
        strategy=StrategyName.IMMEDIATE_REACTION,
        action=action,
        generated_at=generated_at,
        target_weight=weight if trade else 0.0,
        holding_window=window,
        stop_loss_pct=stop if trade else None,
        reason="test (detail 1)",
    )


def test_long_trade_without_frictions(calculator: WindowCalculator) -> None:
    result = BacktestEngine(calculator, FREE).run(
        [signal("UP", utc(2025, 3, 3, 16, 0))], {"e1": ["tariffs_trade"]}
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_ts == utc(2025, 3, 4, 14, 30)  # next session open
    assert trade.exit_ts == utc(2025, 3, 4, 21, 0)
    assert trade.qty == pytest.approx(10_000 / 100.0)
    assert trade.pnl == pytest.approx(200.0)
    assert trade.return_pct == pytest.approx(0.02)
    assert trade.exit_reason == "holding_period"
    assert trade.categories == ["tariffs_trade"]
    assert result.equity_curve[-1].equity == pytest.approx(100_200.0)


def test_short_trade_profits_from_a_fall(calculator: WindowCalculator) -> None:
    result = BacktestEngine(calculator, FREE).run(
        [signal("DOWN", utc(2025, 3, 3, 16, 0), SignalAction.SELL)]
    )
    trade = result.trades[0]
    assert trade.side is OrderSide.SELL
    assert trade.pnl == pytest.approx(500.0)


def test_entry_is_never_before_the_signal(calculator: WindowCalculator) -> None:
    signals = [
        signal("UP", utc(2025, 3, 3 + d, h, 7), event_id=f"e{d}{h}")
        for d in range(4)
        for h in (3, 15, 22)
    ]
    result = BacktestEngine(calculator, FREE).run(signals)
    assert result.trades
    for trade in result.trades:
        assert trade.entry_ts >= trade.signal_ts


def test_costs_and_slippage_reduce_returns(calculator: WindowCalculator) -> None:
    signals = [signal("UP", utc(2025, 3, 3, 16, 0))]
    free = BacktestEngine(calculator, FREE).run(signals).trades[0]
    priced = (
        BacktestEngine(calculator, ExecutionConfig(cost_bps=5.0, slippage_bps=10.0))
        .run(signals)
        .trades[0]
    )

    assert priced.entry_price == pytest.approx(100.0 * 1.001)  # buys fill higher
    assert priced.exit_price == pytest.approx(102.0 * 0.999)  # sells fill lower
    qty = 10_000 / (100.0 * 1.001)
    expected_costs = 0.0005 * qty * (priced.entry_price + priced.exit_price)
    assert priced.costs == pytest.approx(expected_costs)
    assert priced.pnl == pytest.approx(
        qty * (priced.exit_price - priced.entry_price) - expected_costs
    )
    assert priced.pnl < free.pnl


def test_slippage_also_hurts_shorts(calculator: WindowCalculator) -> None:
    engine = BacktestEngine(calculator, ExecutionConfig(cost_bps=0.0, slippage_bps=10.0))
    trade = engine.run([signal("DOWN", utc(2025, 3, 3, 16, 0), SignalAction.SELL)]).trades[0]
    assert trade.entry_price == pytest.approx(100.0 * 0.999)  # sells lower
    assert trade.exit_price == pytest.approx(95.0 * 1.001)  # buys back higher


def test_stop_loss_on_a_daily_bar(calculator: WindowCalculator) -> None:
    # DOWN falls 5% within the session; a 3% stop exits at 97.
    result = BacktestEngine(calculator, FREE).run(
        [signal("DOWN", utc(2025, 3, 3, 16, 0), stop=0.03)]
    )
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == pytest.approx(97.0)
    assert trade.return_pct == pytest.approx(-0.03)
    # A wider stop is not touched (low is 95 * 0.999).
    wide = (
        BacktestEngine(calculator, FREE)
        .run([signal("DOWN", utc(2025, 3, 3, 16, 0), stop=0.10)])
        .trades[0]
    )
    assert wide.exit_reason == "holding_period" and wide.exit_price == pytest.approx(95.0)


def test_stop_loss_gap_fills_at_the_open(
    paths: DataPaths, calendar: TradingCalendar, calculator: WindowCalculator
) -> None:
    store = CandleStore(paths)
    session = calendar.sessions[0]
    # Hourly bars: 100, 99.5, then the third bar opens far below the 3% stop.
    prices = {0: 100.0, 1: 99.5, 2: 90.0, 3: 90.0}
    gap = intraday_candles("GAP", session, "1h", lambda k: prices.get(k, 90.0))
    # Make the second bar close at 99.5 and the third open at 90 (a gap between bars).
    second_bar = pl.int_range(pl.len()) == 1
    gap = gap.with_columns(
        pl.when(second_bar).then(99.5).otherwise(pl.col("close")).alias("close"),
        pl.when(second_bar).then(99.4).otherwise(pl.col("low")).alias("low"),
    )
    store.upsert(gap)
    store.upsert(intraday_candles("SPY", session, "1h", lambda k: 400.0))
    universe = Universe([member("SPY"), member("GAP")], "SPY")
    calc = WindowCalculator(store, calendar, universe, DataQuality.SYNTHETIC)
    result = BacktestEngine(calc, FREE).run(
        [signal("GAP", session.open, stop=0.03, window=EventWindow.H4)]
    )
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == pytest.approx(90.0)  # worse than the 97 stop level
    assert trade.exit_ts == session.open + timedelta(hours=2)


def test_one_position_per_symbol(calculator: WindowCalculator) -> None:
    same_session = [
        signal("UP", utc(2025, 3, 3, 15, 0), event_id="a"),
        signal("UP", utc(2025, 3, 3, 16, 0), event_id="b"),
    ]
    result = BacktestEngine(calculator, FREE).run(same_session)
    assert len(result.trades) == 1
    assert result.no_trade_reasons == {"risk: position already open in symbol": 1}


def test_gross_exposure_limit(calculator: WindowCalculator) -> None:
    config = ExecutionConfig(cost_bps=0, slippage_bps=0, max_gross_exposure=0.15)
    signals = [
        signal("UP", utc(2025, 3, 3, 16, 0), event_id="a"),
        signal("OTHER", utc(2025, 3, 3, 16, 0), event_id="b"),
    ]
    result = BacktestEngine(calculator, config).run(signals)
    assert len(result.trades) == 1
    assert result.no_trade_reasons == {"risk: gross exposure limit": 1}


def test_position_weight_is_capped(calculator: WindowCalculator) -> None:
    config = ExecutionConfig(cost_bps=0, slippage_bps=0, max_position_weight=0.05)
    trade = (
        BacktestEngine(calculator, config)
        .run([signal("UP", utc(2025, 3, 3, 16, 0), weight=0.50)])
        .trades[0]
    )
    assert trade.qty * trade.entry_price == pytest.approx(5_000.0)


def test_no_trade_and_unfillable_signals_are_counted(calculator: WindowCalculator) -> None:
    signals = [
        signal("UP", utc(2025, 3, 3, 16, 0), SignalAction.NO_TRADE),
        signal("MISSING", utc(2025, 3, 3, 16, 0)),
        signal("UP", utc(2030, 1, 1, 0, 0), event_id="late"),
    ]
    result = BacktestEngine(calculator, FREE).run(signals)
    assert result.trades == []
    assert result.signal_count == 3 and result.no_trade_count == 3
    assert result.no_trade_reasons == {
        "strategy: test": 1,
        "execution: symbol not eligible on the session date": 1,
        "execution: no trading session after the anchor": 1,
    }


def test_equity_compounds_in_exit_order(calculator: WindowCalculator) -> None:
    signals = [
        signal("UP", utc(2025, 3, 3, 16, 0), event_id="a"),
        signal("UP", utc(2025, 3, 4, 22, 0), event_id="b"),
    ]
    result = BacktestEngine(calculator, FREE).run(signals)
    first, second = result.trades
    assert first.exit_ts <= second.entry_ts
    assert first.pnl == pytest.approx(200.0)
    assert second.pnl == pytest.approx(100_200.0 * 0.10 * 0.02)
    assert [p.equity for p in result.equity_curve] == pytest.approx([100_200.0, 100_400.4])
