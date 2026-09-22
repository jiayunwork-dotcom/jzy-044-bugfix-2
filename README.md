# 填料吸收塔传质高度核算服务

常驻 HTTP 后端，接收稀溶质气液逆流吸收的一股操作条件，返回传质单元高度
**HOG**、传质单元数 **NOG**、填料层高度 **Z**，并明确回答该操作条件
**离夹点（最小液气比）还有多远**。被夹点限制时拒绝计算并返回
`pinch_limited`，绝不给出虚假的有限高度。

- 运行时：Python 3.12 + FastAPI + Uvicorn
- 仅 HTTP/JSON 接口，无前端、无账户权限
- 支持单次核算、批量核算、具名工况档（持久化、跨重启、线程安全）

## 物理模型

记号：1 = 塔底（气相入口/液相出口），2 = 塔顶（气相出口/液相入口）。
`G`、`L` 均以塔截面单位面积为基准给入。

- 平衡线（亨利型直线）：`y* = m·x`
- 操作线（全塔物料衡算钉死）：`G·(y1 − y2) = L·(x1 − x2)`
- 传质单元高度：`HOG = G / (Kya·a·S)`
- 传质单元数（气相推动力，积分限 y2 → y1）：
  `NOG = ∫ dy / (y − y*)`
- 填料高度：`Z = HOG · NOG`

稀相、两线均为直线时取对数平均推动力封闭解，令 `r = m·G/L`、
两端推动力 `Δy1 = y1 − m·x1`、`Δy2 = y2 − m·x2`：

- `r ≠ 1`：`NOG = 1/(1−r) · ln(Δy1/Δy2)`
  （等价于 `(y1−y2)/Δy_lm`）
- `r = 1`：推动力沿塔为常数，退化为 `NOG = (y1−y2)/Δy2`
  —— 服务内部按 `r` 是否等于 1 自行选支
- `y1 = y2`（无净传质）：合法退化，`NOG = Z = 0`
- `Δy1 ≤ 0` 或 `Δy2 ≤ 0`：夹点/两线交叉，判 `pinch_limited`，HTTP 409

离夹点距离指标：最小推动力 `min(Δy1, Δy2)` 及其位置、当前 `L/G`、
最小液气比 `(L/G)_min = m·(y1−y2)/(y1−m·x2)`、余量倍数
`(L/G)/(L/G)_min`。

## 目录结构（按职责拆模块）

| 文件 | 职责 |
|---|---|
| `app/schemas.py` | 请求/响应模型与字段级校验 |
| `app/validation.py` | 正负号、摩尔分率区间、吸收方向、全塔物料衡算校验 |
| `app/operating_line.py` | 物料衡算、操作线/平衡线、推动力、最小液气比 |
| `app/transfer.py` | HOG、NOG 积分两支、夹点判定、离夹点距离 |
| `app/presets.py` | 具名工况档登记与 JSON 原子持久化（含内置示范档） |
| `app/service.py` | 工况档合并 → 校验 → 核算 → 响应组装（批量隔离） |
| `app/main.py` | FastAPI 路由与统一错误响应 |
| `tests/` | 物理联动、非法输入、批量隔离、持久化、并发测试 |

## 本地运行（Python 3.12）

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
PRESETS_PATH=data/presets.json .venv/bin/uvicorn app.main:app --port 8000
# 交互式文档：http://localhost:8000/docs
```

## 容器构建与运行

```bash
docker build -t packed-absorber-height .          # 构建阶段会自动跑全部测试
docker run -d -p 8000:8000 -v presets_data:/data packed-absorber-height
# 或：docker compose up --build -d
```

## 接口

### `POST /calculate` 单次核算

```json
{
  "G": 0.02, "L": 0.04, "Kya": 0.08, "a": 2.5, "S": 1.0, "m": 1.0,
  "y1": 0.10, "y2": 0.01, "x1": 0.045, "x2": 0.0
}
```

也可点名已登记工况档，并以临时字段覆盖：`{"preset": "demo_air_water", "Kya": 0.16}`。

成功 `200`：

```json
{
  "HOG": 0.1, "NOG": 3.4094961844768505, "Z": 0.340949618447685,
  "pinch_limited": false, "branch": "log_mean", "ratio_mG_over_L": 0.5,
  "driving_force": {"delta_y_bottom": 0.055, "delta_y_top": 0.01,
                    "min": 0.01, "min_location": "塔顶"},
  "distance_to_pinch": {"min_driving_force": 0.01,
                        "min_driving_force_location": "塔顶",
                        "l_over_g": 2.0, "min_l_over_g": 0.9,
                        "l_over_g_margin": 2.2222222222222223}
}
```

夹点 `409 pinch_limited`（响应不含 HOG/NOG/Z，只给原因与离夹点指标）；
非法输入 `422 invalid_input`，`errors[]` 逐条给出字段与原因。

### `POST /calculate/batch` 批量核算

请求体 `{"cases": [ <单次请求>, ... ]}`。逐
条返回 `results[]`（带 `index`、`ok`），个别条目非法或夹点只影响该条，
其余照常算完。

### 工况档

- `GET /presets`、`GET /presets/{name}`
- `POST /presets/{name}`（201；重名 409）
- `PUT /presets/{name}`（覆盖更新）
- `DELETE /presets/{name}`（204）

工况档可只登记部分参数（如塔几何/传质参数），调用时再用临时字段补齐。
内置示范档 `demo_air_water` 可手算核对：

```
G=0.02,L=0.04,Kya=0.08,a=2.5,S=1,m=1,y1=0.10,y2=0.01,x1=0.045,x2=0
→ Δy1=0.055, Δy2=0.01, r=0.5
→ HOG=0.1 m, NOG=2·ln(5.5)≈3.4095, Z≈0.3409 m, (L/G)_min=0.9
```

内置档每次启动自动补种，不可被覆盖或删除。

## 非法输入（统一 422，逐条原因）

- `G`、`L`、`Kya`、`a`、`S` 不为正；`m` 为负
- 任一摩尔分率越出 `[0,1]`；数值为 NaN/Inf
- 进出口分率违反 `G·(y1−y2)=L·(x1−x2)`（容差 `BALANCE_REL_TOL`，默认 1e-6）
- 吸收方向矛盾（`y1<y2`）
- 缺少必填参数、出现未声明字段

## 自动化测试

```bash
.venv/bin/python -m pytest
```

覆盖并逐条守住三条联动：

1. **Kya 放大两倍 → HOG、Z 减半，NOG 不变**（`a`、`S` 同理）
2. **远离夹点区间加大 L/G → 推动力拉开、NOG 下降**（另验证逼近夹点时 NOG 发散）
3. **y1=y2 → NOG=Z=0（合法退化，不报错）**

另含：闭式解与 20 万段数值积分一致、`r=1` 退化支、塔底/塔顶相切与
两线交叉的夹点拒绝（409）、全部非法输入、批量隔离、工况档 CRUD、
跨“重启”持久化、并发核算与并发登记互不污染。

## 配置（环境变量）

| 变量 | 默认 | 含义 |
|---|---|---|
| `PRESETS_PATH` | `data/presets.json` | 工况档持久化文件 |
| `BALANCE_REL_TOL` | `1e-6` | 物料衡算相对容差 |
| `PINCH_ABS_TOL` | `1e-9` | 推动力触零（夹点）绝对阈值 |
| `UNITY_REL_TOL` | `1e-12` | 判定 `mG/L=1` 的相对容差 |
