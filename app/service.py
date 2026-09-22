"""核算服务层：工况档合并 → 校验 → 传质内核 → 响应组装。"""
from __future__ import annotations

from typing import Any, Optional

from .errors import ServiceError
from .presets import PresetRepository
from .schemas import CASE_FIELDS
from .transfer import calculate_transfer, result_to_dict
from .validation import validate_case


def resolve_inputs(req: Any, presets: PresetRepository) -> dict[str, float]:
    """把单次请求（可能引用工况档、可能带临时覆盖）解析为完整参数。"""
    overrides = {f: getattr(req, f) for f in CASE_FIELDS}
    if req.preset is not None:
        return presets.resolve(req.preset, overrides)
    return overrides


def run_calculation(req: Any, presets: PresetRepository) -> dict[str, Any]:
    """执行一次核算并返回成功响应体。非法/夹点以异常上抛由路由层处理。"""
    merged = resolve_inputs(req, presets)
    values = validate_case(merged)
    result = calculate_transfer(values)
    body = result_to_dict(result)
    body["preset"] = req.preset
    return body


def run_calculation_safe(index: int, req: Any, presets: PresetRepository) -> dict[str, Any]:
    """批量用：单条异常不外泄，转为该条目的错误对象，其余条目互不牵连。"""
    try:
        body = run_calculation(req, presets)
        return {"index": index, "ok": True, "result": body}
    except ServiceError as exc:
        item: dict[str, Any] = {
            "index": index,
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }
        if exc.errors:
            item["error"]["errors"] = exc.errors
        if exc.detail:
            item["error"]["detail"] = exc.detail
        return item
