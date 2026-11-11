"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import stream
from src.api.routers import events, market, research, system, trading
from src.api.services import Services
from src.core.logging import configure_logging
from src.core.settings import Settings, get_settings
from src.market_data.calendar import TradingCalendar

DESCRIPTION = (
    "Research and paper-trading API. Paper trading only: no endpoint can place a real-money "
    "order. Results are historical research, not investment advice."
)


def create_app(
    settings: Settings | None = None, calendar: TradingCalendar | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services.broadcaster.attach_loop(asyncio.get_running_loop())
        yield
        app.state.services.close()

    app = FastAPI(title="TradeBot API", version="0.1.0", description=DESCRIPTION, lifespan=lifespan)
    app.state.services = Services(settings, calendar)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(system.router)
    app.include_router(events.router)
    app.include_router(market.router)
    app.include_router(research.router)
    app.include_router(trading.router)
    app.include_router(stream.router)
    return app


def create_app_from_env() -> FastAPI:
    """Entry point for `uvicorn --factory`."""
    configure_logging("INFO")
    return create_app()
