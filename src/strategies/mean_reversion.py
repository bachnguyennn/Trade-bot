"""Strategy C: after an unusually large move, bet on a partial reversal."""

from __future__ import annotations

from src.contracts import SignalAction, StrategyName, TradingSignal
from src.strategies.base import StrategyConfig, StrategyContext, make_signal


class MeanReversionStrategy:
    """Waits for the trigger window to finish, then fades a move above the threshold."""

    name = StrategyName.MEAN_REVERSION

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()

    def decide(self, context: StrategyContext) -> TradingSignal:
        trigger = context.trigger
        if trigger is None or not trigger.available or trigger.abnormal_ret is None:
            return make_signal(
                self.name,
                self.config,
                context,
                SignalAction.NO_TRADE,
                "initial move could not be measured",
            )
        assert trigger.exit_ts is not None
        move = trigger.abnormal_ret
        if abs(move) < self.config.reversion_threshold:
            return make_signal(
                self.name,
                self.config,
                context,
                SignalAction.NO_TRADE,
                f"initial move below threshold ({move:+.4f}, threshold "
                f"{self.config.reversion_threshold:.4f})",
                generated_at=trigger.exit_ts,
            )
        action = SignalAction.SELL if move > 0 else SignalAction.BUY
        return make_signal(
            self.name,
            self.config,
            context,
            action,
            f"fade initial {trigger.window.value} abnormal move of {move:+.4f}",
            generated_at=trigger.exit_ts,
        )
