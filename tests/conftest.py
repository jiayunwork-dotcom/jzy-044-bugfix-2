"""pytest 夹具：每个测试使用独立临时工况档文件，互不污染。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

# 与内置示范工况一致的完整内联参数
DEMO_CASE: dict[str, float] = {
    "G": 0.02, "L": 0.04, "Kya": 0.08, "a": 2.5, "S": 1.0, "m": 1.0,
    "y1": 0.10, "y2": 0.01, "x1": 0.045, "x2": 0.0,
}


@pytest.fixture()
def preset_path(tmp_path: pytest.TempPathFactory) -> str:
    return str(tmp_path / "presets.json")


@pytest.fixture()
def client(preset_path: str) -> TestClient:
    app = create_app(preset_path)
    with TestClient(app) as c:
        yield c
