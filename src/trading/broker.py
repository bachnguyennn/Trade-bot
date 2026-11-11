"""Execution interface and the built-in simulator.

There are exactly two implementations of `ExecutionBroker`: `SimulatedBroker` here and
`AlpacaPaperBroker`, which only talks to the paper-trading endpoint. No live adapter
exists, so no configuration can route an order to a real-money account.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from src.contracts import BrokerName, OrderSide, OrderStatus
from src.core.timeutils import utc_now


class BrokerError(RuntimeError):
    """A transient failure: the broker could not be reached or did not answer."""


class BrokerRejection(RuntimeError):
    """The broker received the order and refused it."""


class BrokerOrder(BaseModel):
    """What a broker reports about one order."""

    client_order_id: str
    broker_order_id: str
    symbol: str
    side: OrderSide
    qty: float
    status: OrderStatus
    filled_price: float | None = None
    filled_at: datetime | None = None
    reason: str | None = None


class Position(BaseModel):
    symbol: str
    qty: float  # negative for a short position
    avg_price: float
    market_value: float | None = None


class AccountState(BaseModel):
    cash: float
    equity: float


class ExecutionBroker(Protocol):
    name: BrokerName

    def submit(self, client_order_id: str, symbol: str, side: OrderSide, qty: float) -> BrokerOrder:
        """Submit a market order. Must be idempotent on `client_order_id`."""
        ...

    def get_order(self, client_order_id: str) -> BrokerOrder | None: ...

    def positions(self) -> list[Position]: ...

    def account(self) -> AccountState: ...


PriceSource = Callable[[str], float | None]


class SimulatedBroker:
    """Fills market orders immediately at the latest known price, with slippage.

    Assumption: the fill price is the most recent stored close, moved against the trader
    by the slippage setting. It is a simulation of bookkeeping, not of market microstructure.
    """

    name: BrokerName = "simulator"

    def __init__(
        self,
        initial_cash: float,
        price_source: PriceSource,
        slippage_bps: float = 0.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._cash = initial_cash
        self._price_source = price_source
        self._slippage = slippage_bps / 10_000.0
        self._clock = clock
        self._orders: dict[str, BrokerOrder] = {}
        self._positions: dict[str, tuple[float, float]] = {}  # symbol -> (qty, avg_price)

    def submit(self, client_order_id: str, symbol: str, side: OrderSide, qty: float) -> BrokerOrder:
        existing = self._orders.get(client_order_id)
        if existing is not None:
            return existing
        if qty <= 0:
            raise BrokerRejection("quantity must be positive")
        price = self._price_source(symbol)
        if price is None or price <= 0:
            raise BrokerRejection(f"no price available for {symbol}")
        direction = 1.0 if side is OrderSide.BUY else -1.0
        fill_price = price * (1 + direction * self._slippage)
        order = BrokerOrder(
            client_order_id=client_order_id,
            broker_order_id=f"sim-{len(self._orders) + 1:06d}",
            symbol=symbol,
            side=side,
            qty=qty,
            status=OrderStatus.FILLED,
            filled_price=fill_price,
            filled_at=self._clock(),
        )
        self._apply_fill(symbol, direction * qty, fill_price)
        self._orders[client_order_id] = order
        return order

    def _apply_fill(self, symbol: str, signed_qty: float, price: float) -> None:
        self._cash -= signed_qty * price
        held, average = self._positions.get(symbol, (0.0, 0.0))
        new_qty = held + signed_qty
        if abs(new_qty) < 1e-9:
            self._positions.pop(symbol, None)
            return
        if held == 0 or (held > 0) == (signed_qty > 0):
            average = (held * average + signed_qty * price) / new_qty  # adding to a position
        elif (new_qty > 0) != (held > 0):
            average = price  # crossed through zero: the remainder was opened at this price
        self._positions[symbol] = (new_qty, average)

    def restore(self, orders: list[BrokerOrder]) -> None:
        """Rebuild cash and positions from previously filled orders, in fill order."""
        filled = [o for o in orders if o.status is OrderStatus.FILLED and o.filled_price]
        for order in sorted(filled, key=lambda o: (o.filled_at or utc_now(), o.client_order_id)):
            if order.client_order_id in self._orders:
                continue
            assert order.filled_price is not None
            direction = 1.0 if order.side is OrderSide.BUY else -1.0
            self._apply_fill(order.symbol, direction * order.qty, order.filled_price)
            self._orders[order.client_order_id] = order

    def get_order(self, client_order_id: str) -> BrokerOrder | None:
        return self._orders.get(client_order_id)

    def positions(self) -> list[Position]:
        out: list[Position] = []
        for symbol, (qty, average) in sorted(self._positions.items()):
            price = self._price_source(symbol)
            out.append(
                Position(
                    symbol=symbol,
                    qty=qty,
                    avg_price=average,
                    market_value=None if price is None else qty * price,
                )
            )
        return out

    def account(self) -> AccountState:
        # A position with no current price is valued at cost rather than guessed.
        value = sum(
            p.market_value if p.market_value is not None else p.qty * p.avg_price
            for p in self.positions()
        )
        return AccountState(cash=self._cash, equity=self._cash + value)
