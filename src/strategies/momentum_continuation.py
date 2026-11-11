"""Strategy B: after an initial move, bet that it continues."""

from __future__ import annotations

from src.contracts import SignalAction, StrategyName, TradingSignal
from src.strategies.base import StrategyConfig, StrategyContext, make_signal


class MomentumContinuationStrategy:
    """Waits for the trigger window to finish, then follows a large enough abnormal move.

    The decision is dated at the end of the trigger window, because the initial move is
    not known before then.
    """

    name = StrategyName.MOMENTUM_CONTINUATION

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
        if abs(move) < self.config.momentum_threshold:
            return make_signal(
                self.name,
                self.config,
                context,
                SignalAction.NO_TRADE,
                f"initial move below threshold ({move:+.4f}, threshold "
                f"{self.config.momentum_threshold:.4f})",
                generated_at=trigger.exit_ts,
            )
        action = SignalAction.BUY if move > 0 else SignalAction.SELL
        return make_signal(
            self.name,
            self.config,
            context,
            action,
            f"follow initial {trigger.window.value} abnormal move of {move:+.4f}",
            generated_at=trigger.exit_ts,
        )
