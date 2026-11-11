"""Paper trading. No route here can reach a real-money account."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.deps import ServicesDep
from src.contracts import PaperOrder, TradingSignal
from src.trading.broker import BrokerError, Position
from src.trading.service import Portfolio, ReconcileReport, RiskState

router = APIRouter(prefix="/api/v1/trading", tags=["trading"])


class KillSwitchRequest(BaseModel):
    enabled: bool


@router.get("/orders", response_model=list[PaperOrder])
def list_orders(services: ServicesDep) -> list[PaperOrder]:
    return list(reversed(services.orders.orders()))


@router.post("/orders", response_model=PaperOrder)
def submit_order(signal: TradingSignal, services: ServicesDep) -> PaperOrder:
    """Submit a signal. The result may be `blocked` or `rejected`, with the reason."""
    return services.orders.submit_signal(signal)


@router.get("/positions", response_model=list[Position])
def positions(services: ServicesDep) -> list[Position]:
    try:
        return services.orders.positions()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/portfolio", response_model=Portfolio)
def portfolio(services: ServicesDep) -> Portfolio:
    try:
        return services.orders.portfolio()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/risk", response_model=RiskState)
def risk(services: ServicesDep) -> RiskState:
    try:
        return services.orders.risk_state()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/kill-switch", response_model=RiskState)
def kill_switch(request: KillSwitchRequest, services: ServicesDep) -> RiskState:
    state = services.orders.set_kill_switch(request.enabled)
    services.broadcaster.publish("status", {"kill_switch": state.kill_switch})
    return state


@router.post("/reconcile", response_model=ReconcileReport)
def reconcile(services: ServicesDep) -> ReconcileReport:
    return services.orders.reconcile()
