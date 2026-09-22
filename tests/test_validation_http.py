"""非法输入的 HTTP 层测试：逐条原因、状态码与批量隔离。"""
from __future__ import annotations

import pytest

from .conftest import DEMO_CASE, client


def _post_calc(cl, body: dict):
    return cl.post("/calculate", json=body)


def test_valid_demo_case_ok(client) -> None:
    r = _post_calc(client, DEMO_CASE)
    assert r.status_code == 200
    body = r.json()
    assert body["pinch_limited"] is False
    assert body["HOG"] > 0 and body["NOG"] > 0 and body["Z"] > 0


@pytest.mark.parametrize("field", ["G", "L", "Kya", "a", "S"])
def test_nonpositive_quantities_rejected(client, field: str) -> None:
    case = dict(DEMO_CASE)
    case[field] = 0.0
    r = _post_calc(client, case)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_input"
    assert any(e["field"] == field for e in err["errors"])


@pytest.mark.parametrize("field,value", [
    ("y1", 1.2), ("y2", -0.1), ("x1", 2.0), ("x2", -0.0001),
])
def test_fraction_out_of_range_rejected(client, field: str, value: float) -> None:
    # 给越界值时同时放开衡算字段，确保先/同时被区间校验挡回
    case = dict(DEMO_CASE)
    case[field] = value
    r = _post_calc(client, case)
    assert r.status_code == 422
    assert any(e["field"] == field for e in r.json()["error"]["errors"])


def test_material_balance_contradiction_rejected(client) -> None:
    case = dict(DEMO_CASE, x1=0.05)
    r = _post_calc(client, case)
    assert r.status_code == 422
    assert "物料衡算" in r.json()["error"]["message"]


def test_missing_field_rejected(client) -> None:
    case = dict(DEMO_CASE)
    del case["Kya"]
    r = _post_calc(client, case)
    assert r.status_code == 422
    assert any("Kya" in e["field"] for e in r.json()["error"]["errors"])


def test_unknown_field_rejected(client) -> None:
    r = _post_calc(client, {**DEMO_CASE, "bogus": 1})
    assert r.status_code == 422


def test_nan_and_infinity_rejected(client) -> None:
    for token in ("NaN", "Infinity"):
        r = client.post("/calculate", content=(
            '{"G":' + token + ',"L":0.04,"Kya":0.08,"a":2.5,"S":1,"m":1,'
            '"y1":0.1,"y2":0.01,"x1":0.045,"x2":0}'
        ), headers={"content-type": "application/json"})
        assert r.status_code == 422


def test_negative_m_rejected(client) -> None:
    # 若 m 为负，衡算也会被破坏，这里只要求 422 且不产生结果
    case = dict(DEMO_CASE, m=-1.0, x1=-0.045)
    r = _post_calc(client, case)
    assert r.status_code == 422


def test_equal_gas_composition_legal_degenerate(client) -> None:
    case = dict(DEMO_CASE, y1=0.03, y2=0.03, x1=0.02, x2=0.02)
    r = _post_calc(client, case)
    assert r.status_code == 200
    body = r.json()
    assert body["NOG"] == 0.0
    assert body["Z"] == 0.0
    assert body["HOG"] > 0


def test_pinch_returns_409_and_no_finite_height(client) -> None:
    pinch_case = dict(DEMO_CASE, L=0.018, x1=0.10)  # Δy1=0
    r = _post_calc(client, pinch_case)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "pinch_limited"
    assert err["detail"]["pinch_limited"] is True
    assert "L/G" in err["message"]
    # 关键：响应里不得出现伪造的有限高度字段
    assert "Z" not in err and "NOG" not in err
