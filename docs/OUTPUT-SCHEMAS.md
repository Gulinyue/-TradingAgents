# 输出对象 Schema 定义

> V2.1 | 规范所有中间对象和最终对象的字段

---

## 1. portfolio_snapshot

快照时刻的账户+标的上下文。

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | str | 标的代码 |
| `trade_date` | str | 交易日期 YYYY-MM-DD |
| `account_code` | str | 账户代码 |
| `account_id` | int | 账户 ID |
| `balance` | float | 可用资金（元） |
| `total_equity` | float | 总权益 |
| `cash_ratio_pct` | float | 现金占比（0~1） |
| `is_held` | bool | 当前是否持仓 |
| `position_qty` | float | 持仓数量 |
| `avg_cost` | float | 持仓均价 |
| `last_price` | float | 最新价 |
| `market_value` | float | 市值 |
| `unrealized_pnl` | float | 浮动盈亏 |
| `same_sector_exposure` | float | 同行业占比（0~1） |
| `watchlist_tags` | list[str] | 来自股票池的标签 |
| `constraints` | dict | 组合约束配置 |
| `latest_bar` | dict | 最近一条日线 OHLCV |
| `latest_factors` | list[dict] | 最新因子值列表 |
| `latest_prediction` | dict | ML 预测（如果有） |
| `data_completeness` | dict | 见下方 |

### data_completeness 子对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `has_balance` | bool | 有资金数据 |
| `has_bar` | bool | 有日线数据 |
| `bar_count` | int | 当前 bar 数量 |
| `has_minimum_bars` | bool | ≥20 bars |
| `has_enough_bars` | bool | ≥60 bars（推荐标准） |
| `has_full_bars` | bool | ≥120 bars |
| `bar_quality_level` | str | insufficient/minimum_only/good/full |
| `bars_to_good` | int | 距 good 标准还差多少 |
| `bars_to_full` | int | 距 full 标准还差多少 |
| `has_factors` | bool | 有因子数据 |
| `has_prediction` | bool | 有 ML 预测 |
| `review_required` | bool | 是否需要人工复核 |

---

## 2. portfolio_context

构建给 TA 图的 prompt 上下文。

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | str | 标的代码 |
| `trade_date` | str | 交易日期 |
| `is_held` | bool | 是否在持仓 |
| `cash_ratio_pct` | float | 现金占比 |
| `same_sector_exposure` | float | 同行业暴露 |
| `data_completeness` | dict | 继承自 snapshot |
| `soft_constraints_hit` | list[str] | 命中的软约束 |
| `hard_constraints_hit` | list[str] | 命中的硬约束 |
| `context_summary` | str | 供 LLM 看的文字摘要 |

---

## 3. ta_result（_parse_ta_result 返回）

TA 图的原始输出。

| 字段 | 类型 | 说明 |
|------|------|------|
| `decision` | str | ENTER/ADD/HOLD/TRIM/EXIT/AVOID/REVIEW |
| `decision_score` | str | 原始决策文本（截断200字符） |
| `technical_report` | str | 技术分析报告（来自 market_report） |
| `fundamental_report` | str | 基本面报告 |
| `sentiment` | str | 情绪报告 |
| `news_events` | list | 新闻事件列表 |
| `risk_factors` | list | 风险因素列表 |
| `raw_full_report` | str | 完整图 state 的字符串表示 |
| `analyst_signals` | dict | 各分析师信号 |

### analyst_signals 子对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `market` | str | 技术分析报告（market_report） |
| `fundamentals` | str | 基本面报告 |
| `sentiment` | str | 情绪报告 |
| `news` | str | 新闻报告 |

---

## 4. decision_output（runner.analyze 返回）

单票分析的最终输出。

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | str | 标的代码 |
| `trade_date` | str | 交易日期 |
| `account_code` | str | 账户代码 |
| `watchlist_code` | str | 股票池代码 |
| `action` | str | 最终动作（HOLD 等） |
| `raw_decision` | str | TA 原始决策 |
| `confidence` | float | 置信度 |
| `risk_level` | str | 风险等级 |
| `final_summary` | str | 摘要 |
| `overlay_reasons` | list[str] | 组合修正原因 |
| `hard_constraints_hit` | list[str] | 命中的硬约束 |
| `soft_constraints_hit` | list[str] | 命中的软约束 |
| `decision_rank_score` | float | 排名分数 |
| `candidate_bucket` | str | EXECUTE/CANDIDATE/REVIEW |
| `rank_reason` | str | 排名原因 |
| `portfolio_context` | dict | 组合上下文 |
| `analysis_run_id` | int | DB run_id |
| `ta_result` | dict | 见上方 ta_result |
| `run_status` | str | success/partial/failed |
| `status_reason` | str | 状态原因 |
| `status_tags` | list[str] | 结构化标签 |
| `parser_fallback_triggered` | bool | 是否走了 fallback 路径 |

---

## 5. batch_summary

批量分析的聚合摘要。

| 字段 | 类型 | 说明 |
|------|------|------|
| `batch_id` | str | 批次唯一 ID |
| `generated_at` | str | 生成时间 ISO |
| `context` | dict | 上下文（account_code, watchlist_code, total_symbols） |
| `counts` | dict | success/partial/failed/error 计数 |
| `action_distribution` | dict | 各动作数量 |
| `action_distribution_excl_review` | dict | 排除 REVIEW 后的动作分布 |
| `bucket_distribution` | dict | EXECUTE/CANDIDATE/REVIEW 分布 |
| `status_distribution` | dict | success/partial/failed 分布 |
| `runtime` | dict | avg_seconds, total_seconds |
| `quality` | dict | tech_ok_pct, bars_ok_pct |
| `top_ranked_candidates` | list[dict] | 分数最高的标的 |
| `constraint_hits` | dict | hard/soft 约束命中统计 |
| `errors` | list[str] | 报错股票列表 |
| `per_symbol` | list[dict] | 每只股票的详细结果 |

---

## 6. raw_output_quality

TA 输出质量评估。

| 字段 | 类型 | 说明 |
|------|------|------|
| `technical_report_nonempty` | bool | 技术报告有实质内容 |
| `fundamental_report_nonempty` | bool | 基本面报告有实质内容 |
| `raw_confidence_present` | bool | 有置信度数据 |
| `raw_risk_present` | bool | 有风险等级数据 |
| `raw_decision_score_known` | bool | 决策分数已知 |
| `ta_decision_nondefault` | bool | 决策不是默认的 REVIEW |

---

## 7. run_status

标准化运行状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_status` | str | success / partial / failed |
| `status_reason` | str | 人类可读原因 |
| `status_tags` | list[str] | 结构化标签 |
| `is_success` | bool | 简写 |
| `is_partial` | bool | 简写 |
| `is_failed` | bool | 简写 |

### 判定规则

**success**：
- TA 图执行完成
- `technical_report_nonempty = True`
- `has_enough_bars = True`（≥60 bars）
- 无关键运行时错误

**partial**：
- 主链完成，但存在质量缺口
- 任一：`bar_count < 60`、`missing_technical_report`、`parser_fallback_triggered`

**failed**：
- TA 图未执行完成（超时/崩溃）
- DB 写入失败
- 关键结果提取失败
