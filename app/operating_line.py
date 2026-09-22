"""全塔物料衡算与操作线 / 平衡线。

物理约定
--------
* 平衡线（亨利型直线）：``y* = m·x``。
* 操作线由进、出口端点钉死：``G·(y1 - y2) = L·(x1 - x2)``，
  在 x-y 图上是一条过 (x2, y2) 与 (x1, y1) 的直线：
      y = (L/G)·(x - x2) + y2。
* 下标记号：1 = 塔底（气相入口、液相出口），2 = 塔顶（气相出口、液相入口）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatingLine:
    """一条已确定的操作线与平衡线对。"""

    G: float
    L: float
    m: float
    x1: float
    x2: float
    y1: float
    y2: float

    @property
    def slope(self) -> float:
        """操作线斜率 L/G。"""
        return self.L / self.G

    @property
    def ratio_mG_over_L(self) -> float:
        """斜率比 r = m·G/L = m/(L/G)（NOG 分支判据）。"""
        return self.m * self.G / self.L

    def y_operating(self, x: float) -> float:
        """操作线上液相分率 x 对应的气相分率 y。"""
        return self.slope * (x - self.x2) + self.y2

    def y_equilibrium(self, x: float) -> float:
        """与液相分率 x 平衡的气相分率 y* = m·x。"""
        return self.m * x

    def y_star_at_gas(self, y: float) -> float:
        """沿操作线，气相分率为 y 时与之接触的液相所对应的平衡分率 y*。

        由操作线反解 x = x2 + (G/L)·(y - y2)，故
            y* = m·x = m·x2 + m·(G/L)·(y - y2)。
        """
        return self.m * self.x2 + (self.m * self.G / self.L) * (y - self.y2)

    def driving_force(self, y: float) -> float:
        """气相总推动力 Δy = y - y*（方向：实际分率减去平衡分率）。"""
        return y - self.y_star_at_gas(y)

    @property
    def delta_y_bottom(self) -> float:
        """塔底推动力 Δy1 = y1 - m·x1。"""
        return self.y1 - self.m * self.x1

    @property
    def delta_y_top(self) -> float:
        """塔顶推动力 Δy2 = y2 - m·x2。"""
        return self.y2 - self.m * self.x2

    def min_L_over_G(self) -> float | None:
        """由两端组成给出的最小液气比 (L/G)_min = m·(y1-y2)/(y1-m·x2)。

        推导：夹点极限下操作线在塔底端点 (x1*, y1) 与平衡线相交，即 x1* = y1/m；
        代入物料衡算 L/G·(x1* - x2) = y1 - y2 即得。
        当 y1 - m·x2 <= 0 时任何 L/G 都无法满足吸收要求，返回 ``None``。
        """
        denom = self.y1 - self.m * self.x2
        if denom <= 0:
            return None
        return self.m * (self.y1 - self.y2) / denom

    def L_over_G_margin(self) -> float | None:
        """当前 L/G 相对最小液气比的倍数（衡量离夹点多远）；不可算时为 None。"""
        lmin = self.min_L_over_G()
        if lmin is None or lmin <= 0:
            return None
        return self.slope / lmin
