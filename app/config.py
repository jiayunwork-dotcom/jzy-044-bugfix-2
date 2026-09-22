"""运行期配置。

默认值可被同名环境变量覆盖，便于容器化部署与测试隔离。
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    # 工况档持久化文件
    presets_path: str = os.environ.get("PRESETS_PATH", "data/presets.json")
    # 全塔物料衡算的相对容差：|G(y1-y2) - L(x1-x2)| <= tol * max(...)
    balance_rel_tol: float = _get_float("BALANCE_REL_TOL", 1e-6)
    # 判定“平衡线与操作线相切/相交（夹点）”的绝对推动力阈值
    pinch_abs_tol: float = _get_float("PINCH_ABS_TOL", 1e-9)
    # 判定斜率比 mG/L == 1（退化支）的相对容差
    unity_rel_tol: float = _get_float("UNITY_REL_TOL", 1e-12)


settings = Settings()
