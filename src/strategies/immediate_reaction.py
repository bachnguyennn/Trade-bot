"""Strategy A: trade the predicted short-term reaction as soon as a post is available."""

from __future__ import annotations

from src.contracts import Direction, SignalAction, StrategyName, TradingSignal
from src.strategies.base import StrategyConfig, StrategyContext, make_signal


class ImmediateReactionStrategy:
    """Uses an out-of-sample model prediction. Without one, it does not trade."""

    name = StrategyName.IMMEDIATE_REACTION

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()

    def decide(self, context: StrategyContext) -> TradingSignal:
        prediction = context.prediction
        if prediction is None:
            return make_signal(
                self.name,
                self.config,
                context,
                SignalAction.NO_TRADE,
                "no out-of-sample prediction available",
            )
        if prediction.predicted_at > context.decision_time:
            return make_signal(
                self.name,
                self.config,
                context,
                SignalAction.NO_TRADE,
                "prediction is dated after the decision time",
            )
        if prediction.confidence < self.config.min_confidence:
            return make_signal(
                self.name,
                self.config,
                context,
                SignalAction.NO_TRADE,
                f"confidence below threshold ({prediction.confidence:.3f} < "
                f"{self.config.min_confidence:.3f})",
            )
        if prediction.direction is Direction.UP:
            action = SignalAction.BUY
        elif prediction.direction is Direction.DOWN:
            action = SignalAction.SELL
        else:
            return make_signal(
                self.name, self.config, context, SignalAction.NO_TRADE, "prediction is flat"
            )
        reason = (
            f"model {prediction.model_version} predicts {prediction.direction.value} "
            f"(p_up={prediction.prob_up:.3f})"
        )
        return make_signal(self.name, self.config, context, action, reason)
