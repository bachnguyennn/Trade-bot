"""API behaviour on an empty store and on a populated store."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.core.storage import DataPaths
from tests.helpers import save_synthetic_model

LIST_ENDPOINTS = [
    "/api/v1/posts",
    "/api/v1/events",
    "/api/v1/market/features",
    "/api/v1/backtests",
    "/api/v1/models",
    "/api/v1/predictions",
    "/api/v1/signals",
    "/api/v1/trading/orders",
    "/api/v1/trading/positions",
]


def test_health_is_independent_of_data(empty_client: TestClient) -> None:
    assert empty_client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
def test_empty_store_returns_empty_lists(empty_client: TestClient, path: str) -> None:
    response = empty_client.get(path)
    assert response.status_code == 200
    assert response.json() == []


def test_empty_store_is_not_ready_and_has_no_invented_numbers(empty_client: TestClient) -> None:
    ready = empty_client.get("/ready").json()
    assert ready["ready"] is False
    assert not ready["checks"]["posts"]["ok"] and not ready["checks"]["candles"]["ok"]

    status = empty_client.get("/api/v1/status").json()
    assert status["posts"] == 0 and status["events"] == 0 and status["candles"] == 0
    assert status["latest_post_at"] is None and status["market_data_quality"] is None
    assert status["model_version"] is None
    assert status["paper_trading_only"] is True and status["broker"] == "simulator"

    assert empty_client.get("/api/v1/research/event-study").status_code == 404
    assert empty_client.get("/api/v1/market/candles", params={"symbol": "SPY"}).json() == []
    assert empty_client.get("/api/v1/events/evt_missing").status_code == 404
    assert empty_client.get("/api/v1/backtests/bt_missing").status_code == 404

    portfolio = empty_client.get("/api/v1/trading/portfolio").json()
    assert portfolio["positions"] == [] and portfolio["equity"] == portfolio["cash"]


def test_predict_without_a_model_is_a_conflict(empty_client: TestClient) -> None:
    response = empty_client.post("/api/v1/models/predict", json={"text": "tariffs on steel"})
    assert response.status_code == 409
    assert "no trained model" in response.json()["detail"]


def test_validation_errors(empty_client: TestClient) -> None:
    assert empty_client.get("/api/v1/posts", params={"limit": 0}).status_code == 422
    assert empty_client.get("/api/v1/posts", params={"limit": 501}).status_code == 422
    assert empty_client.get("/api/v1/events", params={"category": "nonsense"}).status_code == 422
    assert empty_client.get("/api/v1/market/candles", params={"symbol": "NOPE"}).status_code == 404
    assert empty_client.get("/api/v1/backtests/..%2F..%2Fsecret").status_code == 404
    bad_signal = empty_client.post("/api/v1/trading/orders", json={"symbol": "SPY"})
    assert bad_signal.status_code == 422


def test_unverified_source_is_forbidden(empty_client: TestClient) -> None:
    response = empty_client.post("/api/v1/ingest/run", json={"source": "cnn"})
    assert response.status_code == 403
    assert "unverified" in response.json()["detail"]


def test_posts_and_events(populated_client: TestClient) -> None:
    posts = populated_client.get("/api/v1/posts").json()
    assert len(posts) == 7
    assert [p["published_at"] for p in posts] == sorted(
        (p["published_at"] for p in posts), reverse=True
    )
    assert all(p["published_at"].endswith("Z") and p["retrieved_at"].endswith("Z") for p in posts)
    assert len(populated_client.get("/api/v1/posts", params={"q": "TARIFF"}).json()) == 2
    assert len(populated_client.get("/api/v1/posts", params={"limit": 2, "offset": 6}).json()) == 1

    events = populated_client.get("/api/v1/events").json()
    assert len(events) == 3
    tariffs = populated_client.get("/api/v1/events", params={"category": "tariffs_trade"}).json()
    assert len(tariffs) == 1 and len(tariffs[0]["post_ids"]) == 2
    assert (
        populated_client.get("/api/v1/events", params={"symbol": "nvda"}).json()[0]["event_id"]
        == events[0]["event_id"]
    )

    detail = populated_client.get(f"/api/v1/events/{tariffs[0]['event_id']}").json()
    assert len(detail["posts"]) == 2
    assert {f["window"] for f in detail["features"]} >= {"1d", "close_to_close", "5m"}
    assert detail["predictions"] == []


def test_market_endpoints(populated_client: TestClient) -> None:
    universe = populated_client.get("/api/v1/universe").json()
    assert any(m["symbol"] == "SPY" for m in universe)
    candles = populated_client.get(
        "/api/v1/market/candles", params={"symbol": "nue", "interval": "1d", "limit": 3}
    ).json()
    assert len(candles) == 3 and candles[0]["ts"] < candles[-1]["ts"]
    assert {c["quality"] for c in candles} == {"synthetic"}  # labelled, never passed off as real
    features = populated_client.get(
        "/api/v1/market/features", params={"window": "1d", "available_only": True}
    ).json()
    assert features and all(f["available"] and f["window"] == "1d" for f in features)


def test_research_endpoints(populated_client: TestClient) -> None:
    study = populated_client.get("/api/v1/research/event-study").json()
    assert study["events_total"] == 3 and study["caveats"]
    rerun = populated_client.post("/api/v1/research/event-study/run").json()
    assert rerun["content_hash"] == study["content_hash"]

    backtests = populated_client.get("/api/v1/backtests").json()
    assert {b["strategy"] for b in backtests} == {"momentum_continuation", "mean_reversion"}
    full = populated_client.get(f"/api/v1/backtests/{backtests[0]['run_id']}").json()
    assert full["assumptions"] and "equity_curve" in full
    for trade in full["trades"]:
        assert trade["entry_ts"] >= trade["signal_ts"]

    run = populated_client.post(
        "/api/v1/backtests/run", json={"strategy": "momentum_continuation", "cost_bps": 0}
    ).json()
    assert run["config"]["execution"]["cost_bps"] == 0
    signals = populated_client.get(
        "/api/v1/signals", params={"strategy": "momentum_continuation"}
    ).json()
    assert signals and all(s["strategy"] == "momentum_continuation" for s in signals)


def test_model_endpoints(populated_client: TestClient, paths: DataPaths) -> None:
    version = save_synthetic_model(paths)
    models = populated_client.get("/api/v1/models").json()
    assert models[0]["model_version"] == version
    assert set(models[0]["splits"]) == {"train", "validation", "test"}
    assert "majority_class_accuracy" in models[0]["baselines"]

    prediction = populated_client.post(
        "/api/v1/models/predict", json={"text": "steel tariffs boom", "symbols": ["NUE"]}
    ).json()
    assert prediction[0]["model_version"] == version and prediction[0]["direction"] == "up"
    mismatch = populated_client.post(
        "/api/v1/models/predict",
        json={"text": "steel", "symbols": ["NUE"], "model_version": "other"},
    )
    assert mismatch.status_code == 409 and "requested model version" in mismatch.json()["detail"]
    assert populated_client.get("/api/v1/status").json()["model_version"] == version


def test_stream_sends_status_on_connect(populated_client: TestClient) -> None:
    with populated_client.websocket_connect("/api/v1/stream") as socket:
        message = socket.receive_json()
    assert message["type"] == "status" and message["data"]["posts"] == 7
    assert message["ts"]
