"""传质内核：HOG、NOG 积分（对数平均推动力封闭解）与夹点判定。

闭式推导（稀相、平衡线与操作线均为直线）
----------------------------------------
沿塔高对气相总推动力积分：

    NOG = ∫_{y2}^{y1} dy / (y - y*)

由操作线 y = (L/G)(x - x2) + y2 反解 x，代入平衡线 y* = m·x：

    y - y* = (1 - mG/L)·y + (mG/L)·y2 - m·x2

推动力是 y 的线性函数。两端点处：

    Δy1 = y1 - m·x1 （塔底）,  Δy2 = y2 - m·x2 （塔顶）

* 当 r = m·G/L ≠ 1 时，

      NOG = 1/(1-r) · ln(Δy1/Δy2)

* 当 r = 1 时，Δy 沿塔为常数，退化为

      NOG = (y1 - y2) / Δy2

夹点
----
操作线与平衡线相切/相交时，某点 Δy → 0，积分发散（塔无穷高）。
本模块在 Δy1 <= tol、Δy2 <= tol 或两端异号（两线交叉）时判为夹点受限并拒绝，
绝不返回虚假的有限高度。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from .config import settings
from .errors import PinchError
from .operating_line import OperatingLine


@dataclass(frozen=True)
class TransferResult:
    HOG: float
    NOG: float
    Z: float
    r: float                       # 斜率比 m·G/L
    delta_y_bottom: float          # Δy1
    delta_y_top: float             # Δy2
    l_over_g: float                # 当前 L/G
    min_l_over_g: Optional[float]  # 最小液气比
    l_over_g_margin: Optional[float]  # (L/G)/(L/G)_min
    min_driving_force: float       # 全程最小气相推动力（绝对值意义上的最小正值）
    pinch_location: Optional[str]  # 最小推动力出现位置
    branch: str                    # log_mean | unity | no_transfer


def calc_HOG(G: float, Kya: float, a: float, S: float) -> float:
    """传质单元高度 HOG = G / (Kya·a·S)。

    说明：按委托方给定的公式字面实现；Kya 为体积传质系数、a 为比表面积、
    S 为塔截面积，G 以塔截面单位面积为基准。
    """
    return G / (Kya * a * S)


def _log_mean_driving_force(d1: float, d2: float) -> float:
    """对数平均推动力 Δy_lm = (Δy1 - Δy2)/ln(Δy1/Δy2)，数值稳定实现。"""
    if math.isclose(d1, d2, rel_tol=1e-14, abs_tol=0.0):
        return d1
    # log1p((d1-d2)/d2) = ln(d1/d2)，避免近夹点/近相等时的相消
    ratio_term = (d1 - d2) / d2
    return (d1 - d2) / math.log1p(ratio_term)


def _assess_pinch(op: OperatingLine) -> None:
    """检查夹点（含平衡线与操作线相切、相交、交叉）。命中即抛 PinchError。"""
    d1 = op.delta_y_bottom
    d2 = op.delta_y_top
    tol = settings.pinch_abs_tol

    locations: list[str] = []
    if d1 <= tol:
        locations.append("塔底")
    if d2 <= tol:
        locations.append("塔顶")

    if not locations:
        return

    # 区分“切于一点（夹点）”与“两线交叉（操作线越过平衡线，物理不可行）”
    crosses = d1 < -tol or d2 < -tol
    if crosses:
        msg = (
            "操作线与平衡线在塔内相交（气相推动力 y-y* 变号），"
            "该液气比无法实现规定的吸收要求；请提高液气比 L/G 拉开推动力。"
        )
    else:
        where = "、".join(locations)
        msg = (
            f"操作线在{where}与平衡线相切，局部气相推动力 y-y* 趋于零，"
            "NOG 积分发散、理论上需要无穷高的填料层（夹点受限）。"
            "必须提高液气比 L/G（或降低平衡线斜率 m、提高吸收剂入口纯度）以拉开推动力。"
        )

    detail = {
        "pinch_limited": True,
        "locations": locations,
        "delta_y_bottom": d1,
        "delta_y_top": d2,
        "l_over_g": op.slope,
        "min_l_over_g": op.min_L_over_G(),
        "l_over_g_margin": op.L_over_G_margin(),
    }
    raise PinchError(msg, detail=detail)


def _distance_to_pinch(op: OperatingLine) -> dict[str, Any]:
    """汇总“这套操作条件离夹点还有多远”的可核对指标。"""
    d1 = op.delta_y_bottom
    d2 = op.delta_y_top
    min_df = min(d1, d2)
    location = "塔底" if d1 <= d2 else "塔顶"
    return {
        "min_driving_force": min_df,
        "min_driving_force_location": location,
        "delta_y_bottom": d1,
        "delta_y_top": d2,
        "l_over_g": op.slope,
        "min_l_over_g": op.min_L_over_G(),
        # (L/G)/(L/G)_min：>1 的倍数即当前液气比高出夹点极限的余量
        "l_over_g_margin": op.L_over_G_margin(),
    }


def calculate_transfer(vals: dict[str, float]) -> TransferResult:
    """对一整套已校验的操作条件执行传质高度核算。"""
    op = OperatingLine(
        G=vals["G"], L=vals["L"], m=vals["m"],
        x1=vals["x1"], x2=vals["x2"], y1=vals["y1"], y2=vals["y2"],
    )
    hog = calc_HOG(vals["G"], vals["Kya"], vals["a"], vals["S"])

    # 合法退化：进、出口气相分率相同 → 无净传质 → NOG = Z = 0
    if op.y1 == op.y2:
        return TransferResult(
            HOG=hog, NOG=0.0, Z=0.0, r=op.ratio_mG_over_L,
            delta_y_bottom=op.delta_y_bottom, delta_y_top=op.delta_y_top,
            l_over_g=op.slope, min_l_over_g=op.min_L_over_G(),
            l_over_g_margin=op.L_over_G_margin(),
            min_driving_force=min(op.delta_y_bottom, op.delta_y_top),
            pinch_location=None, branch="no_transfer",
        )

    # 夹点 / 交叉判定（Δy1、Δy2 触零或变号即拒绝）
    _assess_pinch(op)

    d1 = op.delta_y_bottom
    d2 = op.delta_y_top
    r = op.ratio_mG_over_L

    # 斜率比等于 1：推动力沿塔为常数，走退化支；否则走对数平均推动力支
    if math.isclose(r, 1.0, rel_tol=settings.unity_rel_tol, abs_tol=0.0):
        nog = (op.y1 - op.y2) / d2
        branch = "unity"
    else:
        lm = _log_mean_driving_force(d1, d2)
        nog = (op.y1 - op.y2) / lm
        branch = "log_mean"

    dist = _distance_to_pinch(op)
    return TransferResult(
        HOG=hog, NOG=nog, Z=hog * nog, r=r,
        delta_y_bottom=d1, delta_y_top=d2,
        l_over_g=op.slope, min_l_over_g=dist["min_l_over_g"],
        l_over_g_margin=dist["l_over_g_margin"],
        min_driving_force=dist["min_driving_force"],
        pinch_location=dist["min_driving_force_location"], branch=branch,
    )


def result_to_dict(res: TransferResult) -> dict[str, Any]:
    """把核算结果（含离夹点距离）序列化为响应字典。"""
    return {
        "HOG": res.HOG,
        "NOG": res.NOG,
        "Z": res.Z,
        "pinch_limited": False,
        "branch": res.branch,
        "ratio_mG_over_L": res.r,
        "driving_force": {
            "delta_y_bottom": res.delta_y_bottom,
            "delta_y_top": res.delta_y_top,
            "min": res.min_driving_force,
            "min_location": res.pinch_location,
        },
        "distance_to_pinch": {
            "min_driving_force": res.min_driving_force,
            "min_driving_force_location": res.pinch_location,
            "l_over_g": res.l_over_g,
            "min_l_over_g": res.min_l_over_g,
            "l_over_g_margin": res.l_over_g_margin,
        },
    }
