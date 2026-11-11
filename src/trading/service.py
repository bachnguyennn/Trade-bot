"""Order service: every paper order passes through these checks, in this order.

1. Duplicate prevention: one order per signal, enforced by a unique key in the store.
2. `no_trade` signals never become orders.
3. Kill switch: when on, nothing is submitted.
4. Market hours: no order outside a regular session.
5. Daily loss limit: no new order once the day's loss reaches the limit.
6. Sizing from the signal's target weight and the latest price.
7. Submission with retries that first ask the broker whether an earlier attempt arrived.

Every decision, including each refusal and its reason, is logged and stored.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel

from src.contracts import (
    OrderSide,
    OrderStatus,
    OrderStatusChange,
    PaperOrder,
    SignalAction,
    TradingSignal,
)
from src.core.logging import get_logger
from src.core.timeutils import utc_now
from src.market_data.calendar import TradingCalendar
from src.trading.broker import (
    AccountState,
    BrokerError,
    BrokerOrder,
    BrokerRejection,
    ExecutionBroker,
    Position,
    PriceSource,
)
from src.trading.state import OrderStateStore

log = get_logger(__name__)

KILL_SWITCH_KEY = "kill_switch"
MAX_SUBMIT_ATTEMPTS = 3


class RiskState(BaseModel):
    kill_switch: bool
    daily_loss_limit_pct: float
    day: str
    day_start_equity: float
    equity: float
    day_pnl: float
    loss_limit_breached: bool
    market_open: bool
    enforce_market_hours: bool


class Portfolio(BaseModel):
    broker: str
    cash: float
    equity: float
    day_pnl: float
    gross_exposure: float
    positions: list[Position]


class ReconcileReport(BaseModel):
    orders_checked: int
    orders_updated: int
    position_mismatches: dict[str, dict[str, float]]

    @property
    def consistent(self) -> bool:
        return not self.position_mismatches


class OrderService:
    def __init__(
        self,
        broker: ExecutionBroker,
        state: OrderStateStore,
        calendar: TradingCalendar,
        price_source: PriceSource,
        daily_loss_limit_pct: float = 0.02,
        enforce_market_hours: bool = True,
        clock: Callable[[], datetime] = utc_now,
        on_order: Callable[[PaperOrder], None] | None = None,
    ) -> None:
        self._broker = broker
        self._state = state
        self._calendar = calendar
        self._price_source = price_source
        self._loss_limit = daily_loss_limit_pct
        self._enforce_hours = enforce_market_hours
        self._clock = clock
        self._on_order = on_order
        self._lock = threading.RLock()

    # -- risk state ----------------------------------------------------------------

    @property
    def kill_switch(self) -> bool:
        return self._state.get_value(KILL_SWITCH_KEY) == "on"

    def set_kill_switch(self, enabled: bool) -> RiskState:
        self._state.set_value(KILL_SWITCH_KEY, "on" if enabled else "off")
        log.warning("kill switch changed", extra={"enabled": enabled})
        return self.risk_state()

    def _trading_day(self, now: datetime) -> str:
        """The session date the loss limit applies to: today's session, else the next one."""
        session = self._calendar.session_at(now) or self._calendar.first_close_after(now)
        return (session.date if session else now.date()).isoformat()

    def _account(self) -> AccountState:
        return self._broker.account()

    def risk_state(self) -> RiskState:
        now = self._clock()
        day = self._trading_day(now)
        equity = self._account().equity
        start = float(self._state.set_value_if_absent(f"day_start_equity:{day}", repr(equity)))
        pnl = equity - start
        return RiskState(
            kill_switch=self.kill_switch,
            daily_loss_limit_pct=self._loss_limit,
            day=day,
            day_start_equity=start,
            equity=equity,
            day_pnl=pnl,
            loss_limit_breached=pnl <= -self._loss_limit * start,
            market_open=self._calendar.is_open(now),
            enforce_market_hours=self._enforce_hours,
        )

    # -- orders --------------------------------------------------------------------

    def _finish(self, order: PaperOrder) -> PaperOrder:
        self._state.update(order)
        log.info(
            "order decision",
            extra={
                "client_order_id": order.client_order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "qty": order.qty,
                "status": order.status.value,
                "reason": order.reject_reason,
                "broker": order.broker,
            },
        )
        if self._on_order is not None:
            self._on_order(order)
        return order

    def _transition(
        self, order: PaperOrder, status: OrderStatus, note: str = "", **changes: object
    ) -> PaperOrder:
        if order.status.is_terminal:
            return order
        history = [*order.history, OrderStatusChange(status=status, at=self._clock(), note=note)]
        data = order.model_dump()
        data.update(changes)
        data.update(status=status, history=history)
        return PaperOrder.model_validate(data)

    def submit_signal(self, signal: TradingSignal) -> PaperOrder:
        """Turn a signal into at most one paper order. Safe to call repeatedly."""
        with self._lock:
            return self._submit_signal(signal)

    def _submit_signal(self, signal: TradingSignal) -> PaperOrder:
        existing = self._state.get(signal.signal_id)
        if existing is not None:
            log.info(
                "duplicate signal ignored",
                extra={"signal_id": signal.signal_id, "status": existing.status.value},
            )
            return existing

        now = self._clock()
        side = OrderSide.SELL if signal.action is SignalAction.SELL else OrderSide.BUY
        price = self._price_source(signal.symbol)
        equity = self._account().equity
        qty = (
            round(signal.target_weight * equity / price, 4)
            if price and price > 0 and signal.target_weight > 0
            else 0.0
        )
        created = OrderStatusChange(status=OrderStatus.PENDING, at=now, note="created")
        block = self._block_reason(signal, qty, price)
        order = PaperOrder(
            order_id=f"ord_{uuid.uuid4().hex[:16]}",
            client_order_id=signal.signal_id,
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            side=side,
            qty=max(qty, 0.0),
            status=OrderStatus.PENDING if block is None else OrderStatus.BLOCKED,
            broker=self._broker.name,
            created_at=now,
            reject_reason=block,
            history=[created]
            if block is None
            else [created, OrderStatusChange(status=OrderStatus.BLOCKED, at=now, note=block)],
        )
        # The unique key makes this the single point where a signal becomes an order.
        if not self._state.insert_new(order):
            stored = self._state.get(signal.signal_id)
            assert stored is not None
            return stored
        if block is not None:
            return self._finish(order)
        return self._finish(self._submit(order))

    def _block_reason(self, signal: TradingSignal, qty: float, price: float | None) -> str | None:
        if signal.action is SignalAction.NO_TRADE:
            return f"signal is no_trade: {signal.reason}"
        if self.kill_switch:
            return "kill switch is on"
        risk = self.risk_state()
        if self._enforce_hours and not risk.market_open:
            return "market is closed"
        if risk.loss_limit_breached:
            return (
                f"daily loss limit reached ({risk.day_pnl:.2f} on {risk.day}, "
                f"limit {self._loss_limit:.2%})"
            )
        if price is None or price <= 0:
            return f"no price available for {signal.symbol}"
        if qty <= 0:
            return "order size is zero"
        return None

    def _submit(self, order: PaperOrder) -> PaperOrder:
        last_error = "unknown error"
        for attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
            try:
                if attempt > 1:
                    # A failed attempt may still have reached the broker. Ask before resending.
                    arrived = self._broker.get_order(order.client_order_id)
                    if arrived is not None:
                        return self._apply(order, arrived, f"found at broker on attempt {attempt}")
                result = self._broker.submit(
                    order.client_order_id, order.symbol, order.side, order.qty
                )
                return self._apply(order, result, f"submitted on attempt {attempt}")
            except BrokerRejection as exc:
                reason = f"broker rejected: {exc}"
                return self._transition(order, OrderStatus.REJECTED, reason, reject_reason=reason)
            except BrokerError as exc:
                last_error = str(exc)
                log.warning(
                    "order submission failed",
                    extra={
                        "client_order_id": order.client_order_id,
                        "attempt": attempt,
                        "error": last_error,
                    },
                )
        reason = f"broker unreachable after {MAX_SUBMIT_ATTEMPTS} attempts: {last_error}"
        return self._transition(order, OrderStatus.REJECTED, reason, reject_reason=reason)

    def _apply(self, order: PaperOrder, result: BrokerOrder, note: str) -> PaperOrder:
        submitted_at = order.submitted_at or self._clock()
        if result.status is OrderStatus.FILLED:
            staged = (
                self._transition(order, OrderStatus.SUBMITTED, note, submitted_at=submitted_at)
                if order.status is OrderStatus.PENDING
                else order
            )
            return self._transition(
                staged,
                OrderStatus.FILLED,
                "filled",
                filled_price=result.filled_price,
                filled_at=result.filled_at or self._clock(),
            )
        if result.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
            reason = result.reason or f"broker reported {result.status.value}"
            return self._transition(
                order, result.status, reason, reject_reason=reason, submitted_at=submitted_at
            )
        if order.status is OrderStatus.PENDING:
            return self._transition(order, OrderStatus.SUBMITTED, note, submitted_at=submitted_at)
        return order

    # -- views and reconciliation --------------------------------------------------

    def orders(self) -> list[PaperOrder]:
        return self._state.list()

    def positions(self) -> list[Position]:
        return self._broker.positions()

    def portfolio(self) -> Portfolio:
        account = self._account()
        positions = self._broker.positions()
        risk = self.risk_state()
        gross = sum(
            abs(p.market_value if p.market_value is not None else p.qty * p.avg_price)
            for p in positions
        )
        return Portfolio(
            broker=self._broker.name,
            cash=account.cash,
            equity=account.equity,
            day_pnl=risk.day_pnl,
            gross_exposure=gross / account.equity if account.equity > 0 else 0.0,
            positions=positions,
        )

    def reconcile(self) -> ReconcileReport:
        """Bring open orders up to date and compare positions with the broker's."""
        checked = updated = 0
        for order in self._state.list():
            if order.status.is_terminal:
                continue
            checked += 1
            try:
                result = self._broker.get_order(order.client_order_id)
            except BrokerError:
                continue
            if result is None:
                continue
            refreshed = self._apply(order, result, "reconciled")
            if refreshed.status is not order.status:
                self._finish(refreshed)
                updated += 1

        expected: dict[str, float] = {}
        for order in self._state.list():
            if order.status is OrderStatus.FILLED:
                signed = order.qty if order.side is OrderSide.BUY else -order.qty
                expected[order.symbol] = expected.get(order.symbol, 0.0) + signed
        actual = {p.symbol: p.qty for p in self._broker.positions()}
        mismatches = {
            symbol: {"expected": expected.get(symbol, 0.0), "broker": actual.get(symbol, 0.0)}
            for symbol in sorted(set(expected) | set(actual))
            if abs(expected.get(symbol, 0.0) - actual.get(symbol, 0.0)) > 1e-6
        }
        report = ReconcileReport(
            orders_checked=checked, orders_updated=updated, position_mismatches=mismatches
        )
        if mismatches:
            log.error("position mismatch", extra={"mismatches": mismatches})
        return report
