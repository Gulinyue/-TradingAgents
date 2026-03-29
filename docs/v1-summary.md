# TradingAgents × PostgreSQL V1 总结

## 目标

实现最小闭环：**数据库读股票池 → 读账户持仓 → 生成组合上下文 → 调用 TradingAgents → 组合修正 → 写回 analysis_runs / analysis_decisions**

---

## 架构图

```
┌─────────────────────────────────────────────────────────┐
│  run.py / scheduler.py                                  │
│    CLI: --account-code, --from-db-watchlist             │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  runner.py :: analyze()                                │
│  1. build_portfolio_context()  ← repositories.py        │
│  2. create_analysis_run()     ← repositories.py        │
│  3. ta.propagate()           ← TradingAgents          │
│  4. apply_portfolio_overlay() ← portfolio_context.py   │
│  5. insert_analysis_decision()← repositories.py        │
│  6. mark_run_success()       ← repositories.py        │
└─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  PostgreSQL 18 + TimescaleDB 2.26 + pgvector 0.8     │
│  端口: 6543 | 容器: pg18-ta                          │
└─────────────────────────────────────────────────────────┘
```

---

## 文件清单

### 新增文件

| 文件 | 职责 |
|---|---|
| `tradingagents_runner/db.py` | psycopg2 连接池、URL 构建、ping |
| `tradingagents_runner/repositories.py` | 4 个 Repo 类，数据读写接口 |
| `tradingagents_runner/portfolio_context.py` | 组合上下文构建 + 组合修正层 |
| `docker-compose.yml` | 一键启动 PG18 + TimescaleDB |
| `docker/Dockerfile.pg18` | 源码编译镜像 |
| `docker/init.sql` | 扩展初始化 |
| `schema_v1.sql` | 完整 DB schema |
| `.env.db.example` | 数据库凭证模板 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `tradingagents_runner/runner.py` | 集成 DB 上下文、组合修正、写库 |
| `tradingagents_runner/run.py` | CLI 支持 `--account-code` / `--from-db-watchlist` |
| `tradingagents_runner/scheduler.py` | 静态股票数组 → `watchlist_code` |
| `tradingagents_runner/pyproject.toml` | 添加 `psycopg2-binary` 依赖 |
| `tradingagents/dataflows/tushare_data.py` | `.SS` → `.SH` 统一 |
| `tradingagents/dataflows/akshare_data.py` | 兼容 `.SH/.SZ/.SS` |
| `tradingagents/llm_clients/base_client.py` | `ThinkingBlock` Pydantic 兼容修复 |
| `README.md` | clone URL → fork、文档更新 |
| `QUICKREF.md` | `.SS` → `.SH`、相对路径 |
| `.env.example` | 添加 DB 连接变量 |

---

## 数据库 Schema

### core（核心业务）

| 表 | 说明 |
|---|---|
| `accounts` | 账户表（paper/live/research） |
| `positions` | 持仓快照（按日） |
| `account_balances` | 账户资金净值快照 |
| `instruments` | 证券主表 |
| `watchlists` | 股票池 |
| `watchlist_members` | 股票池成员 |

### market（行情）

| 表 | 说明 |
|---|---|
| `market_bars_daily` | 日线行情（TimescaleDB hypertable） |
| `factor_values` | 因子值（TimescaleDB hypertable） |

### research（分析）

| 表 | 说明 |
|---|---|
| `analysis_runs` | 分析任务记录 |
| `analysis_decisions` | 单票分析结论 |
| `model_predictions` | ML 模型预测 |
| `research_embeddings` | 向量检索（pgvector） |

### 视图

| 视图 | 说明 |
|---|---|
| `core.v_latest_positions` | 当前持仓（最新快照，不用写 `max(as_of_date)`） |

### 应用账号

| 账号 | 密码占位符 | 权限 |
|---|---|---|
| `ta_app_rw` | `CHANGE_ME` | 读写 |
| `ta_panel_rw` | `CHANGE_ME` | 读写 |
| `ta_ml_ro` | `CHANGE_ME` | 只读 |

---

## 股票代码规范

**DB 内部标准：** `.SH`（沪市）/ `.SZ`（深市）

外部数据源适配时做 `.SH ↔ .SS` 转换：

| 数据源 | 说明 |
|---|---|
| Tushare | `.SS`（旧别名）→ 自动转为 `.SH` |
| AKShare | 兼容 `.SH/.SZ/.SS` |
| 用户输入 | `.SS` → `.SH` |

---

## 组合修正层（apply_portfolio_overlay）

| 规则 | 条件 | 动作 |
|---|---|---|
| R1 | 已持仓 + 原始 BUY | BUY → **ADD** |
| R2 | 未持仓 + 买 + 同板块已有仓 | BUY → **REVIEW** |
| R3 | 未持仓 + 买 + 同行业已有仓 | BUY → **REVIEW** |
| R4 | 已持仓 + 原始 SELL | SELL → **TRIM** |
| R5 | 已持仓 + 盈利 HOLD | 摘要加注"已盈利" |
| R6 | 来自核心池 | 摘要注明"核心持仓关注池" |

---

## CLI 用法

```bash
# 单股分析（带 DB 上下文）
python run.py analyze 600036.SH 2026-03-29 \
    --account-code paper_main \
    --watchlist-code core_holdings_focus \
    -v

# 从 DB 股票池批量分析
python run.py batch --from-db-watchlist core_holdings_focus \
    --account-code paper_main

# 监控模式
python run.py watch --from-db-watchlist core_holdings_focus \
    --account-code paper_main

# 定时任务注册
python scheduler.py register daily \
    --account-code paper_main \
    --watchlist-code core_holdings_focus

python scheduler.py list
```

---

## 真实测试结果

**标的：** `600036.SH`（招商银行）  
**账户：** `paper_main` | **股票池：** `core_holdings_focus`  
**数据源：** Tushare（优先）

| 指标 | 值 |
|---|---|
| DB run_id | 3 |
| 最终决策 | **REVIEW** |
| 原始信号 | BUY |
| 组合修正 | 来自核心持仓关注池 |
| TA 调用耗时 | 715s（约12分钟） |
| DB 写回 | ✅ success |

---

## 已知问题（V2 待修）

1. **confidence / risk_level 解析为空** — `_parse_ta_result()` 未从结果 JSON 中提取这两个字段
2. **分析耗时过长（12分钟/标的）** — 可考虑减少 Agent 轮次、缓存行情数据
3. **market.market_bars_daily / factor_values 无数据** — V2 接入 Tushare 日线数据写入
4. **research_embeddings 无数据** — V2 接入研报/新闻 embedding 向量化

---

## V2 路线图

1. 接入 Tushare 日线写入 `market.market_bars_daily`
2. 补 `confidence` / `risk_level` 解析
3. `research_embeddings` 向量检索（RAG）
4. 面板层（读 DB 展示）
5. 机器学习预测回写 `model_predictions`

---

*最后更新：2026-03-29*
