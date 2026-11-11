"""Validation rules of the shared contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.contracts import (
    DataQuality,
    EventCategory,
    EventWindow,
    IngestionMode,
    MarketEvent,
    MarketFeature,
    OrderSide,
    OrderStatus,
    PaperOrder,
    SignalAction,
    SocialPost,
    StockCandle,
    StrategyName,
    TradingSignal,
    UniverseMember,
)

T0 = datetime(2025, 3, 3, 14, 5, tzinfo=UTC)


def make_post(**overrides: object) -> SocialPost:
    data: dict[str, object] = {
        "post_id": "1",
        "source": "file",
        "account": "acct",
        "text": "hello",
        "url": "https://example.invalid/1",
        "published_at": T0,
        "retrieved_at": T0 + timedelta(minutes=1),
        "ingestion_mode": IngestionMode.HISTORICAL,
        "content_hash": "abc",
    }
    data.update(overrides)
    return SocialPost.model_validate(data)


def test_post_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        make_post(published_at=datetime(2025, 3, 3, 14, 5))  # noqa: DTZ001


def test_post_normalises_to_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    post = make_post(published_at=datetime(2025, 3, 3, 9, 5, tzinfo=eastern))
    assert post.published_at == T0
    assert post.published_at.utcoffset() == timedelta(0)


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_post(surprise="x")


def test_event_requires_a_category() -> None:
    with pytest.raises(ValidationError):
        MarketEvent(
            event_id="e",
            post_ids=["1"],
            text="t",
            published_at=T0,
            available_at=T0,
            categories=[],
            relevance_score=0.5,
            classifier_version="rules-v1",
        )


def candle(**overrides: object) -> StockCandle:
    data: dict[str, object] = {
        "symbol": "SPY",
        "interval": "1d",
        "ts": T0,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10.0,
        "adjusted": True,
        "source": "test",
        "quality": DataQuality.SYNTHETIC,
    }
    data.update(overrides)
    return StockCandle.model_validate(data)


def test_candle_range_is_checked() -> None:
    candle()
    with pytest.raises(ValidationError):
        candle(high=100.2)  # close above high
    with pytest.raises(ValidationError):
        candle(low=100.4)  # open below low
    with pytest.raises(ValidationError):
        candle(volume=-1)
    with pytest.raises(ValidationError):
        candle(symbol="spy")


def test_universe_eligibility() -> None:
    member = UniverseMember(
        symbol="NEW",
        name="New Listing",
        kind="stock",
        sector="Tech",
        themes=[EventCategory.TECHNOLOGY_SEMICONDUCTORS],
        eligible_from=date(2024, 3, 26),
        eligible_to=date(2025, 6, 18),
    )
    assert not member.is_eligible(date(2024, 3, 25))
    assert member.is_eligible(date(2024, 3, 26))
    assert member.is_eligible(date(2025, 6, 18))
    assert not member.is_eligible(date(2025, 6, 19))


def feature(**overrides: object) -> MarketFeature:
    data: dict[str, object] = {
        "event_id": "e",
        "symbol": "SPY",
        "window": EventWindow.H1,
        "anchor_ts": T0,
        "entry_ts": T0,
        "exit_ts": T0 + timedelta(hours=1),
        "entry_price": 100.0,
        "exit_price": 101.0,
        "ret": 0.01,
        "benchmark_ret": 0.0,
        "abnormal_ret": 0.01,
        "tradable": True,
        "available": True,
        "quality": DataQuality.SYNTHETIC,
    }
    data.update(overrides)
    return MarketFeature.model_validate(data)


def test_unavailable_feature_needs_a_reason() -> None:
    with pytest.raises(ValidationError):
        feature(available=False, ret=None)
    feature(available=False, ret=None, unavailable_reason="missing candles")


def test_tradable_feature_cannot_enter_before_anchor() -> None:
    with pytest.raises(ValidationError):
        feature(entry_ts=T0 - timedelta(seconds=1))
    # A descriptive window may start before the anchor.
    feature(entry_ts=T0 - timedelta(hours=1), tradable=False, window=EventWindow.CLOSE_TO_CLOSE)


def signal(**overrides: object) -> TradingSignal:
    data: dict[str, object] = {
        "signal_id": "s",
        "event_id": "e",
        "symbol": "SPY",
        "strategy": StrategyName.IMMEDIATE_REACTION,
        "action": SignalAction.BUY,
        "generated_at": T0,
        "target_weight": 0.05,
        "holding_window": EventWindow.D1,
        "reason": "test",
    }
    data.update(overrides)
    return TradingSignal.model_validate(data)


def test_signal_weight_rules() -> None:
    signal()
    signal(action=SignalAction.NO_TRADE, target_weight=0.0)
    with pytest.raises(ValidationError):
        signal(action=SignalAction.NO_TRADE, target_weight=0.05)
    with pytest.raises(ValidationError):
        signal(target_weight=0.0)
    with pytest.raises(ValidationError):
        signal(reason="")
    with pytest.raises(ValidationError):
        signal(holding_window=EventWindow.CLOSE_TO_CLOSE)


def order(**overrides: object) -> PaperOrder:
    data: dict[str, object] = {
        "order_id": "o",
        "client_order_id": "s",
        "signal_id": "s",
        "symbol": "SPY",
        "side": OrderSide.BUY,
        "qty": 1.0,
        "status": OrderStatus.PENDING,
        "broker": "simulator",
        "created_at": T0,
    }
    data.update(overrides)
    return PaperOrder.model_validate(data)


def test_order_rules() -> None:
    order()
    with pytest.raises(ValidationError):
        order(qty=0)
    with pytest.raises(ValidationError):
        order(status=OrderStatus.BLOCKED)
    order(status=OrderStatus.BLOCKED, reject_reason="kill switch")
    with pytest.raises(ValidationError):
        order(status=OrderStatus.FILLED)
    with pytest.raises(ValidationError):
        order(broker="alpaca-live")


def test_window_properties() -> None:
    assert EventWindow.M5.duration == timedelta(minutes=5)
    assert EventWindow.H4.is_intraday
    assert not EventWindow.D1.is_intraday
    assert not EventWindow.CLOSE_TO_CLOSE.tradable
    with pytest.raises(ValueError):
        _ = EventWindow.D1.duration


def test_lowest_quality() -> None:
    assert (
        DataQuality.lowest([DataQuality.CONSOLIDATED, DataQuality.DELAYED]) is DataQuality.DELAYED
    )
    assert OrderStatus.FILLED.is_terminal and not OrderStatus.SUBMITTED.is_terminal
