# CryptoAgg 前端样式重构方案（Agentrade / Deep-Research 风格）

> 目标：参考 https://agentrade.space/deep-research 的视觉语言，对当前 `frontend/` 做**纯样式重构**。不修改功能逻辑、Hook、API 调用或状态管理。保持测试 125 passed / 100% 覆盖率、`build` 与 `lint` 通过。

---

## 审计意见摘要（本次新增）

对初版方案进行自我审计后，发现以下主要问题并已在本文档中修正：

1. **Tailwind `@apply` 与自定义变量命名冲突**：原方案写出 `border-color-cyan/60`、`bg-bg-card/80` 等 `@apply` 语法，但 Tailwind 默认没有 `color-*` / `bg-*` 这种自定义颜色前缀，直接写会编译失败。新版统一用 Tailwind 已有的 `cy`、`purple`、`cyan`、`violet` 等语义命名，或在 CSS 中直接使用 `hsl()` / `rgba()` 而非 `@apply` 伪类。
2. **变量系统碎片化**：原方案同时保留 `--surface-1/2/3`、`--bg-base/card/elevated/hover` 两套背景层级，容易造成维护混乱。新版收敛为 shadcn/ui 兼容的 `--background / --card / --popover / --muted / --accent / --border / --input / --ring`，再用 `--elevated`、`--hover`、`--subtle` 做扩展。
3. **布局改动越界**："Dashboard 改成 Hero 分析面板 + 聊天气泡" 属于交互/布局重构，已超出"只改样式"范围。新版保持现有 DOM 结构与网格布局，仅对视觉层次、颜色、圆角、阴影、边框做升级。
4. **缺少兼容性策略**：如果 PR-1 改完 CSS 变量而组件仍用旧 className，界面可能直接崩掉。新版明确所有旧 `.glass-card`、`.btn-primary` 等类保留映射关系，确保逐 PR 迁移时界面始终可用。
5. **测试策略过粗**：新版给出具体 `grep` 命令，定位测试中可能受影响的 className 断言。
6. **light 主题未细化**：新版给出更克制的 light token，并明确"以 dark 为主、light 可接受"的验收标准。

---

## 1. 设计方向与约束

### 1.1 视觉目标
- **更深的科技底色**：背景进一步压暗，页面、卡片、悬浮层三层对比更清晰。
- **克制的玻璃拟态**：保留 `backdrop-blur`，但降低背景杂色，让卡片更干净、内容更突出。
- **三级边框系统**：`dim`（几乎不可见）→ `subtle`（默认卡片边框）→ `accent`（hover/焦点），避免所有边框一样重。
- **渐变与发光只用于重点**：主按钮、品牌 Logo、报告标题、关键数字；小标签、普通列表禁用 glow。
- **报告感**：结果页像一份结构化的 AI 研究报告，而非聊天对话。

### 1.2 硬性约束
- 只改 `app/globals.css`、`tailwind.config.ts`、组件/页面中的 `className` 字符串。
- 不改动 `hooks/`、`lib/api.ts`、类型定义、测试文件（除非测试断言了被删除的 className，则仅更新该选择器）。
- 新增 CSS 变量必须同时给出 `:root`（light）与 `.dark` 两套值，保持主题切换可用。
- 所有新动画优先使用 Tailwind `animate-*`，并加 `prefers-reduced-motion` 降级。
- **不改动 DOM 结构与布局网格**，仅做视觉升级。

---

## 2. 设计令牌（Design Tokens）

采用 shadcn/ui 语义为主，叠加 Agentrade 风格。所有颜色均以 HSL（无括号形式）存储，保持与现有代码一致。

### 2.1 背景层级

| 变量 | 语义 | dark 建议 | light 建议 |
|---|---|---|---|
| `--background` | 页面底色 | `228 35% 5%` | `220 20% 97%` |
| `--card` | 卡片背景 | `230 24% 9%` | `0 0% 100%` |
| `--popover` | 下拉/弹窗背景 | `230 22% 12%` | `0 0% 100%` |
| `--muted` | 次级区块、hover 底 | `230 20% 15%` | `220 18% 94%` |
| `--accent` | 高亮底、选中态 | `230 25% 18%` | `220 25% 92%` |
| `--elevated` | 悬浮面板、输入框底 | `230 22% 12%` | `220 18% 96%` |

> 旧的 `--surface-1/2/3` 做如下兼容映射，避免中间态界面损坏：
> - `--surface-1` → `--card`
> - `--surface-2` → `--elevated`
> - `--surface-3` → `--muted`

### 2.2 文字层级

| 变量 | 语义 | dark | light |
|---|---|---|---|
| `--foreground` | 主文字 | `210 33% 98%` | `228 35% 10%` |
| `--muted-foreground` | 次要说明 | `220 15% 58%` | `220 12% 45%` |
| `--secondary-foreground` | 辅助标签 | `220 18% 70%` | `220 12% 40%` |

### 2.3 边框层级

| 变量 | 语义 | dark | light |
|---|---|---|---|
| `--border-dim` | 几乎不可见的底边 | `226 20% 18% / 0.35` | `220 18% 85% / 0.45` |
| `--border-subtle` | 默认卡片边框 | `226 20% 22% / 0.55` | `220 18% 85% / 0.75` |
| `--border` | 输入框/分隔 | `226 20% 24%` | `220 18% 82%` |
| `--border-accent` | hover/焦点高亮 | `190 100% 50%` | `193 100% 43%` |
| `--input` | 输入框专用边框 | `226 20% 22%` | `220 18% 85%` |
| `--ring` | focus ring | `190 100% 50%` | `193 100% 43%` |

### 2.4 强调色

保留现有 `cy` / `purple` 扩展，但新增 `cyan` / `violet` 别名，方便使用 Tailwind 默认颜色名写渐变。最终 CSS 中统一用 CSS 变量，Tailwind 配置中同时暴露 `cy`/`purple` 与 `cyan`/`violet`。

| 变量 | dark | light |
|---|---|---|
| `--cyan` | `#00d4ff` | `#00a8cc` |
| `--cyan-glow` | `rgba(0,212,255,0.22)` | `rgba(0,168,204,0.18)` |
| `--purple` | `#9360eb` | `#705ff1` |
| `--purple-glow` | `rgba(147,96,235,0.22)` | `rgba(112,95,241,0.18)` |
| `--gradient-primary` | `linear-gradient(135deg, #00d4ff, #9360eb)` | `linear-gradient(135deg, #00a8cc, #705ff1)` |

### 2.5 功能色

| 变量 | dark | light |
|---|---|---|
| `--success` | `#17cf5a` | `#17cf5a` |
| `--warning` | `#ffb029` | `#ffa50a` |
| `--danger` | `#ff527a` | `#ff426e` |

---

## 3. Tailwind 配置扩展

在 `tailwind.config.ts` 的 `theme.extend` 中：

```ts
colors: {
  // shadcn 语义
  background: "hsl(var(--background))",
  foreground: "hsl(var(--foreground))",
  card: "hsl(var(--card))",
  popover: "hsl(var(--popover))",
  muted: "hsl(var(--muted))",
  accent: "hsl(var(--accent))",
  elevated: "hsl(var(--elevated))",
  border: {
    DEFAULT: "hsl(var(--border))",
    dim: "hsl(var(--border-dim))",
    subtle: "hsl(var(--border-subtle))",
    accent: "hsl(var(--border-accent))",
  },
  input: "hsl(var(--input))",
  ring: "hsl(var(--ring))",
  // 强调色
  cyan: {
    DEFAULT: "var(--cyan)",
    glow: "var(--cyan-glow)",
  },
  violet: {
    DEFAULT: "var(--purple)",
    glow: "var(--purple-glow)",
  },
  // 向后兼容
  cy: { DEFAULT: "var(--cyan)", dark: "var(--cyan)", glow: "var(--cyan-glow)" },
  purple: { DEFAULT: "var(--purple)", dark: "var(--purple)", glow: "var(--purple-glow)" },
  success: { DEFAULT: "var(--success)", dark: "var(--success)" },
  warning: { DEFAULT: "var(--warning)", dark: "var(--warning)" },
  danger: { DEFAULT: "var(--danger)", dark: "var(--danger)" },
},
boxShadow: {
  "glow-cyan": "0 0 28px var(--cyan-glow)",
  "glow-purple": "0 0 28px var(--purple-glow)",
  "glow-sm": "0 0 12px var(--cyan-glow)",
  card: "0 18px 48px rgba(0,0,0,0.28)",
},
backgroundImage: {
  "gradient-primary": "var(--gradient-primary)",
  "gradient-radial-glow": "radial-gradient(circle at 50% 0%, var(--cyan-glow), transparent 55%)",
},
animation: {
  "fade-in": "fadeIn 0.4s ease-out forwards",
  "slide-up": "slideUp 0.35s ease-out forwards",
  "pulse-glow": "pulseGlow 2.5s ease-in-out infinite",
},
keyframes: {
  fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
  slideUp: { from: { opacity: "0", transform: "translateY(12px)" }, to: { opacity: "1", transform: "translateY(0)" } },
  pulseGlow: { "0%, 100%": { opacity: "0.6" }, "50%": { opacity: "1" } },
},
borderRadius: {
  "2xl": "1.25rem",
  "3xl": "1.5rem",
},
```

---

## 4. 全局组件类（globals.css）

所有类使用**实际 CSS 属性**或**已注册的 Tailwind 工具类**，避免 `@apply` 引用未定义的颜色名。

### 4.1 卡片系统

```css
.glass-card {
  border-radius: 1rem;
  border: 1px solid hsl(var(--border-subtle));
  background-color: hsl(var(--card) / 0.85);
  backdrop-filter: blur(20px);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
}

.glass-elevated {
  border-radius: 1rem;
  border: 1px solid hsl(var(--border-subtle));
  background-color: hsl(var(--elevated) / 0.9);
  backdrop-filter: blur(20px);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
}

.glass-hover {
  transition: border-color 0.2s ease, background-color 0.2s ease;
}
.glass-hover:hover {
  border-color: hsl(var(--border-accent));
  background-color: hsl(var(--muted));
}

.gradient-border-card {
  position: relative;
  border-radius: 1rem;
  padding: 1px;
  background: linear-gradient(135deg, var(--cyan) 0%, var(--purple) 100%);
}
.gradient-border-card > .inner {
  border-radius: calc(1rem - 1px);
  background-color: hsl(var(--card));
}
```

### 4.2 按钮系统

```css
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border-radius: 0.75rem;
  padding: 0.625rem 1rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: white;
  background: var(--gradient-primary);
  box-shadow: 0 0 12px var(--cyan-glow);
  transition: box-shadow 0.2s ease, filter 0.2s ease, transform 0.1s ease;
}
.btn-primary:hover {
  box-shadow: 0 0 24px var(--cyan-glow);
  filter: brightness(1.08);
}
.btn-primary:active {
  transform: scale(0.98);
}
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border-radius: 0.75rem;
  border: 1px solid hsl(var(--border-subtle));
  background-color: hsl(var(--elevated));
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: hsl(var(--foreground));
  transition: border-color 0.2s ease, background-color 0.2s ease, transform 0.1s ease;
}
.btn-secondary:hover {
  border-color: hsl(var(--border-accent));
  background-color: hsl(var(--muted));
}
.btn-secondary:active {
  transform: scale(0.98);
}

.btn-ghost {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border-radius: 0.5rem;
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
  color: hsl(var(--muted-foreground));
  transition: background-color 0.2s ease, color 0.2s ease;
}
.btn-ghost:hover {
  background-color: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.btn-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border-radius: 0.75rem;
  padding: 0.625rem 1rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--danger);
  background-color: color-mix(in srgb, var(--danger) 10%, transparent);
  transition: background-color 0.2s ease, box-shadow 0.2s ease;
}
.btn-danger:hover {
  background-color: color-mix(in srgb, var(--danger) 18%, transparent);
  box-shadow: 0 0 16px color-mix(in srgb, var(--danger) 20%, transparent);
}
```

### 4.3 输入框

```css
.input-field {
  width: 100%;
  border-radius: 0.75rem;
  border: 1px solid hsl(var(--input));
  background-color: hsl(var(--elevated));
  padding: 0.625rem 1rem;
  font-size: 0.875rem;
  color: hsl(var(--foreground));
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.input-field::placeholder {
  color: hsl(var(--muted-foreground));
}
.input-field:focus {
  border-color: hsl(var(--border-accent));
  box-shadow: 0 0 0 3px var(--cyan-glow);
}
```

### 4.4 徽章 / Chips

```css
.badge {
  display: inline-flex;
  align-items: center;
  border-radius: 9999px;
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  line-height: 1.25rem;
}
.badge-cyan {
  border: 1px solid color-mix(in srgb, var(--cyan) 30%, transparent);
  background-color: color-mix(in srgb, var(--cyan) 10%, transparent);
  color: var(--cyan);
}
.badge-purple {
  border: 1px solid color-mix(in srgb, var(--purple) 30%, transparent);
  background-color: color-mix(in srgb, var(--purple) 10%, transparent);
  color: var(--purple);
}
.badge-success {
  border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
  background-color: color-mix(in srgb, var(--success) 10%, transparent);
  color: var(--success);
}
.badge-warning {
  border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
  background-color: color-mix(in srgb, var(--warning) 10%, transparent);
  color: var(--warning);
}
.badge-danger {
  border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
  background-color: color-mix(in srgb, var(--danger) 10%, transparent);
  color: var(--danger);
}
.badge-subtle {
  border: 1px solid hsl(var(--border-subtle));
  background-color: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
}
```

### 4.5 报告卡片

```css
.report-hero {
  position: relative;
  overflow: hidden;
  border-radius: 1.5rem;
  border: 1px solid hsl(var(--border-subtle));
  background: linear-gradient(145deg, hsl(var(--elevated)) 0%, hsl(var(--card)) 100%);
  padding: 1.5rem;
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
}
.report-card {
  border-radius: 1rem;
  border: 1px solid hsl(var(--border-subtle));
  background-color: hsl(var(--card) / 0.8);
  padding: 1.25rem;
}
.report-card-accent {
  border-left: 2px solid var(--cyan);
  background-color: hsl(var(--elevated) / 0.6);
}
```

### 4.6 背景装饰与动画

```css
.login-grid-line {
  background-image: linear-gradient(to right, var(--cyan-glow) 1px, transparent 1px),
                    linear-gradient(to bottom, var(--cyan-glow) 1px, transparent 1px);
  background-size: 48px 48px;
}

.bg-radial-glow {
  pointer-events: none;
  position: fixed;
  inset: 0;
  background: radial-gradient(circle at 50% 0%, var(--cyan-glow), transparent 55%);
  opacity: 0.6;
}

.shimmer {
  background: linear-gradient(
    90deg,
    hsl(var(--muted) / 0.4) 25%,
    color-mix(in srgb, var(--cyan) 6%, transparent) 50%,
    hsl(var(--muted) / 0.4) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.6s infinite linear;
}

@media (prefers-reduced-motion: reduce) {
  .shimmer,
  .animate-fade-in,
  .animate-slide-up,
  .animate-pulse-glow {
    animation: none !important;
  }
}
```

---

## 5. 页面级样式映射（保持 DOM 不变）

### 5.1 `/login`
- 背景：`bg-background` + `login-grid-line opacity-30` + 底部渐变遮罩。
- 品牌 Logo 容器：`gradient-border-card` + inner 中放 `rounded-2xl bg-gradient-to-br from-cyan to-violet shadow-glow-cyan`。
- 标题：`text-gradient` 保留，但使用新的 `--gradient-primary`。
- 表单卡片：`glass-elevated p-6 sm:p-8`。
- input：`input-field pl-10`。
- 提交按钮：`btn-primary w-full`。
- 错误提示：`badge-danger block rounded-lg px-3 py-2 text-sm`。

### 5.2 `/dashboard`
**保持当前左右布局**，仅替换视觉类：
- 左侧 Form 容器：`glass-elevated`（或外层再加 `report-hero`  if 需要氛围）。
- input / select：`input-field`。
- 分析按钮：`btn-primary`。
- 结果卡片：`report-card`；重要结论块可用 `report-card-accent`。
- 关键数字：`text-gradient`。
- HistoryRail 容器：`glass-card`。
- 历史项：`glass-hover rounded-xl border border-transparent bg-muted/50 px-3 py-3`。
- Header：`glass-elevated` 或底部边框 `border-dim`。
- QuotaBadge：`badge-cyan`。
- ThemeToggle：容器 `rounded-full border border-border-subtle bg-card p-1`，active 项 `bg-cyan/10 text-cyan shadow-glow-sm`。

### 5.3 `/analysis/[id]`
- 外层：`report-hero`。
- 子区块：`report-card`。
- KPI 数字：`text-gradient`。
- 返回按钮：`btn-ghost`。

### 5.4 `/history`
- 列表项：`glass-card glass-hover`。
- 状态 chip：`badge-success` / `badge-warning` / `badge-danger`。
- 方向 chip：`badge-success` / `badge-danger` / `badge-subtle`。
- 筛选 select：`input-field w-auto py-2`。
- 详情按钮：`btn-secondary py-2 px-3 text-xs`。
- 空状态：`glass-elevated p-8 text-center text-sm text-muted-foreground`。

### 5.5 `/settings`
- section：`glass-card`。
- InfoRow：`rounded-xl border border-transparent bg-muted/60 px-4 py-3 transition-colors hover:border-border-subtle hover:bg-muted`。
- 图标容器：`badge-subtle h-8 w-8 items-center justify-center rounded-full`。
- 进度条：`h-1.5 rounded-full bg-muted overflow-hidden`；填充 `bg-gradient-to-r from-cyan to-violet`。
- 退出登录：`btn-danger w-full`。

### 5.6 `/position`
- panel：`glass-card`。
- 账户结构进度条：底层 `bg-muted rounded-full overflow-hidden`；填充分三段 `bg-cyan`、`bg-violet`、`bg-success`。
- 风险等级 chip：`badge-cyan` / `badge-warning` / `badge-danger`。
- 输入框：`input-field`。
- 按钮：`btn-primary`、`btn-secondary`、`btn-ghost`。
- 持仓列表行：`glass-hover rounded-xl border border-transparent bg-muted/40 px-3 py-2`。

---

## 6. 组件级改动清单

| 文件 | 改动 |
|---|---|
| `app/globals.css` | 重写 token 与组件类；保留旧变量映射；加 reduce-motion |
| `tailwind.config.ts` | 扩展 colors / shadows / animations / gradients / radius |
| `components/layout/header.tsx` | 导航 `.nav-item` 更新为新的 hover/active 态 |
| `components/shared/theme-toggle.tsx` | pill 容器 + active glow |
| `components/shared/quota-badge.tsx` | 改为 `badge-cyan` |
| `components/dashboard/analysis-form.tsx` | 外层 `glass-elevated`，控件 `input-field`，按钮 `btn-primary` |
| `components/dashboard/result-card.tsx` | `report-card` / `report-card-accent`，关键数字 `text-gradient` |
| `components/dashboard/history-rail.tsx` | 容器 `glass-card`，列表项 `glass-hover` |
| `components/position/*` | panel / 输入 / 按钮 / chip 统一使用新类 |
| `app/login/page.tsx` | `gradient-border-card`、`glass-elevated`、`input-field`、`btn-primary` |
| `app/history/page.tsx` | 列表项、chip、空状态、筛选器使用新类 |
| `app/settings/page.tsx` | section、info row、进度条、退出按钮使用新类 |
| `app/analysis/[id]/page.tsx` | `report-hero` + `report-card` |

---

## 7. 动画与微交互

1. **页面进入**：主面板加 `animate-fade-in animate-slide-up`；多个面板通过 inline `animation-delay` 形成 stagger。
2. **按钮**：primary hover 亮度 `1.08` + glow 放大；active `scale-[0.98]`。
3. **卡片 hover**：边框 `border-subtle` → `border-accent`；背景 `bg-card` → `bg-muted`；200ms ease。
4. **shimmer**：颜色从纯白改为 cyan tint，更克制。
5. **focus ring**：input / button focus 使用 `box-shadow: 0 0 0 3px var(--cyan-glow)`，替代默认 ring。
6. **reduce motion**：所有动画在 `prefers-reduced-motion: reduce` 下禁用。

---

## 8. 响应式

- `report-hero` 在 `sm` 以下 padding 从 `p-6` 降为 `p-4`，圆角保持。
- Dashboard 网格保持现有 `lg:grid-cols-[1fr_360px]`，不改动。
- `.badge` 保持 `text-xs`，避免小屏换行；必要时用 `whitespace-nowrap`。

---

## 9. 迁移步骤（分 3 个 PR，每步界面可用）

### PR-1：设计令牌 + 兼容层
1. 在 `app/globals.css` 新增 `:root`/`.dark` token；旧 `--surface-*` 映射到新变量。
2. 重写 `.glass-card`、`.btn-primary`、`.btn-secondary`、`.input-field`、`.badge-*` 等类；保留旧类名作为 alias 至少到 PR-3 结束。
3. 更新 `tailwind.config.ts`。
4. 验证：
   ```bash
   npm run lint
   npm run test
   npm run build
   ```

### PR-2：共享组件
1. 改 `header.tsx`、`theme-toggle.tsx`、`quota-badge.tsx`。
2. 改 `analysis-form.tsx`、`result-card.tsx`、`history-rail.tsx`。
3. 跑测试与构建。

### PR-3：页面收尾 + 清理
1. 改 `login/page.tsx`、`history/page.tsx`、`settings/page.tsx`、`analysis/[id]/page.tsx`、`position/*`。
2. 全局搜索仍在使用的旧 className / 旧变量，统一替换。
3. 移除 PR-1 中为了兼容而保留的旧 alias（如果确认无其他引用）。
4. 跑测试与构建。

---

## 10. 测试策略（更具体）

### 10.1 先定位风险
运行以下命令，找出测试中直接断言的 className：

```bash
# 查找测试中使用的 className 断言
grep -R "toHaveClass\|toHaveAttribute.*class\|getByClassName" frontend --include="*.test.*" --include="*.spec.*"

# 查找组件/页面中仍在使用旧 surface 类的位置
grep -R "surface-1\|surface-2\|surface-3" frontend/app frontend/components --include="*.tsx"

# 查找旧 glass-card-dark 等一次性类
grep -R "glass-card-dark\|glass-card-light" frontend --include="*.tsx" --include="*.css"
```

### 10.2 验收命令
每次 PR 后必须执行：

```bash
cd frontend
npm run test
npm run build
npm run lint
```

### 10.3 标准
- 125 passed。
- 覆盖率 statements/branches/functions/lines 均为 100%。
- `build` 与 `lint` 零错误。

---

## 11. 风险与回退

| 风险 | 缓解 |
|---|---|
| 改了 className 导致测试选择器失效 | 迁移前先用 grep 定位；只更新断言中的类名，不改测试逻辑 |
| 中间 PR 界面样式崩坏 | PR-1 保留旧类名 alias；所有旧 `--surface-*` 映射到新变量 |
| 新颜色对比度不足 | 用 DevTools Lighthouse 检查，主文字对比度 ≥ 4.5:1，大文字 ≥ 3:1 |
| light 主题不协调 | 提供独立 light token；验收时同时检查 light/dark |
| 动画过强 | 加 `prefers-reduced-motion` 全局关闭 |
| `color-mix()` 兼容性 | 目标浏览器为现代 Chromium/WebKit（Next 14 默认），可接受；如需降级可用 `rgba()` 硬编码 |

---

## 12. 需要用户确认的问题

1. **是否保留 light 主题？** Agentrade 风格偏 dark，但当前项目支持 light。建议保留 light，但以 dark 为验收重点。
2. **是否接受 `color-mix()`？** 若需兼容旧版浏览器，可把 badge/button 的半透明背景改成硬编码 `rgba()`。
3. **是否开始实施？** 确认后按 PR-1 → PR-2 → PR-3 执行。
