"""Shared dependencies and small helpers for the routes."""

from __future__ import annotations

from typing import Annotated

import polars as pl
from fastapi import Depends, Query, Request

from src.api.services import Services


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


def page(frame: pl.DataFrame, limit: int, offset: int) -> pl.DataFrame:
    return frame.slice(offset, limit)
