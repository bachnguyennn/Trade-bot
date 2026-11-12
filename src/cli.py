"""`tradebot` command line. Each command prints a JSON summary to stdout and logs to stderr."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from src.contracts import EventWindow, IngestionMode, SocialPost, StrategyName
from src.core.logging import configure_logging
from src.core.settings import Settings, get_settings
from src.core.storage import DataPaths, read_parquet
from src.market_data.calendar import TradingCalendar, xnys_calendar
from src.market_data.universe import Universe, default_universe

app = typer.Typer(no_args_is_help=True, add_completion=False, help="TradeBot research pipeline.")
ingest_app = typer.Typer(no_args_is_help=True, help="Collect posts and market data.")
build_app = typer.Typer(no_args_is_help=True, help="Build derived tables.")
research_app = typer.Typer(no_args_is_help=True, help="Run research reports.")
model_app = typer.Typer(no_args_is_help=True, help="Train and use models.")
backtest_app = typer.Typer(no_args_is_help=True, help="Run strategy backtests.")
pipeline_app = typer.Typer(no_args_is_help=True, help="Run the whole pipeline.")
app.add_typer(ingest_app, name="ingest")
app.add_typer(build_app, name="build")
app.add_typer(research_app, name="research")
app.add_typer(model_app, name="model")
app.add_typer(backtest_app, name="backtest")
app.add_typer(pipeline_app, name="pipeline")


class Context:
    """Objects every command needs."""

    def __init__(self) -> None:
        self.settings: Settings = get_settings()
        self.paths = DataPaths(self.settings.data_dir)
        self.universe: Universe = default_universe(self.settings.benchmark_symbol)

    @property
    def calendar(self) -> TradingCalendar:
        return xnys_calendar()


def _emit(payload: BaseModel | dict[str, Any]) -> None:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    typer.echo(json.dumps(data, indent=2, default=str))


def _fail(message: str) -> None:
    typer.echo(json.dumps({"error": message}), err=True)
    raise typer.Exit(code=1)


@app.callback()
def main(log_level: Annotated[str, typer.Option(help="Log level.")] = "WARNING") -> None:
    configure_logging(log_level)


# -- ingest ----------------------------------------------------------------------------


@ingest_app.command("posts")
def ingest_posts_command(
    source: Annotated[str, typer.Option(help="stiles, cnn, or file")] = "stiles",
    path: Annotated[Path | None, typer.Option(help="Archive file for --source file")] = None,
    mode: Annotated[IngestionMode, typer.Option(help="historical or live")] = (
        IngestionMode.HISTORICAL
    ),
) -> None:
    """Import posts into Bronze and rebuild Silver. Safe to run repeatedly."""
    from src.ingestion.http import FetchError
    from src.ingestion.sources import SourceNotPermitted, build_source
    from src.pipelines.posts import ingest_posts

    ctx = Context()
    try:
        post_source = build_source(source, ctx.settings, path)
        report = asyncio.run(ingest_posts(post_source, mode, ctx.paths, ctx.settings))
    except (SourceNotPermitted, FetchError, ValueError, OSError) as exc:
        _fail(str(exc))
        return
    _emit(report)


@ingest_app.command("market")
def ingest_market_command(
    interval: Annotated[str, typer.Option(help="1d, 1h, 30m, 15m, 5m, or 1m")] = "1d",
    start: Annotated[datetime, typer.Option(formats=["%Y-%m-%d"])] = datetime(2022, 1, 1),  # noqa: DTZ001
    end: Annotated[datetime | None, typer.Option(formats=["%Y-%m-%d"])] = None,
    provider: Annotated[str | None, typer.Option(help="alpaca or yfinance")] = None,
) -> None:
    """Download candles for the universe and benchmark."""
    from src.market_data.providers import ProviderError, build_provider
    from src.market_data.store import CandleStore
    from src.pipelines.market import ingest_market

    ctx = Context()
    try:
        market_provider = build_provider(ctx.settings, ctx.calendar, provider)
    except ProviderError as exc:
        _fail(str(exc))
        return
    report = ingest_market(
        market_provider,
        CandleStore(ctx.paths),
        ctx.universe,
        interval,
        start.date(),
        end.date() if end else None,
    )
    _emit(report)


# -- build -----------------------------------------------------------------------------


@build_app.command("events")
def build_events_command(
    include_reposts: Annotated[bool, typer.Option(help="Treat reposts as events too.")] = False,
) -> None:
    """Classify posts, recognise entities, and cluster them into events."""
    from src.pipelines.events import build_events

    ctx = Context()
    _emit(build_events(ctx.paths, ctx.settings, ctx.universe, include_reposts))


@build_app.command("features")
def build_features_command() -> None:
    """Measure every window for every event and affected symbol."""
    from src.pipelines.features import build_features

    ctx = Context()
    _emit(build_features(ctx.paths, ctx.settings, ctx.universe, ctx.calendar))


# -- research --------------------------------------------------------------------------


def _run_event_study(ctx: Context, windows: list[EventWindow] | None = None) -> BaseModel:
    from src.backtesting.event_study import study_from_store
    from src.market_data.store import CandleStore

    return study_from_store(
        ctx.paths, ctx.settings, CandleStore(ctx.paths), ctx.universe.benchmark, windows
    )


@research_app.command("reaction-size")
def reaction_size_command() -> None:
    """Compare the size of moves after posts with the same symbols on nearby quiet days."""
    from src.backtesting.reaction_size import reaction_size_from_store
    from src.market_data.store import CandleStore
    from src.market_data.windows import WindowCalculator
    from src.pipelines.features import stored_quality

    ctx = Context()
    store = CandleStore(ctx.paths)
    calendar = ctx.calendar
    calculator = WindowCalculator(store, calendar, ctx.universe, stored_quality(store))
    _emit(reaction_size_from_store(ctx.paths, calculator, calendar, ctx.universe.benchmark))


@research_app.command("event-study")
def event_study_command(
    window: Annotated[list[EventWindow] | None, typer.Option(help="Repeatable.")] = None,
    full: Annotated[bool, typer.Option(help="Print the full report.")] = False,
) -> None:
    """Run the event study and store a report. Identical data gives an identical report."""
    ctx = Context()
    report = _run_event_study(ctx, window)
    if full:
        _emit(report)
        return
    data = report.model_dump(mode="json")
    _emit(
        {
            "report_id": data["report_id"],
            "content_hash": data["content_hash"],
            "events_total": data["events_total"],
            "events_measured": data["events_measured"],
            "data_quality": data["data_quality"],
            "overall": data["overall"],
        }
    )


# -- models ----------------------------------------------------------------------------


@model_app.command("train")
def model_train_command(
    window: Annotated[EventWindow, typer.Option(help="Label window.")] = EventWindow.D1,
    min_samples: Annotated[int, typer.Option(help="Refuse to train below this.")] = 200,
) -> None:
    """Train and evaluate the baseline model on chronological splits."""
    from src.ml.baseline import InsufficientData, train_baseline

    ctx = Context()
    try:
        report = train_baseline(ctx.paths, ctx.settings, ctx.universe, window, min_samples)
    except InsufficientData as exc:
        _fail(str(exc))
        return
    _emit(report)


@model_app.command("predict")
def model_predict_command(
    text: Annotated[str, typer.Option(help="Post text.")],
    symbol: Annotated[list[str] | None, typer.Option(help="Repeatable.")] = None,
) -> None:
    """Predict the reaction to a text with the latest trained model."""
    from src.ml.inference import InferenceService, ModelUnavailable

    ctx = Context()
    try:
        service = InferenceService(ctx.paths, ctx.settings, ctx.universe)
        predictions = service.predict_text(text, symbol)
    except ModelUnavailable as exc:
        _fail(str(exc))
        return
    _emit({"predictions": [p.model_dump(mode="json") for p in predictions]})


# -- backtests -------------------------------------------------------------------------


@backtest_app.command("run")
def backtest_run_command(
    strategy: Annotated[StrategyName, typer.Option(help="Strategy to test.")],
    cost_bps: Annotated[float | None, typer.Option(help="Cost per side in basis points.")] = None,
    slippage_bps: Annotated[float | None, typer.Option(help="Slippage per side.")] = None,
) -> None:
    """Backtest one strategy and store the result."""
    from src.backtesting.runner import run_backtest

    ctx = Context()
    result = run_backtest(
        ctx.paths,
        ctx.settings,
        ctx.universe,
        ctx.calendar,
        strategy,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
    )
    data = result.model_dump(mode="json", exclude={"equity_curve", "benchmark_curve", "trades"})
    _emit(data)


# -- pipeline --------------------------------------------------------------------------


@pipeline_app.command("run")
def pipeline_run_command(
    skip_download: Annotated[bool, typer.Option(help="Use stored posts and candles.")] = False,
    start: Annotated[datetime, typer.Option(formats=["%Y-%m-%d"])] = datetime(2021, 12, 1),  # noqa: DTZ001
) -> None:
    """Run ingest, build, event study, model training, and all three backtests."""
    from src.backtesting.runner import run_backtest
    from src.ingestion.sources import build_source
    from src.market_data.providers import build_provider
    from src.market_data.store import CandleStore
    from src.ml.baseline import InsufficientData, train_baseline
    from src.pipelines.events import build_events
    from src.pipelines.features import build_features
    from src.pipelines.market import ingest_market
    from src.pipelines.posts import ingest_posts

    ctx = Context()
    summary: dict[str, Any] = {}
    if not skip_download:
        source = build_source("stiles", ctx.settings)
        posts = asyncio.run(ingest_posts(source, IngestionMode.HISTORICAL, ctx.paths, ctx.settings))
        summary["posts"] = posts.model_dump(mode="json", exclude={"new_post_ids"})
        provider = build_provider(ctx.settings, ctx.calendar)
        store = CandleStore(ctx.paths)
        for interval in ("1d", "1h"):
            market = ingest_market(provider, store, ctx.universe, interval, start.date())
            summary[f"market_{interval}"] = market.model_dump(mode="json")
    summary["events"] = build_events(ctx.paths, ctx.settings, ctx.universe).model_dump(mode="json")
    summary["features"] = build_features(
        ctx.paths, ctx.settings, ctx.universe, ctx.calendar
    ).model_dump(mode="json")
    study = _run_event_study(ctx).model_dump(mode="json")
    summary["event_study"] = {k: study[k] for k in ("report_id", "events_total", "events_measured")}
    try:
        model = train_baseline(ctx.paths, ctx.settings, ctx.universe, EventWindow.D1)
        summary["model"] = {"version": model.model_version, "test": model.test_metrics}
    except InsufficientData as exc:
        summary["model"] = {"skipped": str(exc)}
    summary["backtests"] = {}
    for strategy in StrategyName:
        result = run_backtest(ctx.paths, ctx.settings, ctx.universe, ctx.calendar, strategy)
        summary["backtests"][strategy.value] = {
            "run_id": result.run_id,
            "metrics": result.metrics.model_dump(mode="json"),
        }
    _emit(summary)


# -- service ---------------------------------------------------------------------------


@app.command("serve")
def serve_command(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
) -> None:
    """Start the API."""
    import uvicorn

    uvicorn.run("src.api.app:create_app_from_env", host=host, port=port, factory=True)


@app.command("status")
def status_command() -> None:
    """Print store counts and data quality."""
    from src.market_data.store import CandleStore
    from src.pipelines.events import load_events

    ctx = Context()
    posts = read_parquet(ctx.paths.silver_posts, SocialPost)
    store = CandleStore(ctx.paths)
    features = read_parquet(ctx.paths.gold_features)
    _emit(
        {
            "data_dir": str(ctx.paths.root),
            "posts": posts.height,
            "posts_first": posts["published_at"].min() if posts.height else None,
            "posts_last": posts["published_at"].max() if posts.height else None,
            "posts_missing_timestamps": int(
                posts["published_at"].null_count() + posts["retrieved_at"].null_count()
            ),
            "events": len(load_events(ctx.paths)),
            "features": features.height,
            "candles": store.count(),
            "candle_intervals": store.intervals(),
            "candle_quality": store.quality_summary(),
            "market_provider": ctx.settings.resolved_market_provider(),
            "broker": ctx.settings.broker,
            "today": date.today().isoformat(),  # noqa: DTZ011
        }
    )


if __name__ == "__main__":
    app()
