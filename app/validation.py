"""请求校验：把物理一致性要求集中挡在核算内核之外。

校验失败时抛出 :class:`app.errors.ValidationError`，携带逐条原因。
"""
from __future__ import annotations

from typing import Any, Mapping

from .config import settings
from .errors import ValidationError
from .schemas import CASE_FIELDS

# 必须严格为正的量
_POSITIVE_FIELDS = ("G", "L", "Kya", "a", "S")
# 摩尔分率（落在闭区间 [0, 1]）
_FRACTION_FIELDS = ("y1", "y2", "x1", "x2")


def validate_case(data: Mapping[str, Any]) -> dict[str, float]:
    """校验一整套已补全的操作条件，返回纯净的浮点字典。

    收集所有问题一次性返回，便于调用方（尤其批量接口）定位错误条目。
    """
    problems: list[dict[str, str]] = []

    # 1) 字段齐全
    missing = [f for f in CASE_FIELDS if data.get(f) is None]
    if missing:
        problems.append({"field": ",".join(missing), "reason": "缺少必填参数"})

    values: dict[str, float] = {}
    for f in CASE_FIELDS:
        v = data.get(f)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            problems.append({"field": f, "reason": "必须是数值"})
            continue
        fv = float(v)
        if fv != fv or fv in (float("inf"), float("-inf")):
            problems.append({"field": f, "reason": "必须是有限数值"})
            continue
        values[f] = fv

    if problems:
        raise ValidationError("输入参数不合法", errors=problems)

    # 2) 正量与区间
    for f in _POSITIVE_FIELDS:
        if values[f] <= 0.0:
            problems.append({"field": f, "reason": f"{f} 必须为正数"})

    if values["m"] < 0.0:
        problems.append({"field": "m", "reason": "平衡线斜率 m 不能为负"})

    for f in _FRACTION_FIELDS:
        if not 0.0 <= values[f] <= 1.0:
            problems.append({"field": f, "reason": f"{f} 是摩尔分率，必须落在 [0, 1]"})

    # 3) 吸收方向：塔底进气 y1 不得小于塔顶出气 y2（逆流吸收）
    if values["y1"] < values["y2"]:
        problems.append({
            "field": "y1,y2",
            "reason": "塔底气相分率 y1 不得小于塔顶 y2（与逆流吸收方向矛盾）",
        })

    if problems:
        raise ValidationError("输入参数不合法", errors=problems)

    # 4) 全塔物料衡算自洽：G·(y1-y2) = L·(x1-x2)
    gas_side = values["G"] * (values["y1"] - values["y2"])
    liq_side = values["L"] * (values["x1"] - values["x2"])
    scale = max(abs(gas_side), abs(liq_side), values["G"], values["L"], 1.0)
    if abs(gas_side - liq_side) > settings.balance_rel_tol * scale:
        raise ValidationError(
            "进出口分率与物料衡算自相矛盾：要求 G·(y1-y2) = L·(x1-x2)",
            errors=[{
                "field": "G,L,y1,y2,x1,x2",
                "reason": (
                    f"气相侧 G(y1-y2)={gas_side:.6g} 与液相侧 L(x1-x2)={liq_side:.6g} "
                    f"不一致，超过相对容差 {settings.balance_rel_tol:g}"
                ),
            }],
        )

    # 物料衡算 + y1>=y2 已隐含 x1>=x2（G,L>0），这里显式兜底一次。
    if values["x1"] < values["x2"]:
        raise ValidationError(
            "液相进出口方向与物料衡算矛盾",
            errors=[{"field": "x1,x2", "reason": "塔底液相分率 x1 不得小于塔顶 x2"}],
        )

    return values
