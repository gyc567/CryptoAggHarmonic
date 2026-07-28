# 合约数据实时数据源设计方案

**日期:** 2026-07-28
**状态:** **方案 A 已确认**
**优先级:** P0

---

## 1. 背景与目标

### 现状

现有 `/api/analyze` 数据流：

```
用户请求 → fetch_market_data() → BinanceCandleData.get_candles() [REST 现货轮询]
                                           ↓
                              HarmonicSearch / DivergenceSearch
                                           ↓
                              generate_chart() + 上传 Supabase Storage
```

**问题:**
- 现货数据无法满足合约（期货/永续）分析需求
- REST 轮询有频率限制，无法实时响应
- 缺少 WebSocket 驱动的低延迟数据更新

### 目标

新增 **合约数据实时数据源**，以 WebSocket 驱动为主、REST 为辅，作为主数据源。使用 Binance USDT-M 永续合约正式网。

---

## 2. 核心决策

| 决策点 | 选择 |
|--------|------|
| 架构方案 | **方案 A：客户端直连 Binance WebSocket** |
| 网络 | 正式网 `fstream.binance.com` |
| 降级策略 | Futures REST 失败 → 降级现货 `BinanceCandleData` |
| Pattern 重检测 | 客户端轮询触发，每 10s 最多一次 |

---

## 3. 最终架构（方案 A）

```
客户端请求 /api/analyze
         ↓
  AnalysisOrchestrator.analyze()
         ↓
  fetch_market_data(Market.FUTURES)
         ↓
  ┌──────────────────────────────────────┐
  │  FuturesDataSource                   │
  │  GET /fapi/v1/klines (REST)        │
  └──────────────────────────────────────┘
         ↓
  detect_patterns() ← 复用现有逻辑
         ↓
  generate_chart() → 上传 Supabase
         ↓
  返回:
  {
    "analysis_id": "xxx",
    "chart_url": "...",
    "binance_ws_url": "wss://fstream.binance.com/ws/btcusdt@kline_1m",
    "symbol": "BTCUSDT",
    "interval": "1m"
  }

  客户端直连 binance_ws_url
         ↓
  实时 K 线到达
         ↓
  客户端轮询 GET /api/analysis/{id} 每 10s
         ↓
  服务端返回最新 pattern 结果
```

---

## 4. API 设计

### 4.1 POST /api/analyze

**请求变更:**

```python
class AnalyzeRequest(BaseModel):
    market: Market = Market.FUTURES  # 默认改为期货
    symbol: str
    interval: Interval
    candles: int = 100
    # ... 其他字段不变
```

**响应变更:**

```python
class AnalyzeResponse(BaseModel):
    # ... 现有字段
    binance_ws_url: str           # 新增：客户端直连 Binance WS URL
    analysis_id: str              # 新增：用于后续轮询
    symbol: str                   # 新增：合约交易对
    interval: str                 # 新增：K 线周期
```

### 4.2 GET /api/analysis/{analysis_id}

**新增端点**，客户端轮询获取最新分析结果：

**响应:**

```json
{
  "analysis_id": "xxx",
  "symbol": "BTCUSDT",
  "interval": "1m",
  "last_kline_time": 1722123456789,
  "patterns": [
    {
      "type": "Gartley",
      "direction": "bullish",
      "entry": 96100,
      "stop": 95800,
      "target": 96800
    }
  ],
  "divergences": [...],
  "position": "bullish",
  "chart_url": "https://xxx.supabase.co/storage/..."
}
```

---

## 5. 核心组件设计

### 5.1 枚举扩展 (`app/domain/enums.py`)

```python
class Market(Enum):
    BINANCE = "binance"       # 现货
    FUTURES = "futures"       # USDT-M 永续合约
```

### 5.2 数据源类 (`app/infra/futures_data_source.py`)

```python
import json
import requests
from dataclasses import dataclass
from typing import AsyncIterator, Optional
from datetime import datetime

import websockets
from websockets.client import WebSocket


@dataclass
class KlineData:
    """K 线数据，与 pyharmonics 内部格式兼容"""
    open_time: int          # 毫秒时间戳
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    is_closed: bool


class FuturesDataSource:
    """
    Binance USDT-M 永续合约数据源。
    仅使用 REST 接口，WebSocket URL 生成给客户端直连。
    """

    _rest_base = "https://fapi.binance.com"
    _ws_url = "wss://fstream.binance.com/ws"

    def __init__(self, symbol: str, interval: str):
        """
        Args:
            symbol: 合约交易对，如 "BTCUSDT"
            interval: K 线周期，如 "1m", "15m", "1h", "4h", "1d"
        """
        self.symbol = symbol.upper()
        self.interval = interval

    # ===== REST 接口（主链路）=====

    def get_candles(self, limit: int = 100) -> list[KlineData]:
        """
        获取历史 K 线（REST 主链路）。
        """
        response = requests.get(
            f"{self._rest_base}/fapi/v1/klines",
            params={
                "symbol": self.symbol,
                "interval": self.interval,
                "limit": limit
            },
            timeout=10
        )
        response.raise_for_status()
        return [self._parse_rest_kline(k) for k in response.json()]

    def get_latest_close_time(self) -> Optional[int]:
        """
        获取最新一根 K 线的收盘时间，用于客户端轮询时判断是否有新数据。
        """
        candles = self.get_candles(limit=1)
        return candles[0].close_time if candles else None

    # ===== WebSocket URL（供客户端直连）=====

    @property
    def websocket_url(self) -> str:
        """
        返回客户端直连 Binance 的 WebSocket URL。
        格式: <symbol>@kline_<interval>
        """
        return f"{self._ws_url}/{self.symbol.lower()}@kline_{self.interval}"

    # ===== 内部解析方法 =====

    def _parse_rest_kline(self, k: list) -> KlineData:
        """
        解析 REST K 线格式。
        REST 返回: [open_time, open, high, low, close, volume, close_time, ...]
        """
        return KlineData(
            open_time=int(k[0]),
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
            close_time=int(k[6]),
            is_closed=bool(k[8]) if len(k) > 8 else True
        )
```

### 5.3 适配器扩展 (`app/infra/pyharmonics_adapter.py`)

在现有 `fetch_market_data()` 中扩展 dispatch：

```python
from app.domain.enums import Market


def fetch_market_data(market, symbol, interval, candles):
    if market == Market.FUTURES:
        source = FuturesDataSource(symbol, interval)
        return source.get_candles(limit=candles)
    # ... 保留现货逻辑
    raise AppError(
        code="UNSUPPORTED_MARKET",
        message=f"Market {market} is not supported"
    )
```

### 5.4 路由扩展 (`app/main.py`)

新增轮询端点：

```python
@app.get("/api/analysis/<analysis_id>")
@require_auth
def get_analysis_update(analysis_id):
    """
    客户端轮询获取最新分析结果。
    """
    # 1. 验证 analysis_id 属于当前用户
    # 2. 从数据库读取 analysis 记录
    # 3. 重新检测 pattern（如果需要）
    # 4. 返回最新结果
    pass
```

---

## 6. 降级链路

```
请求 [Market.FUTURES]
  │
  ├─ try: FuturesDataSource.get_candles() REST
  │     └─ 失败: 超时 10s / 4xx / 5xx
  │            ↓
  └─ fallback: BinanceCandleData()  # 现货兜底
```

**降级触发条件:**

| 状态码 | 处理 |
|--------|------|
| 429 (限频) | 等待 1s 重试，共 3 次 |
| 5xx (服务器错误) | 超时 10s 切换现货 |
| 网络错误 | 超时 10s 切换现货 |

---

## 7. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/infra/futures_data_source.py` | **新增** | 数据源类（REST + WebSocket URL） |
| `app/domain/enums.py` | **修改** | 加 `FUTURES` 枚举值 |
| `app/domain/schemas.py` | **修改** | `AnalyzeRequest` 默认 `FUTURES`，`AnalyzeResponse` 加字段 |
| `app/infra/pyharmonics_adapter.py` | **修改** | dispatch 加 FUTURES + 降级逻辑 |
| `app/services/analysis.py` | **修改** | 返回中加 `binance_ws_url`、`analysis_id` |
| `app/main.py` | **修改** | 注册 `GET /api/analysis/<id>` 轮询端点 |
| `tests/test_futures_datasource.py` | **新增** | 独立验证 REST |

**不改动:**

- `app/openai_handler.py` — 函数路由不变
- `app/api/auth.py` — 鉴权逻辑不变
- `app/api/middleware.py` — 不涉及
- `app/websocket_handler.py` — 不需要（方案 A 客户端直连）

---

## 8. 实现计划

```
阶段 1          阶段 2           阶段 3
  ↓               ↓                ↓
独立验证 REST   基础集成         轮询端点
  (测试网验证)   + FuturesDataSource
              + enums/schemas
              + adapter
```

### 阶段 1：独立验证（关键！）

**目标:** 验证 Binance Futures 正式网 REST 是否正常返回数据。

创建 `tests/test_futures_datasource.py`：

```python
import pytest
from app.infra.futures_data_source import FuturesDataSource


class TestFuturesDataSource:
    """阶段 1：独立验证 Binance Futures REST 接口"""

    def test_get_candles_returns_data(self):
        """正式网 REST /fapi/v1/klines 返回正确数据"""
        source = FuturesDataSource("BTCUSDT", "1m")
        candles = source.get_candles(limit=10)

        assert len(candles) == 10
        assert all(c.close > 0 for c in candles)
        assert all(c.volume >= 0 for c in candles)
        # K 线应按时间升序
        for i in range(1, len(candles)):
            assert candles[i].open_time > candles[i-1].open_time

    def test_get_candles_latest_close_time(self):
        """最新 K 线收盘时间合理（接近当前时间）"""
        source = FuturesDataSource("BTCUSDT", "1m")
        close_time = source.get_latest_close_time()

        assert close_time is not None
        # 1m K 线关闭时间应在当前时间前后 2min 内
        import time
        now_ms = int(time.time() * 1000)
        assert abs(now_ms - close_time) < 120_000

    def test_websocket_url_format(self):
        """WebSocket URL 格式正确"""
        source = FuturesDataSource("BTCUSDT", "1m")
        assert source.websocket_url == "wss://fstream.binance.com/ws/btcusdt@kline_1m"

    def test_symbol_normalized_to_uppercase(self):
        """symbol 自动转大写"""
        source = FuturesDataSource("btcusdt", "1h")
        assert source.symbol == "BTCUSDT"
        assert "BTCUSDT" in source.websocket_url

    def test_invalid_symbol_raises(self):
        """无效交易对返回错误"""
        source = FuturesDataSource("INVALIDPAIR", "1m")
        with pytest.raises(Exception):  # requests.HTTPError
            source.get_candles(limit=1)

    @pytest.mark.parametrize("interval", ["1m", "5m", "15m", "1h", "4h", "1d"])
    def test_different_intervals(self, interval):
        """各周期 K 线都能正常获取"""
        source = FuturesDataSource("BTCUSDT", interval)
        candles = source.get_candles(limit=5)
        assert len(candles) == 5
```

**运行方式:**
```bash
# 先确保网络能访问 Binance 正式网
pytest tests/test_futures_datasource.py -v
```

### 阶段 2：基础集成

- 实现 `FuturesDataSource` 完整类
- 修改 `fetch_market_data()` dispatch
- 修改 enums 加 `FUTURES`
- 修改 schemas 的默认值和响应字段
- 集成测试验证完整流程

### 阶段 3：轮询端点

- 实现 `GET /api/analysis/<id>` 轮询端点
- 前端适配：拿到 `binance_ws_url` 后直连 Binance
- 设置 10s 轮询间隔

---

## 9. 错误处理

| 场景 | 处理 |
|------|------|
| REST 超时 10s | 降级现货 `BinanceCandleData` |
| REST 429 限频 | 等待 1s 重试，共 3 次 |
| REST 5xx | 降级现货 |
| 无效交易对 | 返回 400 错误 |
| 客户端 WS 断开 | 客户端自动重连 Binance |

---

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Binance Futures REST 不稳定 | 降级到现货兜底，不阻塞用户 |
| 客户端轮询过于频繁 | 服务端限制最低 5s 间隔 |
| 客户端直连 WS 失败 | 客户端指数退避重连 |
| 交易对不支持 | 接口层校验，返回友好错误 |

---

## 11. 测试计划

| 测试类型 | 覆盖场景 |
|---------|---------|
| 单元测试 | `FuturesDataSource` 各方法 |
| 集成测试 | 完整 `analyze()` 流程（Futures market） |
| 降级测试 | Futures REST 失败 → 现货兜底 |
| 格式验证 | K 线数据与 pyharmonics 兼容 |

---

## 12. 相关文档

- [Binance Futures REST API - Klines](https://developers.binance.com/docs/futures/usdt-m contracts/klines)
- [Binance Futures WebSocket API - Kline Streams](https://developers.binance.com/docs/futures/usdt-m contracts/kline-streams)
