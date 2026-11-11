"""Event study, backtests, models, predictions, and signals."""

from __future__ import annotations

from datetime import datetime

import polars as pl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.deps import Limit, Offset, ServicesDep, page
from src.backtesting.event_study import (
    EventStudyReport,
    latest_event_study,
    study_from_store,
)
from src.backtesting.runner import load_backtest, load_backtests, run_backtest
from src.contracts import (
    BacktestMetrics,
    BacktestResult,
    DataQuality,
    EventWindow,
    ModelPrediction,
    StrategyName,
    TradingSignal,
)
from src.core.storage import from_frame, read_parquet
from src.ml.baseline import load_reports
from src.ml.evaluation import ModelReport
from src.ml.inference import ModelUnavailable, ModelVersionMismatch
from src.strategies import StrategyConfig

router = APIRouter(prefix="/api/v1", tags=["research"])


class BacktestSummary(BaseModel):
    run_id: str
    strategy: StrategyName
    created_at: datetime
    period_start: datetime
    period_end: datetime
    metrics: BacktestMetrics
    benchmark_symbol: str
    benchmark_metrics: BacktestMetrics | None
    signal_count: int
    no_trade_count: int
    data_quality: DataQuality


class BacktestRequest(BaseModel):
    strategy: StrategyName
    config: StrategyConfig | None = None
    cost_bps: float | None = None
    slippage_bps: float | None = None


class PredictRequest(BaseModel):
    text: str
    symbols: list[str] | None = None
    model_version: str | None = None


# -- event study -----------------------------------------------------------------------


@router.get("/research/event-study", response_model=EventStudyReport)
def get_event_study(services: ServicesDep) -> EventStudyReport:
    report = latest_event_study(services.paths)
    if report is None:
        raise HTTPException(status_code=404, detail="no event study has been run yet")
    return report


@router.post("/research/event-study/run", response_model=EventStudyReport)
def run_event_study_endpoint(
    services: ServicesDep, windows: list[EventWindow] | None = None
) -> EventStudyReport:
    return study_from_store(
        services.paths,
        services.settings,
        services.candle_store(),
        services.universe.benchmark,
        windows,
    )


# -- backtests -------------------------------------------------------------------------


def _summary(result: BacktestResult) -> BacktestSummary:
    return BacktestSummary(**result.model_dump(include=set(BacktestSummary.model_fields)))


@router.get("/backtests", response_model=list[BacktestSummary])
def list_backtests(services: ServicesDep) -> list[BacktestSummary]:
    return [_summary(r) for r in reversed(load_backtests(services.paths))]


@router.get("/backtests/{run_id}", response_model=BacktestResult)
def get_backtest(run_id: str, services: ServicesDep) -> BacktestResult:
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=404, detail="backtest not found")
    result = load_backtest(services.paths, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"backtest {run_id} not found")
    return result


@router.post("/backtests/run", response_model=BacktestResult)
def run_backtest_endpoint(request: BacktestRequest, services: ServicesDep) -> BacktestResult:
    return run_backtest(
        services.paths,
        services.settings,
        services.universe,
        services.calendar,
        request.strategy,
        request.config,
        request.cost_bps,
        request.slippage_bps,
    )


# -- models ----------------------------------------------------------------------------


@router.get("/models", response_model=list[ModelReport])
def list_models(services: ServicesDep) -> list[ModelReport]:
    return list(reversed(load_reports(services.paths)))


@router.post("/models/predict", response_model=list[ModelPrediction])
def predict(request: PredictRequest, services: ServicesDep) -> list[ModelPrediction]:
    try:
        return services.inference.predict_text(request.text, request.symbols, request.model_version)
    except (ModelUnavailable, ModelVersionMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/predictions", response_model=list[ModelPrediction])
def list_predictions(
    services: ServicesDep,
    limit: Limit = 100,
    offset: Offset = 0,
    event_id: str | None = None,
    symbol: str | None = None,
) -> list[ModelPrediction]:
    frame = read_parquet(services.paths.gold_predictions, ModelPrediction)
    if event_id:
        frame = frame.filter(pl.col("event_id") == event_id)
    if symbol:
        frame = frame.filter(pl.col("symbol") == symbol.upper())
    frame = frame.sort("predicted_at", descending=True)
    return from_frame(page(frame, limit, offset), ModelPrediction)


@router.get("/signals", response_model=list[TradingSignal])
def list_signals(
    services: ServicesDep,
    limit: Limit = 100,
    offset: Offset = 0,
    strategy: StrategyName | None = None,
    trades_only: bool = False,
) -> list[TradingSignal]:
    frame = read_parquet(services.paths.gold_signals, TradingSignal)
    if strategy is not None:
        frame = frame.filter(pl.col("strategy") == strategy.value)
    if trades_only:
        frame = frame.filter(pl.col("action") != "no_trade")
    frame = frame.sort("generated_at", descending=True)
    return from_frame(page(frame, limit, offset), TradingSignal)
