"""Objects shared by the API routes, built once per application."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from src.api.stream import Broadcaster
from src.contracts import OrderStatus, PaperOrder, SocialPost
from src.core.settings import Settings
from src.core.storage import DataPaths, read_parquet
from src.market_data.calendar import TradingCalendar, xnys_calendar
from src.market_data.store import CandleStore
from src.market_data.universe import Universe, default_universe
from src.ml.inference import InferenceService
from src.pipelines.features import stored_quality
from src.trading.broker import BrokerOrder, ExecutionBroker, SimulatedBroker
from src.trading.service import OrderService
from src.trading.state import OrderStateStore

PRICE_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d"]


class Services:
    def __init__(self, settings: Settings, calendar: TradingCalendar | None = None) -> None:
        self.settings = settings
        self.paths = DataPaths(settings.data_dir)
        self.universe: Universe = default_universe(settings.benchmark_symbol)
        self.calendar = calendar or xnys_calendar()
        self.broadcaster = Broadcaster()
        self.pipeline_lock = threading.Lock()
        self.inference = InferenceService(self.paths, settings, self.universe)
        self._store = CandleStore(self.paths)
        self.state = OrderStateStore(self.paths.orders_db)
        self.broker = self._build_broker()
        self.orders = OrderService(
            self.broker,
            self.state,
            self.calendar,
            self.latest_price,
            daily_loss_limit_pct=settings.daily_loss_limit_pct,
            enforce_market_hours=settings.enforce_market_hours,
            on_order=self._publish_order,
        )

    # -- market data ---------------------------------------------------------------

    def candle_store(self) -> CandleStore:
        """A store that sees files written by other processes since the last request."""
        self._store.clear_cache()
        return self._store

    def latest_price(self, symbol: str) -> float | None:
        """Most recent stored close for a symbol, from the finest interval available.

        This is the last price the platform has, which may be delayed. It is used to size
        and simulate paper orders, never presented as a live quote.
        """
        best: tuple[Any, float] | None = None
        for interval in PRICE_INTERVALS:
            frame = self._store.read(symbol, interval)
            if frame.height == 0:
                continue
            ts, close = frame.select("ts", "close").row(-1)
            if best is None or ts > best[0]:
                best = (ts, float(close))
        return best[1] if best else None

    # -- trading -------------------------------------------------------------------

    def _build_broker(self) -> ExecutionBroker:
        settings = self.settings
        if settings.broker == "alpaca-paper":
            from src.trading.alpaca_paper import AlpacaPaperBroker

            key = settings.alpaca_api_key.get_secret_value() if settings.alpaca_api_key else ""
            secret = (
                settings.alpaca_api_secret.get_secret_value() if settings.alpaca_api_secret else ""
            )
            return AlpacaPaperBroker(key, secret)
        simulator = SimulatedBroker(
            settings.paper_initial_cash, self.latest_price, settings.slippage_bps
        )
        simulator.restore(
            [
                BrokerOrder(
                    client_order_id=o.client_order_id,
                    broker_order_id=o.order_id,
                    symbol=o.symbol,
                    side=o.side,
                    qty=o.qty,
                    status=o.status,
                    filled_price=o.filled_price,
                    filled_at=o.filled_at,
                )
                for o in self.state.list()
                if o.status is OrderStatus.FILLED
            ]
        )
        return simulator

    def _publish_order(self, order: PaperOrder) -> None:
        self.broadcaster.publish("order", order.model_dump(mode="json"))

    # -- status --------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        posts = read_parquet(self.paths.silver_posts, SocialPost)
        events = read_parquet(self.paths.gold_events)
        features = read_parquet(self.paths.gold_features)
        store = self.candle_store()
        candle_count = store.count()
        latest = posts["published_at"].max() if posts.height else None
        return {
            "posts": posts.height,
            "latest_post_at": latest.isoformat() if isinstance(latest, datetime) else None,
            "events": events.height,
            "features": features.height,
            "candles": candle_count,
            "candle_intervals": store.intervals(),
            "candle_quality": store.quality_summary(),
            "market_data_provider": self.settings.resolved_market_provider(),
            "market_data_quality": stored_quality(store).value if candle_count else None,
            "model_version": self.inference.version,
            "broker": self.broker.name,
            "kill_switch": self.orders.kill_switch,
            "market_open": self.orders.risk_state().market_open,
            "paper_trading_only": True,
        }

    def close(self) -> None:
        self.state.close()
