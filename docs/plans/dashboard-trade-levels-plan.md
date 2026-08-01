# Dashboard 交易价位缺失修复方案（审计修订版）

> 现象：dashboard 的"技术结果"只剩 `入场价 596.74`，`止损价 / 目标价 / 风险收益比` 全为 `—`。
> 本文是初版方案的严格审计结果：**8 个缺陷已修正**，以本文为准实施。

---

## 0. 审计结论：初版方案的 8 个缺陷

| # | 缺陷 | 严重度 | 修正方向 |
|---|------|--------|----------|
| 1 | **`_PatternPosition` 字段名错误**：`getattr(pattern, "stop_loss", None)` / `getattr(pattern, "targets", [])` 在 `HarmonicPattern` 上永远是 `None / []`。已读 `pyharmonics/patterns.py` 坐实：`HarmonicPattern` / `ABCDPattern` / `XABCDPattern` 仅暴露 `completion_min_price / completion_max_price / abc_extensions / x / y / name / bullish`，**无** `stop_loss`、**无** `targets`。这就是 bug 的物理根因 | 高 | 用 pyharmonics 真 `Position(pattern, strike, dollar_amount)` 派生 stop/targets（`_set_stop`/`_set_targets` 现成），不再自己造轮子（见 2.1） |
| 2 | **Family ≠ XABCD 时 strike 语义错位**：真 `Position._set_targets(C)` 用 `pattern.y[-2]`（C 点）。ABC 形态只有 3 点，`y[-2] = B` 而 `y[-1] = C`，且 `completion_min == completion_max == C`，`strike = mid(PRZ) = C`——结果 C-strike 距离按 B 算，与"以 PRZ 入场"语义不一致 | 高 | 按 family 校准 strike：XABCD/ABCD 用 `mid(PRZ)`（≈ D 点）；ABC 用 `completion_max_price`（即 C 点）；让 `y[-2]` 仍是 BC 段参考点，与现有 `_set_targets` 自洽 |
| 3 | **targets 形态分支未统一**：真 `Position.targets` 是裸 `list[float]`（长度 3），`Signal.to_dict()["targets"]` 是 `list[{label, price, fib_basis, ...}]`。`technical_result_to_schema` 在两个分支各写一遍"取第一个 TP"，逻辑重复且脆 | 中 | 抽出纯函数 `_first_target_price(targets)`：list 元素是 dict 取 `["price"]`，是 float 直接用，空/None 返回 None（见 2.2） |
| 4 | **风险收益比自己重写**：初版提 `abs(target - entry) / abs(entry - stop)`，但 `app.domain.signals.net_rr` 已经处理 fee + slippage 净额比、并有 icontract 契约护栏 | 中 | 直接调 `net_rr(entry, stop, target1)` / `net_rr(entry, stop, target2)`，形成模式把 `net_rr_tp1 / net_rr_tp2` 补齐到 `forming_signal_dict`（见 2.3） |
| 5 | **`forming_signal_dict` 与 `signal` 不同源**：`scored[0][0]`（line 234，引擎挑的 top）与 `forming_view[0]`（line 249，原始顺序 top）不是同一个候选。当 `build_signal` 抛异常走 fallback 时，`technical_result_to_schema(signal=forming_signal_dict)` 展示的是**未排序的第一个**而不是引擎实际选中的 | 高 | 让 `forming_signal_dict` 与 `signal` 共用 `scored[0][0]`；`scored` 为空时直接置 None，不再构造 fallback dict |
| 6 | **`forming_signal_dict` 自身 bug 三连**：(a) `targets` 用 generator expression 不是 list，`technical_result_to_schema` 里 `targets[0]` 会 `TypeError`；(b) 缺 `net_rr_tp1 / net_rr_tp2`；(c) 两个 `"macro"` key 重复，后者覆盖前者（dict 字面量顺序求值） | 高 | 一次性修：list 推导 + label/fib_basis 字段、复用 `net_rr`、合并 `macro` 字段为单一定义；同时把 `"formed": False` 硬编码改为 `top.formed`（top 可能 formed） |
| 7 | **缓存命中路径未审计**：`AnalysisOrchestrator._restore_cached`（analysis.py:101）从 `analysis_json` 反序列化 `AnalysisData`。旧 cache 里 `technical_result` 已固化"无 stop/target"，**修复后旧 cache 仍会让用户看不到 stop/target**，且不会重跑检测 | 中 | cache key 加 schema version（`v2:...`），旧 key 全部失效；同时 `_restore_cached` 校验 `technical_result.signal.stop_loss` 必填，缺失则降级为 `no_result` 而不是回显破损数据（见 2.5） |
| 8 | **测试桩不稳**：初版说"用真实 `ABCDPattern` 构造"。pyharmonics `ABCDPattern.__init__` 要求 x/y tuple + 完整 `retraces` 字典，缺一即 `TypeError`，且 `retraces` 与 `name` 必须出现在 `constants.MATRIX_PATTERNS` 里，构造代价大、版本敏感 | 低 | 引入 `_FakePattern`（只带 `completion_min_price / completion_max_price / x / y / bullish / name / abc_extensions`），绕过 pyharmonics 构造路径，断言契约稳定；外加一条"集成 smoke"——真 Position 实例化成功后断言 stop/targets 非空（双层护栏） |

---

## 1. 根因（维持初版结论，证据已坐实）

**`_PatternPosition` 用根本不存在的字段读取 pyharmonics 形态**：

```python
# app/infra/pyharmonics_adapter.py:115–116
self.stop = getattr(pattern, "stop_loss", None)        # ← HarmonicPattern 无此字段
self.targets = getattr(pattern, "targets", []) or []   # ← HarmonicPattern 无此字段
```

`dashboard` 默认 `analysis_type = "auto"`，orchestrator 不跑信号引擎（`build_signal` 只在 `analysis_type == "forming"` 时调），`technical_result_to_schema` 落到 `elif position:` 分支（pyharmonics_adapter.py:267–279），于是 stop / target / RR 全是 None，前端表格里只有 `entry_price`（= mid(PRZ)）有数字。

次因（forming 路径）：

```python
# app/services/analysis.py:260–262
"targets": (
    [{"label": "TP1", "price": t}] for t in (top.targets or [])  # 生成器
),
```

`technical_result_to_schema` 里 `targets[0].get("price")` 在 generator 上 `TypeError`。

---

## 2. 修订后方案

### 2.1 Fix 1：用真 `Position` 派生 stop / targets

`app/infra/pyharmonics_adapter.py`，`_PatternPosition.__init__`：

- 删除两行错误 `getattr`。
- 构造 `pyharmonics.positions.Position(pattern, strike=strike, dollar_amount=100)`：
  - XABCD / ABCD：`strike = (completion_min_price + completion_max_price) / 2`（≈ D 点）；
  - ABC：`strike = completion_max_price`（即 C 点，与 PRZ 一致）；
  - 长度不足 / 退化形态：`try/except` 包住，失败打 warning 并回退到**仅 entry_price 的最小 dict**（保留 `confidence = "raw-position-minimal"`），不让请求整体失败。
- 拷 `pos.stop` / `pos.targets` 到 `_PatternPosition`；`to_dict()` 同步更新。
- `detect_patterns` 返回 `position` 不变（接口稳定）。

### 2.2 Fix 2：`technical_result_to_schema` 防御化 + 抽公共函数

`app/infra/pyharmonics_adapter.py:225`：

- 新增模块级纯函数：
  ```
  _first_target_price(targets) -> Optional[float]
      []/None → None
      [dict, ...] → targets[0].get("price")
      [float, ...] → targets[0]
      其他 → None（防御性）
  ```
- `if signal:` 与 `elif position:` 两个分支统一调它取 TP1：
  - `result.target_price = _first_target_price(targets)`
  - `result.stop_loss = signal.get("stop_loss")` 或 `position.stop`（二选一，signal 优先）
  - `result.risk_reward_ratio` 直接调 `app.domain.signals.net_rr(entry, stop, target_price)`（**不复写**）：三者任一缺失 → None。
- `position` 路径补 `result.targets = [float(t) for t in (position.targets or [])]`（裸 float），signal 路径保持 list[dict]。

### 2.3 Fix 3：`forming_signal_dict` 整体重写

`app/services/analysis.py:247–282`：

- 改用与 `signal` 同源的 `top = scored[0][0]`（line 234 的 `top`）。`scored` 为空 → `forming_signal_dict = None`，不再构造。
- 重写为：

  ```
  forming_signal_dict = {
      "status": "forming" if not top.formed else "formed",
      "grade": "C",                                         # fallback 硬降级，加注释说明
      "direction": top.direction or "long",
      "pattern_name": top.pattern_name or "unknown",
      "family": top.family or "XABCD",
      "formed": bool(top.formed),                           # 修硬编码 False
      "entry_zone": [...], "entry_reference": top.entry_price,
      "stop_loss": top.stop_loss,
      "targets": [                                          # list 推导，非生成器
          {"label": t.label, "price": float(t.price),
           "fib_basis": t.fib_basis, "close_pct": t.close_pct,
           "move_stop_to": t.move_stop_to}
          for t in (top.targets or [])
      ],
      "net_rr_tp1": net_rr(top.entry_price, top.stop_loss, top.targets[0].price) if top.targets else None,
      "net_rr_tp2": net_rr(top.entry_price, top.stop_loss, top.targets[1].price) if len(top.targets or []) >= 2 else None,
      "confluence_score": int((top.metrics.confidence or 0) * 100),
      "macro": ({"size_mult": top.macro.size_mult, "advice": top.macro.advice} if top.macro else None),
      "width_pct": top.width_pct, "bars_since_c": ..., "stale": ..., "past_tp2": ..., "in_prz": ..., "dist_pct": ...,
  }
  ```

- 删掉重复的 `"macro"` key；`confidence` 字段补 `"raw-forming-c"` 给前端辨识。

### 2.4 Fix 4（轻量）：前端展示对齐

- `frontend/components/dashboard/result-panel.tsx:124–127` 已经读 `tech.{stop_loss, target_price, risk_reward_ratio}`，后端补齐即显示，**无需改前端逻辑**。
- RR 当前用 `formatNumber(rr, 2)` 输出 `2.50`，与"风险收益比"语义对齐性较弱；UI 接受两种风格，本次**不强制改格式**，留待 P2 视觉统一。
- 类型 `frontend/types/index.ts::TechnicalResult` 已 Optional，向后兼容，无需扩张。

### 2.5 Fix 5：缓存失效与降级

- `app/services/analysis.py:157` cache key 改为 `f"v2:{user_id}:{idempotency_key}"`，旧 `v1:` key 全部失效（TTL 内自然淘汰，零迁移成本）。
- `_restore_cached` 反序列化后做轻校验：`if not data.technical_result or (data.technical_result.entry_price and not data.technical_result.stop_loss):` → 视为脏 cache，删 key 后重跑检测（与 cache miss 路径一致）。

### 2.6 测试方案（双层护栏）

| 类型 | 文件 | 用例 |
|------|------|------|
| 单元 | `tests/test_pyharmonics_adapter.py`（新） | (a) `_FakePattern` + 真 `Position`：断言 `_PatternPosition.stop` / `targets` 非空、`stop > 0`、targets 长度 ≥ 3；(b) `technical_result_to_schema({..., "patterns": {"direction": "bullish"}, "position": FakePattern})` 返回 `entry_price / stop_loss / target_price / risk_reward_ratio` 全非 None；(c) `_first_target_price` 4 种输入形态；(d) 退化形态（family=ABC、completion 区间 0）打 warning 不抛 |
| 单元 | `tests/test_analysis_forming_signal_dict.py`（新） | (e) `forming_signal_dict` 是 dict（非 None 时），`targets` 是 list，`net_rr_tp1/net_rr_tp2` 是 float 或 None；(f) 无 `"macro"` 重复键；(g) `formed` 字段跟随 `top.formed`；(h) `scored` 为空 → `forming_signal_dict is None` |
| 集成 | `tests/test_api_analyze.py`（扩） | (i) `POST /api/analyze {analysis_type:"auto", market:"binance", symbol:"BTCUSDT"}` → 200 且 `technical_result` 含 `entry_price / stop_loss / target_price / risk_reward_ratio`；(j) idempotent 二次请求命中新 cache key，旧 v1 key 已失效 |
| 前端 | `frontend/components/dashboard/result-panel.test.tsx`（扩） | (k) `result.technical_result` 含全字段 → DOM 出现非空 `止损价 / 目标价 / 风险收益比`；(l) 仅含 `entry_price` → 显示 `—` 占位（保持旧行为） |
| E2E | ego-browser | (m) dashboard 触发一次分析，断言 4 行单元格全部非 `—`；gunicorn 日志无 `TypeError: 'generator' object is not subscriptable`、无新 traceback |

---

## 3. 改动文件清单

| 文件 | 改动行数（估） | 性质 |
|------|---------------|------|
| `app/infra/pyharmonics_adapter.py` | ~40 | 改 `_PatternPosition` + 加 `_first_target_price` |
| `app/services/analysis.py` | ~30 | 改 `forming_signal_dict` + cache key + `_restore_cached` |
| `tests/test_pyharmonics_adapter.py` | 新增 ~120 | 单元 |
| `tests/test_analysis_forming_signal_dict.py` | 新增 ~80 | 单元 |
| `tests/test_api_analyze.py` | 扩 ~30 | 集成 |
| `frontend/components/dashboard/result-panel.test.tsx` | 扩 ~20 | 前端 |

**前端零改动**（已对齐 Optional 字段）。

---

## 4. 边界情况（写入代码注释）

| 场景 | 行为 |
|------|------|
| 形态已找到但 `Position` 构造抛异常 | `_PatternPosition` 打 warning，返回仅 `entry_price` 的最小 dict，`confidence = "raw-position-minimal"`；`status` 仍 `completed`，前端 4 行变 3 行（入全场 1 行），不算"失败" |
| ABC 形态 + completion_min == completion_max | strike = completion_max，`Position._set_targets` 用 `pattern.y[-2]` (= B) 算 TP，可能出现"TP 距 strike 过大"——属 pyharmonics 既有行为，本次不修，但用 `_FakePattern` 单元测试断言 RR 在合理范围 (0.1 < RR < 10) |
| `top.targets` 长度 < 2 | `net_rr_tp2 = None`，前端仅显示 TP1 对应的 RR（`net_rr_tp1`），不报错 |
| cache 命中旧 v1 数据 | 反序列化校验失败 → 删 key → 重跑（与 cache miss 等价） |
| 未来 pyharmonics 升级改 `Position.__init__` 签名 | `try/except` 包裹，回退到最小 dict 并 log.error，UI 降级而非 500 |

---

## 5. 明确不做（防范围蔓延）

1. 不重写 `_PatternPosition` 为 dataclass 公开字段——保留轻量包装，对外接口稳定；
2. 不动前端 `formatNumber` RR 格式——视觉统一留 P2；
3. 不动 `pattern_type` 字段语义（与 `auto-analysis-type-plan.md` 解耦）；
4. 不引入新的依赖（`net_rr` 已在 `app.domain.signals`）；
5. 不做"无信号但显示止盈止损"的兜底——若 `entry_price` 也为 None（无形态），`status=no_result` 走原"暂无有效信号"分支，不展示任何价位。

---

## 6. 影响面与兼容性

- **响应契约**：仅新增/填实已有 Optional 字段，旧客户端无感；
- **缓存**：v1 key 失效，TTL 内自然过期，零迁移成本；
- **计算成本**：真 `Position` 构造 ≈ 几十次浮点运算，对一次分析耗时（数百 ms ~ 数 s）可忽略；
- **回退路径**：所有修复都有 `try/except` 兜底，最坏情况回到当前 buggy 行为（不优于现在，不劣于现在）。