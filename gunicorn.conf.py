"""Gunicorn configuration for pyharmonics-gpt.

为什么用 gthread + 多进程:
- 默认配置（1 个 sync worker）意味着全站同时只能处理 1 个请求，一条 Vibe SSE
  长连接（/api/vibe/runs/<id>/events）就能挂死整个后端；且 sync worker 会被
  timeout 杀掉长连接。
- gthread worker：每条连接一个线程，SSE 空闲等待时 GIL 已释放，单进程可扛
  数十到数百条并发流；gthread 的主线程独立心跳，长连接不会被 timeout 误杀。
  零额外依赖（gevent 需要 greenlet，当前 pip 源装不了，是可选项不是必需项）。
- CPU 密集的形态检测（pyharmonics）靠多进程（workers）并行，这是 Python 绕开
  GIL 的标准方式。

注意:
- CPU 密集任务（形态检测、Kaleido 渲染）在进程内仍受 GIL 约束，会把同进程的
  其他线程拖慢。后续可把 /api/analyze 卸载到 RQ worker（见
  docs/go-migration-evaluation.md 方案 A）。
- 每个 worker 都会加载 pandas/plotly（约 200-300MB 内存），workers 不要盲目调大。
- 若 pip 源可安装 greenlet，可将 GUNICORN_WORKER_CLASS=gevent 获得更高的
  连接密度（协程比线程轻量），无需改代码。
"""
import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"

# 默认 min(CPU, 4)：多进程扛 CPU 并行；内存受限环境用 GUNICORN_WORKERS 调小。
workers = int(os.getenv("GUNICORN_WORKERS", str(min(multiprocessing.cpu_count(), 4))))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")
# 每 worker 的线程数 = 单进程最大并发连接数（含 SSE）。总并发 ≈ workers × threads。
threads = int(os.getenv("GUNICORN_THREADS", "50"))

# 覆盖 LLM 慢调用和 Kaleido 首次渲染；gthread 长连接不受此值影响（见上方说明）。
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

# 定期回收 worker，防止 plotly/kaleido 的内存缓慢增长累积。
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = 100

accesslog = "-"
errorlog = "-"
