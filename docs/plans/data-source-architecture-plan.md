# 数据获取模块架构优化方案

> 本文档对当前数据获取模块进行全面审计，并提出优化方案。

**文档版本**: v1.0
**创建日期**: 2026-08-03
**状态**: 待评审

---

## 一、当前架构审计

### 1.1 现有架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    当前数据获取架构                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   TradingView Bridge (Node.js)                                   │
│        │                                                        │
│        ↓ (失败时)                                               │
│   DirectBinanceCandleData (Spot)                              │
│        │                                                        │
│        ↓ (失败时)                                               │
│   DirectBinanceFuturesCandleData (USDT-M Futures)              │
│        │                                                        │
│        ↓ (失败时)                                               │
│   YahooCandleData (股票/加密货币)                               │
│        │                                                        │
│        ↓ (所有都失败)                                           │
│   AppError: MARKET_DATA_UNAVAILABLE                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 现有代码结构

| 文件 | 职责 | 行数 |
|------|------|------|
| `app/infra/marketdata.py` | Binance 直连适配器 | 284 |
| `app/infra/tradingview_adapter.py` | TradingView Bridge 适配器 | 235 |
| `app/infra/pyharmonics_adapter.py` | 形态检测和转换层 | 352 |

### 1.3 审计发现的问题

#### 🔴 严重问题

| # | 问题 | 影响 | 优先级 |
|---|------|------|--------|
| P1 | 无数据缓存层 | 重复请求浪费资源，同一 symbol 不同请求返回不一致数据 | P0 |
| P2 | 无多镜像备用 | api.binance.com 在某些地区被墙，无法自动切换 | P0 |
| P3 | Binance API Key 明文暴露 | 已在 .env 中配置，但缺少使用说明 | P1 |

#### 🟡 中等问题

| # | 问题 | 影响 | 优先级 |
|---|------|------|--------|
| P4 | 仅支持 Binance + Yahoo | 无法接入 OKX/Bybit 等其他交易所 | P2 |
| P5 | 无数据版本控制 | 调试困难，无法追踪数据变化 | P2 |
| P6 | TradingView Bridge 依赖 Node.js | 额外运维复杂度 | P2 |

#### 🟢 轻微问题

| # | 问题 | 影响 | 优先级 |
|---|------|------|--------|
| P7 | 代码复用性低 | DirectBinanceCandleData 和 DirectBinanceFuturesCandleData 重复代码 | P3 |
| P8 | 错误处理不一致 | 不同适配器错误处理逻辑不同 | P3 |

---

## 二、CCXT 方案评估

### 2.1 CCXT 核心能力

| 评估维度 | 详情 |
|---------|------|
| **支持交易所** | 100+ 家（Binance, OKX, Bybit, Coinbase, Kraken 等） |
| **支持语言** | Python, JavaScript/TypeScript, PHP, C# |
| **4H K线支持** | ✅ 所有主流交易所均原生支持 `4h` 时间框架 |
| **历史数据深度** | 通常可获取 1000~3000 根 K线（约 6个月~1.5年 的 4H 数据） |
| **费用** | 完全免费开源（MIT 协议） |
| **速率限制** | 各交易所不同，通常 1200 次请求/分钟 |

### 2.2 方案对比

| 维度 | 当前方案 | CCXT 方案 | 推荐 |
|------|---------|-----------|------|
| **依赖** | 无额外依赖 | `ccxt` (~2MB) | 当前方案 |
| **交易所数** | 3个（Binance+Yahoo） | 100+ | CCXT |
| **API 复杂度** | 自维护 | CCXT 统一封装 | CCXT |
| **速率限制** | 自处理 | CCXT 内置 | CCXT |
| **数据质量** | Binance 直连，最新 | 统一抽象，延迟略高 | 当前方案 |
| **运维复杂度** | 低 | 中 | 当前方案 |

### 2.3 决策矩阵

```
                          │
        需要多交易所?        │
              │            │
        ┌─────┴─────┐    │
        │            │    │
       否           是     │
        │            │    │
        ↓            ↓     │
   ┌────────┐  ┌────────┐│
   │保持当前│  │引入CCXT │
   │方案+缓存│ │统一接口 │
   └────────┘  └────────┘│
```

**结论**: 引入 CCXT 作为数据源统一层，但保持 Binance 作为首选。

---

## 三、优化方案

### 3.1 目标架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        优化后数据获取架构                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │                    数据源优先级层                                  │     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │     │
│  │  │ 1. TradingView │  │ 2. CCXT       │  │ 3. Direct API │       │     │
│  │  │    (高质量)     │  │   (多交易所)   │  │  (Binance)    │       │     │
│  │  └──────────────┘  └──────────────┘  └──────────────┘       │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                                   │                                      │
│                                   ↓                                      │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │                      缓存层 (Redis + Memory)                    │     │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐              │     │
│  │  │ K线缓存     │  │ 形态缓存   │  │ 指标缓存    │              │     │
│  │  │ TTL: 15min │  │ TTL: 5min  │  │ TTL: 10min  │              │     │
│  │  └────────────┘  └────────────┘  └────────────┘              │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                                   │                                      │
│                                   ↓                                      │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │                      数据标准化层                                  │     │
│  │                   (统一 CandleData 接口)                          │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据源配置

#### 3.2.1 多镜像自动切换

```python
# 配置优先级
BINANCE_MIRRORS = [
    "https://api.binance.com",      # 主
    "https://api.binance.me",       # 中国镜像
    "https://api.binance.us",       # 美国
]

FUTURES_MIRRORS = [
    "https://fapi.binance.com",     # 主
    "https://fapi.binance.me",      # 中国镜像
]
```

#### 3.2.2 交易所支持矩阵

| 交易所 | 优先级 | 数据源 | 状态 | 备注 |
|--------|--------|--------|------|------|
| Binance Spot | 1 | Direct API | ✅ 已有 | 主数据源 |
| Binance Futures | 1 | Direct API | ✅ 已有 | 主数据源 |
| TradingView | 1 | Bridge | ✅ 已有 | 高质量数据 |
| CCXT-Binance | 2 | CCXT | 🟡 新增 | 备用 |
| CCXT-OKX | 3 | CCXT | 🟡 新增 | 扩展 |
| CCXT-Bybit | 3 | CCXT | 🟡 新增 | 扩展 |
| Yahoo | 4 | 直接 | ✅ 已有 | 股票数据 |

### 3.3 缓存策略

#### 3.3.1 缓存配置

| 缓存类型 | TTL | 键格式 | 说明 |
|----------|-----|--------|------|
| K线数据 | 15 分钟 | `kline:{exchange}:{symbol}:{interval}:{limit}` | 允许 K 线在形成期间变化 |
| 形态检测 | 5 分钟 | `pattern:{hash}` | 形态结果相对稳定 |
| 指标计算 | 10 分钟 | `indicator:{exchange}:{symbol}:{interval}` | ATR, RSI 等指标变化慢 |
| 健康检查 | 5 秒 | `health:{source}` | 快速缓存避免频繁探测 |

#### 3.3.2 缓存键设计

```python
# 统一缓存键格式
CACHE_KEY_FORMAT = {
    "kline": "kline:{exchange}:{symbol}:{interval}:{limit}:{version}",
    "pattern": "pattern:{symbol}:{interval}:{type}:{params_hash}",
    "indicator": "indicator:{exchange}:{symbol}:{interval}:{indicator_type}",
}

# 版本号用于区分数据更新
DATA_VERSION = "v2"
```

### 3.4 数据版本控制

```python
@dataclass
class CandleDataWithMeta:
    """带元数据的 K 线数据"""
    candles: pd.DataFrame
    source: str                              # "tradingview" | "ccxt" | "binance"
    exchange: str                            # "binance" | "okx" | "bybit"
    symbol: str                              # "BTCUSDT"
    interval: str                            # "4h"
    version: str = DATA_VERSION              # 数据版本
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    latency_ms: float = 0.0                  # 数据获取延迟
    is_final: bool = True                    # K 线是否已收线
```

---

## 四、模块设计

### 4.1 目录结构

```
app/infra/
├── __init__.py
├── marketdata.py              # 保留：基础适配器
├── tradingview_adapter.py      # 保留：TradingView 适配器
├── pyharmonics_adapter.py     # 保留：形态检测适配器
│
├── data_source/               # 新增：统一数据源层
│   ├── __init__.py
│   ├── base.py               # 抽象基类 DataSource
│   ├── registry.py           # 数据源注册表
│   ├── ccxt_adapter.py       # CCXT 适配器
│   ├── binance_adapter.py    # Binance 直连适配器（重构）
│   └── tradingview_adapter.py # TradingView 适配器（迁移）
│
├── cache/                     # 新增：缓存层
│   ├── __init__.py
│   ├── base.py               # 缓存抽象接口
│   ├── redis_cache.py        # Redis 缓存实现
│   └── memory_cache.py       # 内存缓存（已有）
│
└── data_warehouse.py         # 新增：数据仓库（统一入口）
```

### 4.2 核心接口

```python
# app/infra/data_source/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import pandas as pd


@dataclass
class DataSourceResponse:
    """数据源统一响应格式"""
    df: pd.DataFrame
    source: str                    # 数据源标识
    exchange: str                 # 交易所
    symbol: str
    interval: str
    version: str = "v1"
    fetched_at: datetime = None
    latency_ms: float = 0.0
    is_final: bool = True        # K 线是否已收线


class DataSource(ABC):
    """数据源抽象基类"""

    name: str                     # 数据源名称
    priority: int = 100          # 优先级，数字越小优先级越高

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        interval: str,
        limit: int = 1000,
        since: Optional[int] = None,
    ) -> DataSourceResponse:
        """获取 K 线数据"""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查"""
        pass

    @abstractmethod
    def get_supported_intervals(self) -> list[str]:
        """获取支持的时间框架"""
        pass


# app/infra/data_source/registry.py
class DataSourceRegistry:
    """数据源注册表"""

    def __init__(self):
        self._sources: dict[str, DataSource] = {}
        self._lock = threading.Lock()

    def register(self, name: str, source: DataSource) -> None:
        """注册数据源"""
        with self._lock:
            self._sources[name] = source

    def get(self, name: str) -> Optional[DataSource]:
        return self._sources.get(name)

    def get_all(self) -> list[DataSource]:
        """获取所有数据源，按优先级排序"""
        return sorted(self._sources.values(), key=lambda s: s.priority)

    def fetch_with_fallback(
        self,
        symbol: str,
        interval: str,
        limit: int = 1000,
    ) -> DataSourceResponse:
        """按优先级尝试所有数据源"""
        last_error = None
        for source in self.get_all():
            try:
                if source.health_check():
                    return source.fetch(symbol, interval, limit)
            except Exception as e:
                last_error = e
                logger.warning(f"{source.name} failed: {e}")
                continue
        raise AppError(
            ErrorCode.MARKET_DATA_UNAVAILABLE,
            f"所有数据源都不可用: {last_error}",
            retryable=True,
        )
```

### 4.3 CCXT 适配器

```python
# app/infra/data_source/ccxt_adapter.py
import ccxt
from typing import Optional

class CCXTAdapter(DataSource):
    """CCXT 多交易所适配器"""

    name = "ccxt"
    priority = 20

    def __init__(
        self,
        exchange_name: str = "binance",
        rate_limit: bool = True,
        proxies: Optional[dict] = None,
    ):
        self.exchange_name = exchange_name
        self._exchange = getattr(ccxt, exchange_name)()
        if rate_limit:
            self._exchange.enableRateLimit = True
        if proxies:
            self._exchange.proxies = proxies

    def fetch(
        self,
        symbol: str,
        interval: str,
        limit: int = 1000,
        since: Optional[int] = None,
    ) -> DataSourceResponse:
        start_time = time.time()

        ohlcv = self._exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=interval,
            limit=limit,
            since=since,
        )

        df = pd.DataFrame(
            ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)

        # 检查是否最新 K 线已收线
        is_final = True  # CCXT 不直接提供此信息

        return DataSourceResponse(
            df=df,
            source=self.name,
            exchange=self.exchange_name,
            symbol=symbol,
            interval=interval,
            latency_ms=(time.time() - start_time) * 1000,
            is_final=is_final,
        )

    def health_check(self) -> bool:
        try:
            return self._exchange.has.get('fetchOHLCV', False)
        except:
            return False

    def get_supported_intervals(self) -> list[str]:
        return list(self._exchange.timeframes.keys())
```

### 4.4 缓存实现

```python
# app/infra/cache/redis_cache.py
import json
import hashlib
from typing import Optional, Any

class RedisCache:
    """Redis 缓存实现"""

    def __init__(self, client=None, default_ttl: int = 300):
        if client is None:
            from app.infra.redis_client import get_redis_client
            client = get_redis_client()
        self._client = client
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """获取缓存，自动反序列化"""
        if self._client is None:
            return None
        try:
            value = self._client.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """设置缓存，自动序列化"""
        if self._client is None:
            return False
        try:
            ttl = ttl or self._default_ttl
            serialized = json.dumps(value, default=str)
            return self._client.setex(key, ttl, serialized)
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")
            return False

    def delete(self, key: str) -> bool:
        """删除缓存"""
        if self._client is None:
            return False
        try:
            return self._client.delete(key) > 0
        except:
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """按模式批量删除（如清除某 symbol 的所有缓存）"""
        if self._client is None:
            return 0
        try:
            keys = self._client.keys(pattern)
            if keys:
                return self._client.delete(*keys)
        except:
            pass
        return 0
```

### 4.5 数据仓库（统一入口）

```python
# app/infra/data_warehouse.py
class DataWarehouse:
    """统一数据访问入口"""

    def __init__(
        self,
        cache: Optional[Cache] = None,
        registry: Optional[DataSourceRegistry] = None,
    ):
        self._cache = cache or MemoryCache()
        self._registry = registry or create_default_registry()

    def get_candles(
        self,
        symbol: str,
        interval: str = "4h",
        limit: int = 1000,
        force_refresh: bool = False,
    ) -> DataSourceResponse:
        """获取 K 线数据（带缓存）"""

        # 生成缓存键
        cache_key = self._make_cache_key(symbol, interval, limit)

        # 尝试从缓存获取
        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit: {cache_key}")
                return self._deserialize_response(cached)

        # 从数据源获取
        response = self._registry.fetch_with_fallback(
            symbol=symbol,
            interval=interval,
            limit=limit,
        )

        # 存入缓存
        self._cache.set(cache_key, self._serialize_response(response))

        return response

    def _make_cache_key(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> str:
        """生成缓存键"""
        return f"kline:{symbol}:{interval}:{limit}:{DATA_VERSION}"

    def invalidate(self, symbol: str, interval: str = "*") -> int:
        """清除某 symbol 的缓存"""
        pattern = f"kline:{symbol}:{interval}:*"
        return self._cache.invalidate_pattern(pattern)
```

---

## 五、实施计划

### 5.1 阶段一：缓存层（1-2天）

| 任务 | 负责 | 状态 |
|------|-------|------|
| 1.1 创建 `app/infra/cache/` 目录结构 | - | 🟡 待开发 |
| 1.2 实现 Redis 缓存类 | - | 🟡 待开发 |
| 1.3 实现内存缓存（扩展现有） | - | 🟡 待开发 |
| 1.4 集成到 `fetch_market_data` | - | 🟡 待开发 |
| 1.5 添加缓存配置到 `.env` | - | 🟡 待开发 |

**验收标准**：
- [ ] 相同请求 5 分钟内返回缓存数据
- [ ] 缓存命中率 > 80%
- [ ] 缓存未命中时自动回源

### 5.2 阶段二：多镜像切换（1天）

| 任务 | 负责 | 状态 |
|------|-------|------|
| 2.1 添加镜像配置 | - | 🟡 待开发 |
| 2.2 实现自动切换逻辑 | - | 🟡 待开发 |
| 2.3 添加中国镜像 | - | 🟡 待开发 |

**验收标准**：
- [ ] 主 API 失败时自动切换到镜像
- [ ] 切换日志记录
- [ ] 最多尝试 3 个镜像

### 5.3 阶段三：CCXT 集成（3-5天）

| 任务 | 负责 | 状态 |
|------|-------|------|
| 3.1 添加 CCXT 依赖 | - | 🟡 待开发 |
| 3.2 创建 `app/infra/data_source/` 目录 | - | 🟡 待开发 |
| 3.3 实现 `DataSource` 抽象基类 | - | 🟡 待开发 |
| 3.4 实现 `DataSourceRegistry` | - | 🟡 待开发 |
| 3.5 实现 `CCXTAdapter` | - | 🟡 待开发 |
| 3.6 实现 `BinanceDirectAdapter`（重构） | - | 🟡 待开发 |
| 3.7 实现 `DataWarehouse` | - | 🟡 待开发 |
| 3.8 集成到现有代码 | - | 🟡 待开发 |

**验收标准**：
- [ ] 支持 Binance/OKX/Bybit 三家交易所
- [ ] 数据源自动降级
- [ ] 所有现有测试通过

### 5.4 阶段四：数据版本控制（1天）

| 任务 | 负责 | 状态 |
|------|-------|------|
| 4.1 添加 `DataSourceResponse` 元数据 | - | 🟡 待开发 |
| 4.2 在日志中记录数据源信息 | - | 🟡 待开发 |
| 4.3 添加调试端点 | - | 🟡 待开发 |

**验收标准**：
- [ ] API 响应包含数据源信息
- [ ] 日志包含完整链路追踪

---

## 六、API 变更

### 6.1 新增端点

```python
# GET /api/data/sources
@app.route("/api/data/sources", methods=["GET"])
def list_data_sources():
    """列出所有可用数据源及其状态"""
    sources = registry.get_all()
    return jsonify({
        "sources": [
            {
                "name": s.name,
                "priority": s.priority,
                "healthy": s.health_check(),
                "intervals": s.get_supported_intervals(),
            }
            for s in sources
        ]
    })

# POST /api/data/refresh
@app.route("/api/data/refresh", methods=["POST"])
def refresh_cached_data():
    """强制刷新某 symbol 的缓存"""
    symbol = request.json.get("symbol")
    interval = request.json.get("interval", "4h")
    warehouse.invalidate(symbol, interval)
    return jsonify({"success": True})
```

### 6.2 响应格式变更

```python
# 现有响应
{
    "technical_result": {...}
}

# 优化后响应（新增 meta 字段）
{
    "technical_result": {...},
    "_meta": {
        "data_source": "tradingview",
        "exchange": "binance",
        "fetched_at": "2026-08-03T13:00:00Z",
        "latency_ms": 120,
        "is_final": true,
        "cache_hit": false
    }
}
```

---

## 七、依赖变更

### 7.1 新增依赖

```txt
# requirements.txt 新增
ccxt>=4.0.0
redis>=5.0.0
```

### 7.2 配置变更

```bash
# .env 新增
# 数据源配置
USE_TRADINGVIEW=true
USE_CCXT=true
CCXT_EXCHANGE=binance

# Binance 镜像
BINANCE_API_BASE_URL=https://api.binance.com
BINANCE_FUTURES_API_BASE_URL=https://fapi.binance.com

# 备用镜像（逗号分隔）
BINANCE_MIRRORS=https://api.binance.com,https://api.binance.me,https://api.binance.us
FUTURES_MIRRORS=https://fapi.binance.com,https://fapi.binance.me

# 缓存配置
REDIS_CACHE_TTL_KLINE=900      # 15分钟
REDIS_CACHE_TTL_PATTERN=300    # 5分钟
REDIS_CACHE_TTL_INDICATOR=600  # 10分钟
```

---

## 八、监控和告警

### 8.1 关键指标

| 指标 | 描述 | 告警阈值 |
|------|------|---------|
| `data_fetch_latency_ms` | 数据获取延迟 | > 5000ms |
| `data_fetch_error_rate` | 数据获取错误率 | > 1% |
| `cache_hit_rate` | 缓存命中率 | < 60% |
| `data_source_health` | 数据源健康状态 | any down |

### 8.2 日志格式

```python
# 结构化日志
logger.info(
    "Data fetched",
    extra={
        "source": "tradingview",
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "candles": 1000,
        "latency_ms": 150,
        "cache_hit": False,
        "version": "v1",
    }
)
```

---

## 九、测试计划

### 9.1 单元测试

| 测试用例 | 描述 |
|---------|------|
| `test_ccxt_adapter_fetch` | CCXT 适配器获取数据 |
| `test_ccxt_adapter_health` | 健康检查 |
| `test_cache_get_set` | 缓存读写 |
| `test_cache_invalidate` | 缓存失效 |
| `test_registry_fallback` | 数据源降级 |
| `test_warehouse_cache_hit` | 缓存命中 |
| `test_warehouse_cache_miss` | 缓存未命中 |

### 9.2 集成测试

| 测试用例 | 描述 |
|---------|------|
| `test_full_pipeline` | 完整数据获取流程 |
| `test_binance_mirror_failover` | Binance 镜像切换 |
| `test_all_sources_down` | 所有数据源不可用 |

---

## 十、风险和缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| CCXT 引入增加依赖 | 中 | 保持 Direct API 作为核心 |
| 缓存数据不一致 | 高 | 短 TTL + 版本控制 |
| 多交易所数据格式差异 | 中 | 统一 DataSourceResponse 格式 |
| Redis 不可用 | 低 | 降级到内存缓存 |

---

## 十一、附录

### A. 参考项目

| 项目 | Stars | 用途 |
|------|-------|------|
| [Freqtrade](https://github.com/freqtrade/freqtrade) | 30k+ | 数据下载模块参考 |
| [Jesse](https://github.com/jesse-ai/jesse) | 6k+ | 量化研究框架参考 |
| [CCXT](https://github.com/ccxt/ccxt) | 30k+ | 多交易所适配 |

### B. CCXT 时间框架映射

```python
CCXT_TIMEFRAMES = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}
```

### C. 相关文档

- [TradingView Bridge 设计](../plans/2026-07-28-futures-realtime-data-source.md)
- [Maker-Checker 架构审计](../maker-checker-architecture-audit-and-optimization.md)

---

## 变更历史

| 版本 | 日期 | 修改内容 | 作者 |
|------|------|---------|------|
| 1.0 | 2026-08-03 | 初始版本 | AI |
