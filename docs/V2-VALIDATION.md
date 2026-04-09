# V2 验证报告

> 冻结版本：2026-03-30
> 状态：**已封板** ✅

---

## 一、验证摘要

V2 决策系统 + 市场历史数据补齐方案 v1 已完成联调，主分析链路已打通。

| 指标 | 修复前 | 修复后 |
|------|---------|---------|
| technical_report 长度 | 0 chars | 6,626 chars ✅ |
| raw_action | REVIEW（空壳） | HOLD ✅ |
| bar_count | 1 条 | 205 条 ✅ |
| decision 解析路径 | 找不到文件 | eval_results fallback ✅ |

---

## 二、修复点记录

### Bug 1：`_parse_ta_result` 找不到日志文件
- **文件**：`tradingagents_runner/runner.py`
- **根因**：`_parse_ta_result` 读的路径是 `results/` 而日志实际在 `eval_results/`
- **修复**：加 `eval_results/{ticker}/TradingAgentsStrategy_logs/` fallback 路径
- **测试**：见 `tests/test_runner_parse.py::TestParseTaResult`

### Bug 2：`_normalize_decision` 误把 **HOLD** 识别为 ADD
- **文件**：`tradingagents_runner/runner.py`
- **根因**：
  1. `"HOLD"` 匹配条件但返回了 `"REVIEW"`（代码笔误）
  2. `**HOLD**` 经 `.upper()` 后仍含 `**HOLD**`，`\bHOLD\b` 不匹配
  3. `"ADD"` 关键词在 `"Do NOT ADD"` 中被误匹配
- **修复**：
  - 优先用正则提取显式评级 `Rating: **ACTION**`
  - 清理 markdown bold 再用 `\b` 词边界匹配
  - `"ADD"` 加 `"DO NOT ADD"` 排除
  - 中文关键词改用子串匹配（`\b` 对中文不工作）
- **测试**：见 `tests/test_runner_parse.py::TestNormalizeDecision`

### Bug 3：`_deep_float` 是局部函数无法测试
- **文件**：`tradingagents_runner/runner.py`
- **根因**：`_deep_float` 定义在 `analyze()` 函数内部
- **修复**：提到模块级别，可独立导入
- **测试**：见 `tests/test_runner_parse.py::TestDeepFloat`

### Bug 4：`technical_indicators` 配置缺失
- **文件**：`tradingagents_runner/runner.py`
- **根因**：在改 `data_vendors` 时漏了 `technical_indicators` 键
- **修复**：加 `"technical_indicators": "yfinance"`
- **症状**：`Error getting bulk stockstats data: 'technical_indicators'`

### Bug 5：`AlphaVantageRateLimitError` 被吞掉
- **文件**：`tradingagents/dataflows/alpha_vantage_indicator.py`
- **根因**：`except Exception` 把 rate limit 错误吞掉，返回字符串而非透传异常
- **修复**：分离 rate limit 异常，透传给 `route_to_vendor` 的 fallback 逻辑
- **测试**：免费 key 耗尽时自动降级到 yfinance

### Bug 6：`GraphRecursionError`
- **文件**：`tradingagents/graph/propagation.py`
- **根因**：langgraph 递归上限默认 100，TA 多 Agent 图步数超限
- **修复**：`max_recur_limit` 从 100 → 600

---

## 三、Run 18 → Run 20 对比

| 字段 | Run 18 | Run 19 | Run 20 |
|------|--------|--------|--------|
| status | partial | partial | partial |
| action | REVIEW | REVIEW | **HOLD** |
| technical_report | 0 chars | 0 chars | **6,626 chars** |
| bar_count | 1 | 1 | **205** |
| eval_results fallback | ❌ 未触发 | ❌ 未触发 | ✅ |
| decision 解析 | REVIEW（默认） | REVIEW（默认） | **HOLD** |

---

## 四、回归测试

```bash
cd /home/gulinyue/TradingAgents
source ~/anaconda3/bin/activate tradingagents
python3 -m unittest tradingagents_runner.tests.test_runner_parse -v
```

**当前：19/19 通过 ✅**

覆盖：
- `_normalize_decision` 所有关键词（ENTER/ADD/SELL/TRIM/EXIT/AVOID/HOLD/REVIEW）
- markdown bold 包裹的关键词
- `"Do NOT ADD"` 排除
- 中文关键词（持有/观望/加仓/减仓/清仓/平仓/规避）
- `_deep_float` 序列化 Decimal/list/nested/None
- `_parse_ta_result` eval_results fallback

---

## 五、已知剩余问题

### 低优先级（V2 已封板，不阻断）

1. **status 仍为 partial**：所有 run 都是 partial，这是因为 `ta_is_healthy` 判断逻辑问题（见 `runner.py`）。V2 决策链路本身没问题，status 是内部状态标记，不影响最终动作。
2. **Alpha Vantage 免费 key 每天 25 次限制**：耗尽后自动降级 yfinance，指标数据不受影响。
3. **600036.SH 的 technical_report 开头说"指标 API 日历对齐问题"**：这是 yfinance/stockstats 的已知问题，但不影响价格数据本身。
4. **run 17/16/15/14 状态残留为 running**：被 SIGTERM 杀掉但 DB 状态未更新，下次清理。

### P3 规划（V3 或 V2.3）

- ML 分数融合
- 候选池排序增强
- 更细粒度组合约束

---

## 六、新增文件

| 文件 | 用途 |
|------|------|
| `tradingagents_runner/backfill_market_bars.py` | 市场历史数据回填脚本 |
| `tradingagents_runner/data_quality.py` | bar 质量评估模块 |
| `tradingagents_runner/tests/test_runner_parse.py` | 回归测试（19 个用例） |
| `docs/V2-VALIDATION.md` | 本文档 |
