"""Health, readiness, and status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from src.api.deps import ServicesDep

router = APIRouter(tags=["system"])


class Check(BaseModel):
    ok: bool
    detail: str


class Readiness(BaseModel):
    ready: bool
    checks: dict[str, Check]


@router.get("/health")
def health() -> dict[str, str]:
    """The process is up. Says nothing about whether data is loaded."""
    return {"status": "ok"}


@router.get("/ready", response_model=Readiness)
def ready(services: ServicesDep) -> Readiness:
    """Whether the platform has the data it needs to show research results."""
    status = services.status()
    checks = {
        "posts": Check(ok=status["posts"] > 0, detail=f"{status['posts']} posts stored"),
        "candles": Check(ok=status["candles"] > 0, detail=f"{status['candles']} candles stored"),
        "events": Check(ok=status["events"] > 0, detail=f"{status['events']} events built"),
        "model": Check(
            ok=status["model_version"] is not None,
            detail=status["model_version"] or "no trained model",
        ),
    }
    required = ("posts", "candles")
    return Readiness(ready=all(checks[name].ok for name in required), checks=checks)


@router.get("/api/v1/status")
def status(services: ServicesDep) -> dict[str, Any]:
    return services.status()
