import copy
from pathlib import Path

import pytest

from src.rules import Corpus

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-10-28"


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", help="启用真实 API 集成与变异测试，会产生模型调用费用")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-live"):
        marker = pytest.mark.skip(reason="Live 未启用；配置凭证后使用 --run-live")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(marker)


@pytest.fixture
def corpus():
    return Corpus.load(ROOT / "data/documents.json")


@pytest.fixture
def raw(corpus):
    return copy.deepcopy(corpus.data)
