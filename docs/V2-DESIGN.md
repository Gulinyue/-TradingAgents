# TradingAgents × PostgreSQL V2 设计文档

> 基于 V1/V1.1 基线：tradingagents_runner/ 已承担数据库驱动壳层，runner.py 支持 DB 上下文，portfolio_context.py 读取 core.account_balances。

## 1. 目标

### 1.1 主目标
从"数据库驱动的分析系统"升级为"**组合约束驱动的决策系统**"。

不仅说"看多/看空"，而是能回答：
- 在当前现金、仓位、行业暴露、单票上限下，应该 ENTER/ADD/HOLD/TRIM/EXIT/AVOID/REVIEW 中的哪一个
- 为什么这个动作和原始 TA 结论不同
- 哪些约束改变了最终动作

### 1.2 次目标
1. 保持 V1 现有边界稳定（壳层分层清晰，不动图谱内核）
2. 让组合约束成为一等公民（硬约束/软约束/解释性约束）
3. 批量分析具备可排序输出（candidate bucket + rank score）
4. 为宿主机 ML 做接口预留（research.model_predictions）

### 1.3 非目标
- 不直接做自动下单
- 不大改 TradingAgentsGraph
- 不做 ORM 重构
- 不强耦合 ML 进主执行链

## 2. 约束对象（三层）

### 2.1 硬约束（直接限制动作上限）
| 约束 | 对象字段 | 效果 |
|---|---|---|
| 账户现金约束 | portfolio_cash / available_cash | 现金不足时 ENTER/ADD → REVIEW/AVOID |
| 单票权重约束 | weight / max_symbol_weight | 已达上限时 ADD → HOLD/TRIM |
| 行业暴露约束 | sector_weight / max_sector_weight | 行业超配时 ENTER → REVIEW/AVOID |
| 持仓状态约束 | is_held / unrealized_pnl | 已持仓/未持仓是完全不同的动作路径 |

### 2.2 软约束（改变信心、优先级、摘要）
| 约束 | 对象 | 效果 |
|---|---|---|
| 股票池来源约束 | watchlist_code / tag / priority | 核心池标的优先级更高 |
| 数据完整性约束 | 是否有 bar / factor / balance | 数据缺失时动作降为 REVIEW |
| 市场环境约束 | regime / 波动 / 回撤状态 | 高波动偏 REVIEW |

### 2.3 解释性约束（决定"为什么"）
| 对象 | 效果 |
|---|---|
| raw_action / raw_confidence | decision_json 保留原始值 |
| overlay_reasons | 面板/回测可复盘 |

## 3. 决策矩阵

### 3.1 七类动作
ENTER / ADD / HOLD / TRIM / EXIT / AVOID / REVIEW

### 3.2 判定顺序
1. 是否持仓（is_held）
2. 是否满足硬约束
3. TA 原始方向与置信度
4. 是否命中软约束
5. 最终动作与理由

### 3.3 优先级规则链
- **第一优先级（硬降级）**：ENTER → REVIEW、ADD → HOLD、ENTER → AVOID
  - 触发：现金不足 / 单票超限 / 行业超限 / 账户冻结
- **第二优先级（持仓语义修正）**：BUY+已持仓→ADD、BUY+未持仓→ENTER、SELL+已持仓→TRIM/EXIT
- **第三优先级（软约束保守化）**：弱冲突下核心池标的仍可 REVIEW

### 3.4 最终输出对象（decision_policy.py 唯一出口）
```python
{
    # 原始
    "raw_action": str,           # TA 原始结论
    # 决策
    "final_action": str,          # 最终结论（ENTER/ADD/HOLD/TRIM/EXIT/AVOID/REVIEW）
    "overlay_applied": bool,
    # 理由
    "overlay_reasons": list[str],
    "hard_constraints_hit": list[str],
    "soft_constraints_hit": list[str],
    # 排序（ranking.py 产出）
    "decision_rank_score": float,
    "candidate_bucket": str,     # EXECUTE / CANDIDATE / AVOID
    "rank_reason": str,
}
```

## 4. 数据库补充

### 4.1 优先补视图
| 视图 | 用途 |
|---|---|
| `core.v_latest_positions` | 已有 |
| `core.v_latest_account_balance` | 新增：直接拿最新余额快照 |
| `core.v_account_portfolio_snapshot` | 新增：一次拿到组合摘要 |
| `core.v_sector_exposure` | 新增：行业暴露视图 |

### 4.2 core.account_constraints（核心新表）
```sql
CREATE TABLE core.account_constraints (
    constraint_id      BIGSERIAL PRIMARY KEY,
    account_id        BIGINT NOT NULL REFERENCES core.accounts(account_id),
    max_symbol_weight NUMERIC(8,4)    DEFAULT 0.15,    -- 单票最大权重 15%
    max_sector_weight NUMERIC(8,4)    DEFAULT 0.30,    -- 行业最大权重 30%
    min_cash_ratio    NUMERIC(8,4)    DEFAULT 0.05,    -- 最小现金比例 5%
    max_new_positions_per_day INTEGER  DEFAULT 3,
    allow_add_on_profit_only BOOLEAN  DEFAULT FALSE,
    allow_add_on_loss   BOOLEAN  DEFAULT FALSE,
    review_on_missing_balance BOOLEAN DEFAULT TRUE,
    is_active          BOOLEAN  NOT NULL DEFAULT TRUE,
    metadata           JSONB NOT NULL DEFAULT '{}',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (account_id)
);
```

### 4.3 research.model_predictions 升级
- 宿主机 ML 回写后，V2 读取最新预测分数作为排序因子
- 不覆盖 TA 原始判断，作为软约束

## 5. 代码改造边界

### 5.1 继续保留的边界
```
tradingagents/         = 分析内核（不动）
tradingagents_runner/  = A 股运行壳层（V2 主要改造点）
PostgreSQL            = 状态与研究底座
```

### 5.2 新增文件
| 文件 | 职责 |
|---|---|
| `tradingagents_runner/decision_policy.py` | **V2 唯一决策出口**：硬/软约束链 → 产出 final_action / raw_action / reasons / score |
| `tradingagents_runner/portfolio_snapshot.py` | 只做"取数与聚合"，输出原始事实快照，不做策略判断 |
| `tradingagents_runner/ranking.py` | 只做排序：decision_rank_score / candidate_bucket / rank_reason，**不改 action** |

### 5.3 扩展现有文件
| 文件 | 扩展内容 |
|---|---|
| `repositories.py` | get_latest_account_balance() / get_account_constraints() / get_sector_exposure() / get_latest_model_prediction() |
| `portfolio_context.py` | 只做"把快照整理成决策可读对象"，不产生 final_action |
| `runner.py` | 三阶段：TA分析 → 组合约束决策 → 批量排序/写回 |

### 5.4 职责边界原则（最重要）
```
portfolio_snapshot.py  = 取数据（事实快照）
portfolio_context.py   = 组装上下文（决策语义对象）
decision_policy.py     = 唯一决策出口（final_action / reasons / score）
ranking.py            = 排序（只读 decision，不改 action）
runner.py             = 编排（调用以上四者，不自行修正 action）
```

**绝对禁止：**
- runner.py 里有临时 if/else 修正 action
- portfolio_context.py 里藏修正规则
- ranking.py 反过来改 ENTER/ADD/HOLD...

所有动作修正收口到 `decision_policy.py`。

## 6. 实施顺序

1. **补数据库视图 + account_constraints 表**
2. **升级 repositories.py**（新增4个读取方法）
3. **新增 portfolio_snapshot.py**（取数与聚合，不做策略判断）
4. **升级 portfolio_context.py**（组装决策语义对象，不产生 final_action）
5. **新增 decision_policy.py**（V2 唯一决策出口）
6. **升级 runner.py**（调用 decision_policy.py，不自行修正 action）
7. **新增 ranking.py**（排序只读 decision，不改 action）

---

*文档来源：2026-03-29 林月整理，Sophia 存档*
