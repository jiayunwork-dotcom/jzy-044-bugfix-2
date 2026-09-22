"""HTTP 请求/响应的数据模型（Pydantic）。

这里只负责字段存在性、类型与数值有限性；
业务校验（正负号、摩尔分率区间、物料衡算、吸收方向）在
``app.validation`` 中集中处理，以便核算内核可以被独立复用。
"""
from __future__ import annotations

import math
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 一套操作条件里的全部物理量。工况档登记、单次核算、批量条目共用同一组字段。
CASE_FIELDS: tuple[str, ...] = (
    "G", "L", "Kya", "a", "S", "m",
    "y1", "y2", "x1", "x2",
)


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是数值")
    fv = float(value)
    if not math.isfinite(fv):
        raise ValueError(f"{name} 必须是有限数值（不能为 NaN 或无穷）")
    return fv


class CaseInput(BaseModel):
    """单条操作条件（全部必填，除非通过已登记工况档补全）。"""

    model_config = ConfigDict(extra="forbid")

    G: Optional[float] = Field(default=None, description="气相摩尔流量，以塔截面单位面积为基准")
    L: Optional[float] = Field(default=None, description="液相摩尔流量，以塔截面单位面积为基准")
    Kya: Optional[float] = Field(default=None, description="气相总（体积）传质系数")
    a: Optional[float] = Field(default=None, description="填料比表面积")
    S: Optional[float] = Field(default=None, description="塔截面积")
    m: Optional[float] = Field(default=None, description="亨利型平衡关系 y*=m·x 的斜率")
    y1: Optional[float] = Field(default=None, description="塔底气相摩尔分率")
    y2: Optional[float] = Field(default=None, description="塔顶气相摩尔分率")
    x1: Optional[float] = Field(default=None, description="塔底液相摩尔分率")
    x2: Optional[float] = Field(default=None, description="塔顶液相摩尔分率")

    @field_validator(*CASE_FIELDS)
    @classmethod
    def _check_finite(cls, v: Any, info: Any) -> Optional[float]:
        if v is None:
            return None
        return _finite_float(v, info.field_name)


class CalculationRequest(CaseInput):
    """单次核算请求：可点名工况档，并临时覆盖其中任意字段。"""

    model_config = ConfigDict(extra="forbid")

    preset: Optional[str] = Field(default=None, description="已登记工况档名称")


class BatchCalculationRequest(BaseModel):
    """批量核算请求。"""

    model_config = ConfigDict(extra="forbid")

    cases: list[CalculationRequest] = Field(..., min_length=1, description="待核算操作条件列表")


class PresetInput(CaseInput):
    """登记/更新工况档：允许只给部分字段（调用时再与临时参数合并）。"""

    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = Field(default=None, description="工况档说明")


class PresetOut(BaseModel):
    name: str
    description: Optional[str] = None
    params: dict[str, float]
    builtin: bool


# 成功响应是普通 dict；错误与夹点响应使用下面两个模型约束结构。
class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    errors: Optional[list[dict[str, Any]]] = None
    detail: Optional[dict[str, Any]] = None
