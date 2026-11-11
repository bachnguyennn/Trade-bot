from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from src.contracts import OrderSide, OrderStatus
from src.trading.alpaca_paper import PAPER_BASE_URL, AlpacaPaperBroker, LiveTradingForbidden
from src.trading.broker import BrokerError, BrokerRejection, SimulatedBroker

NOW = datetime(2025, 3, 3, 15, 0, tzinfo=UTC)
PRICES = {"AAA": 100.0, "BBB": 50.0}


def simulator(slippage_bps: float = 0.0) -> SimulatedBroker:
    return SimulatedBroker(10_000.0, PRICES.get, slippage_bps, clock=lambda: NOW)


def test_simulator_fills_and_tracks_cash_and_positions() -> None:
    broker = simulator()
    order = broker.submit("c1", "AAA", OrderSide.BUY, 10)
    assert order.status is OrderStatus.FILLED and order.filled_price == 100.0
    assert order.filled_at == NOW
    assert broker.account().cash == pytest.approx(9_000.0)
    assert broker.account().equity == pytest.approx(10_000.0)
    [position] = broker.positions()
    assert (position.symbol, position.qty, position.avg_price) == ("AAA", 10, 100.0)


def test_simulator_is_idempotent_on_client_order_id() -> None:
    broker = simulator()
    first = broker.submit("c1", "AAA", OrderSide.BUY, 10)
    second = broker.submit("c1", "AAA", OrderSide.BUY, 10)
    assert first == second
    assert broker.positions()[0].qty == 10
    assert broker.get_order("c1") == first and broker.get_order("nope") is None


def test_simulator_slippage_works_against_the_trader() -> None:
    broker = simulator(slippage_bps=10)
    buy = broker.submit("c1", "AAA", OrderSide.BUY, 1)
    sell = broker.submit("c2", "AAA", OrderSide.SELL, 1)
    assert buy.filled_price == pytest.approx(100.1)
    assert sell.filled_price == pytest.approx(99.9)
    assert broker.account().cash == pytest.approx(10_000 - 0.2)
    assert broker.positions() == []


def test_simulator_short_and_cross_through_zero() -> None:
    broker = simulator()
    broker.submit("c1", "AAA", OrderSide.SELL, 5)
    assert broker.positions()[0].qty == -5
    broker.submit("c2", "AAA", OrderSide.BUY, 8)
    [position] = broker.positions()
    assert position.qty == 3 and position.avg_price == 100.0


def test_simulator_rejects_unknown_symbol_and_bad_quantity() -> None:
    broker = simulator()
    with pytest.raises(BrokerRejection, match="no price available"):
        broker.submit("c1", "ZZZ", OrderSide.BUY, 1)
    with pytest.raises(BrokerRejection, match="positive"):
        broker.submit("c2", "AAA", OrderSide.BUY, 0)
    assert broker.account().cash == 10_000.0


def test_simulator_restore_rebuilds_state() -> None:
    first = simulator()
    orders = [
        first.submit("c1", "AAA", OrderSide.BUY, 10),
        first.submit("c2", "BBB", OrderSide.SELL, 4),
    ]
    second = simulator()
    second.restore(orders)
    second.restore(orders)  # restoring twice changes nothing
    assert second.account() == first.account()
    assert second.positions() == first.positions()


@pytest.mark.parametrize(
    "url",
    [
        "https://api.alpaca.markets",
        "https://api.alpaca.markets/",
        "http://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets.evil.example",
        "https://example.com",
        "",
    ],
)
def test_paper_adapter_refuses_every_other_endpoint(url: str) -> None:
    with pytest.raises(LiveTradingForbidden):
        AlpacaPaperBroker("k", "s", base_url=url)


def test_paper_adapter_requires_keys() -> None:
    with pytest.raises(BrokerError):
        AlpacaPaperBroker("", "")


def paper(handler: object) -> AlpacaPaperBroker:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return AlpacaPaperBroker("k", "s", client=client)


ORDER_JSON = {
    "id": "b-1",
    "client_order_id": "c1",
    "symbol": "AAA",
    "side": "buy",
    "qty": "10",
    "status": "filled",
    "filled_avg_price": "100.5",
    "filled_at": "2025-03-03T15:00:01Z",
}


def test_paper_adapter_submits_only_to_the_paper_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ORDER_JSON)

    order = paper(handler).submit("c1", "AAA", OrderSide.BUY, 10)
    assert order.status is OrderStatus.FILLED and order.filled_price == 100.5
    assert order.filled_at == datetime(2025, 3, 3, 15, 0, 1, tzinfo=UTC)
    assert [r.url.host for r in seen] == ["paper-api.alpaca.markets"]
    assert str(seen[0].url).startswith(PAPER_BASE_URL)
    assert seen[0].headers["APCA-API-KEY-ID"] == "k"


def test_paper_adapter_maps_errors() -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(BrokerError):
        paper(unavailable).submit("c1", "AAA", OrderSide.BUY, 10)

    def rejected(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(403, json={"message": "insufficient buying power"})
        return httpx.Response(404)

    with pytest.raises(BrokerRejection, match="insufficient buying power"):
        paper(rejected).submit("c1", "AAA", OrderSide.BUY, 10)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(BrokerError, match="unreachable"):
        paper(down).get_order("c1")


def test_paper_adapter_duplicate_returns_existing_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(422, json={"message": "client_order_id must be unique"})
        return httpx.Response(200, json=ORDER_JSON)

    order = paper(handler).submit("c1", "AAA", OrderSide.BUY, 10)
    assert order.broker_order_id == "b-1"


def test_paper_adapter_reads_account_and_positions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/account":
            return httpx.Response(200, json={"cash": "9000", "equity": "10050"})
        return httpx.Response(
            200,
            json=[{"symbol": "AAA", "qty": "10", "avg_entry_price": "100", "market_value": "1050"}],
        )

    broker = paper(handler)
    assert broker.account().equity == 10_050.0
    assert broker.positions()[0].market_value == 1_050.0
