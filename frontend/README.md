# CryptoAgg 前端

基于 Next.js 14 + TypeScript + Tailwind CSS 的 CryptoAgg SaaS 前端，风格参考 agentrade.space 的深色科技风 + 玻璃拟态。

## 快速开始

```bash
cd frontend
cp .env.example .env.local
# 填入 Supabase 与后端 API 配置
npm install
npm run dev
```

访问 http://localhost:3000。

## 环境变量

| 变量 | 说明 |
|------|------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase 项目 URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase 匿名公钥 |
| `BACKEND_API_BASE` | 本地开发时 Flask 后端地址，默认 `http://127.0.0.1:5000` |

## 本地联调

1. 启动 Python 后端：
   ```bash
   cd ..
   python -m app.main
   ```
2. Next.js 开发服务器已将 `/api/*` 重写到 Flask 后端。

## 页面

- `/login` — 邮箱魔法链接登录
- `/dashboard` — 分析工作台（默认页）
- `/history` — 历史记录
- `/settings` — 账户与主题设置
- `/admin` — 管理员占位面板
- `/analysis/[id]` — 分析详情
