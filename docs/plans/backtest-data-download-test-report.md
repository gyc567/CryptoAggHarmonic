# 回测数据下载脚本 - 测试报告

## 概述

本报告记录了 `scripts/download_backtest_data.py` 的实现与测试情况。

## 测试结果

| 指标 | 结果 |
|------|------|
| 测试用例数 | 40 |
| 通过 | 40 |
| 失败 | 0 |
| 代码覆盖率 | 88.20% |

## 测试用例清单

### TestGetDataPath (3 tests)
- `test_basic` - 基本路径生成
- `test_different_exchange` - 不同交易所路径
- `test_symbol_with_prefix` - 交易对路径

### TestGetMetaPath (2 tests)
- `test_basic` - 基本元数据路径
- `test_different_symbol` - 不同交易对元数据路径

### TestSaveData (5 tests)
- `test_save_creates_directories` - 创建目录结构
- `test_save_parquet_roundtrip` - Parquet 读写往返
- `test_save_creates_meta_file` - 创建元数据文件
- `test_save_meta_content` - 元数据内容正确
- `test_save_empty_df` - 空数据框处理

### TestLoadCached (4 tests)
- `test_load_nonexistent_returns_none` - 不存在返回 None
- `test_load_existing` - 加载已缓存数据
- `test_load_preserves_columns` - 保留列
- `test_load_preserves_index` - 保留索引

### TestValidateData (7 tests)
- `test_valid_df` - 有效数据通过验证
- `test_none_returns_false` - None 拒绝
- `test_empty_df_returns_false` - 空数据拒绝
- `test_missing_columns_returns_false` - 缺失列拒绝
- `test_non_monotonic_index_returns_false` - 非单调索引拒绝
- `test_high_below_low_returns_false` - 异常高低值拒绝
- `test_negative_close_returns_false` - 负收盘价拒绝

### TestDownloadData (5 tests)
- `test_download_calls_api` - 调用 Binance API
- `test_download_saves_to_cache` - 保存到缓存
- `test_download_retries_on_failure` - 失败重试
- `test_download_raises_after_max_retries` - 最大重试后异常
- `test_download_invalid_interval_raises` - 无效周期异常
- `test_download_validates_data` - 数据验证

### TestEnsureData (2 tests)
- `test_ensure_returns_cached` - 返回缓存数据
- `test_ensure_downloads_when_not_cached` - 未缓存时下载

### TestGetCacheStatus (3 tests)
- `test_status_empty_cache` - 空缓存状态
- `test_status_with_cached_data` - 有缓存状态
- `test_status_filter_by_symbol` - 按交易对筛选

### TestCleanCache (3 tests)
- `test_clean_deletes_files` - 删除文件
- `test_clean_returns_count` - 返回删除计数
- `test_clean_nonexistent_returns_zero` - 不存在返回 0

### TestCLI (4 tests)
- `test_status_command` - 状态命令
- `test_clean_command` - 清理命令
- `test_download_single` - 单个下载
- `test_batch_command` - 批量下载
- `test_invalid_interval_exits_with_error` - 无效参数退出

## 未覆盖代码

以下行未被测试覆盖（主要是 verbose 打印语句）：
- 行 167, 180, 194: verbose 打印
- 行 216-217, 251-252: main() verbose 打印
- 行 342-354, 358-359, 367-368, 372: CLI verbose 打印

这些是调试/日志输出，当 `verbose=False` 时跳过。

## 功能清单

### 核心函数
- `get_data_path()` - 获取数据文件路径
- `get_meta_path()` - 获取元数据路径
- `load_cached()` - 从缓存加载
- `save_data()` - 保存到缓存
- `validate_data()` - 数据验证
- `download_data()` - 下载数据
- `ensure_data()` - 缓存优先加载
- `get_cache_status()` - 获取缓存状态
- `clean_cache()` - 清理缓存

### CLI 命令
- 默认: 下载 BTCUSDT 4h 数据
- `--status`: 显示缓存状态
- `--clean`: 清理所有缓存
- `--symbol SYMBOL`: 指定交易对
- `--interval INTERVAL`: 指定周期
- `--days DAYS`: 指定天数
- `--force`: 强制重新下载
- `--all`: 下载所有支持的组合
- `--batch SYM:INT [...]`: 批量下载

## 与 backtest_harmonic.py 集成

已将 `--data-loader cache` 作为默认值：
```bash
# 使用缓存（默认，最快）
python scripts/backtest_harmonic.py --symbol BTCUSDT --interval 4h

# 强制重新下载
python scripts/download_backtest_data.py --force

# 查看缓存状态
python scripts/download_backtest_data.py --status
```

## 文件变更

| 文件 | 变更 |
|------|------|
| `scripts/download_backtest_data.py` | 新增 |
| `tests/test_download_backtest_data.py` | 新增 |
| `scripts/backtest_harmonic.py` | 修改：集成缓存加载 |

生成时间: 2026-08-03
