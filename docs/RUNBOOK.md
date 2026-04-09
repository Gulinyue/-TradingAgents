# 排障手册

> V2.1 | 按层定位，快速找到问题

---

## 诊断入口：查 status

```sql
SELECT run_id, status, status_reason, status_tags
FROM research.analysis_runs r
LEFT JOIN research.analysis_decisions d ON d.run_id = r.run_id
ORDER BY created_at DESC LIMIT 10;
```

`status_reason` 字段告诉你当前 run 卡在哪一层。

---

## 按层排查

### 1. 数据层：bar_count / has_enough_bars

```sql
-- 检查 bar 数是否达标
SELECT symbol, COUNT(*) AS bar_count
FROM market.market_bars_daily
GROUP BY symbol
HAVING COUNT(*) < 60
ORDER BY bar_count;
```

**修复**：跑回填脚本
```bash
source ~/anaconda3/bin/activate tradingagents
python3 tradingagents_runner/backfill_market_bars.py --target 60
```

---

### 2. TA 图层：technical_report / fundamental_report

先看图是否真的跑完了：
```sql
SELECT r.run_id, r.runtime_ms, d.decision_json->>'run_status' as run_status,
       d.decision_json->>'status_reason' as status_reason
FROM research.analysis_runs r
LEFT JOIN research.analysis_decisions d ON d.run_id = r.run_id
WHERE d.symbol = '600519.SH'
ORDER BY r.created_at DESC LIMIT 5;
```

检查 `technical_report_nonempty`（来自 `raw_output_quality`）：
- `False` → TA 图没有产出文字报告
- 检查 graph log：`eval_results/{symbol}/TradingAgentsStrategy_logs/full_states_log_{date}.json`

**检查图原始输出**：
```bash
python3 -c "
import json
with open('eval_results/600519.SH/TradingAgentsStrategy_logs/full_states_log_2026-03-29.json') as f:
    data = json.load(f)
state = data['2026-03-29']
print('market_report len:', len(state.get('market_report', '')))
print('fundamentals_report len:', len(state.get('fundamentals_report', '')))
print('final_trade_decision len:', len(state.get('final_trade_decision', '')))
"
```

---

### 3. 提取层：_parse_ta_result

症状：`technical_report` 是空字符串，但 graph log 里明明有内容。

**检查路径**：
- 优先级1：`results/600519_SH_2026-03-29.json`（结构化输出）
- 优先级2：`eval_results/600519.SH/TradingAgentsStrategy_logs/full_states_log_2026-03-29.json`

**检查 parser fallback 是否触发**：
```sql
SELECT decision_json->>'parser_fallback_triggered' as fallback
FROM research.analysis_decisions
WHERE symbol = '600519.SH'
ORDER BY created_at DESC LIMIT 5;
```
`true` → 说明走了 fallback 路径（正常）。

**检查 decision 解析是否正确**：
```python
from runner import _normalize_decision
_normalize_decision("**HOLD** in markdown")  # 应返回 HOLD
```

---

### 4. 决策层：raw_action / final_action

检查约束命中：
```sql
SELECT symbol,
       decision_json->>'final_action' as final_action,
       decision_json->>'hard_constraints_hit' as hard,
       decision_json->>'soft_constraints_hit' as soft,
       decision_json->>'candidate_bucket' as bucket
FROM research.analysis_decisions
WHERE symbol = '600519.SH'
ORDER BY created_at DESC LIMIT 5;
```

**常见约束**：
- `symbol_overweight` → 该标的超出权重上限，强制 HOLD
- `already_held` → 已在持仓，路径是 HOLD
- `bar_quality_insufficient` → bar 数不足（<60）

---

### 5. Batch 输出层：序列化错误

症状：batch 跑完后报错 `Decimal is not JSON serializable`

**检查**：
```python
from serialization import json_dumps_safe
# 不应该再有任何序列化报错
```

**修复**：所有 artifact 写入路径都已改走 `json_dumps_safe`，正常不会再出现。

---

## 快速命令清单

```bash
# 1. 检查 bar 数
psql "$DB" -c "SELECT symbol, count(*) FROM market.market_bars_daily GROUP BY symbol"

# 2. 检查最近 run 状态
psql "$DB" -c "SELECT run_id, status, status_reason FROM research.analysis_runs ORDER BY created_at DESC LIMIT 10"

# 3. 检查单票 TA 质量
psql "$DB" -c "SELECT symbol, action, decision_json->>'status_reason' as reason FROM research.analysis_decisions ORDER BY created_at DESC LIMIT 10"

# 4. 回填 bar 数据
python3 tradingagents_runner/backfill_market_bars.py --target 60

# 5. 跑回归测试
python3 tradingagents_runner/tests/test_runner_parse.py

# 6. 重跑单票分析
python3 tradingagents_runner/run.py analyze 600519.SH 2026-03-29 \
    --account-code paper_main --watchlist-code core_holdings_focus -v
```

---

## 常见症状 → 根因映射

| 症状 | 最可能原因 | 查哪里 |
|------|-----------|--------|
| technical_report 为空 | `_parse_ta_result` 找不到文件 | 检查 `eval_results/` 路径 |
| decision = REVIEW | `_normalize_decision` 解析失败 | 直接测函数 |
| bar_count = 1 | 历史数据未回填 | 跑 `backfill_market_bars.py` |
| GraphRecursionError | `max_recur_limit` 太小 | 改 `propagation.py` |
| Alpha Vantage 报错 | 免费 key 每天 25 次限制 | 等待次日或禁用 |
| Decimal 序列化报错 | 未走 `deep_serialize` | 全局搜索 `_deep_float` |
| status = partial 但有报告 | bar 数 <60 | 检查 `has_enough_bars` |
