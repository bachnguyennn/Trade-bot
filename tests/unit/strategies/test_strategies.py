from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.contracts import (
    DataQuality,
    Direction,
    EventCategory,
    EventWindow,
    MarketEvent,
    MarketFeature,
    ModelPrediction,
    SignalAction,
    StrategyName,
)
from src.strategies import (
    ImmediateReactionStrategy,
    MeanReversionStrategy,
    MomentumContinuationStrategy,
    StrategyConfig,
    StrategyContext,
    build_strategy,
    signal_id,
)

T0 = datetime(2025, 3, 3, 15, 0, tzinfo=UTC)
DECISION = T0 + timedelta(seconds=30)
TRIGGER_END = T0 + timedelta(hours=6)

EVENT = MarketEvent(
    event_id="e1",
    post_ids=["1"],
    text="Tariffs on China",
    published_at=T0,
    available_at=T0,
    categories=[EventCategory.TARIFFS_TRADE],
    symbols=["NUE"],
    relevance_score=0.5,
    classifier_version="rules-v1",
)


def prediction(prob_up: float, predicted_at: datetime = DECISION) -> ModelPrediction:
    direction = (
        Direction.UP if prob_up > 0.52 else Direction.DOWN if prob_up < 0.48 else Direction.FLAT
    )
    return ModelPrediction(
        prediction_id="p1",
        event_id="e1",
        symbol="NUE",
        window=EventWindow.D1,
        model_name="m",
        model_version="v1",
        predicted_at=predicted_at,
        direction=direction,
        prob_up=prob_up,
        expected_abnormal_return=0.0,
        confidence=abs(prob_up - 0.5) * 2,
    )


def trigger(abnormal: float | None) -> MarketFeature:
    if abnormal is None:
        return MarketFeature(
            event_id="e1",
            symbol="NUE",
            window=EventWindow.D1,
            anchor_ts=DECISION,
            tradable=True,
            available=False,
            unavailable_reason="missing",
            quality=DataQuality.SYNTHETIC,
        )
    return MarketFeature(
        event_id="e1",
        symbol="NUE",
        window=EventWindow.D1,
        anchor_ts=DECISION,
        entry_ts=DECISION,
        exit_ts=TRIGGER_END,
        entry_price=100.0,
        exit_price=100.0,
        ret=abnormal,
        benchmark_ret=0.0,
        abnormal_ret=abnormal,
        tradable=True,
        available=True,
        quality=DataQuality.SYNTHETIC,
    )


def ctx(pred: ModelPrediction | None = None, trig: MarketFeature | None = None) -> StrategyContext:
    return StrategyContext(
        event=EVENT, symbol="NUE", decision_time=DECISION, prediction=pred, trigger=trig
    )


def test_immediate_reaction_follows_confident_predictions() -> None:
    strategy = ImmediateReactionStrategy()
    buy = strategy.decide(ctx(prediction(0.60)))
    assert buy.action is SignalAction.BUY and buy.target_weight == 0.05
    assert buy.generated_at == DECISION and buy.stop_loss_pct == 0.03
    assert buy.prediction_id == "p1" and "v1" in buy.reason
    sell = strategy.decide(ctx(prediction(0.40)))
    assert sell.action is SignalAction.SELL


def test_immediate_reaction_no_trade_cases() -> None:
    strategy = ImmediateReactionStrategy()
    missing = strategy.decide(ctx(None))
    assert missing.action is SignalAction.NO_TRADE and missing.target_weight == 0.0
    assert missing.reason == "no out-of-sample prediction available"
    weak = strategy.decide(ctx(prediction(0.53)))
    assert weak.action is SignalAction.NO_TRADE
    assert weak.reason.startswith("confidence below threshold (")
    future = strategy.decide(ctx(prediction(0.70, DECISION + timedelta(minutes=1))))
    assert future.action is SignalAction.NO_TRADE and "after the decision time" in future.reason


def test_short_selling_can_be_disabled() -> None:
    strategy = ImmediateReactionStrategy(StrategyConfig(allow_short=False))
    signal = strategy.decide(ctx(prediction(0.30)))
    assert signal.action is SignalAction.NO_TRADE
    assert signal.reason.startswith("short selling disabled")


def test_momentum_follows_the_initial_move_after_it_is_known() -> None:
    strategy = MomentumContinuationStrategy()
    up = strategy.decide(ctx(trig=trigger(0.012)))
    assert up.action is SignalAction.BUY
    assert up.generated_at == TRIGGER_END  # not before the initial move is observable
    down = strategy.decide(ctx(trig=trigger(-0.012)))
    assert down.action is SignalAction.SELL
    small = strategy.decide(ctx(trig=trigger(0.001)))
    assert small.action is SignalAction.NO_TRADE
    assert small.reason.startswith("initial move below threshold (")
    assert strategy.decide(ctx(trig=trigger(None))).action is SignalAction.NO_TRADE
    assert strategy.decide(ctx()).reason == "initial move could not be measured"


def test_mean_reversion_fades_large_moves_only() -> None:
    strategy = MeanReversionStrategy()
    fade_up = strategy.decide(ctx(trig=trigger(0.03)))
    assert fade_up.action is SignalAction.SELL and fade_up.generated_at == TRIGGER_END
    fade_down = strategy.decide(ctx(trig=trigger(-0.03)))
    assert fade_down.action is SignalAction.BUY
    # A move that momentum would trade is too small to fade.
    assert strategy.decide(ctx(trig=trigger(0.012))).action is SignalAction.NO_TRADE


def test_thresholds_are_configurable() -> None:
    config = StrategyConfig(
        momentum_threshold=0.02,
        position_weight=0.02,
        stop_loss_pct=None,
        holding_window=EventWindow.H4,
    )
    strategy = MomentumContinuationStrategy(config)
    assert strategy.decide(ctx(trig=trigger(0.012))).action is SignalAction.NO_TRADE
    signal = strategy.decide(ctx(trig=trigger(0.03)))
    assert signal.target_weight == 0.02 and signal.stop_loss_pct is None
    assert signal.holding_window is EventWindow.H4


def test_signal_ids_are_deterministic_and_distinct() -> None:
    a = signal_id(StrategyName.MEAN_REVERSION, "e1", "NUE")
    assert a == signal_id(StrategyName.MEAN_REVERSION, "e1", "NUE")
    assert a != signal_id(StrategyName.MOMENTUM_CONTINUATION, "e1", "NUE")
    assert a != signal_id(StrategyName.MEAN_REVERSION, "e1", "CAT")
    strategy = MeanReversionStrategy()
    first = strategy.decide(ctx(trig=trigger(0.03)))
    second = strategy.decide(ctx(trig=trigger(0.03)))
    assert first.signal_id == second.signal_id


@pytest.mark.parametrize("name", list(StrategyName))
def test_build_strategy(name: StrategyName) -> None:
    assert build_strategy(name).name is name
