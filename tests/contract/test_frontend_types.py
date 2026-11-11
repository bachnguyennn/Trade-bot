"""The dashboard's TypeScript types must match the backend contracts field for field."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from src import contracts
from src.api.routers.events import EventDetail
from src.api.routers.research import BacktestSummary
from src.backtesting.event_study import EventStudyReport, WindowStats
from src.contracts import (
    DataQuality,
    Direction,
    EventCategory,
    EventWindow,
    OrderSide,
    OrderStatus,
    SignalAction,
    StrategyName,
)
from src.ml.evaluation import ModelReport, SplitInfo
from src.trading.broker import Position
from src.trading.service import Portfolio, RiskState

TYPES_FILE = Path(__file__).parents[2] / "frontend" / "src" / "api" / "types.ts"
SOURCE = TYPES_FILE.read_text(encoding="utf-8")

_INTERFACE = re.compile(
    r"export interface (?P<name>\w+)(?: extends (?P<base>\w+))? \{(?P<body>.*?)\n\}", re.DOTALL
)
_FIELD = re.compile(r"^\s{2}(\w+)\??:", re.MULTILINE)
_UNION = re.compile(r"export type (?P<name>\w+) =(?P<body>[^;]+);", re.DOTALL)


def interface_fields(name: str) -> set[str]:
    for match in _INTERFACE.finditer(SOURCE):
        if match.group("name") == name:
            fields = set(_FIELD.findall(match.group("body")))
            if match.group("base"):
                fields |= interface_fields(match.group("base"))
            return fields
    raise AssertionError(f"interface {name} not found in types.ts")


def union_values(name: str) -> set[str]:
    for match in _UNION.finditer(SOURCE):
        if match.group("name") == name:
            return set(re.findall(r'"([^"]+)"', match.group("body")))
    raise AssertionError(f"type {name} not found in types.ts")


MODELS: dict[str, type[BaseModel]] = {
    "SocialPost": contracts.SocialPost,
    "Entity": contracts.Entity,
    "MarketEvent": contracts.MarketEvent,
    "StockCandle": contracts.StockCandle,
    "UniverseMember": contracts.UniverseMember,
    "MarketFeature": contracts.MarketFeature,
    "ModelPrediction": contracts.ModelPrediction,
    "TradingSignal": contracts.TradingSignal,
    "BacktestMetrics": contracts.BacktestMetrics,
    "EquityPoint": contracts.EquityPoint,
    "BacktestTrade": contracts.BacktestTrade,
    "BacktestResult": contracts.BacktestResult,
    "OrderStatusChange": contracts.OrderStatusChange,
    "PaperOrder": contracts.PaperOrder,
    "BacktestSummary": BacktestSummary,
    "EventDetail": EventDetail,
    "WindowStats": WindowStats,
    "EventStudyReport": EventStudyReport,
    "SplitInfo": SplitInfo,
    "ModelReport": ModelReport,
    "Position": Position,
    "Portfolio": Portfolio,
    "RiskState": RiskState,
}


@pytest.mark.parametrize("name", sorted(MODELS))
def test_interface_matches_model(name: str) -> None:
    assert interface_fields(name) == set(MODELS[name].model_fields), name


@pytest.mark.parametrize(
    ("name", "enum"),
    [
        ("EventCategory", EventCategory),
        ("EventWindow", EventWindow),
        ("DataQuality", DataQuality),
        ("Direction", Direction),
        ("SignalAction", SignalAction),
        ("StrategyName", StrategyName),
        ("OrderSide", OrderSide),
        ("OrderStatus", OrderStatus),
    ],
)
def test_union_matches_enum(name: str, enum: type) -> None:
    assert union_values(name) == {member.value for member in enum}  # type: ignore[attr-defined]
