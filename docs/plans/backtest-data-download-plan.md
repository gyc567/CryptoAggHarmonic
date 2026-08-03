# 回测数据下载脚本设计方案

## 1. 背景与目标

### 现状
- 回测脚本 `scripts/backtest_harmonic.py` 每次运行都从 Binance API 下载数据
- 900天 4h 数据约 5400 根 K 线，网络请求耗时约 5-10 秒
- 频繁修改参数/调试时重复下载，浪费时间

### 目标
- 一次性下载并持久化存储 BTCUSDT 4h 回测数据
- 回测脚本优先从本地缓存读取，避免重复下载
- 支持后续扩展其他交易对和时间周期

---

## 2. 审计现有代码

### 2.1 现有数据获取链路

| 组件 | 路径 | 说明 |
|------|------|------|
| `scripts/_binance_stdlib.py` | `fetch_binance_klines()` | urllib 标准库实现，兼容性好 |
| `scripts/backtest_harmonic.py` | `--data-loader stdlib` | CLI 入口，支持 `prod` 和 `stdlib` 两种加载器 |
| `app/infra/historical_data.py` | `fetch_historical_data()` | 生产环境数据获取，支持 TradingView 降级 |

### 2.2 现有回测数据

```
docs/_backtest_artifacts/
├── baseline/          # 基准回测结果
│   ├── BTCUSDT_4h_900d.json
│   └── BTCUSDT_4h_900d.md
├── postfix/          # 修改后回测结果
└── BTCUSDT_4h_90d.json
```

已有数据范围：
- BTCUSDT 4h: 90d, 120d
- BTCUSDT 1d: 90d, 180d, 900d

### 2.3 数据格式

`fetch_binance_klines()` 返回 DataFrame:
```python
columns: ['open', 'high', 'low', 'close', 'volume', 'dts', 'close_time']
index: dts (UTC)
示例: 2026-08-01 00:00:00+00:00
```

---

## 3. 优化方案

### 3.1 目录结构

```
data/
└── backtest/
    ├── binance/
    │   ├── BTCUSDT/
    │   │   ├── 4h.parquet      # 主数据文件
    │   │   └── 4h.meta.json    # 元数据
    │   └── ETHUSDT/
    │       └── 4h.parquet
    └── README.md
```

**设计理由：**
- 按交易所/交易对/周期分层，便于扩展
- Parquet 格式：列式存储、压缩率高、读取快
- 元数据文件记录下载时间、数据范围，便于调试

### 3.2 元数据格式

```json
{
  "symbol": "BTCUSDT",
  "interval": "4h",
  "exchange": "binance",
  "downloaded_at": "2026-08-03T14:00:00Z",
  "date_range": {
    "start": "2021-08-03T00:00:00Z",
    "end": "2026-08-03T00:00:00Z"
  },
  "candles": 5475,
  "source": "binance_stdlib",
  "version": "v1"
}
```

### 3.3 核心函数设计

```python
# scripts/download_backtest_data.py

from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

DATA_ROOT = Path("data/backtest")

def get_data_path(symbol: str, interval: str, exchange: str = "binance") -> Path:
    """返回数据文件路径: data/backtest/binance/BTCUSDT/4h.parquet"""
    return DATA_ROOT / exchange / symbol / f"{interval}.parquet"

def get_meta_path(symbol: str, interval: str, exchange: str = "binance") -> Path:
    """返回元数据路径: data/backtest/binance/BTCUSDT/4h.meta.json"""
    return DATA_ROOT / exchange / symbol / f"{interval}.meta.json"

def download_btc_4h(days: int = 730) -> pd.DataFrame:
    """下载 BTCUSDT 4h K 线数据并保存"""
    from scripts._binance_stdlib import fetch_binance_klines
    
    end = datetime(2026, 8, 1, tzinfo=timezone.utc)  # 固定结束日期保证可重现
    start = end - timedelta(days=days)
    
    df = fetch_binance_klines("BTCUSDT", "4h", start, end)
    save_data(df, "BTCUSDT", "4h")
    return df

def save_data(df: pd.DataFrame, symbol: str, interval: str, exchange: str = "binance"):
    """保存 DataFrame 到 Parquet 文件及元数据"""
    path = get_data_path(symbol, interval, exchange)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # 保存主数据
    df.to_parquet(path, index=True)
    
    # 保存元数据
    meta = {
        "symbol": symbol,
        "interval": interval,
        "exchange": exchange,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "date_range": {
            "start": df.index[0].isoformat(),
            "end": df.index[-1].isoformat()
        },
        "candles": len(df),
        "source": "binance_stdlib",
        "version": "v1"
    }
    with open(get_meta_path(symbol, interval, exchange), 'w') as f:
        json.dump(meta, f, indent=2)

def load_cached(symbol: str, interval: str, exchange: str = "binance") -> pd.DataFrame | None:
    """从本地缓存加载数据，不存在则返回 None"""
    path = get_data_path(symbol, interval, exchange)
    if path.exists():
        return pd.read_parquet(path)
    return None

def ensure_btc_4h(days: int = 730) -> pd.DataFrame:
    """优先从缓存加载，无则下载"""
    df = load_cached("BTCUSDT", "4h")
    if df is not None:
        print(f"[cache] loaded {len(df)} candles from {path}")
        return df
    return download_btc_4h(days)
```

### 3.4 与回测脚本集成

修改 `scripts/backtest_harmonic.py`：

```python
# 新增 --data-file 参数
parser.add_argument("--data-file", type=Path, default=None,
    help="Local parquet file to load instead of fetching (overrides --data-loader)")

# 在 main() 中
if args.data_file:
    from scripts.download_backtest_data import load_cached_data
    df = load_cached_data(args.data_file)
elif args.data_loader == "prod":
    # 现有逻辑
else:
    # 现有逻辑
```

或更简单的集成方式：让回测脚本自动发现本地缓存

```python
# 回测脚本自动检查缓存
df = load_cached("BTCUSDT", "4h")
if df is None:
    print("[warn] No cached data, fetching from API...")
    df = download_btc_4h()
else:
    print(f"[cache] Using cached data: {len(df)} candles")
```

### 3.5 CLI 脚本

```bash
# 下载 BTC 4h 数据（默认 730 天 ≈ 2 年）
python scripts/download_backtest_data.py

# 指定天数
python scripts/download_backtest_data.py --days 900

# 下载其他交易对
python scripts/download_backtest_data.py --symbol ETHUSDT --interval 4h

# 查看缓存状态
python scripts/download_backtest_data.py --status

# 清理缓存
python scripts/download_backtest_data.py --clean
```

---

## 4. 数据范围选择

| 回测周期 | 推荐数据范围 | 4h K线数量 | 说明 |
|----------|--------------|------------|------|
| 90d | 180d | ~1080 | 短期验证 |
| 180d | 365d | ~2190 | 季度分析 |
| 365d | 730d | ~4380 | 年度分析 |
| 900d | 1100d | ~6600 | 完整牛熊周期 |

**推荐：730 天（约 2 年）**
- 覆盖 2024 年牛市、2025 年熊市、2026 年复苏
- 数据量适中，下载约 10-20 秒
- 满足大多数回测需求

---

## 5. 错误处理与健壮性

### 5.1 网络重试

```python
def fetch_with_retry(symbol: str, interval: str, start, end, max_retries=3):
    for attempt in range(max_retries):
        try:
            return fetch_binance_klines(symbol, interval, start, end)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            print(f"[warn] Attempt {attempt+1} failed: {e}, retrying...")
            time.sleep(2 ** attempt)
```

### 5.2 数据校验

```python
def validate_data(df: pd.DataFrame) -> bool:
    """校验数据完整性"""
    if df is None or df.empty:
        return False
    # 检查列
    required = {'open', 'high', 'low', 'close', 'volume'}
    if not required.issubset(df.columns):
        return False
    # 检查时间连续性
    if not df.index.is_monotonic_increasing:
        return False
    # 检查异常值
    if (df['high'] < df['low']).any():
        return False
    return True
```

### 5.3 固定结束日期

为保证回测可重现，使用固定结束日期而非实时日期：

```python
# 固定结束日期（每月更新）
FIXED_END_DATE = datetime(2026, 8, 1, tzinfo=timezone.utc)
```

---

## 6. 可扩展性设计

### 6.1 支持多交易对

```python
# 下载多个交易对
TRADING_PAIRS = [
    ("BTCUSDT", "4h"),
    ("ETHUSDT", "4h"),
    ("SOLUSDT", "4h"),
]

def download_all(pairs: list = None):
    pairs = pairs or TRADING_PAIRS
    for symbol, interval in pairs:
        print(f"Downloading {symbol} {interval}...")
        ensure_data(symbol, interval)
```

### 6.2 支持多时间周期

```python
# 下载多个周期
INTERVALS = ["15m", "1h", "4h", "1d"]

for interval in INTERVALS:
    ensure_data("BTCUSDT", interval)
```

---

## 7. 实现计划

### Phase 1: 基础功能
- [ ] 创建 `scripts/download_backtest_data.py`
- [ ] 实现 `download_btc_4h()` 函数
- [ ] 实现 `load_cached()` 函数
- [ ] 添加 `--data-file` 参数到回测脚本

### Phase 2: 完善功能
- [ ] 添加数据校验逻辑
- [ ] 添加进度显示
- [ ] 添加 `--status` 和 `--clean` 命令

### Phase 3: 扩展支持
- [ ] 支持多交易对下载
- [ ] 添加数据更新检查（比较时间戳）
- [ ] 集成到 CI/CD（可选）

---

## 8. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| Binance API 限流 | 添加延迟和重试机制 |
| 数据不完整 | 校验函数检查 K 线连续性 |
| 本地文件损坏 | 保留 `.bak` 备份，损坏时重新下载 |
| 回测结果不可重现 | 使用固定结束日期 |

---

## 9. 替代方案对比

| 方案 | 优点 | 缺点 |
|------|------|------|
| **Parquet（本方案）** | 列式存储、压缩率高、pandas 原生支持 | 需要 pyarrow 依赖 |
| CSV | 通用性好、无依赖 | 文件大、读取慢 |
| Pickle | Python 原生、读取快 | 不可跨语言、可能存在安全问题 |
| SQLite | 查询灵活、单机好 | 过度设计，K 线数据适合列式存储 |

**选择 Parquet**：平衡了性能和兼容性，大多数数据科学环境已安装。

---

## 10. 结论

本方案通过持久化缓存机制，避免回测时重复下载数据：
1. **单次下载**：730 天 BTCUSDT 4h 数据约 10-20 秒
2. **快速加载**：Parquet 读取约 50ms
3. **透明集成**：回测脚本自动发现并使用缓存
4. **可扩展**：支持多交易对、多周期

建议优先实现 Phase 1，验证后再扩展功能。
