"""Signal to reconciled paper order through the API, and the live processing cycle."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.contracts import IngestionMode
from src.core.settings import Settings
from src.core.storage import DataPaths
from src.core.timeutils import utc_now
from src.ingestion.sources import ArchiveFileSource
from src.market_data.calendar import TradingCalendar
from src.pipelines.live import run_live_cycle
from tests.helpers import save_synthetic_model

SIGNAL = {
    "signal_id": "sig_api_1",
    "event_id": "evt_test",
    "symbol": "NUE",
    "strategy": "immediate_reaction",
    "action": "buy",
    "generated_at": "2025-03-03T15:00:00Z",
    "target_weight": 0.05,
    "holding_window": "1d",
    "stop_loss_pct": 0.03,
    "reason": "integration test",
}


def test_signal_becomes_one_reconciled_order(populated_client: TestClient) -> None:
    client = populated_client
    order = client.post("/api/v1/trading/orders", json=SIGNAL).json()
    assert order["status"] == "filled" and order["broker"] == "simulator"
    assert order["client_order_id"] == "sig_api_1"
    price = order["filled_price"]
    assert order["qty"] * price / 100_000 == 0.05 or abs(order["qty"] * price - 5_000) < 5

    # The same signal again returns the same order and changes nothing.
    again = client.post("/api/v1/trading/orders", json=SIGNAL).json()
    assert again["order_id"] == order["order_id"]
    assert len(client.get("/api/v1/trading/orders").json()) == 1

    positions = client.get("/api/v1/trading/positions").json()
    assert [(p["symbol"], p["qty"]) for p in positions] == [("NUE", order["qty"])]
    portfolio = client.get("/api/v1/trading/portfolio").json()
    assert 0.049 < portfolio["gross_exposure"] < 0.051
    reconcile = client.post("/api/v1/trading/reconcile").json()
    assert reconcile["position_mismatches"] == {}


def test_kill_switch_stops_new_orders_through_the_api(populated_client: TestClient) -> None:
    client = populated_client
    state = client.post("/api/v1/trading/kill-switch", json={"enabled": True}).json()
    assert state["kill_switch"] is True
    for index in range(3):
        order = client.post(
            "/api/v1/trading/orders", json={**SIGNAL, "signal_id": f"sig_blocked_{index}"}
        ).json()
        assert order["status"] == "blocked" and order["reject_reason"] == "kill switch is on"
    assert client.get("/api/v1/trading/positions").json() == []
    assert client.get("/api/v1/status").json()["kill_switch"] is True

    client.post("/api/v1/trading/kill-switch", json={"enabled": False})
    released = client.post(
        "/api/v1/trading/orders", json={**SIGNAL, "signal_id": "sig_after"}
    ).json()
    assert released["status"] == "filled"


def test_orders_outside_market_hours_are_blocked(
    posts_fixture: Path, paths: DataPaths, settings: Settings, api_calendar: TradingCalendar
) -> None:
    from tests.integration.conftest import populate

    populate(posts_fixture, paths, settings, api_calendar)
    # The synthetic calendar has no session today, so the market is closed right now.
    with TestClient(create_app(settings, api_calendar)) as client:
        order = client.post("/api/v1/trading/orders", json=SIGNAL).json()
    assert order["status"] == "blocked" and order["reject_reason"] == "market is closed"


def test_orders_survive_an_api_restart(
    posts_fixture: Path, paths: DataPaths, open_settings: Settings, api_calendar: TradingCalendar
) -> None:
    from tests.integration.conftest import populate

    populate(posts_fixture, paths, open_settings, api_calendar)
    with TestClient(create_app(open_settings, api_calendar)) as client:
        first = client.post("/api/v1/trading/orders", json=SIGNAL).json()
    with TestClient(create_app(open_settings, api_calendar)) as client:
        assert (
            client.post("/api/v1/trading/orders", json=SIGNAL).json()["order_id"]
            == (first["order_id"])
        )
        positions = client.get("/api/v1/trading/positions").json()
        assert [(p["symbol"], p["qty"]) for p in positions] == [("NUE", first["qty"])]
        assert client.post("/api/v1/trading/reconcile").json()["position_mismatches"] == {}


def no_real_money_route_exists(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    text = json.dumps(schema).lower()
    assert "live" not in [p.split("/")[-1] for p in schema["paths"]]
    assert "base_url" not in text and "api.alpaca.markets" not in text


def test_no_endpoint_accepts_a_broker_url(empty_client: TestClient) -> None:
    no_real_money_route_exists(empty_client)


def fresh_archive(source: Path, target: Path, post_id: str, text: str, age_minutes: float) -> Path:
    records = json.loads(source.read_text(encoding="utf-8"))
    records.append(
        {
            "id": post_id,
            "created_at": (utc_now() - timedelta(minutes=age_minutes)).isoformat(),
            "content": f"<p>{text}</p>",
            "media": [],
        }
    )
    target.write_text(json.dumps(records), encoding="utf-8")
    return target


async def test_live_cycle_from_new_post_to_paper_order(
    posts_fixture: Path,
    paths: DataPaths,
    open_settings: Settings,
    api_calendar: TradingCalendar,
    tmp_path: Path,
) -> None:
    import asyncio

    from tests.integration.conftest import populate

    await asyncio.to_thread(populate, posts_fixture, paths, open_settings, api_calendar)
    version = save_synthetic_model(paths)
    app = create_app(open_settings, api_calendar)
    services = app.state.services
    published: list[tuple[str, object]] = []

    def publish(kind: str, data: object) -> None:
        published.append((kind, data))

    async def cycle(archive: Path):  # type: ignore[no-untyped-def]
        return await run_live_cycle(
            ArchiveFileSource(archive),
            paths,
            open_settings,
            services.universe,
            services.inference,
            services.orders,
            publish,
        )

    # 1. A fresh post about tariffs arrives.
    archive = fresh_archive(
        posts_fixture,
        tmp_path / "live1.json",
        "900000000000000101",
        "SYNTHETIC TEST FIXTURE. New tariffs on China steel boom today.",
        2,
    )
    report = await cycle(archive)
    assert report.ingest.posts_new == 1 and report.new_events == 1
    assert report.model_version == version
    assert report.predictions > 0 and report.trade_signals > 0
    assert report.orders.get("filled", 0) == report.trade_signals
    assert {kind for kind, _ in published} == {"event", "prediction", "signal"}
    assert services.orders.reconcile().consistent
    filled = [o for o in services.orders.orders() if o.status.value == "filled"]
    assert filled and all(o.broker == "simulator" for o in filled)

    # 2. Running the same archive again changes nothing: no duplicate events or orders.
    orders_before = len(services.orders.orders())
    repeat = await cycle(archive)
    assert repeat.new_events == 0 and repeat.orders == {}
    assert len(services.orders.orders()) == orders_before

    # 3. With the kill switch on, a new post still produces signals but no order is placed.
    services.orders.set_kill_switch(True)
    archive2 = fresh_archive(
        archive,
        tmp_path / "live2.json",
        "900000000000000102",
        "SYNTHETIC TEST FIXTURE. Oil drilling boom, Exxon wins.",
        1,
    )
    blocked = await cycle(archive2)
    assert blocked.new_events == 1 and blocked.trade_signals > 0
    assert set(blocked.orders) == {"blocked"}
    services.orders.set_kill_switch(False)

    # 4. A post that is live-collected but already old is not traded.
    stale_archive = fresh_archive(
        archive2,
        tmp_path / "live3.json",
        "900000000000000103",
        "SYNTHETIC TEST FIXTURE. The Fed must cut interest rates, boom.",
        120,
    )
    stale = await cycle(stale_archive)
    assert stale.new_events == 1 and stale.trade_signals == 0 and stale.orders == {}
    services.close()


async def test_backfilled_events_are_never_traded(
    posts_fixture: Path,
    paths: DataPaths,
    open_settings: Settings,
    api_calendar: TradingCalendar,
) -> None:
    save_synthetic_model(paths)
    app = create_app(open_settings, api_calendar)
    services = app.state.services
    report = await run_live_cycle(
        ArchiveFileSource(posts_fixture),
        paths,
        open_settings,
        services.universe,
        services.inference,
        services.orders,
        mode=IngestionMode.LIVE,
    )
    # The fixture posts are from 2025: a live fetch that picks them up is backfill.
    assert report.new_events == 3 and report.signals > 0
    assert report.trade_signals == 0 and report.predictions == 0 and report.orders == {}
    assert services.orders.orders() == []
    services.close()
