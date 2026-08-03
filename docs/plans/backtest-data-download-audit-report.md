# 代码审计报告

## 概述

审计范围：
- `scripts/download_backtest_data.py` (新增)
- `tests/test_download_backtest_data.py` (新增)
- `scripts/backtest_harmonic.py` (修改)
- `scripts/_binance_stdlib.py` (依赖)

---

## 问题清单

### 🔴 严重问题

#### 1. data/backtest/ 目录未加入 .gitignore
**文件**: `.gitignore`

数据缓存目录会包含大量下载的数据文件，不应提交到版本控制。

**建议**:
```gitignore
# Data cache
data/backtest/
```

#### 2. parquet 文件损坏时程序崩溃
**文件**: `scripts/download_backtest_data.py:80`

```python
def load_cached(...):
    if path.exists():
        return pd.read_parquet(path)  # 可能抛出异常
```

如果缓存文件损坏，`pd.read_parquet()` 会抛出异常。

**建议**: 添加 try-except 处理：
```python
def load_cached(...):
    path = get_data_path(symbol, interval, exchange, root)
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception:
            # 文件损坏，删除并返回 None
            path.unlink()
            return None
    return None
```

#### 3. coverage.json 被提交到版本控制
**文件**: 已提交

覆盖率报告文件不应提交。

**建议**: 删除并添加到 `.gitignore`:
```gitignore
coverage.json
.coverage
```

---

### 🟡 中等问题

#### 4. --batch 模式缺少参数验证
**文件**: `scripts/download_backtest_data.py:355`

```python
sym, iv = pair.split(":", 1)
ensure_data(sym, iv, args.days, root=root)  # 没有验证 sym/iv 是否有效
```

用户可以输入无效的 symbol 或 interval，如 `--batch INVALID:4h`。

**建议**: 添加验证逻辑：
```python
sym, iv = pair.split(":", 1)
if sym not in SUPPORTED_SYMBOLS or iv not in SUPPORTED_INTERVALS:
    print(f"[error] Unsupported: {pair}")
    continue
```

#### 5. 重试次数不一致
**文件**: `scripts/_binance_stdlib.py` vs `scripts/download_backtest_data.py`

| 文件 | max_retries=3 行为 |
|------|---------------------|
| `_binance_stdlib.py:78-90` | 最多尝试 4 次 (循环条件 `attempt <= max_retries`) |
| `download_backtest_data.py:172` | 最多尝试 3 次 (循环条件 `attempt < max_retries`) |

**建议**: 统一重试逻辑，在文档中明确说明。

#### 6. backtest_harmonic.py 默认值变更可能影响现有行为
**文件**: `scripts/backtest_harmonic.py:51`

默认值从 `stdlib` 改为 `cache`。虽然 cache 底层也是 stdlib，但行为略有不同（固定结束日期 vs 实时日期）。

**建议**: 
- 在文档中明确说明此变更
- 或者保持 `stdlib` 为默认值，让用户通过 `--data-loader cache` 显式选择

---

### 🟢 轻微问题

#### 7. 测试中 `sample_meta` fixture 未使用
**文件**: `tests/test_download_backtest_data.py:47-62`

定义了但没有被任何测试使用。

**建议**: 删除未使用的 fixture，或添加使用它的测试。

#### 8. 时区说明不清晰
**文件**: `scripts/download_backtest_data.py:36`

`FIXED_END_DATE` 固定为 UTC 时区，但没有在文档中明确说明。

**建议**: 在文档字符串中添加时区说明。

#### 9. 没有处理文件系统权限错误
**文件**: `scripts/download_backtest_data.py:96`

如果无法创建目录或写入文件，会抛出异常。

**建议**: 添加适当的错误处理。

#### 10. 重复代码
**文件**: `scripts/download_backtest_data.py:166-167, 215-217`

verbose 打印逻辑重复出现。

**建议**: 提取为辅助函数。

---

## 代码质量评估

### 优点 ✅

1. **KISS 原则**: 代码简洁，职责清晰
2. **高内聚**: 每个函数职责单一
3. **可扩展性**: 支持多交易所、多交易对、多周期
4. **错误处理**: 有网络重试、数据校验
5. **测试覆盖**: 88.20% 覆盖率，40 个测试用例
6. **文档完整**: 有 docstring、使用示例

### 缺点 ❌

1. **健壮性不足**: 缺少对文件损坏、权限错误等的处理
2. **边界条件**: --batch 模式缺少参数验证
3. **一致性**: 重试次数不一致
4. **遗漏**: data/backtest/ 未加入 .gitignore

---

## 风险评估

| 风险 | 概率 | 影响 | 优先级 |
|------|------|------|--------|
| parquet 文件损坏导致程序崩溃 | 低 | 高 | 中 |
| 无效参数导致下载失败 | 中 | 低 | 低 |
| data/backtest/ 污染版本库 | 高 | 低 | 中 |
| 默认值变更影响现有脚本 | 低 | 中 | 中 |

---

## 修复建议优先级

1. **P0 (立即修复)**:
   - 添加 data/backtest/ 到 .gitignore
   - 修复 parquet 损坏处理
   - 删除 coverage.json

2. **P1 (建议修复)**:
   - 添加 --batch 参数验证
   - 统一重试次数逻辑
   - 删除未使用的 sample_meta fixture

3. **P2 (可选)**:
   - 改进时区说明
   - 提取重复代码
   - 添加文件系统错误处理

---

## 结论

代码整体质量良好，符合 KISS 原则和低耦合设计。主要问题集中在健壮性方面，建议优先修复 P0 级别的安全问题。

**审计时间**: 2026-08-03
**审计人**: AI Assistant
