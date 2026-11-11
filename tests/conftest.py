"""Shared test fixtures. All data created here is synthetic and stays in temp directories."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.settings import Settings
from src.core.storage import DataPaths

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings isolated from the developer's environment and `.env` file."""
    return Settings(_env_file=None, data_dir=tmp_path / "data")  # type: ignore[call-arg]


@pytest.fixture
def paths(settings: Settings) -> DataPaths:
    return DataPaths(settings.data_dir)


@pytest.fixture
def posts_fixture() -> Path:
    return FIXTURES / "posts_sample.json"
