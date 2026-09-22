"""具名工况档的登记与持久化。

* 存储为单个 JSON 文件，写入采用“临时文件 + os.replace”原子替换，
  进程崩溃不会留下半截文件；进程重启后自动重新加载。
* 进程内以 :class:`threading.RLock` 串行化读改写，多个并发请求互不写串。
* 内置一个可手算核对的稀相空气吸收示范工况 ``demo_air_water``，
  每次启动自动补种且不可被覆盖/删除。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any, Optional

from .errors import PresetConflictError, PresetNotFoundError, ValidationError
from .schemas import CASE_FIELDS
from .validation import validate_case

# 可手算核对的稀相空气吸收示范工况：
#   G=0.02, L=0.04 → L/G=2；m=1；x2=0；y1=0.10, y2=0.01
#   物料衡算 x1 = x2 + G/L·(y1-y2) = 0.5·0.09 = 0.045
#   Δy1 = 0.10-1·0.045 = 0.055, Δy2 = 0.01
#   r = mG/L = 0.5；Δy_lm = (0.055-0.01)/ln(5.5) ≈ 0.026397
#   NOG = 0.09/Δy_lm = 2·ln(5.5) ≈ 3.4095
#   HOG = G/(Kya·a·S) = 0.02/(0.08·2.5·1) = 0.1 m；Z ≈ 0.3409 m
#   (L/G)_min = m·(y1-y2)/(y1-m·x2) = 0.9，当前 L/G=2（余量倍数 2.22）
BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "demo_air_water": {
        "description": (
            "稀相空气吸收示范工况（可手算核对）：y1=0.10,y2=0.01,x1=0.045,x2=0；"
            "L/G=2,m=1；NOG≈3.4095，HOG=0.1m，Z≈0.3409m；(L/G)_min=0.9。"
        ),
        "params": {
            "G": 0.02, "L": 0.04, "Kya": 0.08, "a": 2.5, "S": 1.0, "m": 1.0,
            "y1": 0.10, "y2": 0.01, "x1": 0.045, "x2": 0.0,
        },
    },
}


class PresetRepository:
    """工况档仓库（线程安全，JSON 持久化）。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        with self._lock:
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as fh:
                        loaded = json.load(fh)
                    if isinstance(loaded, dict):
                        self._data = {
                            k: v for k, v in loaded.items()
                            if isinstance(v, dict) and k not in BUILTIN_PRESETS
                        }
                except (json.JSONDecodeError, OSError):
                    # 文件损坏不致命：以内置工况档重新开始
                    self._data = {}
            self._seed_builtins()

    def _seed_builtins(self) -> None:
        for name, body in BUILTIN_PRESETS.items():
            self._data[name] = {
                "description": body["description"],
                "params": dict(body["params"]),
                "builtin": True,
            }

    def _flush_locked(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        # 原子替换：先写同目录临时文件，再 os.replace
        fd, tmp = tempfile.mkstemp(prefix=".presets-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ---------- 查询 ----------
    def list_presets(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._view_locked(name) for name in sorted(self._data)]

    def get(self, name: str) -> dict[str, Any]:
        with self._lock:
            if name not in self._data:
                raise PresetNotFoundError(f"工况档 '{name}' 未登记")
            return self._view_locked(name)

    def _view_locked(self, name: str) -> dict[str, Any]:
        rec = self._data[name]
        return {
            "name": name,
            "description": rec.get("description"),
            "params": dict(rec["params"]),
            "builtin": bool(rec.get("builtin", False)),
        }

    # ---------- 写入 ----------
    def create(self, name: str, params: dict[str, Any], description: Optional[str], *, overwrite: bool = False) -> dict[str, Any]:
        clean = self._clean_params(params)
        with self._lock:
            if name in BUILTIN_PRESETS:
                raise PresetConflictError(f"工况档 '{name}' 是内置示范工况，不可覆盖或删除")
            if name in self._data and not overwrite:
                raise PresetConflictError(f"工况档 '{name}' 已存在；如需更新请使用 PUT 或显式覆盖")
            # 登记成套参数时即做一致性校验，拒绝把自相矛盾的工况档落盘
            if set(clean.keys()) == set(CASE_FIELDS):
                validate_case(clean)
            self._data[name] = {
                "description": description,
                "params": clean,
                "builtin": False,
            }
            self._flush_locked()
            return self._view_locked(name)

    def delete(self, name: str) -> None:
        with self._lock:
            if name not in self._data:
                raise PresetNotFoundError(f"工况档 '{name}' 未登记")
            if name in BUILTIN_PRESETS:
                raise PresetConflictError(f"工况档 '{name}' 是内置示范工况，不可删除")
            del self._data[name]
            self._flush_locked()

    @staticmethod
    def _clean_params(params: dict[str, Any]) -> dict[str, float]:
        clean: dict[str, float] = {}
        for f in CASE_FIELDS:
            v = params.get(f)
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValidationError(
                    "工况档参数不合法",
                    errors=[{"field": f, "reason": "必须是有限数值"}],
                )
            clean[f] = float(v)
        if not clean:
            raise ValidationError("工况档未提供任何参数")
        return clean

    # ---------- 调用时合并 ----------
    def resolve(self, name: str, overrides: dict[str, Any]) -> dict[str, float]:
        """取具名工况档并以临时非空字段覆盖，返回合并后的完整参数字典。

        合并结果是否自洽交由 ``validation.validate_case`` 统一判定。
        """
        with self._lock:
            merged: dict[str, Any] = dict(self._data[name]["params"])
        for f in CASE_FIELDS:
            v = overrides.get(f)
            if v is not None:
                merged[f] = v
        return merged
