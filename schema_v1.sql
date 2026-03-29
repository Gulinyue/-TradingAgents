BEGIN;

-- =========================================================
-- TradingAgents schema v1
-- Target DB: tradingagents
-- PG: 18.x
-- Extensions: TimescaleDB 2.26.x, pgvector 0.8.x
-- =========================================================

-- 0) Extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

-- 1) Lock down PUBLIC defaults a bit
REVOKE ALL ON DATABASE tradingagents FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- 2) Application roles
--    首次执行会创建；再次执行不会重置你已经改过的密码
-- 2) Application roles
DO $_t$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ta_app_rw') THEN
        CREATE ROLE ta_app_rw LOGIN PASSWORD 'CHANGE_ME';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ta_panel_rw') THEN
        CREATE ROLE ta_panel_rw LOGIN PASSWORD 'CHANGE_ME';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ta_ml_ro') THEN
        CREATE ROLE ta_ml_ro LOGIN PASSWORD 'CHANGE_ME';
    END IF;
END $_t$;

GRANT CONNECT ON DATABASE tradingagents TO ta_app_rw, ta_panel_rw, ta_ml_ro;

-- 3) Schemas
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS research;

-- 4) Helper function: updated_at trigger
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

-- =========================================================
-- CORE SCHEMA
-- =========================================================

-- 4.1 instruments: 证券主表
CREATE TABLE IF NOT EXISTS core.instruments (
    symbol              TEXT PRIMARY KEY,              -- 例: 600519.SH
    exchange            TEXT NOT NULL,                 -- SSE / SZSE / HKEX ...
    market              TEXT NOT NULL DEFAULT 'CN-A',  -- CN-A / HK / US ...
    asset_type          TEXT NOT NULL DEFAULT 'EQUITY',
    name                TEXT NOT NULL,
    industry            TEXT,
    sector              TEXT,
    list_date           DATE,
    delist_date         DATE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    currency            TEXT NOT NULL DEFAULT 'CNY',
    extra               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT instruments_symbol_fmt_chk
        CHECK (symbol ~ '^[0-9A-Z._-]+$')
);

CREATE INDEX IF NOT EXISTS idx_instruments_market_active
    ON core.instruments (market, is_active);

CREATE INDEX IF NOT EXISTS idx_instruments_name
    ON core.instruments (name);

DROP TRIGGER IF EXISTS trg_instruments_updated_at ON core.instruments;
CREATE TRIGGER trg_instruments_updated_at
BEFORE UPDATE ON core.instruments
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

-- 4.2 accounts: 账户表
CREATE TABLE IF NOT EXISTS core.accounts (
    account_id          BIGSERIAL PRIMARY KEY,
    account_code        TEXT NOT NULL UNIQUE,          -- 例: paper_main
    account_name        TEXT NOT NULL,
    broker              TEXT,
    account_type        TEXT NOT NULL DEFAULT 'paper', -- paper / live / research
    base_currency       TEXT NOT NULL DEFAULT 'CNY',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT accounts_type_chk
        CHECK (account_type IN ('paper', 'live', 'research'))
);

CREATE INDEX IF NOT EXISTS idx_accounts_active
    ON core.accounts (is_active);

DROP TRIGGER IF EXISTS trg_accounts_updated_at ON core.accounts;
CREATE TRIGGER trg_accounts_updated_at
BEFORE UPDATE ON core.accounts
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

-- 4.3 positions: 持仓快照表
-- 一天一快照；如果你以后要盘中多快照，可把 as_of_date 换成 as_of_ts
CREATE TABLE IF NOT EXISTS core.positions (
    position_id         BIGSERIAL PRIMARY KEY,
    account_id          BIGINT NOT NULL REFERENCES core.accounts(account_id) ON DELETE CASCADE,
    symbol              TEXT NOT NULL REFERENCES core.instruments(symbol) ON DELETE RESTRICT,
    as_of_date          DATE NOT NULL,
    position_qty        NUMERIC(20, 4) NOT NULL DEFAULT 0,
    available_qty       NUMERIC(20, 4) NOT NULL DEFAULT 0,
    frozen_qty          NUMERIC(20, 4) NOT NULL DEFAULT 0,
    avg_cost            NUMERIC(20, 6),
    last_price          NUMERIC(20, 6),
    market_value        NUMERIC(20, 2),
    unrealized_pnl      NUMERIC(20, 2),
    weight              NUMERIC(12, 8),
    source              TEXT NOT NULL DEFAULT 'manual',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT positions_unique_snapshot
        UNIQUE (account_id, symbol, as_of_date),
    CONSTRAINT positions_nonnegative_chk
        CHECK (
            position_qty >= 0
            AND available_qty >= 0
            AND frozen_qty >= 0
        ),
    CONSTRAINT positions_available_le_position_chk
        CHECK (available_qty <= position_qty),
    CONSTRAINT positions_frozen_le_position_chk
        CHECK (frozen_qty <= position_qty)
);

CREATE INDEX IF NOT EXISTS idx_positions_account_date
    ON core.positions (account_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_positions_symbol_date
    ON core.positions (symbol, as_of_date DESC);

DROP TRIGGER IF EXISTS trg_positions_updated_at ON core.positions;
CREATE TRIGGER trg_positions_updated_at
BEFORE UPDATE ON core.positions
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

-- 4.4 trades: 成交流水表
CREATE TABLE IF NOT EXISTS core.trades (
    trade_id            BIGSERIAL PRIMARY KEY,
    ext_trade_id        TEXT UNIQUE,                   -- 外部成交编号，可为空
    account_id          BIGINT NOT NULL REFERENCES core.accounts(account_id) ON DELETE CASCADE,
    symbol              TEXT NOT NULL REFERENCES core.instruments(symbol) ON DELETE RESTRICT,
    trade_date          DATE NOT NULL,
    trade_time          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    side                TEXT NOT NULL,                 -- BUY / SELL / DIVIDEND / ...
    qty                 NUMERIC(20, 4) NOT NULL,
    price               NUMERIC(20, 6),
    gross_amount        NUMERIC(20, 2),
    fee                 NUMERIC(20, 2) NOT NULL DEFAULT 0,
    tax                 NUMERIC(20, 2) NOT NULL DEFAULT 0,
    currency            TEXT NOT NULL DEFAULT 'CNY',
    source              TEXT NOT NULL DEFAULT 'manual',
    strategy_tag        TEXT,
    notes               TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT trades_side_chk
        CHECK (side IN ('BUY', 'SELL', 'DIVIDEND', 'SPLIT', 'FEE', 'TRANSFER_IN', 'TRANSFER_OUT')),
    CONSTRAINT trades_qty_nonnegative_chk
        CHECK (qty >= 0),
    CONSTRAINT trades_money_nonnegative_chk
        CHECK (
            COALESCE(fee, 0) >= 0
            AND COALESCE(tax, 0) >= 0
        )
);

CREATE INDEX IF NOT EXISTS idx_trades_account_time
    ON core.trades (account_id, trade_time DESC);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
    ON core.trades (symbol, trade_time DESC);

CREATE INDEX IF NOT EXISTS idx_trades_trade_date
    ON core.trades (trade_date DESC);

-- 4.5 watchlists: 股票池主表
CREATE TABLE IF NOT EXISTS core.watchlists (
    watchlist_id        BIGSERIAL PRIMARY KEY,
    watchlist_code      TEXT NOT NULL UNIQUE,         -- 例: default_a_share
    name                TEXT NOT NULL,
    description         TEXT,
    owner_name          TEXT NOT NULL DEFAULT 'system',
    scope               TEXT NOT NULL DEFAULT 'system', -- system / user / model
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT watchlists_scope_chk
        CHECK (scope IN ('system', 'user', 'model'))
);

CREATE INDEX IF NOT EXISTS idx_watchlists_active
    ON core.watchlists (is_active);

DROP TRIGGER IF EXISTS trg_watchlists_updated_at ON core.watchlists;
CREATE TRIGGER trg_watchlists_updated_at
BEFORE UPDATE ON core.watchlists
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

-- 4.6 watchlist_members: 股票池成员表
CREATE TABLE IF NOT EXISTS core.watchlist_members (
    watchlist_member_id BIGSERIAL PRIMARY KEY,
    watchlist_id        BIGINT NOT NULL REFERENCES core.watchlists(watchlist_id) ON DELETE CASCADE,
    symbol              TEXT NOT NULL REFERENCES core.instruments(symbol) ON DELETE RESTRICT,
    tag                 TEXT,
    source              TEXT NOT NULL DEFAULT 'manual',  -- manual / api / model / rule
    priority            INTEGER NOT NULL DEFAULT 100,
    notes               TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    added_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT watchlist_members_unique
        UNIQUE (watchlist_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_members_watchlist
    ON core.watchlist_members (watchlist_id, priority ASC, added_at DESC);

CREATE INDEX IF NOT EXISTS idx_watchlist_members_symbol
    ON core.watchlist_members (symbol);

DROP TRIGGER IF EXISTS trg_watchlist_members_updated_at ON core.watchlist_members;
CREATE TRIGGER trg_watchlist_members_updated_at
BEFORE UPDATE ON core.watchlist_members
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

-- =========================================================
-- MARKET SCHEMA
-- =========================================================

-- 5.1 market_bars_daily: 日线行情
CREATE TABLE IF NOT EXISTS market.market_bars_daily (
    symbol              TEXT NOT NULL REFERENCES core.instruments(symbol) ON DELETE RESTRICT,
    trade_date          DATE NOT NULL,
    open                NUMERIC(20, 6),
    high                NUMERIC(20, 6),
    low                 NUMERIC(20, 6),
    close               NUMERIC(20, 6),
    volume              NUMERIC(28, 6),
    amount              NUMERIC(28, 2),
    adj_factor          NUMERIC(20, 8),
    source              TEXT NOT NULL DEFAULT 'tushare',
    extra               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, trade_date)
);

SELECT create_hypertable(
    'market.market_bars_daily',
    'trade_date',
    if_not_exists => TRUE,
    create_default_indexes => FALSE
);

CREATE INDEX IF NOT EXISTS idx_market_bars_daily_date_symbol
    ON market.market_bars_daily (trade_date DESC, symbol);

-- 5.2 factor_values: 因子值表
CREATE TABLE IF NOT EXISTS market.factor_values (
    symbol              TEXT NOT NULL REFERENCES core.instruments(symbol) ON DELETE RESTRICT,
    trade_date          DATE NOT NULL,
    factor_name         TEXT NOT NULL,
    factor_value        NUMERIC(30, 12),
    factor_version      TEXT NOT NULL DEFAULT 'v1',
    source              TEXT NOT NULL DEFAULT 'internal',
    extra               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, trade_date, factor_name, factor_version)
);

SELECT create_hypertable(
    'market.factor_values',
    'trade_date',
    if_not_exists => TRUE,
    create_default_indexes => FALSE
);

CREATE INDEX IF NOT EXISTS idx_factor_values_factor_date
    ON market.factor_values (factor_name, trade_date DESC, symbol);

-- =========================================================
-- RESEARCH SCHEMA
-- =========================================================

-- 6.1 analysis_runs: 一次分析任务的运行记录
CREATE TABLE IF NOT EXISTS research.analysis_runs (
    run_id               BIGSERIAL PRIMARY KEY,
    run_source           TEXT NOT NULL DEFAULT 'manual',   -- manual / batch / schedule / api
    triggered_by         TEXT NOT NULL DEFAULT 'system',
    account_id           BIGINT REFERENCES core.accounts(account_id) ON DELETE SET NULL,
    watchlist_id         BIGINT REFERENCES core.watchlists(watchlist_id) ON DELETE SET NULL,
    model_provider       TEXT,
    model_name           TEXT,
    model_version        TEXT,
    symbol_count         INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'running',  -- running / success / failed / partial
    started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at          TIMESTAMPTZ,
    runtime_ms           BIGINT,
    input_params         JSONB NOT NULL DEFAULT '{}'::jsonb,
    runtime_meta         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message        TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT analysis_runs_status_chk
        CHECK (status IN ('running', 'success', 'failed', 'partial'))
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_started_at
    ON research.analysis_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_status
    ON research.analysis_runs (status, started_at DESC);

-- 6.2 analysis_decisions: 单票分析结论
CREATE TABLE IF NOT EXISTS research.analysis_decisions (
    decision_id          BIGSERIAL PRIMARY KEY,
    run_id               BIGINT NOT NULL REFERENCES research.analysis_runs(run_id) ON DELETE CASCADE,
    symbol               TEXT NOT NULL REFERENCES core.instruments(symbol) ON DELETE RESTRICT,
    account_id           BIGINT REFERENCES core.accounts(account_id) ON DELETE SET NULL,
    action               TEXT NOT NULL,     -- ENTER / ADD / HOLD / TRIM / EXIT / AVOID / REVIEW
    confidence           NUMERIC(8, 6),
    risk_level           TEXT,              -- LOW / MEDIUM / HIGH / CRITICAL
    score                NUMERIC(20, 8),    -- 可供后续量化融合
    rationale            TEXT,
    summary              TEXT,
    decision_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT analysis_decisions_action_chk
        CHECK (action IN ('ENTER', 'ADD', 'HOLD', 'TRIM', 'EXIT', 'AVOID', 'REVIEW')),
    CONSTRAINT analysis_decisions_risk_level_chk
        CHECK (risk_level IS NULL OR risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'))
);

CREATE INDEX IF NOT EXISTS idx_analysis_decisions_symbol_time
    ON research.analysis_decisions (symbol, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_analysis_decisions_account_time
    ON research.analysis_decisions (account_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_analysis_decisions_action_time
    ON research.analysis_decisions (action, created_at DESC);

-- 6.3 model_predictions: 机器学习/规则模型输出
CREATE TABLE IF NOT EXISTS research.model_predictions (
    prediction_id        BIGSERIAL PRIMARY KEY,
    model_name           TEXT NOT NULL,
    model_version        TEXT NOT NULL,
    prediction_date      DATE NOT NULL,
    symbol               TEXT NOT NULL REFERENCES core.instruments(symbol) ON DELETE RESTRICT,
    account_id           BIGINT REFERENCES core.accounts(account_id) ON DELETE SET NULL,
    horizon              TEXT NOT NULL DEFAULT 'D1',      -- D1 / D5 / W1 ...
    score                NUMERIC(20, 8),
    rank_value           INTEGER,
    label                TEXT,
    features_version     TEXT,
    prediction_meta      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT model_predictions_unique
        UNIQUE (model_name, model_version, prediction_date, symbol, horizon, account_id)
);

CREATE INDEX IF NOT EXISTS idx_model_predictions_date_model
    ON research.model_predictions (prediction_date DESC, model_name, model_version);

CREATE INDEX IF NOT EXISTS idx_model_predictions_symbol_date
    ON research.model_predictions (symbol, prediction_date DESC);

-- 6.4 research_embeddings: 向量检索表
-- 使用无固定维度 vector，方便以后接不同 embedding 模型
CREATE TABLE IF NOT EXISTS research.research_embeddings (
    embedding_id         BIGSERIAL PRIMARY KEY,
    source_type          TEXT NOT NULL,     -- news / report / company_profile / agent_memory / chat
    source_key           TEXT NOT NULL,     -- 外部ID或你自己的主键
    symbol               TEXT REFERENCES core.instruments(symbol) ON DELETE SET NULL,
    model_name           TEXT NOT NULL,
    content              TEXT,
    embedding            VECTOR,
    meta                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT research_embeddings_unique
        UNIQUE (source_type, source_key, model_name)
);

CREATE INDEX IF NOT EXISTS idx_research_embeddings_symbol
    ON research.research_embeddings (symbol, created_at DESC);

-- =========================================================
-- ACCOUNT BALANCES (净值快照表)
-- =========================================================

CREATE TABLE IF NOT EXISTS core.account_balances (
    balance_id          BIGSERIAL PRIMARY KEY,
    account_id          BIGINT NOT NULL REFERENCES core.accounts(account_id) ON DELETE CASCADE,
    as_of_date          DATE NOT NULL,
    cash                NUMERIC(20, 2) NOT NULL DEFAULT 0,
    available_cash      NUMERIC(20, 2) NOT NULL DEFAULT 0,
    frozen_cash         NUMERIC(20, 2) NOT NULL DEFAULT 0,
    market_value        NUMERIC(20, 2) NOT NULL DEFAULT 0,
    total_equity        NUMERIC(20, 2) NOT NULL DEFAULT 0,
    nav                 NUMERIC(20, 8),
    total_units         NUMERIC(20, 8) DEFAULT NULL,
    currency            TEXT NOT NULL DEFAULT 'CNY',
    source              TEXT NOT NULL DEFAULT 'calculated',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT account_balances_unique UNIQUE (account_id, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_ab_account_date ON core.account_balances (account_id, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_ab_date ON core.account_balances (as_of_date DESC);

DROP TRIGGER IF EXISTS trg_ab_updated ON core.account_balances;
CREATE TRIGGER trg_ab_updated
BEFORE UPDATE ON core.account_balances
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

COMMENT ON TABLE core.account_balances IS '账户资金与净值快照，每日一记';

-- =========================================================
-- GRANTS
-- =========================================================

-- Schema usage
GRANT USAGE ON SCHEMA core, market, research TO ta_app_rw, ta_panel_rw, ta_ml_ro;

-- ta_app_rw: 应用层读写
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core, market, research TO ta_app_rw;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA core, market, research TO ta_app_rw;

-- ta_panel_rw: 面板层读写
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core, market, research TO ta_panel_rw;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA core, market, research TO ta_panel_rw;

-- ta_ml_ro: 机器学习宿主机只读
GRANT SELECT ON ALL TABLES IN SCHEMA core, market, research TO ta_ml_ro;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA core, market, research TO ta_ml_ro;

-- account_balances 权限
GRANT SELECT, INSERT, UPDATE, DELETE ON core.account_balances TO ta_app_rw, ta_panel_rw;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA core TO ta_app_rw, ta_panel_rw;
GRANT SELECT ON core.account_balances TO ta_ml_ro;

-- Default privileges for future tables/sequences created by current owner
ALTER DEFAULT PRIVILEGES IN SCHEMA core, market, research
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ta_app_rw, ta_panel_rw;

ALTER DEFAULT PRIVILEGES IN SCHEMA core, market, research
GRANT SELECT ON TABLES TO ta_ml_ro;

ALTER DEFAULT PRIVILEGES IN SCHEMA core, market, research
GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO ta_app_rw, ta_panel_rw;

ALTER DEFAULT PRIVILEGES IN SCHEMA core, market, research
GRANT USAGE, SELECT ON SEQUENCES TO ta_ml_ro;

-- =========================================================
-- LATEST POSITIONS VIEW（当前持仓视图）
-- =========================================================
DROP VIEW IF EXISTS core.v_latest_positions;
CREATE VIEW core.v_latest_positions AS
SELECT
    p.position_id,
    p.account_id,
    a.account_code,
    a.account_name,
    p.symbol,
    i.name            AS instrument_name,
    i.exchange,
    i.industry,
    p.as_of_date      AS snapshot_date,
    p.position_qty,
    p.available_qty,
    p.frozen_qty,
    p.avg_cost,
    p.last_price,
    p.market_value,
    p.unrealized_pnl,
    p.weight,
    p.source,
    p.metadata,
    CASE WHEN p.avg_cost > 0 AND p.last_price > 0
         THEN ROUND((p.last_price - p.avg_cost) / p.avg_cost * 100, 4)
         ELSE NULL END AS pnl_pct
FROM core.positions p
JOIN core.accounts a ON a.account_id = p.account_id
JOIN core.instruments i ON i.symbol = p.symbol
WHERE p.as_of_date = (
    SELECT MAX(as_of_date)
    FROM core.positions
    WHERE account_id = p.account_id AND symbol = p.symbol
);

COMMENT ON VIEW core.v_latest_positions IS '当前持仓视图（取每个账户每个标的的最新快照）';

GRANT SELECT ON core.v_latest_positions TO ta_app_rw, ta_panel_rw, ta_ml_ro;

COMMIT;
-- =========================================================
-- V2: ADDITIONAL VIEWS AND ACCOUNT_CONSTRAINTS
-- =========================================================

-- Latest account balance view
DROP VIEW IF EXISTS core.v_latest_account_balance;
CREATE VIEW core.v_latest_account_balance AS
SELECT
    b.balance_id,
    b.account_id,
    a.account_code,
    a.account_name,
    b.as_of_date,
    b.cash,
    b.available_cash,
    b.frozen_cash,
    b.market_value,
    b.total_equity,
    b.nav,
    b.total_units,
    b.currency,
    b.source,
    b.metadata
FROM core.account_balances b
JOIN core.accounts a ON a.account_id = b.account_id
WHERE b.as_of_date = (
    SELECT MAX(as_of_date)
    FROM core.account_balances
    WHERE account_id = b.account_id
);

COMMENT ON VIEW core.v_latest_account_balance IS '账户最新资金净值快照';

GRANT SELECT ON core.v_latest_account_balance TO ta_app_rw, ta_panel_rw, ta_ml_ro;

-- Account portfolio snapshot view (one row per account)
DROP VIEW IF EXISTS core.v_account_portfolio_snapshot;
CREATE VIEW core.v_account_portfolio_snapshot AS
SELECT
    a.account_id,
    a.account_code,
    a.account_name,
    a.account_type,
    COALESCE(b.total_equity, 0)               AS total_equity,
    COALESCE(b.nav, 1.0)                      AS nav,
    COALESCE(b.cash, 0)                        AS total_cash,
    COALESCE(b.available_cash, 0)             AS available_cash,
    COALESCE(b.market_value, 0)                AS total_market_value,
    COALESCE(p.position_count, 0)              AS position_count,
    COALESCE(p.holding_count, 0)              AS holding_count,
    COALESCE(p.total_weight, 0)               AS total_weight_pct,
    COALESCE(p.cash_ratio, 0)                AS cash_ratio_pct,
    COALESCE(p.top_symbol_weight, 0)           AS top_symbol_weight_pct,
    COALESCE(p.top_sector_weight, 0)          AS top_sector_weight_pct,
    b.as_of_date                               AS balance_date,
    p.as_of_date                               AS positions_date
FROM core.accounts a
LEFT JOIN core.v_latest_account_balance b ON b.account_id = a.account_id
LEFT JOIN LATERAL (
    SELECT
        COUNT(*)                                          AS position_count,
        COUNT(*) FILTER (WHERE position_qty > 0)          AS holding_count,
        SUM(market_value)                                 AS total_position_mv,
        SUM(market_value) / NULLIF(b.total_equity, 0)   AS total_weight,
        b.cash / NULLIF(b.total_equity, 0)               AS cash_ratio,
        MAX(market_value / NULLIF(b.total_equity, 0))   AS top_symbol_weight,
        0.0                                              AS top_sector_weight,
        MAX(as_of_date)                                   AS as_of_date
    FROM core.positions
    WHERE account_id = a.account_id
      AND as_of_date = (
          SELECT MAX(as_of_date) FROM core.positions WHERE account_id = a.account_id
      )
) p ON TRUE;

COMMENT ON VIEW core.v_account_portfolio_snapshot IS '账户组合汇总快照（持仓统计+资金统计）';

GRANT SELECT ON core.v_account_portfolio_snapshot TO ta_app_rw, ta_panel_rw, ta_ml_ro;

-- Sector exposure view
DROP VIEW IF EXISTS core.v_sector_exposure;
CREATE VIEW core.v_sector_exposure AS
WITH latest_positions AS (
    SELECT p.*
    FROM core.positions p
    WHERE p.as_of_date = (
        SELECT MAX(as_of_date)
        FROM core.positions
        WHERE account_id = p.account_id
    )
),
account_totals AS (
    SELECT
        account_id,
        SUM(market_value) AS total_mv
    FROM latest_positions
    GROUP BY account_id
)
SELECT
    lp.account_id,
    a.account_code,
    i.sector,
    SUM(lp.market_value)                          AS sector_market_value,
    ROUND(SUM(lp.market_value) / NULLIF(at.total_mv, 0) * 100, 4) AS sector_weight_pct,
    COUNT(lp.symbol)                               AS holding_count,
    ARRAY_AGG(lp.symbol ORDER BY lp.market_value DESC)
        FILTER (WHERE i.sector IS NOT NULL)      AS holding_symbols,
    lp.as_of_date                                 AS snapshot_date
FROM latest_positions lp
JOIN core.accounts a ON a.account_id = lp.account_id
JOIN core.instruments i ON i.symbol = lp.symbol
JOIN account_totals at ON at.account_id = lp.account_id
WHERE i.sector IS NOT NULL
GROUP BY lp.account_id, a.account_code, i.sector, lp.as_of_date, at.total_mv;

COMMENT ON VIEW core.v_sector_exposure IS '账户行业暴露视图';

GRANT SELECT ON core.v_sector_exposure TO ta_app_rw, ta_panel_rw, ta_ml_ro;

-- =========================================================
-- ACCOUNT CONSTRAINTS TABLE
-- =========================================================

CREATE TABLE IF NOT EXISTS core.account_constraints (
    constraint_id               BIGSERIAL PRIMARY KEY,
    account_id                 BIGINT NOT NULL UNIQUE REFERENCES core.accounts(account_id) ON DELETE CASCADE,
    max_symbol_weight          NUMERIC(8, 4) NOT NULL DEFAULT 0.15,         -- 单票最大权重 15%
    max_sector_weight          NUMERIC(8, 4) NOT NULL DEFAULT 0.30,         -- 行业最大权重 30%
    min_cash_ratio             NUMERIC(8, 4) NOT NULL DEFAULT 0.05,         -- 最小现金比例 5%
    max_new_positions_per_day  INTEGER NOT NULL DEFAULT 3,                    -- 单日最多新建仓数
    allow_add_on_profit_only   BOOLEAN NOT NULL DEFAULT FALSE,              -- 仅盈利持仓才允许加仓
    allow_add_on_loss          BOOLEAN NOT NULL DEFAULT FALSE,              -- 亏损持仓是否允许加仓
    review_on_missing_balance  BOOLEAN NOT NULL DEFAULT TRUE,               -- 无余额快照时是否降为 REVIEW
    is_active                 BOOLEAN NOT NULL DEFAULT TRUE,
    metadata                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT constraints_max_symbol_range CHECK (max_symbol_weight BETWEEN 0 AND 1),
    CONSTRAINT constraints_max_sector_range CHECK (max_sector_weight BETWEEN 0 AND 1),
    CONSTRAINT constraints_min_cash_range CHECK (min_cash_ratio BETWEEN 0 AND 1)
);

CREATE INDEX IF NOT EXISTS idx_account_constraints_active ON core.account_constraints (account_id, is_active);

DROP TRIGGER IF EXISTS trg_account_constraints_updated_at ON core.account_constraints;
CREATE TRIGGER trg_account_constraints_updated_at
BEFORE UPDATE ON core.account_constraints
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

COMMENT ON TABLE core.account_constraints IS '账户组合约束配置表';
COMMENT ON COLUMN core.account_constraints.max_symbol_weight IS '单票最大权重（如 0.15 = 15%）';
COMMENT ON COLUMN core.account_constraints.max_sector_weight IS '行业最大权重（如 0.30 = 30%）';
COMMENT ON COLUMN core.account_constraints.min_cash_ratio IS '最小现金比例（如 0.05 = 5%）';

-- Default constraints for paper_main and research_main
INSERT INTO core.account_constraints (account_id, max_symbol_weight, max_sector_weight, min_cash_ratio, allow_add_on_profit_only, allow_add_on_loss, review_on_missing_balance)
VALUES
    (1, 0.20, 0.35, 0.05, FALSE, FALSE, TRUE)   -- paper_main: 20%单票/35%行业/5%现金底线
ON CONFLICT (account_id) DO NOTHING;

INSERT INTO core.account_constraints (account_id, max_symbol_weight, max_sector_weight, min_cash_ratio, allow_add_on_profit_only, allow_add_on_loss, review_on_missing_balance)
VALUES
    (2, 0.30, 0.50, 0.10, TRUE, FALSE, TRUE)    -- research_main: 宽松，30%单票/50%行业
ON CONFLICT (account_id) DO NOTHING;

GRANT SELECT, INSERT, UPDATE, DELETE ON core.account_constraints TO ta_app_rw, ta_panel_rw;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA core TO ta_app_rw, ta_panel_rw;
GRANT SELECT ON core.account_constraints TO ta_ml_ro;

COMMIT;
