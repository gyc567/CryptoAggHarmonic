# Auth System — Audit Report v2（审计修复验证）

**Date**: 2026-09-10
**Loop**: AUTH-LOOP-02
**Scope**: 三个审计修复的代码审查 + 测试验证

---

## 修复验证

### Fix 1 — 速率限制（Rate Limiting）

**代码变更**: `app/api/admin_routes.py` line 74

```python
@admin_bp.route("/invites", methods=["POST"])
@require_auth
@_admin_required
@get_limiter().limit("admin")   # ← 新增
def create_invite(user: dict[str, Any]):
```

**装饰器执行顺序**（由内到外）:
1. `@get_limiter().limit("admin")` — 速率检查，读取 `kwargs["user"]`
2. `@_admin_required` — 检查 `role == "admin"`
3. `@require_auth` — 验证 JWT，注入 `user` 到 kwargs

请求流程：`RateLimiterWrapper` → `_admin_required` → `require_auth` → `create_invite`

✅ **正确**：速率限制在外层，不会在认证失败时误消耗限额

✅ **正确**：`get_limiter()` 是单例模式，多次调用返回同一实例，无额外开销

✅ **正确**：超限返回 429 + `Retry-After` 头，响应格式与项目一致

---

### Fix 2 — `max_uses` 上限说明

**代码变更**: docstring + line 97

```python
max_uses: int (default 1) - how many times code can be used (max 100)  # ← 更新

max_uses = max(1, min(data.get("max_uses", 1), 100))  # Clamp to 1-100
```

✅ **正确**：`min(data.get("max_uses", 1), 100)` 硬编码上限 100，DB 约束独立校验

---

### Fix 3 — Service Role 注释

**代码变更**: lines 101-102

```python
try:
    # Safe: service role bypasses RLS, but this route is admin-only
    # and requires a valid admin JWT via @require_auth + @_admin_required.
    client = get_supabase_client(use_service_role=True)
```

✅ **正确**：所有 admin 路由均已通过 `@require_auth + @_admin_required` 双重保护

⚠️ **注意**：`use_service_role=True` 在其余 5 个 admin 路由中也有使用（lines 182, 247, 307, 366, 446），注释仅在 `create_invite` 处有说明。建议统一在模块 docstring 或每个路由处补充说明。

---

## 测试验证

```
tests/api/test_admin_routes.py         16 passed  ✅
tests/test_supabase_client_auth.py    15 passed  ✅
────────────────────────────────────────────────
Total                                 31 passed  ✅
```

**装饰器链集成测试覆盖**：
- `test_disable_auth_bypasses_auth_check` — 验证 `DISABLE_AUTH=1` 绕过 auth，与速率限制装饰器兼容

---

## 剩余观察（非阻塞）

| # | 描述 | 建议 |
|---|---|---|
| A | `use_service_role=True` 在其他 5 个 admin 路由无内联注释 | 在 `admin_routes.py` 模块 docstring 统一说明 |
| B | 内存存储速率限制不跨 gunicorn worker 共享 | 生产环境切换到 Redis 后端（rate_limit.py 已有注释说明） |
| C | 无邀请码暴力破解防护（错误码 3 次后锁定） | 当前通过 admin 身份控制 + 日志审计覆盖，未来可加 count 限制 |

---

## 结论

| 修复项 | 状态 |
|---|---|
| ① 速率限制装饰器 | ✅ 已验证 |
| ② `max_uses` 上限文档 | ✅ 已验证 |
| ③ Service Role 内联注释 | ✅ 已验证 |

31/31 测试通过。三项审计修复实现正确，可以合并。
