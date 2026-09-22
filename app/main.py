"""FastAPI 应用：稀溶质气液逆流吸收塔传质高度核算。

仅经 HTTP 对外提供能力，不含前端。应用通过 ``create_app`` 工厂创建，
便于测试注入独立的工况档存储路径。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from . import __version__
from .config import settings
from .errors import (
    PinchError,
    PresetConflictError,
    PresetNotFoundError,
    ServiceError,
    ValidationError as DomainValidationError,
)
from .presets import BUILTIN_PRESETS, PresetRepository
from .schemas import (
    BatchCalculationRequest,
    CalculationRequest,
    PresetInput,
    PresetOut,
)
from .service import run_calculation, run_calculation_safe


def _json_safe(value: Any) -> Any:
    """把可能含 NaN/Inf 的 Pydantic 错误输入转为可安全 JSON 序列化的形式。"""
    import math

    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _error_response(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    for k, v in extra.items():
        if v is not None:
            payload["error"][k] = v
    return JSONResponse(status_code=status, content=payload)


def create_app(presets_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(
        title="填料吸收塔传质高度核算服务",
        version=__version__,
        description=(
            "计算稀溶质气液逆流吸收塔的 HOG、NOG、填料层高度 Z，"
            "并判定操作条件离夹点（最小液气比）的距离。"
        ),
    )
    repo = PresetRepository(presets_path or settings.presets_path)

    def get_repo() -> PresetRepository:
        return repo

    # ---------- 全局异常 -> 统一错误结构 ----------
    @app.exception_handler(ServiceError)
    async def _on_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        extra: dict[str, Any] = {}
        if exc.errors:
            extra["errors"] = exc.errors
        if exc.detail:
            extra["detail"] = exc.detail
        return _error_response(exc.http_status, exc.code, exc.message, **extra)

    @app.exception_handler(PydanticValidationError)
    async def _on_pydantic_error(_: Request, exc: PydanticValidationError) -> JSONResponse:
        problems = []
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"] if p not in ("body", "cases"))
            problem: dict[str, Any] = {"field": loc, "reason": e["msg"]}
            safe_input = _json_safe(e.get("input"))
            if safe_input is not None and not isinstance(safe_input, (dict, list)):
                problem["input"] = safe_input
            problems.append(problem)
        return _error_response(
            422, "invalid_input", "请求体不符合接口模式", errors=problems
        )

    # FastAPI 请求体校验抛的是 RequestValidationError（更具体的子类），
    # 必须显式注册同一处理器，否则会走默认处理器并把 NaN 等带回 JSON 序列化。
    app.add_exception_handler(RequestValidationError, _on_pydantic_error)

    # ---------- 元信息 ----------
    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, Any]:
        return {
            "service": "packed-absorber-transfer-height",
            "version": __version__,
            "docs": "/docs",
            "endpoints": [
                "POST /calculate",
                "POST /calculate/batch",
                "GET  /presets",
                "POST /presets/{name}",
                "PUT  /presets/{name}",
                "DELETE /presets/{name}",
                "GET  /presets/{name}",
            ],
        }

    # ---------- 单次核算 ----------
    @app.post("/calculate", tags=["calculation"])
    async def calculate(req: CalculationRequest, presets: PresetRepository = Depends(get_repo)) -> dict[str, Any]:
        # 夹点受限以 PinchError(409) 经异常处理器返回，不返回虚假有限高度
        return run_calculation(req, presets)

    # ---------- 批量核算 ----------
    @app.post("/calculate/batch", tags=["calculation"])
    async def calculate_batch(
        req: BatchCalculationRequest,
        presets: PresetRepository = Depends(get_repo),
    ) -> dict[str, Any]:
        # 逐条核算：个别条目非法或夹点不影响其余条目
        items = [run_calculation_safe(i, c, presets) for i, c in enumerate(req.cases)]
        return {
            "count": len(items),
            "ok_count": sum(1 for it in items if it["ok"]),
            "failed_count": sum(1 for it in items if not it["ok"]),
            "results": items,
        }

    # ---------- 工况档管理 ----------
    @app.get("/presets", tags=["presets"], response_model=list[PresetOut])
    async def list_presets(presets: PresetRepository = Depends(get_repo)) -> list[dict[str, Any]]:
        return presets.list_presets()

    @app.get("/presets/{name}", tags=["presets"], response_model=PresetOut)
    async def get_preset(name: str, presets: PresetRepository = Depends(get_repo)) -> dict[str, Any]:
        return presets.get(name)

    @app.post("/presets/{name}", tags=["presets"], response_model=PresetOut, status_code=201)
    async def create_preset(
        name: str,
        body: PresetInput,
        presets: PresetRepository = Depends(get_repo),
    ) -> dict[str, Any]:
        params = body.model_dump(exclude_none=True)
        description = params.pop("description", body.description)
        return presets.create(name, params, description)

    @app.put("/presets/{name}", tags=["presets"], response_model=PresetOut)
    async def upsert_preset(
        name: str,
        body: PresetInput,
        presets: PresetRepository = Depends(get_repo),
    ) -> dict[str, Any]:
        params = body.model_dump(exclude_none=True)
        description = params.pop("description", body.description)
        return presets.create(name, params, description, overwrite=True)

    @app.delete("/presets/{name}", tags=["presets"], status_code=204)
    async def delete_preset(name: str, presets: PresetRepository = Depends(get_repo)) -> JSONResponse:
        presets.delete(name)
        return JSONResponse(status_code=204, content=None)

    return app


app = create_app()
