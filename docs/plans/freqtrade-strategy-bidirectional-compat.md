# Plan: FreqTrade 策略代码双向零修改兼容

> 让本项目所有策略代码 ↔ FreqTrade 项目双向零修改可跑：
> - 本项目策略文件原样复制到 `freqtrade_dev_mcp/user_data/strategies/` 直接运行回测
> - FreqTrade 社区下载的策略文件原样放到本项目，被本项目 API / bench / loop-engineering 消费

## Context

cryptoagg 当前策略形态分裂为两套独立实现，违反 KISS 与单一真相源：

| 路径 | 角色 | 实现 |
|---|---|---|
| `app/domain/strategy_core.py` (367 行) | 本项目"真相" | pandas EWM/RSI/ATR 纯函数 |
| `freqtrade_dev_mcp/user_data/strategies/trend_rsi_strategy.py` (293 行) | FreqTrade 镜像版 | `talib.abstract` 重写一遍 |

同一逻辑两份代码（EMA/RSI/ATR 各算两次），任何参数漂移都会让两边信号不一致。freqtrade 端有现成 12 个 MCP tools 与 `freqtrade backtesting` / `freqtrade hyperopt` 官方命令，但本项目从未把它们当作"主引擎"，只把它们当作"下游验证层"（见 `docs/plans/freqtrade-mcp-integration.md` v2）。

**本方案升级该旧定位**：把 FreqTrade `IStrategy` 提升为**唯一**策略形态，本项目其余一切（扫描 API、回测、bench、loop-engineering、AI 训练）都变成"运行 freqtrade 策略的运行环境"。本项目聚焦于 SaaS 增值层（信号观察、Quota、AI 学习、Promote Gate），指标计算 0 重复。

**与上游计划关系**：

- 本方案**升级** `docs/plans/freqtrade-mcp-integration.md`（v2，301 行）—— 旧计划关注"调 freqtrade 当验证层"，新方案升级为"freqtrade 是唯一策略形态，本项目是 SaaS 外壳"。旧 phase 0-4 全部失效。
- 本方案**不触碰** `docs/plans/ft-strategy-ui-integration.md`（FT 策略中心数据库 / UI / orient / capabilities / preflight / verdict / deploy_pr）—— 这部分与"策略代码形态"无关。
- 本方案**不触碰** `docs/plans/loop-engineering-plan.md` 的 `app/loop/` 内核（CMA-ES / Pareto / Maker-Checker）—— 只改参数来源（从裸 yaml 改为策略反射）。

## Goals

- [ ] 策略代码**单一存储**：物理路径 `app/strategies/`，`freqtrade_dev_mcp/user_data/strategies/` 改为 symlink
- [ ] 删除 `app/domain/strategy_core.py` 与 `app/domain/rsi_trend.py` 中的镜像实现层
- [ ] 新建 `app/services/strategy_runner.py`（freqtrade 协议反射调用层）
- [ ] `/api/rsi-trend/backtest` 转发到 `freqtrade.backtesting.Backtesting.run()`
- [ ] `/api/rsi-trend/scan` 通过 strategy_runner 跑 `populate_indicators` + `populate_entry_trend`
- [ ] `app/loop/strategy_reflection.py` 从 `IStrategy` 类反射 hyperopt 参数空间
- [ ] 双轨灰度：API 支持 `engine=freqtrade|legacy` 参数，1 周过渡
- [ ] Parity test：双向 `diff -r` 一致；策略类 `inspect.getsource()` 一致
- [ ] Hyperopt 闭环：freqtrade hyperopt → `HISTORY.jsonl` → `tuning_promotion.promotion_checklist()`
- [ ] 100% 测试覆盖（AGENTS.md 要求）
- [ ] ADR-0014 落地：`docs/adr/0014-strategy-freqtrade-bidirectional.md`

## Non-Goals

- 不重写 freqtrade 协议本身（INTERFACE_VERSION 沿用 3）
- 不替换 freqtrade 的 backtesting 命令（直接调其 in-process API）
- 不改前端 UI schema（response 保持向后兼容）
- 不改 FT 策略中心数据库（`app/ft_strategy/*` 保持原样）
- 不动 `app/loop/` 的 CMA-ES / Pareto / Maker-Checker 内核

---

## Architecture（目标态）

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       策略形态（唯一）                                     │
│  app/strategies/  ⇄  freqtrade_dev_mcp/user_data/strategies/             │
│      （symlink 桥接，单一存储，diff -r 必须空）                             │
│                                                                          │
│  class TrendRSIStrategy(IStrategy):                                     │
│      INTERFACE_VERSION = 3                                              │
│      timeframe = "1h"                                                   │
│      buy_atr_mult = DecimalParameter(0.5, 3.0, space="buy")             │
│      def populate_indicators(...): ...                                  │
│      def populate_entry_trend(...): ...                                 │
│      def populate_exit_trend(...): ...                                  │
│      def custom_stoploss(...): ...                                      │
│      def custom_exit(...): ...                                          │
└──────────────────────────────────────────────────────────────────────────┘
              ▲                                       ▲
              │                                       │
   ┌──────────┴──────────┐                ┌───────────┴────────────┐
   │ 本项目 (Flask SaaS)  │                │  freqtrade 官方 CLI     │
   │                     │                │                         │
   │ - 扫描 API           │                │  freqtrade backtesting  │
   │ - 回测 Web UI        │                │  freqtrade hyperopt     │
   │ - bench/pipeline     │                │  freqtrade download-data│
   │ - loop-engineering   │                │  freqtrade plot-dataframe│
   │ - LLM 调参           │                │                         │
   │                     │                │                         │
   │ strategy_runner      │                │                         │
   │ (调 freqtrade 引擎)  │                │                         │
   └─────────────────────┘                └─────────────────────────┘
```

**核心转变**：

- 策略代码形态唯一：freqtrade `IStrategy`。本项目所有"策略逻辑"都在 freqtrade 文件里。
- 本项目运行时**直接调 freqtrade**，不重新实现指标。
- `app/domain/strategy_core.py` 整体消失（被 freqtrade 端替代）。`app/domain/rsi_trend_backtest.py` 中的**纯回测指标**（R-multiple、Sharpe、Calmar、Sortino、drawdown 计算）保留——这部分 freqtrade 也不自带。

---

## 七大子方案

### 4.1 策略文件单一存储 + symlink 桥接

**问题**：现在 `app/` 与 `freqtrade_dev_mcp/user_data/strategies/` 是两个文件夹，**手动复制**容易漂移。

**方案**：

- 策略文件**只放一份**，物理路径选 `app/strategies/`（git tracked，IDE 高亮，pytest 易覆盖）。
- `freqtrade_dev_mcp/user_data/strategies/` 改为 **symlink** 指向 `app/strategies/`，或写 `scripts/sync_strategies.sh` 在 CI/dev 时单向同步（rsync `--delete`）。
- 路径选择：建议 **symlink 而非 rsync**——避免"两边文件不一致"的隐藏 bug。
- 加 `Makefile` target `make strategies-sync`（幂等）做交叉验证（CI 上跑 `diff -r` 必须空，否则 build fail）。

**验收**：

- `ls -la freqtrade_dev_mcp/user_data/strategies` 显示指向 `app/strategies/` 的符号链接
- `pytest tests/test_strategies_parity.py`：自动 import 两个路径下同名策略类，对比 `inspect.getsource()` 必须一致

### 4.2 干掉镜像翻译层，统一让 freqtrade 当真相

**问题**：`app/domain/strategy_core.py` 和 `freqtrade_dev_mcp/user_data/strategies/trend_rsi_strategy.py` 是同一逻辑的两个实现，bug 风险大。

**方案**：

- **删除** `app/domain/strategy_core.py`、`app/domain/rsi_trend.py` 中的 `enrich` / `compute_indicators` 等（保留 `rsi_trend_backtest.py` 中纯回测指标）
- 把 `TrendRSIStrategy` 直接搬到 `app/strategies/trend_rsi_strategy.py`
- freqtrade 端的 `trend_rsi_strategy.py` **整文件删除**（symlink 替代）
- `Signal` dataclass 改为 freqtrade 的 `enter_tag` / `enter_long=1,enter_short=1` 表达

**这条最 KISS**：策略逻辑不再有 "本项目版" 与 "freqtrade 版"。

**验收**：

- `git grep "strategy_core"` → 0 hits（除历史 git log）
- `pytest tests/` 全部通过；本项目 `/api/rsi-trend/scan` 与 `freqtrade backtesting --strategy TrendRSIStrategy` 对同一数据输出相同入场信号集合

### 4.3 本项目运行时调 freqtrade 引擎（不再自己写 populate_indicators）

**问题**：`app/services/rsi_trend_service.py` 现在自己调 `compute_indicators(df)` 算 EMA/RSI/ATR——这就是 bug 根源（两份实现）。

**方案**：

- 把"加载 + 计算指标 + 提取入场信号"封装成 `app/services/strategy_runner.py`：
  - `run_populate_indicators(strategy_class, df) -> df_with_indicators`：通过 `freqtrade.resolver.StrategyResolver.load_strategy()` 拿到策略实例，把我们的 `df` 假装成 freqtrade 的 dataframe 喂给 `populate_indicators`、`populate_entry_trend`、`populate_exit_trend`
  - `extract_signals(df_with_enter_long) -> list[StrategySignal]`：扫描 `enter_long==1` / `enter_short==1` 行，按 `enter_tag` 分类
  - `run_backtest(strategy_class, df, ...)`：通过 freqtrade 自带的 `Backtesting.run()` 跑，回测结果用 `extract_backtest_data` 命令解析 JSON
- `rsi_trend_service.py` 改为 thin wrapper：`scan()` 调 `strategy_runner.run_populate_indicators()` + `extract_signals()`
- **`/api/rsi-trend/backtest`** 改为转发到 freqtrade 的 `Backtesting.run()`（或 shell 子进程 + JSON 解析）。指标计算（R-multiple、Sharpe、Calmar 等）freqtrade 自带，我们只负责把 freqtrade 的 `BT_DATA` JSON 翻译回本项目的 response schema

**Ponytail 收益**：消除 ~250 行重复指标代码（pandas EWM/RSI/ATR + talib EWM/RSI/ATR）。

**验收**：

- `tests/test_strategy_runner.py`：把本项目 `/api/rsi-trend/backtest` 输出与 `freqtrade backtesting --export trades` 的 `strategy_comparison` 表逐行 diff，必须字段完全一致（trade_count, profit_total, sharpe, max_drawdown）
- `pytest tests/services/freqtrade/` 全绿

### 4.4 数据格式双向桥接

**问题**：本项目数据在 Supabase / Redis / 本地 feather（OHLCV in `open,high,low,close,volume,date`），freqtrade 数据在 `user_data/data/<exchange>/<PAIR>-<tf>.csv`（含 `open_time,quote_volume,trades,buy_volume,ignore` 列，且 `open_time` 是 unix 秒）。

**方案**：

- **入口侧（写 freqtrade 数据）**：扩展现有 `scripts/feather_to_freqtrade.py`
  - 改为可逆：读 Supabase `candles` 表 / Binance REST → 写 freqtrade CSV（列补齐：`close_time = open_time + tf_seconds - 1`，`quote_volume` 从聚合或留空，`trades/buy_volume/ignore` 填 0）
  - 加 `--direction both` 选项：写 freqtrade CSV 同时把 freqtrade CSV 再读回来验证列对齐
- **出口侧（freqtrade 跑回测时）**：让 freqtrade 直接读 CSV 即可，不需要再喂 DataFrame
- **反向桥接（freqtrade → 本项目 DB）**：freqtrade 跑出的 trade JSON 通过现有的 `app/services/freqtrade/handshake.py` 写入 `HISTORY.jsonl`（已存在），再被 loop-engineering 消费
- **可选进阶**：用 `freqtrade.utils.binance_file_ohlcv_downloader` 或自写 fetcher 把 Binance REST → freqtrade CSV

**验收**：

- `make data-sync` 幂等：`feather_to_freqtrade.py --verify` 必须 0 diff
- `freqtrade list-data --exchange binance` 能看到所有 pair
- `freqtrade backtesting --strategy TrendRSIStrategy --timerange 20240101-20240601 --export trades` 成功

### 4.5 Hyperopt 链对齐（双向调参）

**问题**：本项目 hyperopt 现在通过 `freqtrade_dev_mcp` 的 LangGraph Agent 调，本项目自己的 tuning 数据流是 `HISTORY.jsonl` → `tuning_promotion.py`。

**方案**：

- **沿用现有路径**：freqtrade 自带 hyperopt 命令（`freqtrade hyperopt --strategy X --hyperopt-loss SharpeHyperOptLoss --epochs 100`）→ 写入 `user_data/hyperopt_results/<strategy>.json` → `app/services/freqtrade/handshake.py` 解析 → 写入 `HISTORY.jsonl`（`source: freqtrade_hyperopt`）→ 复用 `tuning_promotion.promotion_checklist()` gate
- **Hyperoptable Parameter 设计原则**（核心）
  - 策略文件里**所有可调参数必须用 `*Parameter` 声明**（不能用裸 `self.x = 1.0`），否则 freqtrade 不会扫到
  - **前缀必须 buy_*/sell_*（或 enter_*/exit_*）**——freqtrade 按前缀分配 hyperopt space
  - 本项目以前用 `atr_mult=1.0` 裸参数 → 改 `buy_atr_mult: DecimalParameter(0.5, 3.0, space="buy")`
  - 写 `docs/strategies/hyperopt-naming-convention.md`：列出本项目所有策略的 buy/sell 前缀约定
- **Loss function**：用 freqtrade 内置（`SharpeHyperOptLoss`、`CalmarHyperOptLoss`、`SortinoHyperOptLoss`、`MaxDrawDownHyperOptLoss`、`ProfitDrawDownHyperOptLoss`）之一，**不写自定义**（自定义很难调试）。若想组合，写一个小的 `CustomHyperOptLoss` 继承 `IHyperOptLoss`，只放 `app/strategies/`
- **新增强约束**：在 `tuning_promotion.promotion_checklist()` 里追加 freqtrade-specific 项（已部分存在，见 ADR-0010 D1）：`epochs_completed >= 50`、`parallel_jobs > 0`（避免单机单线程假结果）

**验收**：

- `freqtrade hyperopt --strategy TrendRSIStrategy --hyperopt-loss SharpeHyperOptLoss --epochs 50 --spaces buy sell` 跑通
- 结果自动出现在 `app/loop/state.py` 的 HISTORY 里
- `python -m loop.loop audit . --suggest` 显示 freqtrade-promoted 参数已被识别

### 4.6 AI / Agent 训练回路对接

**问题**：`app/loop/`（CMA-ES / Pareto）目前完全不读 freqtrade 策略——它读的是 `tuning.py` 这种"裸参数表"。

**方案**：

- 把 `app/loop/` 的搜索空间定义**改为从 freqtrade 策略类反射出来**：
  - 扫描策略类所有 `*Parameter` 属性 → 提取 `low/high/decimals/space/name`
  - CMA-ES 在这些维度上搜索，结果写到 yaml
- 删除 `app/config/tuning.py` 里与 freqtrade 策略参数重复的字段（ATR、RSI 区间等）——**单一真相**在策略文件里
- `loop_runner` 在写完 yaml 后调 freqtrade hyperopt 作"局部精修"（hyperopt 在 CMA-ES 给出的邻域内再扫 50 轮），最终融合回 HISTORY.jsonl
- **回测奖励信号**：freqtrade 自带 backtest JSON 含 Sharpe / Sortino / Calmar / profit_factor / max_drawdown——直接做 fitness 输入，不再让本项目自己跑一遍回测

**验收**：

- `tests/loop/test_loop_strategy_aligned.py`：从 `TrendRSIStrategy` 类反射出 5 个 buy/sell 参数，CMA-ES 搜索 20 代后建议的最优值与 freqtrade hyperopt 的 top-5 重叠率 > 30%

### 4.7 Frontend / API 兼容

**问题**：前端 `/ft-strategy`、`/api/rsi-trend/*` 等接口已上线，不能 break。

**方案**：

- **API 字段保持**：response schema 不变；后端实现从"自己跑计算"改为"调 freqtrade + 翻译回原 schema"
- **新 UI**：在 `/ft-strategy` 页加一个 **"Import freqtrade strategy"** 按钮：
  - 用户上传 `.py` 文件 → 后端做 AST parse → 校验继承 `IStrategy`、有 INTERFACE_VERSION、有 `populate_*` 方法 → 写到 `app/strategies/`
  - 同一个按钮反向：**"Export to freqtrade"** → 把本项目策略打包成 zip（含 `user_data/` 子目录结构、config.json 模板）
- **`/api/rsi-trend/backtest` response 加字段**（向后兼容）：`backtest_engine: "freqtrade"`，让前端知道现在跑的是哪条链路
- **前端可视化**：继续沿用现有 chart 组件；数据流从 freqtrade `BT_DATA` JSON 解析 → 喂给现有 chart

**验收**：

- 所有现有 frontend e2e 测试通过（`tests/e2e/`）
- 旧 API 调用方不需要任何改动（response schema 保持）

---

## FreqTrade 协议"硬契约"（参考自官方文档）

**策略文件要求**：

- `INTERFACE_VERSION = 3`
- 类继承 `IStrategy`，**文件名 ≠ 类名**，freqtrade 用 `--strategy ClassName` 调
- 必填方法：`populate_indicators`、`populate_entry_trend`、`populate_exit_trend`（可选）、`custom_stoploss`（可选）
- 可选：`custom_exit`、`informative_pairs`、`bot_loop_start`、`adjust_entry_price`、`leverage`
- Hyperopt 必须：`buy_*/enter_*` 前缀入 buy 空间、`sell_*/exit_*` 前缀入 sell 空间，类型 `IntParameter` / `DecimalParameter` / `CategoricalParameter` / `BooleanParameter`
- **必须是 vectorized**（不写 iloc 循环）；freqtrade 把整个 dataframe 一次性喂给 `populate_*`
- **不引入未来数据**（freqtrade 内置 lookahead-analysis 检查）
- 数据 OHLCV 列固定：`open / high / low / close / volume`，**不允许覆盖**
- 入场信号 → `enter_long` / `enter_short` 列 = 1
- 出场信号 → `exit_long` / `exit_short` 列 = 1（或者 `use_exit_signal=False` 让 freqtrade 只看 ROI/stoploss）

**数据契约**：

- 数据存 `user_data/data/<exchange>/<PAIR>-<tf>.csv`，列：`open_time,open,high,low,close,volume,close_time,quote_volume,trades,buy_volume,ignore`
- pair 形式：`BTC/USDT`（spot）、`BTC/USDT:USDT`（futures）
- 关键命令：`backtesting`、`hyperopt`、`download-data`、`list-strategies`、`plot-dataframe`

---

## Tasks

### Phase A：基础设施（不破坏现有路径，0.5d）

- [ ] 新建 `app/strategies/` 目录
- [ ] 把 `freqtrade_dev_mcp/user_data/strategies/trend_rsi_strategy.py` 复制到 `app/strategies/trend_rsi_strategy.py`
- [ ] `freqtrade_dev_mcp/user_data/strategies/` 改为 symlink 指向 `app/strategies/`
- [ ] 加 `tests/test_strategies_parity.py`（CI fail if 文件不一致）
- [ ] **现有 API 继续走 strategy_core 路径**，新代码可以同时跑（双轨期）

### Phase B：strategy_runner 落地（2d）

- [ ] 实现 `app/services/strategy_runner.py`（freqtrade 协议调用层）
  - `run_populate_indicators(strategy_class, df) -> df_with_indicators`
  - `extract_signals(df_with_enter_long) -> list[StrategySignal]`
  - `run_backtest(strategy_class, df, ...) -> BacktestResult`
- [ ] 写 `tests/services/test_strategy_runner.py`：freqtrade 端 enter_long 列 = 旧 strategy_core 端 detect_signals 列表的 1:1 映射
- [ ] **不切换 API**：先用 strategy_runner 在 dev 环境跑通，CI 不挂
- [ ] 前端 / API 完全无感

### Phase C：切换默认路径 + 删旧实现（2d）

- [ ] `rsi_trend_service.py` 改为调 strategy_runner
- [ ] `/api/rsi-trend/backtest` 改为调 freqtrade `Backtesting`
- [ ] **灰度开关**：`/api/rsi-trend/*?engine=freqtrade` 显式走新路径，默认仍是旧路径（1 周过渡期）
- [ ] 监控指标：`rsi_trend_scan_duration_seconds`、`rsi_trend_backtest_sharpe`——新旧路径并行一周对比
- [ ] **删除** `app/domain/strategy_core.py`（所有引用方已迁移）
- [ ] **删除** `app/domain/rsi_trend.py`（仅作为 compat 包装，无新内容）
- [ ] **删除** `freqtrade_dev_mcp/user_data/strategies/trend_rsi_strategy.py`（symlink 替代）
- [ ] **清空** `app/services/freqtrade/translator.py` 中的 pattern-driven 翻译块（保留文件骨架与 TODO 注释）
- [ ] ADR-0014 落地

### Phase D：hyperopt 闭环 + AI Agent + 文档（1.5d）

- [ ] `app/loop/strategy_reflection.py` 从 `TrendRSIStrategy` 类反射参数空间
- [ ] CMA-ES + freqtrade hyperopt 双链路写 HISTORY.jsonl
- [ ] Frontend 新增 "Import freqtrade strategy" UI
- [ ] 写 `docs/strategies/hyperopt-naming-convention.md`
- [ ] 写 `docs/strategies/strategy-authoring-guide.md`
- [ ] 写 `docs/adr/0014-strategy-freqtrade-bidirectional.md`
- [ ] `loop audit` 跑分 ≥ 既有水平

---

## Files to Create / Modify

### Delete

| File | 原因 |
|---|---|
| `app/domain/strategy_core.py` | 367 行重复实现，被 freqtrade 端替代 |
| `app/domain/rsi_trend.py` | 仅作为 compat 包装，无新内容 |
| `freqtrade_dev_mcp/user_data/strategies/trend_rsi_strategy.py` | 改为 symlink 指向 `app/strategies/trend_rsi_strategy.py` |
| `app/services/freqtrade/translator.py` 中的 pattern-driven 翻译块（保留 translator.py 骨架与 TODO 注释） | 翻译层失去意义（freqtrade 文件直接 import 即可） |

### Modify

| File | 改动 |
|---|---|
| `app/services/rsi_trend_service.py` | 改为 thin wrapper，调 `strategy_runner.run_populate_indicators()` |
| `app/api/rsi_trend_routes.py` | backtest 路由转发到 freqtrade `Backtesting.run()` |
| `app/loop/tuning_promotion.py` | promotion_checklist 加 freqtrade-specific 项（epochs / parallel_jobs / 数据完整性 hash） |
| `app/loop/state.py` | 读 freqtrade 策略类反射参数而非裸 tuning.py |
| `app/services/freqtrade/loop_runner.py` | hyperopt 触发 + 结果回写 |
| `scripts/feather_to_freqtrade.py` | 加双向 `--verify` 模式 |
| `freqtrade_dev_mcp/user_data/strategies/` | 改为 symlink → `app/strategies/` |
| `.gitignore` | `freqtrade_dev_mcp/user_data/strategies` 不再 ignore（symlink 内容在 git 里追踪） |
| `Makefile`（新增） | 加 `make strategies-sync` / `make data-sync` / `make freqtrade-backtest STRATEGY=X` / `make freqtrade-hyperopt STRATEGY=X EPOCHS=50` |

### Create

| File | 用途 |
|---|---|
| `app/strategies/__init__.py` | 包入口 |
| `app/strategies/trend_rsi_strategy.py` | 唯一 TrendRSI 策略（从 freqtrade 端搬过来） |
| `app/services/strategy_runner.py` | freqtrade strategy 加载 + 指标填充 + 信号提取 |
| `app/services/freqtrade/backtest_runner.py` | freqtrade Backtesting 引擎 in-process 调用 + JSON 解析 |
| `app/loop/strategy_reflection.py` | 从 `IStrategy` 类反射 hyperopt 参数空间 |
| `tests/strategies/test_trend_rsi.py` | 策略本身的单元测试（indicator 正确、enter 信号正确） |
| `tests/services/test_strategy_runner.py` | 喂同样 df，freqtrade 端 vs 本项目端产出的 enter_long 列 byte-identical |
| `tests/test_strategies_parity.py` | `app/strategies/` 与 `freqtrade_dev_mcp/user_data/strategies/` 文件一致性 |
| `tests/loop/test_loop_strategy_aligned.py` | CMA-ES 搜索结果与 freqtrade hyperopt top-5 重叠率 > 30% |
| `docs/strategies/hyperopt-naming-convention.md` | buy_*/sell_* 前缀规范 |
| `docs/strategies/strategy-authoring-guide.md` | 在本项目 / freqtrade 双向开发的开发者手册 |
| `docs/adr/0014-strategy-freqtrade-bidirectional.md` | 架构决策记录 |

### 保留不动

- `app/ft_strategy/*`：FT 策略中心（数据库、orient、capabilities、preflight、verdict、deploy_pr 等）——它是本项目 SaaS 层的业务，跟"策略代码形态"无关
- `app/services/freqtrade/handshake.py`：HISTORY.jsonl 写入逻辑，继续用
- `app/services/freqtrade/mcp_client.py`：调 freqtrade MCP tools 的 client，继续用
- `app/services/freqtrade/event_log.py`：tsv 日志，继续用
- `freqtrade_dev_mcp/` 整个 submodule（除了 strategies 子目录变 symlink）
- `app/loop/` 内核（CMA-ES / Pareto / Maker-Checker）

---

## Verification

| 验证项 | 命令 | 预期 |
|---|---|---|
| 双向文件一致性 | `diff -r app/strategies freqtrade_dev_mcp/user_data/strategies` | 空输出 |
| 策略加载 | `freqtrade list-strategies --strategy-path app/strategies` | 列出 `TrendRSIStrategy` |
| freqtrade 直接跑 | `freqtrade backtesting --strategy TrendRSIStrategy --timerange 20240101-20240601` | exit 0，生成 backtest_results JSON |
| 本项目 API 等价 | `curl /api/rsi-trend/backtest?symbol=BTCUSDT&interval=1h` | 与 freqtrade 结果 `strategy_comparison` 字段一致 |
| Hyperopt | `freqtrade hyperopt --strategy TrendRSIStrategy --epochs 50 --spaces buy sell` | 写入 user_data/hyperopt_results/ |
| 结果回流 | `cat .scratch/loop_state/HISTORY.jsonl \| grep freqtrade_hyperopt` | 有新条目 |
| Promotion gate | `python -m loop.loop gate check .` | 无新违规 |
| Loop readiness | `python -m loop.loop audit . --suggest` | 分数 ≥ 旧值 |
| 测试覆盖 | `pytest --cov=app/strategies --cov=app/services/strategy_runner` | 100%（AGENTS.md 要求） |
| 现有 API 不破 | `pytest tests/api/` | 全绿 |
| 删除旧实现 | `git grep "strategy_core"` | 0 hits |

---

## 风险与回滚

| 风险 | 触发条件 | 回滚动作 |
|---|---|---|
| freqtrade 升级破坏 IStrategy 兼容 | freqtrade major 版本升级 | 锁版本到 `freqtrade<next_major`；`pin_freqtrade.sh` 脚本 |
| Backtesting in-process 进程隔离崩 | freqtrade 内部异常 | 改为 shell 子进程 + 解析 JSON（已有 `mcp_client.py` 模式） |
| strategy_runner 反射数据丢列 | 用户策略覆盖 OHLCV | strategy_runner 顶部做 column guard：`assert {'open','high','low','close','volume'} <= set(df.columns)` |
| symlink 在 Windows CI 失败 | GitHub Actions Windows runner | 退化为 rsync（`scripts/sync_strategies.sh`） |
| 旧 API 调用方需要时间迁移 | response schema 不一致 | Phase C 双轨期提供 `engine=legacy` 参数 |
| 删除 `strategy_core.py` 后测试 fail | 仍有未迁移引用 | CI 加 `grep -r "strategy_core" app/` → fail fast |
| hyperopt 噪声大 | epochs 不足 / 数据不够 | 在 tuning_promotion 加 min epochs + min data points 校验 |
| freqtrade 数据列缺 quote_volume/trades 导致 freqtrade 内部报错 | feather_to_freqtrade 没补齐列 | scripts/feather_to_freqtrade 加 `--strict` 检查 + 列补 0 |

---

## 与现有计划的关系

| 现有计划 | 与本方案的关系 |
|---|---|
| `docs/plans/freqtrade-mcp-integration.md`（v2，301 行） | **大幅修订**：旧计划关注"调 freqtrade 当验证层"，本方案升级为"freqtrade 是唯一策略形态，本项目是 SaaS 外壳"。旧 phase 0/1/2/3/4 全部失效，supersede |
| `docs/plans/ft-strategy-ui-integration.md` | **继续保留**：FT 策略中心数据库 / UI / orient / capabilities 与本方案无冲突 |
| `docs/plans/loop-engineering-plan.md` | **继续保留**：`app/loop/` 不动；只改参数来源（从裸 yaml 改为策略反射）|
| `app/services/okx/*`（同样模式的镜像翻译）| **作为 reference 案例**：本方案完成后，可对 OKX 复用同样的"symlink + strategy_runner"模式 |

---

## 工作量估算

| 阶段 | 文件改动数 | 工时（单人工作日） |
|---|---|---|
| Phase A：symlink + parity test | ~5 | 0.5d |
| Phase B：strategy_runner 实现 + 测试 | ~6 | 2d |
| Phase C：API 切换 + 灰度 + 删除旧实现 | ~12 | 2d |
| Phase D：hyperopt 闭环 + 文档 + ADR | ~10 | 1.5d |
| **合计** | **~33** | **~6 工作日** |

---

_Last updated: 2026-08-12_