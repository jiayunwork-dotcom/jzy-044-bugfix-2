"""领域内异常。"""
from __future__ import annotations

from typing import Any, Optional


class ServiceError(Exception):
    """所有可预期业务错误的基类。"""

    code: str = "service_error"
    http_status: int = 400

    def __init__(
        self,
        message: str,
        *,
        errors: Optional[list[dict[str, Any]]] = None,
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors
        self.detail = detail


class ValidationError(ServiceError):
    """非法输入（正负号、区间、物料衡算矛盾等）。"""

    code = "invalid_input"
    http_status = 422


class PresetNotFoundError(ServiceError):
    code = "preset_not_found"
    http_status = 404


class PresetConflictError(ServiceError):
    code = "preset_conflict"
    http_status = 409


class PinchError(ServiceError):
    """操作条件合法但被夹点限制：理论上需要无穷高填料层。"""

    code = "pinch_limited"
    http_status = 409

    def __init__(
        self,
        message: str,
        *,
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.detail = detail
