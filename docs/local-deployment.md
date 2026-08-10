# Pyharmonics-GPT 本地部署方案（后端）

> 日期：2026-08-04
> 目标：在本机（非容器或容器）完整运行 Pyharmonics-GPT 后端，供开发/测试/联调使用。
> 范围：**只写方案，不写代码**。本文件是部署立项前的决策文档。

---

## 1. 现状分析

### 1.1 项目架构

| 组件 | 技术 | 位置 | 运行方式 |
|------|------|------|----------|
| 后端 API | Flask 2.3.2 + gunicorn 23 | `/app` | `gunicorn -c gunicorn.conf.py app.main:app` |
| 前端 | Next.js 14 (App Router) | `/frontend` | `next dev`（端口 3000，联调用） |
| 市场数据 | TradingView 桥（Node/Express） | `/tradingview-bridge` | 端口 5002，可选 |
| 后台任务 | Redis + RQ | `app/tasks/vibe_worker.py` | `rq worker` |
| 数据库/鉴权/存储 | Supabase（云 SaaS） | — | 云端/外部 |
| LLM | OpenAI compatible（如 MiniMax） | — | 云端/外部 |

后端是 **进程常驻型**（gunicorn 多 worker + gthread），不是无服务器函数。

### 1.2 本地环境（`uname`/机器实测）

| 项目 | 实测值 | 影响 |
|------|--------|------|
| OS | Ubuntu 24.04.3 LTS（x86_64） | — |
| CPU | 5 核 | gunicorn workers 上限 4（默认 `min(CPU,4)`） |
| 内存 | 总 5.8GB / 可用 ~3.3GB | **关键约束**：每个 gunicorn worker 载入 pandas/plotly 后约 200–300MB，需调小 workers |
| 磁盘 | / 剩 23G | 充足 |
| Python | 3.11.15 与 3.12.3 均可用 | `requires-python >= 3.11`，**推荐 3.11**（与 Dockerfile 一致） |
| Node | v22.22.0 | TradingView 桥需要 |
| 包管理器 | pip 24 / uv 均可用 | 用 `uv` 建 venv 更快 |
| Docker | 29.1.4 + Compose v5.0.1，当前 0 容器 | 可选 Redis 容器方案 |
| Redis | **未安装**（无 `redis-server`/`redis-cli`） | 需装或跳过 |
| Postgres | 16 已在 5432 监听（本机） | 后端优先走 Supabase，本地 PG 可选 |
| 证书/密钥 | 无 `.env`、无 `.venv` | 需初始化 |

### 1.3 端口占用现状（关键冲突）

```
5000  ← 已被 /root/vpn/subscription_service.py 占用  ⚠️ 不可用
5001  ← 空闲（后端默认脚本端口）
5002  ← 空闲（TradingView 桥）
3000  ← 空闲（前端，联调用）
6379  ← 空闲（Redis，如启用）
5432  ← Postgres 已在用
```

> **结论**：后端端口必须用 `5001`（项目 `scripts/start-backend.sh` 默认即 5001，且前端 `frontend/.env.example`/`start-frontend.sh` 指向 `http://127.0.0.1:5001`）。**不要用 5000。**

---

## 2. 部署策略选择

### 方案 A：本机运行进程（推荐，最贴合现有脚本）
Python venv + gunicorn 直跑；Redis 用 Docker 容器（隔离、免污染本机）；TradingView 桥直接用 Node 跑。
- 优点：贴近现有 `scripts/*.sh` 工作流、改动最小、调试直观。
- 缺点：依赖本机 Python/Node 环境（各版本共存需小心）。

### 方案 B：全 Docker Compose
复用根目录 `docker-compose.yaml`（自建 Flask 镜像 + redis + 桥）。
- 优点：环境纯净、可复现。
- 缺点：本机内存偏紧（Flask 镜像 worker + redis + node 桥），构建慢；且现有 dev 脚本不依赖容器。

### 方案 C：二选一（Redis 本地安装版）
`apt install redis-server` 替代 Docker 跑 Redis。
- 优点：无容器依赖。
- 缺点：污染系统、需自管 systemd 服务。

**推荐方案 A**，Redis 采用 Docker 单容器（无碍时也可降级为「不配 Redis → vibe 走内存/本地线程后台，见 §4.2」）。

---

## 3. 依赖安装清单

### 3.1 Python 后端（用 3.11，与 Dockerfile 一致）

```bash
cd /root/code/pyharmonics-gpt

# 用 uv 建 venv（更快、更干净）
uv venv --python 3.11 .venv
source .venv/bin/activate

# 生产依赖
uv pip install -r requirements.txt

# （可选）开发/测试依赖
uv pip install -r requirements-dev.txt
```

> 说明：`requirements.txt` 已锁定全部关键版本（含 websockets 11.0.3、alpaca 3.2.0、yfinance 0.2.57 的冲突规避组合），直接照装即可。

### 3.2 Redis（Docker 单容器方案）

```bash
docker run -d --name pyh-redis --restart unless-stopped \
  -p 6379:6379 redis:7-alpine
# 验证
redis-cli -h 127.0.0.1 -p 6379 ping   # → PONG
```

> 若不想用 Docker：`apt install -y redis-server && systemctl start redis`。

### 3.3 TradingView 桥（Node，可选）

```bash
cd /root/code/pyharmonics-gpt/tradingview-bridge
npm install            # 依赖 mathieuc/tradingview（GitHub 源）
node index.js &        # 端口 5002
curl http://127.0.0.1:5002/health
```

> 若网络无法连到 TradingView（如被墙），后端会自动回退 Binance/Yahoo，也可直接设 `USE_TRADINGVIEW=false` 跳过。

### 3.4 前端（仅联调需要）

```bash
cd /root/code/pyharmonics-gpt/frontend
cp .env.example .env.local
npm install
```

---

## 4. 环境变量（`.env`）

复制 `.env.example` 为 `.env` 并填真实值。**本地开发的核心开关是 `DISABLE_AUTH=1`**（跳过 Supabase 鉴权与 quota，`LOCAL_DEV_USER` 直达，见 `app/api/auth.py`）。

```bash
# ---------------------------------------------------------------
# Flask / 应用
# ---------------------------------------------------------------
ENVIRONMENT=development
FLASK_DEBUG=1
DISABLE_AUTH=1            # 仅本地！生产绝不允许

# ---------------------------------------------------------------
# 数据库 / Supabase
# ---------------------------------------------------------------
# 方案①：本地无 Supabase → 保持 DISABLE_AUTH=1，健康检查会跳过 supabase
# SUPABASE_URL=           留空
# SUPABASE_ANON_KEY=      留空
# SUPABASE_SERVICE_ROLE_KEY= 留空
#
# 方案②：有真实 Supabase 项目 → 填以下值（即使开 auth 也要准）
# SUPABASE_URL=https://your-project.supabase.co
# SUPABASE_ANON_KEY=your-anon-key
# SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# ---------------------------------------------------------------
# OpenAI / LLM
# ---------------------------------------------------------------
# 本地必须有真实可用的 key（否则 /api/analyze 的 LLM 解释环节会失败）
OPENAI_API_KEY=sk-xxxx
OPENAI_API_MODEL=gpt-4o-mini
# OPENAI_API_BASE_URL=https://api.openai.com/v1   # 用 MiniMax 等则改这里

# ---------------------------------------------------------------
# Redis（本地用 Docker 方案）
# ---------------------------------------------------------------
REDIS_URL=redis://127.0.0.1:6379/0
# 也可用 Upstash：UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN

# ---------------------------------------------------------------
# TradingView 桥
# ---------------------------------------------------------------
TRADINGVIEW_BRIDGE_URL=http://127.0.0.1:5002
USE_TRADINGVIEW=true      # 无法连 TV 时改 false
```

> **不配 Supabase 的取舍**：`app/factory.py` 在生产判定只在 `ENVIRONMENT=production` 时强制。本地 `development` + `DISABLE_AUTH=1` 下：
> - `/api/analyze` 会走「本地 dev 模式」（`is_local_dev_mode()` 直接通过 quota、建记录失败仅告警，`routes.py` L139/L176）。
> - 依赖 Supabase 的**持久化功能**（分析历史、watchlist、Storage 图表上传）会退化/不可用；核心 `/api/analyze` 分析 + LLM 解释仍可用。
> - 若需完整持久化，务必配置真实 Supabase，或后续接本机 Postgres（见 §8 备选）。

---

## 5. 启动与验证

### 5.1 启动顺序

```bash
cd /root/code/pyharmonics-gpt
source .venv/bin/activate

# ① Redis（若用容器）
docker start pyh-redis

# ② TradingView 桥（可选）
(cd tradingview-bridge && nohup node index.js >../scripts/.run/tv-bridge.log 2>&1 &)

# ③ 后端 —— 内存受限，workers=1 起步（每个 worker ~200-300MB）
export PORT=5001
export GUNICORN_WORKERS=1          # 关键：别让 gunicorn 独占内存
export GUNICORN_THREADS=20
export DISABLE_AUTH=1
nohup .venv/bin/gunicorn -c gunicorn.conf.py app.main:app \
  >scripts/.run/gunicorn.log 2>&1 &
```

> 也可用现成脚本：`scripts/start-backend.sh`（内部已默认 `PORT=5001`、`workers=1`、`DISABLE_AUTH=1`，但**不含 Redis/桥**，需先手动起）。前端可 `scripts/start-frontend.sh`（3000）。

### 5.2 验证

```bash
# 健康检查（supabase/redis/tv-bridge 三方状态）
curl -s http://127.0.0.1:5001/api/health
# 期望：redis=ok，supabase=skipped（未配），tv_bridge=ok/skipped，status=ok

# 市场/区间信息
curl -s http://127.0.0.1:5001/api/markets

# 结构分析（本地 dev 无鉴权，直接可调）
curl -s -X POST http://127.0.0.1:5001/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"market":"crypto","symbol":"BTCUSDT","interval":"4h","analysis_type":"technical"}'

# 全量测试（有 dev 依赖时）
pytest -m "not slow"
```

### 5.3 停机

```bash
scripts/stop-all.sh          # SIGTERM gunicorn/next/tv-bridge
docker stop pyh-redis        # 或保留常驻
```

---

## 6. 内存/性能调优（本机只有 ~3.3GB 可用）

| 参数 | 建议值 | 理由 |
|------|--------|------|
| `GUNICORN_WORKERS` | 1（可试 2） | 每 worker ~200-300MB（pandas/plotly）；5.8G 机 2 个 worker 已占约 600MB，再加 redis/node/os 稳妥 |
| `GUNICORN_THREADS` | 20–50 | gthread 扛 SSE 并发；线程比进程省内存 |
| `GUNICORN_TIMEOUT` | 120（默认已够） | 覆盖 LLM 慢调用 + Kaleido 首渲染 |
| `GUNICORN_MAX_REQUESTS` | 1000（默认） | 定期回收，防 plotly 内存泄漏 |
| TradingView 桥 / redis | 各自 ~100MB | 预算内 |

> 后续若要把 CPU 密集的 `/api/analyze` 挪到 RQ worker，参考 `docs/go-migration-evaluation.md` 方案 A；本机内存有限，先不迁移。

---

## 7. 风险与注意

| 风险 | 等级 | 缓解 |
|------|------|------|
| 端口 5000 被 VPN 占用 | 中 | 一律用 5001，勿改 bind 到 5000 |
| 内存不足导致 worker OOM | 高 | `GUNICORN_WORKERS=1`、`THREADS=20`，监控 `free -m` |
| 无真实 Supabase → 持久化失效 | 中 | 明确接受「仅分析可用」，或配真实 Supabase / 接本机 PG |
| LLM key 缺失 → 解释环节失败 | 高 | 必须填真实 `OPENAI_API_KEY` |
| TradingView 桥被网络墙 | 低 | `USE_TRADINGVIEW=false` 自动回退 Binance/Yahoo |
| Python 版本混杂 | 低 | venv 固定 3.11，避免系统 3.12 干扰 |
| `.env` 含密钥 | 低 | 不入库（`.gitignore` 已有 `.env`） |

---

## 8. 后续可选：本机 Postgres 替代 Supabase（备选）

若不想依赖云端 Supabase 且需要持久化：
1. 已有 Postgres 16 在 5432。
2. 创建库：`sudo -u postgres createdb pyharmonics`。
3. 用仓库 `supabase_schema.sql` 等 schema 文件建表（需评估 RLS/函数与 supabase-py 的兼容性——仓库当前主要通过 supabase REST 操作，直接接 PG 需改动 `supabase_client.py` 走 `get_db_connection_string`/psycopg2）。
4. **注意**：这是较大改动，**不在本次本地部署范围内**，需单独立项。

---

## 9. 决策清单（待确认）

- [ ] **部署方式**：方案 A（本机进程 + Docker redis）？还是 B（全 Compose）？
- [ ] **Redis**：Docker 容器 or `apt` 安装 or 暂时不配（vibe 降级）？
- [ ] **Supabase**：暂不配（仅分析可用）or 配真实项目（完整功能）？
- [ ] **TradingView 桥**：启用 or 关闭（`USE_TRADINGVIEW=false`）？
- [ ] **端口**：确认用 `5001`（避开被占用的 5000）。

确认后即可进入实施（创建 `.env`、建 venv、起服务）。