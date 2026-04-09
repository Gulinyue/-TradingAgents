-- ============================================================
-- V2.1 观测视图 Migration
-- ============================================================
-- 运行方式（PSQL）：
--   psql "postgresql://ta_app_rw:TaAppRW2026!@localhost:6543/tradingagents" -f 002_v21_observability_views.sql
-- ============================================================

-- View 1: 最近运行的聚合摘要（按日期）
CREATE OR REPLACE VIEW research.v_recent_run_summary AS
SELECT
    DATE(r.created_at)              AS run_date,
    COUNT(*)                        AS total_runs,
    COUNT(*) FILTER (WHERE r.status = 'success')  AS success_count,
    COUNT(*) FILTER (WHERE r.status = 'partial')  AS partial_count,
    COUNT(*) FILTER (WHERE r.status = 'failed')   AS failed_count,
    ROUND(AVG(r.runtime_ms) / 1000.0, 1) AS avg_runtime_seconds,
    COUNT(DISTINCT r.account_code)  AS unique_accounts
FROM research.analysis_runs r
GROUP BY DATE(r.created_at)
ORDER BY run_date DESC;

-- View 2: 最近 partial 的原因分布
CREATE OR REPLACE VIEW research.v_recent_partial_reasons AS
SELECT
    DATE(d.created_at)                               AS run_date,
    d.decision_json #>> '{status_tags}'             AS status_tags,
    COUNT(*)                                         AS cnt
FROM research.analysis_decisions d
JOIN research.analysis_runs r ON r.run_id = d.run_id
WHERE r.status = 'partial'
GROUP BY DATE(d.created_at), d.decision_json #>> '{status_tags}'
ORDER BY run_date DESC, cnt DESC;

-- View 3: 每只股票最近一条 decision
CREATE OR REPLACE VIEW research.v_latest_symbol_decisions AS
WITH ranked AS (
    SELECT
        d.symbol,
        r.run_id,
        r.account_code,
        r.watchlist_code,
        d.action                              AS final_action,
        d.decision_json #>> '{raw_action}'    AS raw_action,
        d.decision_json #>> '{ta_result,decision}' AS ta_decision,
        d.decision_json #>> '{candidate_bucket}'  AS candidate_bucket,
        d.decision_json #>> '{decision_rank_score}' AS decision_rank_score,
        d.decision_json #>> '{run_status}'    AS run_status,
        d.decision_json #>> '{status_reason}' AS status_reason,
        r.created_at                          AS decision_time,
        ROW_NUMBER() OVER (
            PARTITION BY d.symbol
            ORDER BY r.created_at DESC
        )                                     AS rn
    FROM research.analysis_decisions d
    JOIN research.analysis_runs r ON r.run_id = d.run_id
)
SELECT *
FROM ranked
WHERE rn = 1;

-- View 4: 每只股票最新 bar 数
CREATE OR REPLACE VIEW market.v_latest_bar_counts AS
SELECT
    symbol,
    COUNT(*)                                    AS bar_count,
    MIN(trade_date)                             AS first_date,
    MAX(trade_date)                             AS last_date,
    CASE
        WHEN COUNT(*) >= 120 THEN 'full'
        WHEN COUNT(*) >= 60  THEN 'good'
        WHEN COUNT(*) >= 20  THEN 'minimum_only'
        ELSE 'insufficient'
    END                                         AS bar_quality_level
FROM market.market_bars_daily
GROUP BY symbol;

-- ============================================================
-- 快速诊断查询（可直接在 psql 中运行）
-- ============================================================

-- 最近 7 天运行质量
-- SELECT * FROM research.v_recent_run_summary ORDER BY run_date DESC LIMIT 7;

-- 找出所有 partial 原因
-- SELECT * FROM research.v_recent_partial_reasons ORDER BY cnt DESC;

-- 看某只股票的最新决策
-- SELECT * FROM research.v_latest_symbol_decisions WHERE symbol = '600519.SH';

-- 看所有标的 bar 数是否达标
-- SELECT * FROM market.v_latest_bar_counts WHERE bar_quality_level != 'full' ORDER BY bar_count;
