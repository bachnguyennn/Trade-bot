"""Alpaca paper-trading adapter. It can only talk to the paper endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from src.contracts import BrokerName, OrderSide, OrderStatus
from src.trading.broker import (
    AccountState,
    BrokerError,
    BrokerOrder,
    BrokerRejection,
    Position,
)

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


class LiveTradingForbidden(RuntimeError):
    """Raised when anything other than the paper endpoint is requested."""


_STATUS_MAP = {
    "new": OrderStatus.SUBMITTED,
    "accepted": OrderStatus.SUBMITTED,
    "pending_new": OrderStatus.SUBMITTED,
    "accepted_for_bidding": OrderStatus.SUBMITTED,
    "partially_filled": OrderStatus.SUBMITTED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELLED,
    "expired": OrderStatus.CANCELLED,
    "done_for_day": OrderStatus.CANCELLED,
    "replaced": OrderStatus.CANCELLED,
    "rejected": OrderStatus.REJECTED,
    "suspended": OrderStatus.REJECTED,
    "stopped": OrderStatus.SUBMITTED,
    "pending_cancel": OrderStatus.SUBMITTED,
    "pending_replace": OrderStatus.SUBMITTED,
    "calculated": OrderStatus.SUBMITTED,
}


class AlpacaPaperBroker:
    """Paper orders through Alpaca.

    The base URL is checked in the constructor and is not a setting. Passing any other
    URL, including Alpaca's live endpoint, raises `LiveTradingForbidden`.
    """

    name: BrokerName = "alpaca-paper"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = PAPER_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        if base_url.rstrip("/") != PAPER_BASE_URL:
            raise LiveTradingForbidden(
                f"only {PAPER_BASE_URL} is allowed; refusing to use {base_url!r}"
            )
        if not api_key or not api_secret:
            raise BrokerError("Alpaca paper API keys are not set")
        self._base = PAPER_BASE_URL
        self._client = client or httpx.Client(timeout=30.0)
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(
                method, f"{self._base}{path}", headers=self._headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise BrokerError(f"broker unreachable: {exc!r}") from exc

    @staticmethod
    def _parse(payload: dict[str, Any]) -> BrokerOrder:
        status = _STATUS_MAP.get(str(payload.get("status")), OrderStatus.SUBMITTED)
        price = payload.get("filled_avg_price")
        filled_at = payload.get("filled_at")
        return BrokerOrder(
            client_order_id=str(payload["client_order_id"]),
            broker_order_id=str(payload["id"]),
            symbol=str(payload["symbol"]),
            side=OrderSide(str(payload["side"])),
            qty=float(payload.get("qty") or 0.0),
            status=status,
            filled_price=float(price) if price else None,
            filled_at=datetime.fromisoformat(filled_at.replace("Z", "+00:00"))
            if filled_at
            else None,
            reason=str(payload["status"]) if status is OrderStatus.REJECTED else None,
        )

    def submit(self, client_order_id: str, symbol: str, side: OrderSide, qty: float) -> BrokerOrder:
        response = self._request(
            "POST",
            "/v2/orders",
            json={
                "symbol": symbol,
                "qty": str(qty),
                "side": side.value,
                "type": "market",
                "time_in_force": "day",
                "client_order_id": client_order_id,
            },
        )
        if response.status_code in (200, 201):
            return self._parse(response.json())
        if response.status_code >= 500 or response.status_code == 429:
            raise BrokerError(f"broker error HTTP {response.status_code}")
        # A duplicate client order id means an earlier attempt got through.
        existing = self.get_order(client_order_id)
        if existing is not None:
            return existing
        raise BrokerRejection(f"HTTP {response.status_code}: {response.text[:200]}")

    def get_order(self, client_order_id: str) -> BrokerOrder | None:
        response = self._request(
            "GET", "/v2/orders:by_client_order_id", params={"client_order_id": client_order_id}
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise BrokerError(f"broker error HTTP {response.status_code}")
        return self._parse(response.json())

    def positions(self) -> list[Position]:
        response = self._request("GET", "/v2/positions")
        if response.status_code >= 400:
            raise BrokerError(f"broker error HTTP {response.status_code}")
        return [
            Position(
                symbol=str(p["symbol"]),
                qty=float(p["qty"]),
                avg_price=float(p["avg_entry_price"]),
                market_value=float(p["market_value"]) if p.get("market_value") else None,
            )
            for p in response.json()
        ]

    def account(self) -> AccountState:
        response = self._request("GET", "/v2/account")
        if response.status_code >= 400:
            raise BrokerError(f"broker error HTTP {response.status_code}")
        payload = response.json()
        return AccountState(cash=float(payload["cash"]), equity=float(payload["equity"]))
