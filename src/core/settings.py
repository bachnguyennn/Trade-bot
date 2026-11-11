"""Runtime configuration. Every value comes from the environment or `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings are read from `TRADEBOT_*` environment variables.

    There is deliberately no setting for a brokerage trading URL: the paper adapter
    hard-codes the paper endpoint so configuration cannot point it at a live account.
    """

    model_config = SettingsConfigDict(
        env_prefix="TRADEBOT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Storage
    data_dir: Path = Path("data")

    # Posts
    account: str = "realDonaldTrump"
    stiles_archive_url: str = "https://stilesdata.com/trump-truth-social-archive/truth_archive.json"
    cnn_archive_url: str = "https://ix.cnn.io/data/truth-social/truth_archive.json"
    allow_unverified_sources: bool = False
    http_user_agent: str = "tradebot-research/0.1"
    http_max_retries: int = Field(default=4, ge=0)
    http_timeout_seconds: float = Field(default=60.0, gt=0)

    # Point-in-time rules
    assumed_latency_seconds: int = Field(default=60, ge=0)
    decision_latency_seconds: int = Field(default=30, ge=0)
    cluster_gap_minutes: int = Field(default=60, ge=0)

    # Market data
    market_provider: Literal["auto", "alpaca", "yfinance"] = "auto"
    alpaca_api_key: SecretStr | None = None
    alpaca_api_secret: SecretStr | None = None
    alpaca_data_url: str = "https://data.alpaca.markets"
    benchmark_symbol: str = "SPY"

    # Backtesting defaults
    cost_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=2.0, ge=0)
    max_position_weight: float = Field(default=0.10, gt=0, le=1)
    max_gross_exposure: float = Field(default=1.0, gt=0)

    # Paper trading
    broker: Literal["simulator", "alpaca-paper"] = "simulator"
    paper_initial_cash: float = Field(default=100_000.0, gt=0)
    daily_loss_limit_pct: float = Field(default=0.02, gt=0, le=1)
    enforce_market_hours: bool = True

    # API
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def has_alpaca_keys(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_api_secret)

    def resolved_market_provider(self) -> Literal["alpaca", "yfinance"]:
        if self.market_provider == "auto":
            return "alpaca" if self.has_alpaca_keys else "yfinance"
        return self.market_provider


@lru_cache
def get_settings() -> Settings:
    return Settings()
