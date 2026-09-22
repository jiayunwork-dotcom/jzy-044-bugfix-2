"""传质内核物理性质测试。

重点守住委托方点名的三条联动：
1. Kya 放大两倍 → HOG、Z 减半，NOG 不变；
2. 远离夹点区间内加大 L/G → 气相推动力拉开、NOG 下降；
3. y1 == y2 → NOG 与 Z 均为零（合法退化）。
另含闭式积分手算核对、r=1 退化支与夹点发散判定。
"""
from __future__ import annotations

import math

import pytest

from app.errors import PinchError, ValidationError
from app.transfer import calculate_transfer
from app.validation import validate_case


def make_case(**overrides: float) -> dict[str, float]:
    base: dict[str, float] = {
        "G": 0.02, "L": 0.04, "Kya": 0.08, "a": 2.5, "S": 1.0, "m": 1.0,
        "y1": 0.10, "y2": 0.01, "x1": 0.045, "x2": 0.0,
    }
    base.update(overrides)
    return validate_case(base)


def calc(**overrides: float):
    return calculate_transfer(make_case(**overrides))


# ---------- 手算核对（内置示范工况） ----------
def test_demo_matches_hand_calculation() -> None:
    r = calc()
    # Δy1=0.055, Δy2=0.01, r=0.5 → NOG = 1/(1-0.5)·ln(5.5)
    assert r.branch == "log_mean"
    assert r.HOG == pytest.approx(0.1, rel=1e-12)
    assert r.NOG == pytest.approx(2.0 * math.log(5.5), rel=1e-12)
    assert r.Z == pytest.approx(0.1 * 2.0 * math.log(5.5), rel=1e-12)
    # (L/G)_min = m·(y1-y2)/(y1-m·x2) = 0.09/0.10 = 0.9
    assert r.min_l_over_g == pytest.approx(0.9, rel=1e-12)
    assert r.l_over_g_margin == pytest.approx(2.0 / 0.9, rel=1e-12)
    assert r.min_driving_force == pytest.approx(0.01, abs=1e-15)
    assert r.pinch_location == "塔顶"


def test_nog_integral_definition_matches_closed_form() -> None:
    """闭式结果必须与逐段数值积分 ∫dy/(y-y*) 一致。"""
    r = calc()
    n = 200_000
    dy = (0.10 - 0.01) / n
    m, x2, G, L, y2 = 1.0, 0.0, 0.02, 0.04, 0.01
    total = 0.0
    for i in range(n):
        y = y2 + (i + 0.5) * dy
        x = x2 + (G / L) * (y - y2)
        total += dy / (y - m * x)
    assert total == pytest.approx(r.NOG, rel=1e-6)


# ---------- 联动 1：Kya 翻倍 ----------
def test_doubling_kya_halves_hog_and_z_keeps_nog() -> None:
    base = calc()
    doubled = calc(Kya=0.16)
    assert doubled.HOG == pytest.approx(base.HOG / 2, rel=1e-12)
    assert doubled.Z == pytest.approx(base.Z / 2, rel=1e-12)
    assert doubled.NOG == pytest.approx(base.NOG, rel=1e-12)


def test_a_and_s_scale_hog_like_kya() -> None:
    base = calc()
    assert calc(a=5.0).HOG == pytest.approx(base.HOG / 2, rel=1e-12)
    assert calc(S=2.0).HOG == pytest.approx(base.HOG / 2, rel=1e-12)


# ---------- 联动 2：加大 L/G 降低 NOG ----------
def test_increasing_l_over_g_decreases_nog() -> None:
    # 固定 G、进出口气相分率与 x2，按物料衡算重算 x1 = x2 + G/L·(y1-y2)
    def with_L(L: float):
        x1 = (0.02 / L) * 0.09
        return calc(L=L, x1=x1)

    far = with_L(0.08)   # L/G = 4
    mid = with_L(0.06)   # L/G = 3
    near = with_L(0.04)  # L/G = 2（更靠近最小液气比 0.9）
    assert far.NOG < mid.NOG < near.NOG
    assert far.Z < mid.Z < near.Z
    # 推动力被拉开：塔底推动力与相对最小液气比的余量都变大
    assert far.delta_y_bottom > near.delta_y_bottom
    assert far.l_over_g_margin > near.l_over_g_margin


# ---------- 联动 3：y1 == y2 合法退化 ----------
def test_equal_inlet_outlet_gas_is_zero_height() -> None:
    r = calc(y1=0.05, y2=0.05, x1=0.02, x2=0.02)
    assert r.branch == "no_transfer"
    assert r.NOG == 0.0
    assert r.Z == 0.0
    # HOG 仍按几何/传质参数给出
    assert r.HOG == pytest.approx(0.1, rel=1e-12)


# ---------- r = mG/L = 1 的退化支 ----------
def test_unity_slope_ratio_uses_constant_driving_force_branch() -> None:
    # L/G = 2, m = 2 → r = 1；取 x2=0, y2=0.01, y1=0.05
    # 衡算 x1 = 0 + 0.5·0.04 = 0.02；Δy1 = 0.05-2·0.02 = 0.01 = Δy2（沿塔常数）
    r = calc(L=0.04, m=2.0, y1=0.05, y2=0.01, x1=0.02, x2=0.0)
    assert r.branch == "unity"
    assert r.NOG == pytest.approx((0.05 - 0.01) / 0.01, rel=1e-12)
    assert r.delta_y_bottom == pytest.approx(r.delta_y_top, abs=1e-15)
    assert r.Z == pytest.approx(r.HOG * r.NOG, rel=1e-12)


# ---------- 夹点判定 ----------
def test_bottom_pinch_is_rejected() -> None:
    # 夹点极限：L/G = (L/G)_min = 0.9，塔底端点落在平衡线上
    # x1 = x2 + G/L·(y1-y2) = 0.10，Δy1 = 0.10-1·0.10 = 0
    with pytest.raises(PinchError) as ei:
        calc(L=0.018, m=1.0, y1=0.10, y2=0.01, x1=0.10, x2=0.0)
    assert ei.value.detail["pinch_limited"] is True
    assert "塔底" in ei.value.detail["locations"]
    assert "L/G" in ei.value.message


def test_top_pinch_is_rejected() -> None:
    # y2 = 0, x2 = 0 → Δy2 = 0（塔顶与纯吸收剂平衡，完全净化需无穷高）
    with pytest.raises(PinchError):
        calc(L=0.04, m=1.0, y1=0.10, y2=0.0, x1=0.05, x2=0.0)


def test_unity_branch_with_zero_driving_force_is_pinch_not_crash() -> None:
    # r=1 且 Δy 恒为 0：必须判夹点，不能走到除零
    with pytest.raises(PinchError):
        calc(L=0.04, m=2.0, y1=0.05, y2=0.0, x1=0.025, x2=0.0)


def test_crossing_lines_is_rejected() -> None:
    # 两端推动力异号（Δy1=+0.02, Δy2=-0.02）：操作线在塔内越过平衡线
    with pytest.raises(PinchError):
        calc(L=0.04, m=1.0, y1=0.10, y2=0.02, x1=0.08, x2=0.04)


def test_near_pinch_drives_nog_to_infinity() -> None:
    """向夹点逼近时 NOG 必须单调发散，而不是给出虚假的有限高度。"""
    def nog_at_L(L: float) -> float:
        # 固定其余组成，按物料衡算重算 x1 = x2 + G/L·(y1-y2)
        x1 = (0.02 / L) * 0.09
        return calc(L=L, x1=x1).NOG

    nogs = [nog_at_L(L) for L in (0.025, 0.021, 0.019, 0.0182, 0.018002)]
    assert all(a < b for a, b in zip(nogs, nogs[1:]))
    assert nogs[-1] > 10 * nogs[0]
    # L = (L/G)_min·G = 0.9·0.02 = 0.018 时塔底 Δy1 = 0，判夹点
    with pytest.raises(PinchError):
        nog_at_L(0.018)


# ---------- 物料衡算 / 输入合法性（内核边界） ----------
def test_material_balance_contradiction_rejected() -> None:
    with pytest.raises(ValidationError) as ei:
        make_case(x1=0.05)  # 应为 0.045
    assert ei.value.errors and "物料衡算" in ei.value.message


def test_absorption_direction_y1_lt_y2_rejected() -> None:
    with pytest.raises(ValidationError):
        make_case(y1=0.01, y2=0.10, x1=0.0, x2=0.045)
