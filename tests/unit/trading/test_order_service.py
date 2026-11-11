"""Order service safety checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.contracts import (
    EventWindow,
    OrderSide,
    OrderStatus,
    PaperOrder,
    SignalAction,
    StrategyName,
    TradingSignal,
)
from src.trading.broker import (
    AccountState,
    BrokerError,
    BrokerOrder,
    BrokerRejection,
    Position,
    SimulatedBroker,
)
from src.trading.service import OrderService
from src.trading.state import OrderStateStore
from tests.helpers import make_calendar

OPEN_TIME = datetime(2025, 3, 3, 15, 0, tzinfo=UTC)  # Monday, inside the session
CLOSED_TIME = datetime(2025, 3, 3, 23, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = OPEN_TIME) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Env:
    def __init__(self, broker: object | None = None, **kwargs: object) -> None:
        self.clock = Clock()
        self.prices = {"AAA": 100.0, "BBB": 50.0}
        self.broker = broker or SimulatedBroker(100_000.0, self.prices.get, clock=self.clock)
        self.state = OrderStateStore(":memory:")
        self.events: list[PaperOrder] = []
        self.service = OrderService(
            self.broker,  # type: ignore[arg-type]
            self.state,
            make_calendar(),
            self.prices.get,
            clock=self.clock,
            on_order=self.events.append,
            **kwargs,  # type: ignore[arg-type]
        )


def signal(
    signal_id: str = "s1",
    symbol: str = "AAA",
    action: SignalAction = SignalAction.BUY,
    weight: float = 0.05,
) -> TradingSignal:
    trade = action is not SignalAction.NO_TRADE
    return TradingSignal(
        signal_id=signal_id,
        event_id="e1",
        symbol=symbol,
        strategy=StrategyName.IMMEDIATE_REACTION,
        action=action,
        generated_at=OPEN_TIME,
        target_weight=weight if trade else 0.0,
        holding_window=EventWindow.D1,
        reason="test",
    )


def test_valid_signal_becomes_a_filled_order() -> None:
    env = Env()
    order = env.service.submit_signal(signal())
    assert order.status is OrderStatus.FILLED and order.broker == "simulator"
    assert order.client_order_id == order.signal_id == "s1"
    assert order.qty == pytest.approx(50.0)  # 5% of 100,000 at 100
    assert order.filled_price == 100.0 and order.reject_reason is None
    assert [h.status for h in order.history] == [
        OrderStatus.PENDING,
        OrderStatus.SUBMITTED,
        OrderStatus.FILLED,
    ]
    assert env.service.positions()[0].qty == pytest.approx(50.0)
    assert env.events == [order]


def test_duplicate_signal_creates_no_second_order() -> None:
    env = Env()
    first = env.service.submit_signal(signal())
    second = env.service.submit_signal(signal())
    assert second == first
    assert len(env.service.orders()) == 1
    assert env.service.positions()[0].qty == pytest.approx(50.0)
    assert len(env.events) == 1


def test_sell_signal_shorts() -> None:
    env = Env()
    order = env.service.submit_signal(signal(action=SignalAction.SELL))
    assert order.side is OrderSide.SELL and env.service.positions()[0].qty == pytest.approx(-50.0)


def test_kill_switch_blocks_everything_and_persists() -> None:
    env = Env()
    env.service.set_kill_switch(True)
    for index in range(5):
        order = env.service.submit_signal(signal(f"s{index}", "AAA" if index % 2 else "BBB"))
        assert order.status is OrderStatus.BLOCKED
        assert order.reject_reason == "kill switch is on"
    assert env.service.positions() == []
    assert env.service.risk_state().kill_switch
    # A blocked signal stays blocked: releasing the switch does not replay it.
    env.service.set_kill_switch(False)
    assert env.service.submit_signal(signal("s0")).status is OrderStatus.BLOCKED
    assert env.service.submit_signal(signal("fresh")).status is OrderStatus.FILLED


def test_market_hours_are_enforced() -> None:
    env = Env()
    env.clock.now = CLOSED_TIME
    order = env.service.submit_signal(signal())
    assert order.status is OrderStatus.BLOCKED and order.reject_reason == "market is closed"
    relaxed = Env(enforce_market_hours=False)
    relaxed.clock.now = CLOSED_TIME
    assert relaxed.service.submit_signal(signal()).status is OrderStatus.FILLED


def test_no_trade_signal_never_reaches_the_broker() -> None:
    env = Env()
    order = env.service.submit_signal(signal(action=SignalAction.NO_TRADE))
    assert order.status is OrderStatus.BLOCKED and order.qty == 0.0
    assert order.reject_reason is not None and order.reject_reason.startswith("signal is no_trade")
    assert env.service.positions() == []


def test_missing_price_blocks_the_order() -> None:
    env = Env()
    order = env.service.submit_signal(signal(symbol="ZZZ"))
    assert order.status is OrderStatus.BLOCKED
    assert order.reject_reason == "no price available for ZZZ"


def test_daily_loss_limit_blocks_until_the_next_trading_day() -> None:
    env = Env(daily_loss_limit_pct=0.02)
    env.service.submit_signal(signal("s1", weight=0.50))  # 500 shares at 100
    assert not env.service.risk_state().loss_limit_breached
    env.prices["AAA"] = 95.0  # 500 * -5 = -2,500, beyond the 2,000 limit
    risk = env.service.risk_state()
    assert risk.day_pnl == pytest.approx(-2_500.0) and risk.loss_limit_breached

    blocked = env.service.submit_signal(signal("s2", "BBB"))
    assert blocked.status is OrderStatus.BLOCKED
    assert blocked.reject_reason is not None
    assert blocked.reject_reason.startswith("daily loss limit reached")

    env.clock.now = OPEN_TIME + timedelta(days=1)
    assert not env.service.risk_state().loss_limit_breached  # new day, new starting equity
    assert env.service.submit_signal(signal("s3", "BBB")).status is OrderStatus.FILLED


class FlakyBroker:
    """Fails a set number of times, optionally after the order has really arrived."""

    name = "simulator"

    def __init__(self, failures: int, arrives_anyway: bool = False) -> None:
        self.failures = failures
        self.arrives_anyway = arrives_anyway
        self.submits = 0
        self.orders: dict[str, BrokerOrder] = {}

    def _fill(self, client_order_id: str, symbol: str, side: OrderSide, qty: float) -> BrokerOrder:
        order = BrokerOrder(
            client_order_id=client_order_id,
            broker_order_id="b1",
            symbol=symbol,
            side=side,
            qty=qty,
            status=OrderStatus.FILLED,
            filled_price=100.0,
            filled_at=OPEN_TIME,
        )
        self.orders[client_order_id] = order
        return order

    def submit(self, client_order_id: str, symbol: str, side: OrderSide, qty: float) -> BrokerOrder:
        self.submits += 1
        if self.failures > 0:
            self.failures -= 1
            if self.arrives_anyway:
                self._fill(client_order_id, symbol, side, qty)
            raise BrokerError("connection reset")
        return self._fill(client_order_id, symbol, side, qty)

    def get_order(self, client_order_id: str) -> BrokerOrder | None:
        return self.orders.get(client_order_id)

    def positions(self) -> list[Position]:
        return [Position(symbol=o.symbol, qty=o.qty, avg_price=100.0) for o in self.orders.values()]

    def account(self) -> AccountState:
        return AccountState(cash=100_000.0, equity=100_000.0)


def test_network_failure_is_retried() -> None:
    broker = FlakyBroker(failures=2)
    env = Env(broker)
    order = env.service.submit_signal(signal())
    assert order.status is OrderStatus.FILLED and broker.submits == 3


def test_retry_does_not_duplicate_an_order_that_already_arrived() -> None:
    broker = FlakyBroker(failures=1, arrives_anyway=True)
    env = Env(broker)
    order = env.service.submit_signal(signal())
    assert order.status is OrderStatus.FILLED
    assert broker.submits == 1  # the retry asked the broker first and did not resend
    assert len(broker.orders) == 1
    assert "found at broker" in order.history[1].note


def test_broker_unreachable_ends_as_rejected() -> None:
    broker = FlakyBroker(failures=99)
    env = Env(broker)
    order = env.service.submit_signal(signal())
    assert order.status is OrderStatus.REJECTED and broker.submits == 3
    assert order.reject_reason is not None and "unreachable after 3 attempts" in order.reject_reason
    # The failure is final for this signal: it is not resubmitted later.
    assert env.service.submit_signal(signal()).status is OrderStatus.REJECTED
    assert broker.submits == 3


class RejectingBroker(FlakyBroker):
    def submit(self, client_order_id: str, symbol: str, side: OrderSide, qty: float) -> BrokerOrder:
        self.submits += 1
        raise BrokerRejection("insufficient buying power")


def test_broker_rejection_is_recorded_and_not_retried() -> None:
    broker = RejectingBroker(failures=0)
    env = Env(broker)
    order = env.service.submit_signal(signal())
    assert order.status is OrderStatus.REJECTED and broker.submits == 1
    assert order.reject_reason == "broker rejected: insufficient buying power"


def test_reconcile_and_portfolio() -> None:
    env = Env()
    env.service.submit_signal(signal("s1", "AAA"))
    env.service.submit_signal(signal("s2", "BBB", SignalAction.SELL))
    report = env.service.reconcile()
    assert report.consistent and report.position_mismatches == {}

    portfolio = env.service.portfolio()
    assert portfolio.broker == "simulator"
    assert portfolio.equity == pytest.approx(100_000.0)
    assert portfolio.gross_exposure == pytest.approx(0.10)
    assert {p.symbol for p in portfolio.positions} == {"AAA", "BBB"}


def test_reconcile_reports_a_mismatch() -> None:
    broker = FlakyBroker(failures=0)
    env = Env(broker)
    env.service.submit_signal(signal("s1", "AAA"))
    broker.orders.clear()  # the broker no longer holds the position
    report = env.service.reconcile()
    assert not report.consistent
    assert report.position_mismatches == {"AAA": {"expected": 50.0, "broker": 0.0}}


def test_state_survives_a_restart(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "state" / "orders.sqlite"
    store = OrderStateStore(path)
    clock = Clock()
    prices = {"AAA": 100.0}
    service = OrderService(
        SimulatedBroker(100_000.0, prices.get, clock=clock),
        store,
        make_calendar(),
        prices.get,
        clock=clock,
    )
    first = service.submit_signal(signal())
    service.set_kill_switch(True)
    store.close()

    reopened = OrderStateStore(path)
    broker = SimulatedBroker(100_000.0, prices.get, clock=clock)
    restarted = OrderService(broker, reopened, make_calendar(), prices.get, clock=clock)
    assert restarted.kill_switch
    assert restarted.submit_signal(signal()) == first  # still deduplicated after restart
    assert len(restarted.orders()) == 1
