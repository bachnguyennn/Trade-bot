"""The published OpenAPI schema must contain every documented path and shared contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.contracts import EventCategory, EventWindow, OrderStatus
from src.core.settings import Settings
from tests.helpers import make_calendar

DOCUMENTED_PATHS = {
    "/health": {"get"},
    "/ready": {"get"},
    "/api/v1/status": {"get"},
    "/api/v1/posts": {"get"},
    "/api/v1/events": {"get"},
    "/api/v1/events/{event_id}": {"get"},
    "/api/v1/ingest/run": {"post"},
    "/api/v1/universe": {"get"},
    "/api/v1/market/candles": {"get"},
    "/api/v1/market/features": {"get"},
    "/api/v1/research/event-study": {"get"},
    "/api/v1/research/event-study/run": {"post"},
    "/api/v1/backtests": {"get"},
    "/api/v1/backtests/{run_id}": {"get"},
    "/api/v1/backtests/run": {"post"},
    "/api/v1/models": {"get"},
    "/api/v1/models/predict": {"post"},
    "/api/v1/predictions": {"get"},
    "/api/v1/signals": {"get"},
    "/api/v1/trading/orders": {"get", "post"},
    "/api/v1/trading/positions": {"get"},
    "/api/v1/trading/portfolio": {"get"},
    "/api/v1/trading/risk": {"get"},
    "/api/v1/trading/kill-switch": {"post"},
    "/api/v1/trading/reconcile": {"post"},
}

SHARED_CONTRACTS = [
    "SocialPost",
    "MarketEvent",
    "StockCandle",
    "MarketFeature",
    "ModelPrediction",
    "TradingSignal",
    "BacktestResult",
    "PaperOrder",
]


def schema(settings: Settings) -> dict:  # type: ignore[type-arg]
    with TestClient(create_app(settings, make_calendar())) as client:
        return client.get("/openapi.json").json()  # type: ignore[no-any-return]


def test_every_documented_path_is_served(settings: Settings) -> None:
    paths = schema(settings)["paths"]
    for path, methods in DOCUMENTED_PATHS.items():
        assert path in paths, f"missing path {path}"
        assert methods <= set(paths[path]), f"{path} is missing {methods - set(paths[path])}"
    # Nothing undocumented has crept in.
    assert set(paths) == set(DOCUMENTED_PATHS)


def test_shared_contracts_are_in_the_schema(settings: Settings) -> None:
    components = schema(settings)["components"]["schemas"]
    for name in SHARED_CONTRACTS:
        assert name in components, f"missing contract {name}"
    assert set(components["EventCategory"]["enum"]) == {c.value for c in EventCategory}
    assert set(components["EventWindow"]["enum"]) == {w.value for w in EventWindow}
    assert set(components["OrderStatus"]["enum"]) == {s.value for s in OrderStatus}
    assert components["PaperOrder"]["properties"]["broker"]["enum"] == ["simulator", "alpaca-paper"]


def test_contract_fields_match_the_models(settings: Settings) -> None:
    from src import contracts

    components = schema(settings)["components"]["schemas"]
    for name in SHARED_CONTRACTS:
        model = getattr(contracts, name)
        assert set(components[name]["properties"]) == set(model.model_fields), name
