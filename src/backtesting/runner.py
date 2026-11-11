"""Generate signals from stored data, run the engine, and store a `BacktestResult`."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import polars as pl

from src.backtesting.engine import BacktestEngine, EngineResult, ExecutionConfig
from src.backtesting.metrics import category_metrics, compute_metrics
from src.contracts import (
    BacktestMetrics,
    BacktestResult,
    DataQuality,
    EquityPoint,
    EventWindow,
    MarketEvent,
    MarketFeature,
    ModelPrediction,
    StrategyName,
    TradingSignal,
)
from src.core.logging import get_logger
from src.core.settings import Settings
from src.core.storage import (
    DataPaths,
    from_frame,
    read_parquet,
    to_frame,
    write_json_atomic,
    write_parquet_atomic,
)
from src.core.timeutils import utc_now
from src.market_data.calendar import TradingCalendar
from src.market_data.store import CandleStore
from src.market_data.universe import Universe
from src.market_data.windows import WindowCalculator
from src.pipelines.events import load_events
from src.pipelines.features import load_features, stored_quality
from src.strategies import Strategy, StrategyConfig, StrategyContext, build_strategy

log = get_logger(__name__)


def load_predictions(paths: DataPaths) -> list[ModelPrediction]:
    return from_frame(read_parquet(paths.gold_predictions, ModelPrediction), ModelPrediction)


def load_signals(paths: DataPaths) -> list[TradingSignal]:
    return from_frame(read_parquet(paths.gold_signals, TradingSignal), TradingSignal)


def generate_signals(
    strategy: Strategy,
    events: list[MarketEvent],
    features: list[MarketFeature],
    predictions: list[ModelPrediction],
    decision_latency: timedelta,
) -> list[TradingSignal]:
    """One signal per event and symbol. Each strategy sees only what its context allows."""
    config = strategy.config
    triggers = {(f.event_id, f.symbol): f for f in features if f.window is config.trigger_window}
    by_prediction = {
        (p.event_id, p.symbol): p for p in predictions if p.window is config.holding_window
    }
    signals: list[TradingSignal] = []
    for event in sorted(events, key=lambda e: (e.available_at, e.event_id)):
        decision_time = event.available_at + decision_latency
        for symbol in event.symbols:
            context = StrategyContext(
                event=event,
                symbol=symbol,
                decision_time=decision_time,
                prediction=by_prediction.get((event.event_id, symbol)),
                trigger=triggers.get((event.event_id, symbol)),
            )
            signals.append(strategy.decide(context))
    return signals


def benchmark_curve(
    store: CandleStore,
    symbol: str,
    initial_equity: float,
    calendar: TradingCalendar,
    start: datetime,
    end: datetime,
) -> list[EquityPoint]:
    """Buy and hold the benchmark from the first close in the period to the last."""
    closes = dict(zip(*store.read(symbol, "1d").select("ts", "close").get_columns(), strict=True))
    points: list[EquityPoint] = []
    first: float | None = None
    for session in calendar.sessions:
        if session.close < start or session.close > end:
            continue
        close = closes.get(session.daily_ts)
        if close is None:
            continue
        first = first or close
        points.append(EquityPoint(ts=session.close, equity=initial_equity * close / first))
    return points


def _assumptions(
    strategy: Strategy, execution: ExecutionConfig, settings: Settings, quality: DataQuality
) -> list[str]:
    config = strategy.config
    notes = [
        f"Entry at the open of the first bar at or after the signal time; exit at the end of "
        f"the {config.holding_window.value} holding window.",
        f"Signals are dated no earlier than availability plus {settings.decision_latency_seconds}s "
        f"decision latency; historical posts are assumed available "
        f"{settings.assumed_latency_seconds}s after publication.",
        f"Transaction cost {execution.cost_bps} bps per side; slippage {execution.slippage_bps} "
        "bps per side, always against the trader.",
        "Stop-loss fills at the stop level, or at the bar open if the price gapped through it."
        if config.stop_loss_pct
        else "No stop-loss.",
        f"Position size {config.position_weight:.0%} of realised equity, capped at "
        f"{execution.max_position_weight:.0%} per position and {execution.max_gross_exposure:.0%} "
        "gross. One open position per symbol.",
        "Short sales are assumed to be available with no borrow cost or locate failure."
        if config.allow_short
        else "Long only.",
        "No market impact is modelled; fills are assumed at the bar open for any size.",
        f"Market data quality: {quality.value}. Delayed or single-venue bars can differ from "
        "consolidated prices.",
        "The symbol universe was chosen today (survivorship bias).",
        "Results describe a historical simulation. They are not evidence of future returns.",
    ]
    if strategy.name is StrategyName.IMMEDIATE_REACTION:
        notes.append(
            "Only walk-forward (out-of-sample) model predictions are used, so the tested period "
            "starts after the model's initial training period."
        )
    else:
        notes.append(
            f"The decision is made after the {config.trigger_window.value} trigger window ends, "
            "when the initial move is known."
        )
    return notes


def run_backtest(
    paths: DataPaths,
    settings: Settings,
    universe: Universe,
    calendar: TradingCalendar,
    strategy_name: StrategyName,
    config: StrategyConfig | None = None,
    cost_bps: float | None = None,
    slippage_bps: float | None = None,
    save: bool = True,
) -> BacktestResult:
    strategy = build_strategy(strategy_name, config)
    execution = ExecutionConfig(
        initial_equity=settings.paper_initial_cash,
        cost_bps=settings.cost_bps if cost_bps is None else cost_bps,
        slippage_bps=settings.slippage_bps if slippage_bps is None else slippage_bps,
        max_position_weight=settings.max_position_weight,
        max_gross_exposure=settings.max_gross_exposure,
    )
    store = CandleStore(paths)
    quality = stored_quality(store)
    calculator = WindowCalculator(store, calendar, universe, quality)

    events = load_events(paths)
    features = load_features(paths)
    predictions = load_predictions(paths)
    signals = generate_signals(
        strategy,
        events,
        features,
        predictions,
        timedelta(seconds=settings.decision_latency_seconds),
    )
    engine_result = BacktestEngine(calculator, execution).run(
        signals, {e.event_id: [c.value for c in e.categories] for e in events}
    )
    result = assemble_result(
        strategy,
        execution,
        settings,
        calendar,
        store,
        universe.benchmark,
        signals,
        engine_result,
        quality,
    )
    if save:
        write_json_atomic(
            result.model_dump_json(indent=2),
            paths.reports_dir("backtests") / f"{result.run_id}.json",
        )
        _store_signals(paths, strategy_name, signals)
    log.info(
        "backtest finished",
        extra={"run_id": result.run_id, "metrics": result.metrics.model_dump(mode="json")},
    )
    return result


def assemble_result(
    strategy: Strategy,
    execution: ExecutionConfig,
    settings: Settings,
    calendar: TradingCalendar,
    store: CandleStore,
    benchmark_symbol: str,
    signals: list[TradingSignal],
    engine_result: EngineResult,
    quality: DataQuality,
) -> BacktestResult:
    trades = engine_result.trades
    now = utc_now()
    if trades:
        start = min(t.entry_ts for t in trades)
        end = max(t.exit_ts for t in trades)
    elif signals:
        start = min(s.generated_at for s in signals)
        end = max(s.generated_at for s in signals)
    else:
        start = end = now

    curve = [EquityPoint(ts=start, equity=execution.initial_equity), *engine_result.equity_curve]
    metrics = compute_metrics(curve, trades, execution.initial_equity, calendar, start, end)

    bench_curve = benchmark_curve(
        store, benchmark_symbol, execution.initial_equity, calendar, start, end
    )
    benchmark_metrics: BacktestMetrics | None = None
    if len(bench_curve) >= 2:
        computed = compute_metrics(bench_curve, [], execution.initial_equity, calendar, start, end)
        benchmark_metrics = computed.model_copy(update={"turnover": 1.0})

    config = {
        "strategy": strategy.config.model_dump(mode="json"),
        "execution": execution.model_dump(mode="json"),
        "decision_latency_seconds": settings.decision_latency_seconds,
        "assumed_latency_seconds": settings.assumed_latency_seconds,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "config": config,
                "signals": [s.signal_id + s.action.value for s in signals],
                "trades": [f"{t.signal_id}:{t.pnl:.6f}" for t in trades],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return BacktestResult(
        run_id=f"bt_{strategy.name.value}_{fingerprint[:10]}",
        strategy=strategy.name,
        config=config,
        created_at=now,
        period_start=start,
        period_end=end,
        initial_equity=execution.initial_equity,
        metrics=metrics,
        benchmark_symbol=benchmark_symbol,
        benchmark_metrics=benchmark_metrics,
        by_category=category_metrics(trades, execution.initial_equity),
        equity_curve=curve,
        benchmark_curve=bench_curve,
        trades=trades,
        signal_count=engine_result.signal_count,
        no_trade_count=engine_result.no_trade_count,
        no_trade_reasons=dict(sorted(engine_result.no_trade_reasons.items())),
        assumptions=_assumptions(strategy, execution, settings, quality),
        data_quality=DataQuality.lowest(list(engine_result.qualities))
        if engine_result.qualities
        else quality,
    )


def _store_signals(paths: DataPaths, strategy: StrategyName, signals: list[TradingSignal]) -> None:
    """Replace the stored signals of one strategy with its latest run."""
    existing = read_parquet(paths.gold_signals, TradingSignal)
    kept = existing.filter(pl.col("strategy") != strategy.value)
    merged = pl.concat([kept, to_frame(signals, TradingSignal)], how="vertical_relaxed")
    write_parquet_atomic(merged, paths.gold_signals)


def load_backtests(paths: DataPaths) -> list[BacktestResult]:
    results = [
        BacktestResult.model_validate(json.loads(f.read_text(encoding="utf-8")))
        for f in paths.report_files("backtests")
    ]
    return sorted(results, key=lambda r: r.created_at)


def load_backtest(paths: DataPaths, run_id: str) -> BacktestResult | None:
    file = paths.reports_dir("backtests") / f"{run_id}.json"
    if not file.exists() or file.parent != paths.reports_dir("backtests"):
        return None
    return BacktestResult.model_validate(json.loads(file.read_text(encoding="utf-8")))


__all__ = [
    "EventWindow",
    "benchmark_curve",
    "generate_signals",
    "load_backtest",
    "load_backtests",
    "load_predictions",
    "load_signals",
    "run_backtest",
]
