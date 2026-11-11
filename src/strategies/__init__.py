"""Trading strategies. Each turns an event into a signal, which may be `no_trade`."""

from src.contracts import StrategyName
from src.strategies.base import Strategy, StrategyConfig, StrategyContext, signal_id
from src.strategies.immediate_reaction import ImmediateReactionStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum_continuation import MomentumContinuationStrategy


def build_strategy(name: StrategyName, config: StrategyConfig | None = None) -> Strategy:
    if name is StrategyName.IMMEDIATE_REACTION:
        return ImmediateReactionStrategy(config)
    if name is StrategyName.MOMENTUM_CONTINUATION:
        return MomentumContinuationStrategy(config)
    if name is StrategyName.MEAN_REVERSION:
        return MeanReversionStrategy(config)
    raise ValueError(f"unknown strategy: {name}")


__all__ = [
    "ImmediateReactionStrategy",
    "MeanReversionStrategy",
    "MomentumContinuationStrategy",
    "Strategy",
    "StrategyConfig",
    "StrategyContext",
    "build_strategy",
    "signal_id",
]
