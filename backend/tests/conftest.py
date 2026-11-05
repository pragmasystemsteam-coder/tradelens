from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def repo() -> Path:
    return REPO


@pytest.fixture
def config_dir() -> Path:
    return REPO / "config"
