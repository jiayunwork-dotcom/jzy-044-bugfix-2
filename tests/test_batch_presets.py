"""批量核算隔离、工况档持久化（跨“重启”）与并发安全测试。"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.presets import PresetRepository

from .conftest import DEMO_CASE


# ---------- 批量：个别失败不牵连其余 ----------
def test_batch_mixed_valid_invalid_pinch(client) -> None:
    cases = [
        DEMO_CASE,                                   # 0 合法
        dict(DEMO_CASE, x1=0.05),                    # 1 衡算矛盾
        dict(DEMO_CASE, L=0.018, x1=0.10),  # 2 夹点（Δy1=0）
        dict(DEMO_CASE, Kya=0.16),                   # 3 合法（Kya 翻倍）
    ]
    r = client.post("/calculate/batch", json={"cases": cases})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 4 and data["ok_count"] == 2 and data["failed_count"] == 2

    results = data["results"]
    assert [it["index"] for it in results] == [0, 1, 2, 3]
    assert results[0]["ok"] and results[3]["ok"]
    assert not results[1]["ok"] and results[1]["error"]["code"] == "invalid_input"
    assert not results[2]["ok"] and results[2]["error"]["code"] == "pinch_limited"

    # 联动性质在批量结果里同样成立
    assert results[3]["result"]["Z"] == results[0]["result"]["Z"] / 2
    assert results[3]["result"]["NOG"] == results[0]["result"]["NOG"]


def test_batch_empty_rejected(client) -> None:
    r = client.post("/calculate/batch", json={"cases": []})
    assert r.status_code == 422


def test_batch_wrong_shape_does_not_500(client) -> None:
    r = client.post("/calculate/batch", json={"cases": "not-a-list"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


def test_batch_unknown_field_in_case_rejected(client) -> None:
    r = client.post("/calculate/batch", json={"cases": [{**DEMO_CASE, "x": 1}]})
    assert r.status_code == 422


def test_batch_preset_and_inline_together(client) -> None:
    r = client.post("/calculate/batch", json={"cases": [
        {"preset": "demo_air_water"},
        {"preset": "demo_air_water", "Kya": 0.16},
        {"preset": "no_such_preset"},
    ]})
    data = r.json()
    assert data["results"][0]["ok"]
    assert data["results"][1]["ok"]
    assert data["results"][1]["result"]["Z"] == data["results"][0]["result"]["Z"] / 2
    assert not data["results"][2]["ok"]
    assert data["results"][2]["error"]["code"] == "preset_not_found"


def test_batch_unknown_preset_isolated_per_item(client) -> None:
    # 未登记档名单独提交时是该条 404，混进批量时也只能拖垮它自己这一条
    solo = client.post("/calculate", json={"preset": "never_registered"})
    assert solo.status_code == 404
    assert solo.json()["error"]["code"] == "preset_not_found"

    r = client.post("/calculate/batch", json={"cases": [
        DEMO_CASE,                          # 0 合法（临时参数）
        {"preset": "never_registered"},     # 1 档名未登记
        {"preset": "demo_air_water"},       # 2 合法（点名内置档）
    ]})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 3 and data["ok_count"] == 2 and data["failed_count"] == 1
    results = data["results"]
    assert results[0]["ok"] and results[2]["ok"]
    assert not results[1]["ok"]
    assert results[1]["error"]["code"] == "preset_not_found"
    assert "未登记" in results[1]["error"]["message"]


# ---------- 工况档：登记、点名、覆盖、删除、内置保护 ----------
def test_preset_crud_and_builtin_protection(client) -> None:
    body = {"description": "试验档", **DEMO_CASE, "Kya": 0.04}
    r = client.post("/presets/tower-a", json=body)
    assert r.status_code == 201
    assert r.json()["name"] == "tower-a"

    # 重复创建冲突
    assert client.post("/presets/tower-a", json=body).status_code == 409

    # 点名使用
    calc = client.post("/calculate", json={"preset": "tower-a"})
    assert calc.status_code == 200
    assert calc.json()["HOG"] == pytest.approx(0.2)

    # 临时参数覆盖工况档
    calc2 = client.post("/calculate", json={"preset": "tower-a", "Kya": 0.08})
    assert calc2.json()["HOG"] == pytest.approx(0.1)

    # 列表含内置与自定义
    names = {p["name"] for p in client.get("/presets").json()}
    assert {"demo_air_water", "tower-a"} <= names

    # 删除
    assert client.delete("/presets/tower-a").status_code == 204
    assert client.post("/calculate", json={"preset": "tower-a"}).status_code == 404

    # 内置工况档受保护
    assert client.delete("/presets/demo_air_water").status_code == 409
    assert client.put("/presets/demo_air_water", json=DEMO_CASE).status_code == 409


def test_preset_invalid_full_params_rejected_at_registration(client, tmp_path) -> None:
    bad = dict(DEMO_CASE, G=-1)
    r = client.post("/presets/bad", json=bad)
    assert r.status_code == 422
    assert client.get("/presets/bad").status_code == 404


def test_partial_preset_completed_by_overrides(tmp_path) -> None:
    repo = PresetRepository(str(tmp_path / "p.json"))
    repo.create("geo", {"Kya": 0.08, "a": 2.5, "S": 1.0}, "仅几何档")
    # 用临时参数补齐其余字段后可算
    cl = TestClient(create_app(str(tmp_path / "p.json")))
    r = cl.post("/calculate", json={"preset": "geo", **{
        k: v for k, v in DEMO_CASE.items() if k in ("G", "L", "m", "y1", "y2", "x1", "x2")
    }})
    assert r.status_code == 200


# ---------- 持久化：进程重启后仍可点名 ----------
def test_presets_survive_process_restart(tmp_path) -> None:
    path = str(tmp_path / "presets.json")
    c1 = TestClient(create_app(path))
    assert c1.post("/presets/keep", json={"description": "d", **DEMO_CASE}).status_code == 201
    assert os.path.exists(path)

    # 模拟重启：重新建 app（重新加载文件）
    c2 = TestClient(create_app(path))
    r = c2.post("/calculate", json={"preset": "keep"})
    assert r.status_code == 200
    assert r.json()["Z"] > 0
    # 文件确实是合法 JSON 且包含该档
    with open(path, encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert "keep" in on_disk and "demo_air_water" in on_disk


# ---------- 并发：核算无状态、登记互不写串 ----------
def test_concurrent_calculations_are_independent(client) -> None:
    barrier = threading.Barrier(8)

    def one(i: int) -> tuple[int, float]:
        barrier.wait()
        kya = 0.08 * (1 + i)
        r = client.post("/calculate", json=dict(DEMO_CASE, Kya=kya))
        return r.status_code, r.json()["HOG"]

    with ThreadPoolExecutor(max_workers=8) as ex:
        outs = list(ex.map(one, range(8)))
    assert all(code == 200 for code, _ in outs)
    hogs = [hog for _, hog in outs]
    expected = [0.1 / (1 + i) for i in range(8)]
    for got, exp in zip(sorted(hogs, reverse=True), sorted(expected, reverse=True)):
        assert got == pytest.approx(exp)


def test_concurrent_preset_writes_do_not_corrupt(tmp_path) -> None:
    path = str(tmp_path / "p.json")
    c = TestClient(create_app(path))

    def register(i: int) -> int:
        return c.post(f"/presets/c{i}", json={"description": str(i), **DEMO_CASE}).status_code

    with ThreadPoolExecutor(max_workers=8) as ex:
        codes = list(ex.map(register, range(16)))
    assert codes.count(201) == 16

    # 重启后 16 个档全部在，文件未损坏
    c2 = TestClient(create_app(path))
    names = {p["name"] for p in c2.get("/presets").json()}
    assert {f"c{i}" for i in range(16)} <= names
