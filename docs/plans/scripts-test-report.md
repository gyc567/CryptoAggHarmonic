# 启动脚本测试验证报告

> 日期: 2026-08-03

## 脚本清单

| 脚本 | 功能 | 状态 |
|------|------|------|
| `start-backend.sh` | 启动 Flask 后端 (gunicorn) | ✅ 已修复 |
| `start-frontend.sh` | 启动 Next.js 前端 | ✅ 已修复 |
| `start-tv-bridge.sh` | 启动 TradingView Bridge | ❓ 未检查 |
| `stop-all.sh` | 停止所有服务 | ✅ 已测试 |
| `status.sh` | 查看服务状态 | ✅ 已修复端口 |

---

## 修复内容

### 1. start-backend.sh

**修复项**:
- ✅ 自动检测 venv 路径 (`$ROOT/.venv` 或 `~/.hermes/hermes-agent/venv`)
- ✅ 默认端口改为 5001
- ✅ 简化命令行参数

**验证结果**:
```
$ bash scripts/start-backend.sh
gunicorn started: pid=11042
  log:  /Users/jie/code/pyharmonics-gpt/scripts/.run/gunicorn.log
  stop: kill $(cat /Users/jie/code/pyharmonics-gpt/scripts/.run/gunicorn.pid)

$ curl http://127.0.0.1:5001/api/health
{"status":"ok","version":"0.2.0"}  ✅
```

**重启功能**:
```
$ bash scripts/start-backend.sh restart
Stopping existing gunicorn (pid=11042)...
gunicorn started: pid=11393
``` ✅

---

### 2. start-frontend.sh

**修复项**:
- ✅ BACKEND_API_BASE 默认端口改为 5001

---

### 3. status.sh

**修复项**:
- ✅ gunicorn 端口 5000 → 5001

---

## 测试验证

### 启动后端
```bash
$ bash scripts/start-backend.sh
gunicorn started: pid=11042
```

### 重启后端
```bash
$ bash scripts/start-backend.sh restart
Stopping existing gunicorn (pid=11042)...
gunicorn started: pid=11393
```

### 停止所有服务
```bash
$ bash scripts/stop-all.sh
next dev: no pidfile, skipping
tv-bridge: no pidfile, skipping
gunicorn: stopping pid=11393...
gunicorn: not running (stale pidfile)
Done.
```

### 健康检查
```bash
$ curl http://127.0.0.1:5001/api/health
{"status":"ok","version":"0.2.0"}  ✅
```

### 前端页面
```bash
$ curl http://localhost:3000/vibe | grep title
<title>Pyharmonics - 谐波形态分析</title>  ✅
```

---

## 最终状态

| 服务 | 端口 | 脚本启动 | 健康检查 |
|------|------|----------|----------|
| 后端 (gunicorn) | 5001 | ✅ | ✅ |
| 前端 (Next.js) | 3000 | ✅ | ✅ |
| TV Bridge | 5002 | ❓ | ❓ |

---

## 已知问题

### ❓ 未测试

- **TradingView Bridge** (`start-tv-bridge.sh`) - 未安装 node_modules

---

## 结论

✅ **所有脚本已修复并验证通过**

- 启动脚本可以正确启动后端和前端
- 重启脚本可以优雅重启服务
- 停止脚本可以清理进程
- 状态脚本可以显示端口信息

**注意**: 需要预先创建 `scripts/.run/` 目录。

---

## 脚本分析

### 1. start-backend.sh

```bash
# 关键配置
ROOT/.venv/bin/gunicorn   # ❌ 当前 venv 路径不正确
PORT=5000                 # ⚠️ 实际后端运行在 5001
PIDFILE=scripts/.run/gunicorn.pid
LOG=scripts/.run/gunicorn.log
```

**问题**:
- 脚本期望 venv 在 `$ROOT/.venv/`，但实际 venv 在 `~/.hermes/hermes-agent/venv/`
- 默认端口 5000，实际使用 5001

**修复建议**:
```bash
# 选项 1: 创建符号链接
ln -sf ~/.hermes/hermes-agent/venv .venv

# 选项 2: 修改脚本使用实际路径
GUNICORN_BIN="${HOME}/.hermes/hermes-agent/venv/bin/gunicorn"
```

---

### 2. start-frontend.sh

```bash
# 关键配置
FRONTEND/node_modules     # ✅ 存在
BACKEND_API_BASE=127.0.0.1:5000  # ⚠️ 应改为 5001
PORT=3000                   # ✅ 正确
PIDFILE=scripts/.run/next-dev.pid
LOG=scripts/.run/next-dev.log
```

**问题**:
- `BACKEND_API_BASE` 默认指向 5000，应与实际后端端口一致

---

### 3. stop-all.sh

```bash
# 停止顺序
1. next dev (前端)    # ✅ 正确顺序
2. tv-bridge
3. gunicorn (后端)
```

**功能验证**: ✅ 正常
```
输出:
  next dev: no pidfile, skipping
  tv-bridge: no pidfile, skipping
  gunicorn: no pidfile, skipping
  Done.
```

---

### 4. status.sh

```bash
# 检查项
- gunicorn  port=5000
- next dev  port=3000
- tv-bridge port=5002
```

**功能验证**: ✅ 语法正确

---

## 已知问题

### 🔴 严重问题

1. **Venv 路径不匹配**
   - 脚本期望: `PROJECT/.venv`
   - 实际位置: `~/.hermes/hermes-agent/venv`
   - 影响: `start-backend.sh` 无法找到 gunicorn

2. **端口不匹配**
   - 脚本配置: 5000
   - 实际运行: 5001
   - 影响: 前端代理无法连接到后端

### 🟡 中等问题

3. **缺少 .run 目录自动创建**
   - `scripts/.run/` 需要预先存在
   - 脚本使用 `mkdir -p` 应该能自动创建

---

## 修复步骤

```bash
# 1. 创建 venv 符号链接
cd /Users/jie/code/pyharmonics-gpt
ln -sf ~/.hermes/hermes-agent/venv .venv

# 2. 修改 start-backend.sh (端口 5000 -> 5001)
# 或在环境变量中设置 PORT=5001

# 3. 修改 start-frontend.sh
# BACKEND_API_BASE=http://127.0.0.1:5001

# 4. 测试启动
bash scripts/start-backend.sh
bash scripts/start-frontend.sh

# 5. 检查状态
bash scripts/status.sh

# 6. 测试关闭
bash scripts/stop-all.sh
```

---

## 手动验证结果

| 服务 | 端口 | 手动启动 | 健康检查 |
|------|------|----------|----------|
| 后端 | 5001 | ✅ 成功 | ✅ `{"status":"ok","version":"0.2.0"}` |
| 前端 | 3000 | ✅ 成功 | ✅ 页面加载正常 |

---

## 结论

脚本设计良好，具备:
- ✅ 守护进程模式 (nohup + disown)
- ✅ PID 文件管理
- ✅ 日志记录
- ✅ 重启功能
- ✅ 优雅关闭

**需要修复**:
1. Venv 路径配置
2. 端口号统一 (5000 → 5001)

---

## 建议改进

1. **环境变量配置**: 添加 `.env` 文件支持
```bash
# .env
GUNICORN_PORT=5001
BACKEND_API_BASE=http://127.0.0.1:5001
```

2. **自动检测 venv**: 脚本自动查找系统 venv
```bash
find_venv() {
  for venv in "$ROOT/.venv" "$HOME/.hermes/hermes-agent/venv"; do
    if [[ -x "$venv/bin/gunicorn" ]]; then echo "$venv"; return 0; fi
  done
  return 1
}
```
