# Supabase 配置指南

> 对应设计文档：docs/plans/2026-07-14-cryptoagg-saas-design.md
> 适用阶段：Phase 2（认证与数据层）+ Phase 3（分析 API 存储集成）

---

## 1. 创建 Supabase 项目

1. 访问 https://supabase.com/dashboard
2. 点击 **New Project**
3. 填写：
   - **Organization**: 你的组织
   - **Project Name**: `cryptoagg-saas`（或 `cryptoagg-saas-prod` / `cryptoagg-saas-preview`）
   - **Database Password**: 生成强密码并保存到密码管理器
   - **Region**: 选择离 Vercel 函数区域最近的（如 `us-east-1`、`ap-southeast-1`）
4. 等待项目初始化（约 2 分钟）

> **关键决策**：Preview 和 Production 必须使用**不同的 Supabase 项目**（推荐）或至少不同的数据库 schema。禁止共用 Production 数据做 Preview 测试。

---

## 2. 获取连接凭证

项目创建后，进入 **Project Settings → API**：

| 变量名 | 位置 | 用途 |
|---|---|---|
| `SUPABASE_URL` | Project URL | 客户端和服务端连接地址 |
| `SUPABASE_ANON_KEY` | `anon` `public` | 前端/匿名客户端使用 |
| `SUPABASE_SERVICE_ROLE_KEY` | `service_role` `secret` | **仅限服务端**，绕过 RLS |

> **安全警告**：`SUPABASE_SERVICE_ROLE_KEY` 拥有超级权限，只能存在于 Vercel 服务端环境变量，禁止泄露到前端或日志。

---

## 3. 数据库表结构

进入 **SQL Editor → New Query**，按顺序执行以下 SQL。

### 3.1 启用 UUID 扩展

```sql
-- 已默认启用，如需确认
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

### 3.2 profiles 表（用户档案）

```sql
CREATE TABLE profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    daily_quota INTEGER NOT NULL DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW()
);

-- 行级安全：用户只能看到自己的档案，管理员可以看全部
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own profile" ON profiles
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" ON profiles
    FOR UPDATE USING (auth.uid() = id);

-- 服务端用 service_role 绕过 RLS 做管理操作
```

### 3.3 invites 表（邀请管理）

```sql
CREATE TABLE invites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    invited_by UUID REFERENCES profiles(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE invites ENABLE ROW LEVEL SECURITY;

-- 只有管理员可以读写 invites（通过服务端 RPC 或 service_role）
CREATE POLICY "No direct access" ON invites
    FOR ALL USING (false);
```

### 3.4 analyses 表（分析记录）

```sql
CREATE TABLE analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    input_mode TEXT NOT NULL DEFAULT 'form' CHECK (input_mode IN ('form', 'natural_language')),
    market TEXT NOT NULL CHECK (market IN ('binance', 'yahoo')),
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL CHECK (interval IN ('15m', '1h', '4h', '1d', '1w')),
    analysis_type TEXT NOT NULL DEFAULT 'forming' CHECK (analysis_type IN ('forming', 'formed', 'divergence')),
    parameters JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN (
        'created', 'validating', 'fetching_market_data', 'detecting_patterns',
        'interpreting', 'rendering_chart', 'completed', 'no_result',
        'failed_upstream', 'failed_model', 'failed_chart', 'rejected', 'stale'
    )),
    technical_result JSONB,
    interpretation JSONB,
    chart_path TEXT,
    model_provider TEXT,
    model_name TEXT,
    prompt_version TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_micros INTEGER,  -- 费用以微分（1/1000000 美元）存储
    error_code TEXT,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    idempotency_key TEXT,
    UNIQUE(user_id, idempotency_key)
);

CREATE INDEX idx_analyses_user_created ON analyses(user_id, created_at DESC);
CREATE INDEX idx_analyses_status ON analyses(status);
CREATE INDEX idx_analyses_idempotency ON analyses(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own analyses" ON analyses
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own analyses" ON analyses
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own analyses" ON analyses
    FOR UPDATE USING (auth.uid() = user_id);
```

### 3.5 usage_ledger 表（额度账本）

```sql
CREATE TABLE usage_ledger (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    analysis_id UUID REFERENCES analyses(id) ON DELETE SET NULL,
    usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
    units_reserved INTEGER NOT NULL DEFAULT 0,
    units_consumed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved', 'consumed', 'released')),
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_micros INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_usage_ledger_user_date ON usage_ledger(user_id, usage_date);

ALTER TABLE usage_ledger ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own ledger" ON usage_ledger
    FOR SELECT USING (auth.uid() = user_id);
```

### 3.6 audit_events 表（审计日志）

```sql
CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor_id UUID REFERENCES profiles(id),
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,  -- 'user', 'invite', 'quota', etc.
    target_id TEXT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

-- 审计表只允许服务端写入，用户不可读
CREATE POLICY "No direct access" ON audit_events
    FOR ALL USING (false);
```

---

## 4. 存储桶配置（图表存储）

进入 **Storage → New Bucket**：

1. 创建 bucket：`charts`
2. 设置为 **Private**（禁止公开访问）
3. 在 bucket 的 **Policies** 中添加：

```sql
-- 允许认证用户上传自己的图表
CREATE POLICY "Users can upload own charts" ON storage.objects
    FOR INSERT TO authenticated WITH CHECK (
        bucket_id = 'charts' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- 允许认证用户读取自己的图表
CREATE POLICY "Users can read own charts" ON storage.objects
    FOR SELECT TO authenticated USING (
        bucket_id = 'charts' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );

-- 允许认证用户删除自己的图表
CREATE POLICY "Users can delete own charts" ON storage.objects
    FOR DELETE TO authenticated USING (
        bucket_id = 'charts' AND
        (storage.foldername(name))[1] = auth.uid()::text
    );
```

> 图表路径格式：`charts/{user_id}/{analysis_id}.png`

---

## 5. Auth 配置（邀请制邮箱登录）

进入 **Authentication → Providers**：

1. 启用 **Email** 提供商
2. 关闭 **Confirm email**（Beta 阶段用魔法链接即可，不需要额外确认）
3. 进入 **Authentication → Email Templates**：
   - 修改 **Magic Link** 模板，确保链接指向你的应用域名：

```html
<h2>Magic Link</h2>
<p>Follow this link to log in:</p>
<p><a href="{{ .SiteURL }}/auth/callback?token={{ .TokenHash }}">Log In</a></p>
<hr />
<p>Or enter the code: <strong>{{ .Token }}</strong></p>
```

4. 进入 **Authentication → URL Configuration**：
   - **Site URL**: `https://your-app.vercel.app`
   - **Redirect URLs**: `https://your-app.vercel.app/auth/callback`

---

## 6. 数据库函数（RPC）

### 6.1 原子额度预占函数

```sql
CREATE OR REPLACE FUNCTION reserve_quota(
    p_user_id UUID,
    p_analysis_id UUID,
    p_units INTEGER DEFAULT 1
) RETURNS TABLE(reserved BOOLEAN, remaining INTEGER) AS $$
DECLARE
    v_daily_quota INTEGER;
    v_used_today INTEGER;
BEGIN
    -- 获取用户每日额度
    SELECT daily_quota INTO v_daily_quota
    FROM profiles WHERE id = p_user_id AND status = 'active';

    IF v_daily_quota IS NULL THEN
        RETURN QUERY SELECT false, 0;
        RETURN;
    END IF;

    -- 计算今日已用额度
    SELECT COALESCE(SUM(units_consumed), 0) INTO v_used_today
    FROM usage_ledger
    WHERE user_id = p_user_id
      AND usage_date = CURRENT_DATE
      AND status = 'consumed';

    -- 检查是否超额
    IF v_used_today + p_units > v_daily_quota THEN
        RETURN QUERY SELECT false, v_daily_quota - v_used_today;
        RETURN;
    END IF;

    -- 原子预占额度
    INSERT INTO usage_ledger (user_id, analysis_id, units_reserved, status)
    VALUES (p_user_id, p_analysis_id, p_units, 'reserved');

    RETURN QUERY SELECT true, v_daily_quota - v_used_today - p_units;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

### 6.2 额度结算函数

```sql
CREATE OR REPLACE FUNCTION consume_quota(
    p_ledger_id UUID,
    p_input_tokens INTEGER DEFAULT NULL,
    p_output_tokens INTEGER DEFAULT NULL,
    p_cost_micros INTEGER DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE usage_ledger
    SET status = 'consumed',
        units_consumed = units_reserved,
        input_tokens = COALESCE(p_input_tokens, input_tokens),
        output_tokens = COALESCE(p_output_tokens, output_tokens),
        estimated_cost_micros = COALESCE(p_cost_micros, estimated_cost_micros),
        updated_at = NOW()
    WHERE id = p_ledger_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

### 6.3 额度释放函数

```sql
CREATE OR REPLACE FUNCTION release_quota(
    p_ledger_id UUID
) RETURNS VOID AS $$
BEGIN
    UPDATE usage_ledger
    SET status = 'released',
        units_consumed = 0,
        updated_at = NOW()
    WHERE id = p_ledger_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

### 6.4 用户注册时自动创建 profile

```sql
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, role, status, daily_quota)
    VALUES (
        NEW.id,
        NEW.email,
        'user',
        'active',
        5  -- Beta 默认每日额度
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 绑定触发器
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();
```

### 6.5 检查用户是否为邀请邮箱

```sql
CREATE OR REPLACE FUNCTION is_invited_email(p_email TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM invites
        WHERE email = LOWER(p_email)
          AND status = 'pending'
          AND expires_at > NOW()
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

---

## 7. Python 服务端连接代码

### 7.1 安装依赖

```bash
pip install supabase==2.5.0
```

添加到 `requirements.txt`：

```
supabase==2.5.0
```

### 7.2 客户端封装

```python
# app/infra/supabase_client.py
import os
import logging
from typing import Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)

_supabase: Optional[Client] = None


def get_supabase_client() -> Client:
    """Get or create Supabase client with service role."""
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _supabase = create_client(url, key)
    return _supabase


def verify_user_token(token: str) -> Optional[dict]:
    """Verify Supabase JWT and return user info.

    Args:
        token: Supabase access token (from Authorization header).

    Returns:
        User dict with id, email, role, status or None if invalid.
    """
    try:
        client = get_supabase_client()
        # Use auth.get_user() with the user's token (not service_role)
        # This requires creating a separate anon client for verification
        from supabase import create_client
        anon_client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_ANON_KEY")
        )
        user = anon_client.auth.get_user(token)
        if not user or not user.user:
            return None

        # Fetch profile for role/quota
        profile = client.table("profiles").select("*").eq("id", user.user.id).single().execute()
        if not profile.data:
            return None

        return {
            "id": user.user.id,
            "email": user.user.email,
            "role": profile.data.get("role", "user"),
            "status": profile.data.get("status", "active"),
            "daily_quota": profile.data.get("daily_quota", 5),
        }
    except Exception:
        logger.exception("Token verification failed")
        return None
```

### 7.3 额度操作封装

```python
# app/infra/quota_manager.py
import logging
from typing import Optional, Tuple
from uuid import UUID
from app.infra.supabase_client import get_supabase_client
from app.api.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)


def reserve_quota(user_id: str, analysis_id: str, units: int = 1) -> Tuple[bool, int, Optional[str]]:
    """Atomically reserve daily quota.

    Returns:
        (success, remaining, ledger_id)
    """
    client = get_supabase_client()
    result = client.rpc("reserve_quota", {
        "p_user_id": user_id,
        "p_analysis_id": analysis_id,
        "p_units": units,
    }).execute()

    if not result.data:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Quota check failed")

    row = result.data[0]
    return row["reserved"], row["remaining"], None  # ledger_id 需要通过查询获取


def get_ledger_id(user_id: str, analysis_id: str) -> Optional[str]:
    """Get the latest ledger entry for an analysis."""
    client = get_supabase_client()
    result = client.table("usage_ledger").select("id").eq("user_id", user_id).eq("analysis_id", analysis_id).eq("status", "reserved").order("created_at", desc=True).limit(1).execute()
    if result.data:
        return result.data[0]["id"]
    return None


def consume_quota(ledger_id: str, input_tokens: Optional[int] = None,
                  output_tokens: Optional[int] = None, cost_micros: Optional[int] = None) -> None:
    """Mark reserved quota as consumed."""
    client = get_supabase_client()
    client.rpc("consume_quota", {
        "p_ledger_id": ledger_id,
        "p_input_tokens": input_tokens,
        "p_output_tokens": output_tokens,
        "p_cost_micros": cost_micros,
    }).execute()


def release_quota(ledger_id: str) -> None:
    """Release reserved quota back to user."""
    client = get_supabase_client()
    client.rpc("release_quota", {
        "p_ledger_id": ledger_id,
    }).execute()
```

### 7.4 分析记录存储

```python
# app/infra/analysis_store.py
import logging
from typing import Optional, List, Dict, Any
from uuid import uuid4
from app.infra.supabase_client import get_supabase_client
from app.domain.enums import Status

logger = logging.getLogger(__name__)


def create_analysis(user_id: str, data: Dict[str, Any]) -> str:
    """Create analysis record and return ID."""
    client = get_supabase_client()
    analysis_id = str(uuid4())
    record = {
        "id": analysis_id,
        "user_id": user_id,
        **data,
        "status": Status.CREATED.value,
    }
    result = client.table("analyses").insert(record).execute()
    if not result.data:
        raise RuntimeError("Failed to create analysis record")
    return analysis_id


def update_analysis(analysis_id: str, updates: Dict[str, Any]) -> None:
    """Update analysis record."""
    client = get_supabase_client()
    client.table("analyses").update(updates).eq("id", analysis_id).execute()


def get_analysis(analysis_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Get single analysis by ID (RLS ensures user isolation)."""
    client = get_supabase_client()
    # 注意：service_role 绕过 RLS，必须手动检查 user_id
    result = client.table("analyses").select("*").eq("id", analysis_id).eq("user_id", user_id).single().execute()
    if result.data:
        return result.data
    return None


def list_analyses(user_id: str, limit: int = 20, offset: int = 0,
                  status: Optional[str] = None, market: Optional[str] = None) -> List[Dict[str, Any]]:
    """List user analyses with optional filters."""
    client = get_supabase_client()
    query = client.table("analyses").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit).offset(offset)
    if status:
        query = query.eq("status", status)
    if market:
        query = query.eq("market", market)
    result = query.execute()
    return result.data or []
```

### 7.5 图表上传/下载

```python
# app/infra/chart_storage.py
import logging
from typing import Optional
from datetime import datetime, timedelta
from app.infra.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)
BUCKET = "charts"


def upload_chart(user_id: str, analysis_id: str, image_bytes: bytes) -> str:
    """Upload chart to Supabase Storage.

    Returns:
        Storage path (e.g., "{user_id}/{analysis_id}.png").
    """
    client = get_supabase_client()
    path = f"{user_id}/{analysis_id}.png"
    result = client.storage.from_(BUCKET).upload(path, image_bytes, {
        "content-type": "image/png",
        "upsert": "true",
    })
    if not result:
        raise RuntimeError("Chart upload failed")
    return path


def get_chart_url(path: str, expires_in: int = 300) -> str:
    """Generate signed URL for chart download.

    Args:
        path: Storage path.
        expires_in: URL 有效期（秒），默认 5 分钟。

    Returns:
        Signed URL string.
    """
    client = get_supabase_client()
    result = client.storage.from_(BUCKET).create_signed_url(path, expires_in)
    if not result or not result.get("signedURL"):
        raise RuntimeError("Failed to create signed URL")
    return result["signedURL"]


def delete_chart(path: str) -> None:
    """Delete chart from storage."""
    client = get_supabase_client()
    client.storage.from_(BUCKET).remove([path])
```

---

## 8. 环境变量清单

添加到 `.env`（本地）和 Vercel Environment Variables（生产/Preview）：

```bash
# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...  # 前端使用
SUPABASE_SERVICE_ROLE_KEY=eyJ...  # 服务端专用

# 应用配置
DAILY_QUOTA_DEFAULT=5
PLATFORM_COST_THRESHOLD_MICROS=5000000  # 每日平台费用阈值（5美元）
APP_URL=https://your-app.vercel.app
ENVIRONMENT=production  # or preview / development

# OpenAI / 模型
OPENAI_API_KEY=sk-...
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_API_MODEL=gpt-4o-mini
```

---

## 9. Vercel 部署配置

### 9.1 `vercel.json`

```json
{
  "builds": [
    {
      "src": "app/main.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "app/main.py"
    },
    {
      "src": "/(.*)",
      "dest": "app/main.py"
    }
  ],
  "functions": {
    "app/main.py": {
      "maxDuration": 120
    }
  }
}
```

### 9.2 环境变量作用域

在 Vercel Dashboard → Project Settings → Environment Variables：

| 变量 | Production | Preview | Development |
|---|---|---|---|
| `SUPABASE_URL` | Prod 项目 URL | Preview 项目 URL | Local URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Prod secret | Preview secret | Local secret |
| `OPENAI_API_KEY` | 生产密钥 | 相同或限制额度 | 开发密钥 |
| `DAILY_QUOTA_DEFAULT` | 5 | 10 | 999 |
| `PLATFORM_COST_THRESHOLD_MICROS` | 5000000 | 1000000 | 999999999 |

---

## 10. 验证清单

部署后验证以下功能：

- [ ] 新用户注册自动创建 profile（触发器工作）
- [ ] 非邀请邮箱登录被拒绝（如需邀请制）
- [ ] 用户只能看到自己的 analyses 记录
- [ ] 用户只能访问自己的 charts 文件
- [ ] 额度预占/消费/释放 RPC 正常工作
- [ ] 分析完成后的图表能上传 Storage 并生成签名 URL
- [ ] 签名 URL 过期后不可访问
- [ ] 管理员可以通过 service_role 查看所有数据
- [ ] Preview 环境不会污染 Production 数据

---

## 11. 常见问题

**Q: 为什么 service_role 绕过 RLS 后还要在代码里检查 user_id？**
A: service_role 是超级权限，服务端代码是最后一道防线。必须在 Python 层显式校验 `user_id = auth.uid()`，防止接口被滥用。

**Q: 魔法链接过期时间怎么调？**
A: Supabase Dashboard → Authentication → Settings → JWT Settings → `JWT Expiration`（默认 3600 秒）。魔法链接本身在 Email Templates 里无法控制过期，由 Supabase 内部管理（默认 1 小时）。

**Q: 额度预占的并发安全如何保证？**
A: `reserve_quota` 使用 `SECURITY DEFINER` 在数据库层执行，PostgreSQL 的行锁和事务隔离确保并发请求不会重复扣费。测试时必须包含并发场景。

**Q: 需要 Redis 吗？**
A: Beta 阶段不需要。Supabase PostgreSQL 的 RPC + 行锁已足够处理额度预占。如果 P95 分析耗时超过 60 秒，再考虑引入独立队列。
