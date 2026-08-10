# CryptoAgg-GPT 部署方案

> 日期: 2026-07-23
> 架构版本: Flask + Next.js + Supabase SaaS

---

## 1. 当前架构分析

### 1.1 技术栈

| 组件 | 技术 | 位置 | 部署状态 |
|------|------|------|----------|
| 前端 | Next.js 14 (App Router) | `/frontend` | Vercel |
| 后端 API | Flask + gunicorn | `/app` | 自建服务器 |
| 数据库/存储 | Supabase (PostgreSQL + Storage) | 云服务 | 已有 |
| 背景任务 | Redis + RQ (vibe_worker) | `/app/tasks` | 自建服务器 |
| LLM | MiniMax API (OpenAI compatible) | 云服务 | 已有 |

### 1.2 Vercel 项目现状

| 项目名 | 域名 | 用途 |
|--------|------|------|
| `pyharmonics-gpt` | pyharmonics-gpt-gyc567s-projects.vercel.app | 主应用 |
| `frontend` | traderflow.cryptoagg.xyz | 旧前端 (已弃用) |

### 1.3 API 路由配置 (next.config.mjs)

```javascript
// 当前配置：所有 /api/* 请求代理到 BACKEND_API_BASE
const apiBase = process.env.BACKEND_API_BASE || "http://127.0.0.1:5000";
// /api/vibe/* → backend/v1/vibe/*
// /api/analyze → backend/v1/analyze
// /api/charts/* → backend/v1/charts/*
```

---

## 2. 问题审计

### 2.1 高优先级问题

**[CRITICAL] Vibe 模块需要 RQ/Redis 背景 worker**

`/app/services/vibe/runner.py` 和 `/app/tasks/vibe_worker.py` 依赖 Redis + RQ 来执行长时间 LLM 交互任务。Vercel Serverless Functions 不支持常驻进程，vibe 的流式响应架构（SSE）需要在请求生命周期内保持连接。

**影响**: vibe 模块在纯 Vercel Serverless 环境下无法工作。

**[HIGH] 后端 API_BASE 硬编码问题**

`next.config.mjs` 的 rewrites 依赖 `BACKEND_API_BASE` 环境变量。在 Vercel 构建时这个变量被嵌入到 rewrites 配置中，而不是运行时动态路由。这限制了灵活性和多环境支持。

**[HIGH] `.env` 文件暴露敏感信息**

根目录 `.env` 包含 `OPENAI_API_KEY` 等敏感信息，已被 git 跟踪（从 git status 可以看到 `.env` 是 tracked 文件）。部署时不应将 `.env` 推送到仓库。

**[MEDIUM] 两个 Vercel 项目造成混乱**

`pyharmonics-gpt` 和 `frontend` 两个项目同时存在，`frontend` 指向旧域名 `traderflow.cryptoagg.xyz`，新代码应统一部署到 `pyharmonics-gpt` 项目。

### 2.2 中优先级问题

**[MEDIUM] CORS 配置硬编码 localhost**

`app/main.py` 中的 `allowed_origins` 只包含 `localhost:3000` 和 `localhost:5001`，Vercel 预览和正式环境域名不在白名单中，会导致 CORS 错误。

**[MEDIUM] 本地开发无 Redis 时 vibe 功能退化**

如果 `REDIS_URL` 未配置，vibe 的 background job 功能会静默失败。应有明确的 fallback 或错误提示。

**[MEDIUM] 图片使用 `unoptimized: true`**

Next.js 图片优化被禁用，原因是配置了自定义 CDN 域名但未在 `images.domain` 中声明。

### 2.3 低优先级问题

**[LOW] 缺少 vercel.json 配置文件**

没有显式的 Vercel 部署配置，无法控制 `regions`、`functions` 数量限制、构建命令等。

**[LOW] `app/main.py` 中 `/query` 和 `/` 路由**

遗留的 chat_ui.html 路由和 `/query` 端点未被 vibe 模块使用，但仍在代码中，可能造成混淆。

---

## 3. 优化方案

### 3.1 架构调整：前后端分离 + API 网关

```
┌─────────────────────────────────────────────────────────────┐
│                         Vercel                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Next.js Frontend                         │   │
│  │  (pyharmonics-gpt project)                            │   │
│  │                                                       │   │
│  │  rewrites: /api/* → ${BACKEND_URL}/api/*             │   │
│  │  env: BACKEND_URL (指向后端服务器)                    │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    后端服务器 (Cloud Run / Railway)          │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Flask API   │  │ Redis + RQ  │  │ Vibe Worker         │ │
│  │ (gunicorn)  │  │ (bg tasks)  │  │ (long-running LLM)  │ │
│  │ :5000       │  │ :6379       │  │                     │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────┐     ┌─────────────────┐
│    MiniMax API     │     │    Supabase     │
│  (LLM Provider)    │     │  (DB + Storage) │
└────────────────────┘     └─────────────────┘
```

**推荐：后端部署到 Google Cloud Run**

理由：
- 原生支持 Docker，零配置扩缩容
- 按请求计费，冷启动快
- 与 Vercel 同为 Google 产品，网络延迟低
- 免费额度充足（每月 240 万 vCPU 秒 + 60 实例小时）

替代方案对比：

| 平台 | 优点 | 缺点 |
|------|------|------|
| Cloud Run | 原生 Docker，冷启动快，Google 生态 | 需要 GCP 项目 |
| Railway | 简单，GitHub 集成，透明定价 | 免费额度少 |
| Render | 稳定，Postgres 内置 | 冷启动慢（~30s） |
| Fly.io | 全球多区域，低延迟 | 配置复杂 |

### 3.2 环境变量管理优化

**新建 `frontend/.env.production`**:

```bash
# Vercel 环境变量（在 Vercel Dashboard 中设置，不要放在 .env.production）
NEXT_PUBLIC_SUPABASE_URL=https://piomgijwxpbsvnigtbmt.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<your-supabase-anon-key>
NEXT_PUBLIC_BACKEND_URL=https://api.pyharmonics-gpt.example.com
```

**后端环境变量（Cloud Run secrets 或 .env）**:

```bash
# Flask / gunicorn
FLASK_ENV=production
PORT=5000
OPENAI_API_KEY=<your-openai-api-key>
OPENAI_API_MODEL=MiniMax-M2.5
OPENAI_API_BASE_URL=https://api.minimaxi.com/v1
SUPABASE_URL=https://piomgijwxpbsvnigtbmt.supabase.co
SUPABASE_ANON_KEY=<your-supabase-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<your-supabase-service-role-key>
# SUPABASE_DB_URL=postgresql://...
REDIS_URL=redis://redis.cloud.run:6379
# DISABLE_AUTH=0 (生产必须关闭!)
```

### 3.3 CORS 动态配置

修改 `app/main.py` 的 `before_request_cors` 函数，从环境变量读取允许的域名：

```python
@app.before_request
def before_request_cors():
    origin = request.headers.get("Origin", "")
    # 从环境变量读取允许的域名列表，逗号分隔
    allowed_str = os.getenv("ALLOWED_ORIGINS", "localhost:3000,localhost:5001")
    allowed_origins = set(allowed_str.split(","))
    # 同时支持 localhost 和 Vercel 预览/生产域名
    if origin in allowed_origins or origin.endswith(".vercel.app"):
        request._cors_origin = origin
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
```

`ALLOWED_ORIGINS` 在 Cloud Run 部署时设置为前端域名。

### 3.4 Vercel 配置文件

新建 `frontend/vercel.json`:

```json
{
  "framework": "nextjs",
  "buildCommand": "npm run build",
  "outputDirectory": ".next",
  "installCommand": "npm install",
  "regions": ["iad1"],
  "env": {
    "NEXT_PUBLIC_SUPABASE_URL": "@supabase-url",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY": "@supabase-anon-key",
    "NEXT_PUBLIC_BACKEND_URL": "@backend-url"
  },
  "git": {
    "deploymentEnabled": false
  }
}
```

### 3.5 后端 Dockerfile 优化（Cloud Run 兼容）

更新 `Dockerfile` 以支持 Cloud Run:

```dockerfile
FROM python:3.11-slim

EXPOSE 8080  # Cloud Run 要求 8080

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

RUN adduser -u 5678 --disabled-password --gecos "" appuser && \
    chown -R appuser /app
USER appuser

# 健康检查 (Cloud Run 需要)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "app.main:app"]
```

### 3.6 vibe Worker 部署方案

vibe 的长时 LLM 任务不适合 Serverless。两种方案：

**方案 A：独立 Cloud Run Service（推荐）**

将 `vibe_worker.py` 作为独立进程部署，与主 API 在同一 Cloud Run 服务中通过 `--worker-class gevent` 共存，或独立扩缩容。

**方案 B：Vercel Functions 模拟（不推荐）**

将 vibe 交互改为轮询模式，前端先发请求，后端立即返回 `202 Accepted`，前端轮询状态。放弃 SSE。

推荐方案 A，保留 SSE 流式体验。

---

## 4. 部署步骤

### Step 1: 准备后端（Cloud Run）

```bash
# 1. 构建并推送到 Google Artifact Registry
gcloud builds submit --tag gcr.io/$PROJECT_ID/pyharmonics-api:v1.0.0

# 2. 部署到 Cloud Run
gcloud run deploy pyharmonics-api \
  --image gcr.io/$PROJECT_ID/pyharmonics-api:v1.0.0 \
  --platform managed \
  --region us-central1 \
  --port 8080 \
  --memory 1Gi \
  --cpu 2 \
  --min-instances 1 \
  --max-instances 10 \
  --set-env-vars "REDIS_URL=redis://$REDIS_HOST:$REDIS_PORT" \
  --set-secrets OPENAI_API_KEY=pyharmonics-openai-key:latest \
  --set-secrets SUPABASE_SERVICE_ROLE_KEY=pyharmonics-supabase-sr:latest \
  --allow-unauthenticated

# 3. 获取 API URL
BACKEND_URL=$(gcloud run services describe pyharmonics-api --format "value(status.url)")
echo $BACKEND_URL
```

### Step 2: 配置 Redis

```bash
# 使用 Google Cloud Memorystore (Redis) 或 Cloud Run 的 sidecar
# Memorystore 方式:
gcloud redis instances create pyharmonics-redis \
  --size=1 \
  --region=us-central1 \
  --redis-version=redis_7_0
```

### Step 3: 部署前端（Vercel）

```bash
cd frontend

# 设置环境变量（通过 Vercel Dashboard 或 CLI）
vercel env add NEXT_PUBLIC_SUPABASE_URL
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY
vercel env add NEXT_PUBLIC_BACKEND_URL   # 值为 Step 1 的 $BACKEND_URL

# 部署到生产
vercel --prod
```

### Step 4: 域名绑定（可选）

在 Vercel Dashboard 中为 `pyharmonics-gpt` 项目绑定自定义域名：

- `pyharmonics-gpt.example.com` → 替代 `pyharmonics-gpt-gyc567s-projects.vercel.app`

更新 `ALLOWED_ORIGINS` 环境变量包含新域名。

---

## 5. 实施清单

### 前端 (Vercel)

- [ ] 在 Vercel Dashboard 设置环境变量 `NEXT_PUBLIC_SUPABASE_URL`
- [ ] 在 Vercel Dashboard 设置环境变量 `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- [ ] 在 Vercel Dashboard 设置环境变量 `NEXT_PUBLIC_BACKEND_URL`
- [ ] 在 `frontend/next.config.mjs` 中添加 `NEXT_PUBLIC_BACKEND_URL` 动态 rewrite
- [ ] 创建 `frontend/vercel.json`
- [ ] 确认部署到 `pyharmonics-gpt` Vercel 项目（不是 `frontend`）
- [ ] 删除或重定向旧的 `frontend` Vercel 项目

### 后端 (Cloud Run)

- [ ] 更新 `Dockerfile` 端口为 8080，添加 health check
- [ ] 创建 GCP 项目或使用现有项目
- [ ] 启用 Cloud Run API
- [ ] 配置 Secret Manager 存储 `OPENAI_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- [ ] 部署后端服务
- [ ] 配置 Redis (Memorystore 或第三方)
- [ ] 设置 `ALLOWED_ORIGINS` 环境变量（Vercel 域名）

### 代码修复

- [ ] 修改 CORS 白名单逻辑，支持动态域名（环境变量 + Vercel 域名自动匹配）
- [ ] 将根目录 `.env` 从 git 中移除（添加到 `.gitignore`）
- [ ] 确认 `DISABLE_AUTH=0` 在生产环境生效
- [ ] 验证 vibe SSE 流式响应在 Cloud Run + Redis 环境下工作

---

## 6. 成本估算（月度）

| 资源 | 规格 | 成本 |
|------|------|------|
| Vercel Frontend | Hobby → Pro $20/mo | $20 |
| Cloud Run API | 2 vCPU, 1Gi, 1 min-inst | ~$15-25 |
| Cloud Memorystore Redis | 1GB | ~$49 |
| Supabase | Pro plan（如果需要） | $25/月起 |
| **合计** | | **~$109-119/月** |

如果 Redis 使用第三方托管（如 Redis Cloud free tier），可省去 Memorystore 费用。

---

## 7. 回滚计划

如果部署失败：

1. **前端回滚**: Vercel Dashboard → `pyharmonics-gpt` → Deployments → 选择上一个成功版本 → "Promote to Production"
2. **后端回滚**: `gcloud run revisions list pyharmonics-api` → `gcloud run services update-traffic pyharmonics-api --to-revision=REVISION_NAME`
3. **数据库回滚**: Supabase 天然支持 Point-in-time Recovery

---

## 附录 A：当前 git 未跟踪文件清单

以下新增文件已 commit 但尚未 push：

```
app/api/vibe_routes.py          # Vibe API 路由
app/domain/vibe_schemas.py      # Vibe Pydantic 模型
app/infra/vibe_*.py             # Vibe 存储层
app/services/vibe/              # Vibe 核心模块 (orchestrator, runner, tools)
app/tasks/vibe_worker.py        # 背景 worker
frontend/app/vibe/              # Vibe 前端页面
frontend/components/vibe/       # Vibe UI 组件
frontend/hooks/use-vibe.ts      # Vibe React hook
frontend/types/vibe.ts          # Vibe TypeScript 类型
tests/test_vibe_*.py            # Vibe 测试
docs/plans/vibe-*.md            # Vibe 设计文档
supabase_schema_vibe.sql        # Vibe 数据库 schema
```

这些文件已在 commit `1845e71` 中，将在 `git push` 后同步到远程。

---

## 附录 B：关键文件路径

```
/
├── Dockerfile                          # 后端 Docker 镜像
├── docker-compose.yaml                 # 本地开发用
├── pyproject.toml                      # Python 依赖
├── requirements.txt                    # Python 依赖（另一份）
├── .env                                # 环境变量（敏感，勿上传）
├── app/
│   ├── main.py                         # Flask 入口
│   ├── api/auth.py                     # 认证装饰器
│   ├── api/vibe_routes.py              # Vibe API 路由
│   ├── infra/supabase_client.py        # Supabase 客户端
│   ├── services/vibe/                  # Vibe 核心逻辑
│   └── tasks/vibe_worker.py            # RQ 背景任务
└── frontend/
    ├── next.config.mjs                 # Next.js 配置（API rewrite）
    ├── package.json                    # Node 依赖
    ├── .env.local                      # 前端环境变量
    └── vercel.json                     # Vercel 配置（待创建）
```
