"""Guards for the rules that keep research results trustworthy and trading paper-only."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from src.backtesting.runner import run_backtest
from src.contracts import DataQuality, StrategyName
from src.core.settings import Settings
from src.core.storage import DataPaths
from src.market_data.calendar import TradingCalendar
from src.market_data.store import CandleStore
from src.market_data.universe import default_universe
from src.pipelines.features import build_features, load_features
from tests.helpers import daily_candles, intraday_candles, make_calendar
from tests.integration.conftest import populate

REPO = Path(__file__).parents[2]


@pytest.fixture
def calendar() -> TradingCalendar:
    return make_calendar(start=date(2025, 2, 24), days=25)


def test_future_prices_cannot_change_earlier_measurements(
    posts_fixture: Path, paths: DataPaths, settings: Settings, calendar: TradingCalendar
) -> None:
    """Rewrite every candle after a cutoff. Measurements that ended before it must not move."""
    populate(posts_fixture, paths, settings, calendar)
    universe = default_universe()
    before = {(f.event_id, f.symbol, f.window): f for f in load_features(paths)}

    cutoff = calendar.sessions[12]
    store = CandleStore(paths)
    for symbol in universe.symbols:
        frame = store.read(symbol, "1d")
        changed = frame.with_columns(
            pl.when(pl.col("ts") >= cutoff.daily_ts)
            .then(pl.col("close") * 3.0)
            .otherwise(pl.col("close"))
            .alias("close"),
            pl.when(pl.col("ts") >= cutoff.daily_ts)
            .then(pl.col("high") * 3.0)
            .otherwise(pl.col("high"))
            .alias("high"),
            # Mark the rewritten bars as better quality so they replace the stored ones.
            pl.lit(DataQuality.CONSOLIDATED.value).alias("quality"),
        )
        store.upsert(changed)
    build_features(paths, settings, universe, calendar)
    after = {(f.event_id, f.symbol, f.window): f for f in load_features(paths)}

    checked = 0
    for key, old in before.items():
        if old.available and old.exit_ts is not None and old.exit_ts < cutoff.open:
            new = after[key]
            assert (new.ret, new.abnormal_ret, new.entry_price, new.exit_price) == (
                old.ret,
                old.abnormal_ret,
                old.entry_price,
                old.exit_price,
            ), key
            checked += 1
    assert checked > 0


def test_backtests_are_reproducible(
    posts_fixture: Path, paths: DataPaths, settings: Settings, calendar: TradingCalendar
) -> None:
    populate(posts_fixture, paths, settings, calendar)
    universe = default_universe()
    for strategy in (StrategyName.MOMENTUM_CONTINUATION, StrategyName.MEAN_REVERSION):
        first = run_backtest(paths, settings, universe, calendar, strategy, save=False)
        second = run_backtest(paths, settings, universe, calendar, strategy, save=False)
        assert first.run_id == second.run_id
        assert first.metrics == second.metrics
        assert first.trades == second.trades
        assert first.assumptions and first.benchmark_symbol == "SPY"
        for trade in first.trades:
            assert trade.entry_ts >= trade.signal_ts


def test_costs_never_improve_a_backtest(
    posts_fixture: Path, paths: DataPaths, settings: Settings, calendar: TradingCalendar
) -> None:
    populate(posts_fixture, paths, settings, calendar)
    universe = default_universe()
    strategy = StrategyName.MOMENTUM_CONTINUATION
    free = run_backtest(
        paths, settings, universe, calendar, strategy, cost_bps=0, slippage_bps=0, save=False
    )
    priced = run_backtest(
        paths, settings, universe, calendar, strategy, cost_bps=5, slippage_bps=10, save=False
    )
    assert free.metrics.trade_count > 0
    assert priced.metrics.cumulative_return <= free.metrics.cumulative_return
    assert any("5.0 bps" in a for a in priced.assumptions)


def test_strategy_a_without_out_of_sample_predictions_does_not_trade(
    posts_fixture: Path, paths: DataPaths, settings: Settings, calendar: TradingCalendar
) -> None:
    populate(posts_fixture, paths, settings, calendar)
    result = run_backtest(
        paths, settings, default_universe(), calendar, StrategyName.IMMEDIATE_REACTION, save=False
    )
    assert result.metrics.trade_count == 0 and result.metrics.cumulative_return == 0.0
    assert result.no_trade_reasons == {
        "strategy: no out-of-sample prediction available": result.signal_count
    }


def test_test_data_is_labelled_synthetic(posts_fixture: Path) -> None:
    records = json.loads(posts_fixture.read_text(encoding="utf-8"))
    for record in records:
        if record.get("content"):
            assert "SYNTHETIC TEST FIXTURE" in record["content"]
        assert "example.invalid" in record["url"]
    calendar = make_calendar(days=2)
    frames = [
        daily_candles("AAA", calendar, lambda i: (1.0, 1.0)),
        intraday_candles("AAA", calendar.sessions[0], "1h", lambda k: 1.0),
    ]
    for frame in frames:
        assert frame["quality"].unique().to_list() == [DataQuality.SYNTHETIC.value]
        assert frame["source"].unique().to_list() == ["synthetic-test"]


def test_only_paper_and_data_hosts_appear_in_source() -> None:
    """No source file may name Alpaca's live trading host."""
    hosts: set[str] = set()
    for file in (REPO / "src").rglob("*.py"):
        hosts.update(re.findall(r"[\w.-]*alpaca\.markets", file.read_text(encoding="utf-8")))
    assert hosts == {"paper-api.alpaca.markets", "data.alpaca.markets"}


def test_settings_have_no_trading_url_or_live_flag() -> None:
    fields = set(Settings.model_fields)
    assert not {f for f in fields if "live" in f or "trading_url" in f or "base_url" in f}
    assert Settings.model_fields["broker"].annotation.__args__ == ("simulator", "alpaca-paper")  # type: ignore[union-attr]


def test_no_secret_files_are_tracked() -> None:
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    names = {Path(name).name for name in tracked}
    assert ".env" not in names
    assert not [n for n in tracked if n.startswith("data/")]
    assert not [n for n in tracked if n.endswith((".parquet", ".sqlite", ".joblib"))]
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        if line.startswith(("TRADEBOT_ALPACA_API_KEY", "TRADEBOT_ALPACA_API_SECRET")):
            assert line.endswith("="), "example file must not contain a key value"
