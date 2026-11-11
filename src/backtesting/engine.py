"""Event-driven backtest engine.

Execution assumptions, all conservative and all stated in every result:

- A signal can only be acted on after its `generated_at` time. Entry is the open of the
  first bar at or after that time; exit is the end of the holding window.
- Slippage moves every fill against the trader. A cost is charged on each side.
- A stop-loss is checked on every bar. It fills at the stop level, or at the bar's open if
  the price has already gapped through it.
- At most one open position per symbol, so overlapping events are not double-counted.
- Position size is a fraction of realised equity, capped per position and in total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

from src.contracts import (
    BacktestTrade,
    DataQuality,
    EquityPoint,
    OrderSide,
    SignalAction,
    TradingSignal,
)
from src.market_data.windows import Measurement, WindowCalculator


class ExecutionConfig(BaseModel):
    initial_equity: float = Field(default=100_000.0, gt=0)
    cost_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=2.0, ge=0)
    max_position_weight: float = Field(default=0.10, gt=0, le=1)
    max_gross_exposure: float = Field(default=1.0, gt=0)


@dataclass
class _Planned:
    signal: TradingSignal
    side: OrderSide
    entry_ts: datetime
    entry_price: float
    exit_ts: datetime
    exit_price: float
    exit_reason: str
    quality: DataQuality


@dataclass
class _Open:
    trade: BacktestTrade
    notional: float


@dataclass
class EngineResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    no_trade_reasons: dict[str, int] = field(default_factory=dict)
    signal_count: int = 0
    qualities: set[DataQuality] = field(default_factory=set)

    @property
    def no_trade_count(self) -> int:
        return sum(self.no_trade_reasons.values())


def apply_stop_loss(
    measurement: Measurement, side: OrderSide, stop_loss_pct: float | None
) -> tuple[datetime, float, str]:
    """Walk the bars between entry and exit and return the actual exit.

    Returns the exit time, the raw exit price (before slippage), and the reason.
    """
    if stop_loss_pct is None or not measurement.path:
        return measurement.exit_ts, measurement.exit_price, "holding_period"
    entry = measurement.entry_price
    if side is OrderSide.BUY:
        stop = entry * (1 - stop_loss_pct)
        for index, bar in enumerate(measurement.path):
            if index > 0 and bar.open <= stop:
                return bar.start, bar.open, "stop_loss"  # gapped through the stop
            if bar.low <= stop:
                return bar.end, stop, "stop_loss"
    else:
        stop = entry * (1 + stop_loss_pct)
        for index, bar in enumerate(measurement.path):
            if index > 0 and bar.open >= stop:
                return bar.start, bar.open, "stop_loss"
            if bar.high >= stop:
                return bar.end, stop, "stop_loss"
    return measurement.exit_ts, measurement.exit_price, "holding_period"


class BacktestEngine:
    def __init__(self, calculator: WindowCalculator, config: ExecutionConfig) -> None:
        self._calculator = calculator
        self._config = config

    def _plan(self, signal: TradingSignal) -> _Planned | str:
        """Work out where a signal would be filled, or why it cannot be."""
        measurement = self._calculator.measure(
            signal.symbol, signal.generated_at, signal.holding_window
        )
        if isinstance(measurement, str):
            return measurement
        side = OrderSide.BUY if signal.action is SignalAction.BUY else OrderSide.SELL
        exit_ts, exit_price, reason = apply_stop_loss(measurement, side, signal.stop_loss_pct)
        return _Planned(
            signal=signal,
            side=side,
            entry_ts=measurement.entry_ts,
            entry_price=measurement.entry_price,
            exit_ts=exit_ts,
            exit_price=exit_price,
            exit_reason=reason,
            quality=measurement.quality,
        )

    def run(
        self, signals: list[TradingSignal], event_categories: dict[str, list[str]] | None = None
    ) -> EngineResult:
        """Simulate the signals in time order."""
        categories = event_categories or {}
        config = self._config
        result = EngineResult(signal_count=len(signals))

        def skip(reason: str) -> None:
            result.no_trade_reasons[reason] = result.no_trade_reasons.get(reason, 0) + 1

        planned: list[_Planned] = []
        for signal in signals:
            if signal.action is SignalAction.NO_TRADE:
                # Details in parentheses vary per signal; group by the leading text.
                skip(f"strategy: {signal.reason.split(' (')[0]}")
                continue
            plan = self._plan(signal)
            if isinstance(plan, str):
                skip(f"execution: {plan}")
            else:
                planned.append(plan)
        planned.sort(key=lambda p: (p.entry_ts, p.signal.signal_id))

        equity = config.initial_equity
        open_positions: list[_Open] = []
        slip = config.slippage_bps / 10_000.0
        cost_rate = config.cost_bps / 10_000.0

        def close_until(ts: datetime | None) -> None:
            nonlocal equity
            due = [o for o in open_positions if ts is None or o.trade.exit_ts <= ts]
            for position in sorted(due, key=lambda o: (o.trade.exit_ts, o.trade.signal_id)):
                open_positions.remove(position)
                equity += position.trade.pnl
                result.trades.append(position.trade)
                result.equity_curve.append(EquityPoint(ts=position.trade.exit_ts, equity=equity))

        for plan in planned:
            close_until(plan.entry_ts)
            if any(o.trade.symbol == plan.signal.symbol for o in open_positions):
                skip("risk: position already open in symbol")
                continue
            weight = min(plan.signal.target_weight, config.max_position_weight)
            gross = sum(o.notional for o in open_positions) / equity if equity > 0 else 0.0
            if equity <= 0:
                skip("risk: no equity left")
                continue
            if gross + weight > config.max_gross_exposure + 1e-9:
                skip("risk: gross exposure limit")
                continue

            direction = 1.0 if plan.side is OrderSide.BUY else -1.0
            # Slippage always works against the trader: buys fill higher, sells lower.
            entry_fill = plan.entry_price * (1 + direction * slip)
            exit_fill = plan.exit_price * (1 - direction * slip)
            notional = weight * equity
            qty = notional / entry_fill
            costs = cost_rate * qty * (entry_fill + exit_fill)
            pnl = direction * qty * (exit_fill - entry_fill) - costs
            trade = BacktestTrade(
                signal_id=plan.signal.signal_id,
                event_id=plan.signal.event_id,
                symbol=plan.signal.symbol,
                side=plan.side,
                qty=qty,
                signal_ts=plan.signal.generated_at,
                entry_ts=plan.entry_ts,
                entry_price=entry_fill,
                exit_ts=plan.exit_ts,
                exit_price=exit_fill,
                costs=costs,
                pnl=pnl,
                return_pct=pnl / notional,
                exit_reason=plan.exit_reason,
                categories=categories.get(plan.signal.event_id, []),
            )
            open_positions.append(_Open(trade=trade, notional=notional))
            result.qualities.add(plan.quality)

        close_until(None)
        return result
