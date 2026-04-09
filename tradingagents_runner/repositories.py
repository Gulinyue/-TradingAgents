import json
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json, RealDictCursor

from db import get_conn


def normalize_db_symbol(symbol: str) -> str:
    """
    数据库内部统一：
    沪市 -> .SH
    深市 -> .SZ
    容错：
    - 600519.ss -> 600519.SH
    - 600519.SH -> 600519.SH
    """
    s = symbol.strip().upper()
    if s.endswith(".SS"):
        s = s[:-3] + ".SH"
    return s


class BaseRepository:
    @staticmethod
    def _fetch_one(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return dict(row) if row else None

    @staticmethod
    def _fetch_all(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]

    @staticmethod
    def _execute_returning_id(sql: str, params: tuple = ()) -> int:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("INSERT did not return an id")
                return int(row[0])

    @staticmethod
    def _execute(sql: str, params: tuple = ()) -> None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)


class AccountRepository(BaseRepository):
    def get_account_by_code(self, account_code: str) -> Optional[Dict[str, Any]]:
        sql = """
        SELECT
            account_id,
            account_code,
            account_name,
            broker,
            account_type,
            base_currency,
            is_active,
            metadata,
            created_at,
            updated_at
        FROM core.accounts
        WHERE account_code = %s
        LIMIT 1;
        """
        return self._fetch_one(sql, (account_code,))

    def get_latest_positions(
        self,
        account_code: str,
        as_of_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if as_of_date:
            sql = """
            SELECT
                p.position_id,
                p.account_id,
                a.account_code,
                p.symbol,
                i.name,
                i.industry,
                i.sector,
                p.as_of_date,
                p.position_qty,
                p.available_qty,
                p.frozen_qty,
                p.avg_cost,
                p.last_price,
                p.market_value,
                p.unrealized_pnl,
                p.weight,
                p.source,
                p.metadata
            FROM core.positions p
            JOIN core.accounts a
              ON a.account_id = p.account_id
            JOIN core.instruments i
              ON i.symbol = p.symbol
            WHERE a.account_code = %s
              AND p.as_of_date = %s
            ORDER BY p.market_value DESC NULLS LAST, p.symbol ASC;
            """
            return self._fetch_all(sql, (account_code, as_of_date))

        sql = """
        WITH latest_dt AS (
            SELECT MAX(p.as_of_date) AS as_of_date
            FROM core.positions p
            JOIN core.accounts a
              ON a.account_id = p.account_id
            WHERE a.account_code = %s
        )
        SELECT
            p.position_id,
            p.account_id,
            a.account_code,
            p.symbol,
            i.name,
            i.industry,
            i.sector,
            p.as_of_date,
            p.position_qty,
            p.available_qty,
            p.frozen_qty,
            p.avg_cost,
            p.last_price,
            p.market_value,
            p.unrealized_pnl,
            p.weight,
            p.source,
            p.metadata
        FROM core.positions p
        JOIN core.accounts a
          ON a.account_id = p.account_id
        JOIN core.instruments i
          ON i.symbol = p.symbol
        JOIN latest_dt ld
          ON ld.as_of_date = p.as_of_date
        WHERE a.account_code = %s
        ORDER BY p.market_value DESC NULLS LAST, p.symbol ASC;
        """
        return self._fetch_all(sql, (account_code, account_code))

    def get_latest_position_for_symbol(
        self,
        account_code: str,
        symbol: str,
        as_of_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        symbol = normalize_db_symbol(symbol)

        if as_of_date:
            sql = """
            SELECT
                p.position_id,
                p.account_id,
                a.account_code,
                p.symbol,
                i.name,
                i.industry,
                i.sector,
                p.as_of_date,
                p.position_qty,
                p.available_qty,
                p.frozen_qty,
                p.avg_cost,
                p.last_price,
                p.market_value,
                p.unrealized_pnl,
                p.weight,
                p.source,
                p.metadata
            FROM core.positions p
            JOIN core.accounts a
              ON a.account_id = p.account_id
            JOIN core.instruments i
              ON i.symbol = p.symbol
            WHERE a.account_code = %s
              AND p.symbol = %s
              AND p.as_of_date = %s
            LIMIT 1;
            """
            return self._fetch_one(sql, (account_code, symbol, as_of_date))

        sql = """
        SELECT
            p.position_id,
            p.account_id,
            a.account_code,
            p.symbol,
            i.name,
            i.industry,
            i.sector,
            p.as_of_date,
            p.position_qty,
            p.available_qty,
            p.frozen_qty,
            p.avg_cost,
            p.last_price,
            p.market_value,
            p.unrealized_pnl,
            p.weight,
            p.source,
            p.metadata
        FROM core.positions p
        JOIN core.accounts a
          ON a.account_id = p.account_id
        JOIN core.instruments i
          ON i.symbol = p.symbol
        WHERE a.account_code = %s
          AND p.symbol = %s
        ORDER BY p.as_of_date DESC
        LIMIT 1;
        """
        return self._fetch_one(sql, (account_code, symbol))


class WatchlistRepository(BaseRepository):
    def get_watchlist_by_code(self, watchlist_code: str) -> Optional[Dict[str, Any]]:
        sql = """
        SELECT
            watchlist_id,
            watchlist_code,
            name,
            description,
            owner_name,
            scope,
            is_active,
            metadata,
            created_at,
            updated_at
        FROM core.watchlists
        WHERE watchlist_code = %s
        LIMIT 1;
        """
        return self._fetch_one(sql, (watchlist_code,))

    def get_watchlist_members(self, watchlist_code: str) -> List[Dict[str, Any]]:
        sql = """
        SELECT
            w.watchlist_id,
            w.watchlist_code,
            m.watchlist_member_id,
            m.symbol,
            i.name,
            i.industry,
            i.sector,
            m.tag,
            m.source,
            m.priority,
            m.notes,
            m.metadata,
            m.added_at
        FROM core.watchlists w
        JOIN core.watchlist_members m
          ON m.watchlist_id = w.watchlist_id
        JOIN core.instruments i
          ON i.symbol = m.symbol
        WHERE w.watchlist_code = %s
          AND w.is_active = TRUE
        ORDER BY m.priority ASC, m.added_at DESC, m.symbol ASC;
        """
        return self._fetch_all(sql, (watchlist_code,))

    def get_symbols_by_watchlist_code(self, watchlist_code: str) -> List[str]:
        rows = self.get_watchlist_members(watchlist_code)
        return [r["symbol"] for r in rows]


    def get_latest_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        symbol = normalize_db_symbol(symbol)

        sql = """
        SELECT
            b.symbol,
            i.name,
            b.trade_date,
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
            b.amount,
            b.adj_factor,
            b.source,
            b.extra
        FROM market.market_bars_daily b
        JOIN core.instruments i
          ON i.symbol = b.symbol
        WHERE b.symbol = %s
        ORDER BY b.trade_date DESC
        LIMIT 1;
        """
        return self._fetch_one(sql, (symbol,))

    def get_latest_factors(
        self,
        symbol: str,
        trade_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        symbol = normalize_db_symbol(symbol)

        if trade_date:
            sql = """
            SELECT
                f.symbol,
                f.trade_date,
                f.factor_name,
                f.factor_value,
                f.factor_version,
                f.source,
                f.extra
            FROM market.factor_values f
            WHERE f.symbol = %s
              AND f.trade_date = %s
            ORDER BY f.factor_name ASC;
            """
            return self._fetch_all(sql, (symbol, trade_date))

        sql = """
        WITH latest_dt AS (
            SELECT MAX(trade_date) AS trade_date
            FROM market.factor_values
            WHERE symbol = %s
        )
        SELECT
            f.symbol,
            f.trade_date,
            f.factor_name,
            f.factor_value,
            f.factor_version,
            f.source,
            f.extra
        FROM market.factor_values f
        JOIN latest_dt ld
          ON ld.trade_date = f.trade_date
        WHERE f.symbol = %s
        ORDER BY f.factor_name ASC;
        """
        return self._fetch_all(sql, (symbol, symbol))

    def get_latest_factors_as_dict(
        self,
        symbol: str,
        trade_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = self.get_latest_factors(symbol, trade_date)
        return {row["factor_name"]: row["factor_value"] for row in rows}


class MarketRepository(BaseRepository):
    def get_bar_count(self, symbol: str) -> int:
        symbol = normalize_db_symbol(symbol)
        result = self._fetch_one(
            "SELECT COUNT(*) AS cnt FROM market.market_bars_daily WHERE symbol = %s",
            (symbol,),
        )
        return int(result["cnt"]) if result else 0

    def get_latest_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        symbol = normalize_db_symbol(symbol)
        sql = """
        SELECT
            b.symbol,
            i.name,
            b.trade_date,
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
            b.amount,
            b.adj_factor,
            b.source,
            b.extra
        FROM market.market_bars_daily b
        JOIN core.instruments i
          ON i.symbol = b.symbol
        WHERE b.symbol = %s
        ORDER BY b.trade_date DESC
        LIMIT 1;
        """
        return self._fetch_one(sql, (symbol,))

    def get_latest_factors(
        self,
        symbol: str,
        trade_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        symbol = normalize_db_symbol(symbol)
        if trade_date:
            sql = """
            SELECT
                f.symbol,
                f.trade_date,
                f.factor_name,
                f.factor_value,
                f.factor_version,
                f.source,
                f.extra
            FROM market.factor_values f
            WHERE f.symbol = %s
              AND f.trade_date = %s
            ORDER BY f.factor_name ASC;
            """
            return self._fetch_all(sql, (symbol, trade_date))
        sql = """
        WITH latest_dt AS (
            SELECT MAX(trade_date) AS trade_date
            FROM market.factor_values
            WHERE symbol = %s
        )
        SELECT
            f.symbol,
            f.trade_date,
            f.factor_name,
            f.factor_value,
            f.factor_version,
            f.source,
            f.extra
        FROM market.factor_values f
        JOIN latest_dt ld
          ON ld.trade_date = f.trade_date
        WHERE f.symbol = %s
        ORDER BY f.factor_name ASC;
        """
        return self._fetch_all(sql, (symbol, symbol))

    def get_latest_factors_as_dict(
        self,
        symbol: str,
        trade_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = self.get_latest_factors(symbol, trade_date)
        return {row["factor_name"]: row["factor_value"] for row in rows}


class ResearchRepository(BaseRepository):
    def create_analysis_run(
        self,
        *,
        run_source: str,
        triggered_by: str,
        account_id: Optional[int],
        watchlist_id: Optional[int],
        model_provider: Optional[str],
        model_name: str,
        model_version: Optional[str],
        symbol_count: int,
        input_params: Optional[Dict[str, Any]] = None,
        runtime_meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        sql = """
        INSERT INTO research.analysis_runs (
            run_source,
            triggered_by,
            account_id,
            watchlist_id,
            model_provider,
            model_name,
            model_version,
            symbol_count,
            status,
            input_params,
            runtime_meta
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'running', %s, %s)
        RETURNING run_id;
        """
        return self._execute_returning_id(
            sql,
            (
                run_source,
                triggered_by,
                account_id,
                watchlist_id,
                model_provider,
                model_name,
                model_version,
                symbol_count,
                Json(input_params or {}),
                Json(runtime_meta or {}),
            ),
        )

    def insert_analysis_decision(
        self,
        *,
        run_id: int,
        symbol: str,
        account_id: Optional[int],
        action: str,
        confidence: Optional[float],
        risk_level: Optional[str],
        score: Optional[float],
        rationale: Optional[str],
        summary: Optional[str],
        decision_json: Optional[Dict[str, Any]] = None,
    ) -> int:
        symbol = normalize_db_symbol(symbol)

        sql = """
        INSERT INTO research.analysis_decisions (
            run_id,
            symbol,
            account_id,
            action,
            confidence,
            risk_level,
            score,
            rationale,
            summary,
            decision_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING decision_id;
        """
        return self._execute_returning_id(
            sql,
            (
                run_id,
                symbol,
                account_id,
                action,
                confidence,
                risk_level,
                score,
                rationale,
                summary,
                Json(decision_json or {}),
            ),
        )

    def mark_run_success(
        self,
        run_id: int,
        *,
        runtime_ms: Optional[int] = None,
        runtime_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        sql = """
        UPDATE research.analysis_runs
        SET
            status = 'success',
            finished_at = NOW(),
            runtime_ms = COALESCE(%s, runtime_ms),
            runtime_meta = CASE
                WHEN %s IS NULL THEN runtime_meta
                ELSE COALESCE(runtime_meta, '{}'::jsonb) || %s::jsonb
            END
        WHERE run_id = %s;
        """
        runtime_meta_json = json.dumps(runtime_meta) if runtime_meta is not None else None
        self._execute(sql, (runtime_ms, runtime_meta_json, runtime_meta_json, run_id))

    def update_run_status(
        self,
        run_id: int,
        status: str,
        *,
        runtime_ms: Optional[int] = None,
        runtime_meta: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        更新 run 状态，支持三种值：
          success  - 链路完整，TA 输出质量达标
          partial  - 链路完整，但数据不完整或 TA 输出退化
          failed   - 链路未完成，或关键写库失败
        """
        sql = """
        UPDATE research.analysis_runs
        SET
            status = %s,
            finished_at = NOW(),
            runtime_ms = COALESCE(%s, runtime_ms),
            error_message = COALESCE(%s, error_message),
            runtime_meta = CASE
                WHEN %s IS NULL THEN runtime_meta
                ELSE COALESCE(runtime_meta, '{}'::jsonb) || %s::jsonb
            END
        WHERE run_id = %s;
        """
        runtime_meta_json = json.dumps(runtime_meta) if runtime_meta is not None else None
        self._execute(
            sql,
            (status, runtime_ms, error_message, runtime_meta_json, runtime_meta_json, run_id),
        )

    def mark_run_failed(
        self,
        run_id: int,
        *,
        error_message: str,
        runtime_ms: Optional[int] = None,
        runtime_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        sql = """
        UPDATE research.analysis_runs
        SET
            status = 'failed',
            finished_at = NOW(),
            runtime_ms = COALESCE(%s, runtime_ms),
            error_message = %s,
            runtime_meta = CASE
                WHEN %s IS NULL THEN runtime_meta
                ELSE COALESCE(runtime_meta, '{}'::jsonb) || %s::jsonb
            END
        WHERE run_id = %s;
        """
        runtime_meta_json = json.dumps(runtime_meta) if runtime_meta is not None else None
        self._execute(
            sql,
            (runtime_ms, error_message, runtime_meta_json, runtime_meta_json, run_id),
        )


# ─────────────────────────────────────────────────────────────────────────────
# V2: AccountSnapshotRepository
# ─────────────────────────────────────────────────────────────────────────────

class AccountSnapshotRepository(BaseRepository):
    """
    V2 专用：读取组合快照视图，不做写操作。
    """

    def get_latest_account_balance(self, account_code: str) -> Optional[Dict[str, Any]]:
        """直接从视图取最新余额快照。"""
        sql = """
        SELECT *
        FROM core.v_latest_account_balance
        WHERE account_code = %s;
        """
        return self._fetch_one(sql, (account_code,))

    def get_account_constraints(self, account_code: str) -> Optional[Dict[str, Any]]:
        """取账户约束配置。"""
        sql = """
        SELECT c.*
        FROM core.account_constraints c
        JOIN core.accounts a ON a.account_id = c.account_id
        WHERE a.account_code = %s
          AND c.is_active = TRUE
        LIMIT 1;
        """
        return self._fetch_one(sql, (account_code,))

    def get_portfolio_snapshot(self, account_code: str) -> Optional[Dict[str, Any]]:
        """取账户组合汇总快照（余额+持仓统计）。"""
        sql = """
        SELECT *
        FROM core.v_account_portfolio_snapshot
        WHERE account_code = %s;
        """
        return self._fetch_one(sql, (account_code,))

    def get_sector_exposure(self, account_code: str) -> List[Dict[str, Any]]:
        """取账户行业暴露列表。"""
        sql = """
        SELECT *
        FROM core.v_sector_exposure
        WHERE account_code = %s
        ORDER BY sector_weight_pct DESC;
        """
        return self._fetch_all(sql, (account_code,))

    def get_sector_for_symbol(self, symbol: str) -> Optional[str]:
        """取股票所属行业。"""
        sql = """
        SELECT sector FROM core.instruments WHERE symbol = %s LIMIT 1;
        """
        row = self._fetch_one(sql, (normalize_db_symbol(symbol),))
        return row["sector"] if row else None

    def get_sector_weight(self, account_code: str, sector: str) -> float:
        """取账户在指定行业的暴露权重。"""
        sql = """
        SELECT sector_weight_pct
        FROM core.v_sector_exposure
        WHERE account_code = %s AND sector = %s
        LIMIT 1;
        """
        row = self._fetch_one(sql, (account_code, sector))
        return float(row["sector_weight_pct"]) if row else 0.0

    def get_symbol_weight(self, account_code: str, symbol: str) -> float:
        """取账户指定股票的权重。"""
        symbol = normalize_db_symbol(symbol)
        sql = """
        SELECT weight
        FROM core.v_latest_positions
        WHERE account_code = %s AND symbol = %s
        LIMIT 1;
        """
        row = self._fetch_one(sql, (account_code, symbol))
        return float(row["weight"]) if row and row.get("weight") is not None else 0.0


class ResearchV2Repository(BaseRepository):
    """V2 扩展：研究层新增读取方法。"""

    def _get_latest_model_prediction_for_account_scope(
        self,
        symbol: str,
        *,
        account_id: Optional[int],
        prediction_date: Optional[str],
        horizon: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        clauses = ["symbol = %s"]
        params: List[Any] = [symbol]

        if account_id is None:
            clauses.append("account_id IS NULL")
        else:
            clauses.append("account_id = %s")
            params.append(account_id)

        if prediction_date is not None:
            clauses.append("prediction_date <= %s")
            params.append(prediction_date)

        if horizon is not None:
            clauses.append("horizon = %s")
            params.append(horizon)

        sql = f"""
        SELECT *
        FROM research.model_predictions
        WHERE {' AND '.join(clauses)}
        ORDER BY prediction_date DESC, created_at DESC
        LIMIT 1;
        """
        return self._fetch_one(sql, tuple(params))

    def get_latest_model_prediction(
        self,
        symbol: str,
        account_id: Optional[int] = None,
        prediction_date: Optional[str] = None,
        horizon: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """取最新 ML 模型预测，优先账户级，缺失时回退到全局(account_id IS NULL)。"""
        symbol = normalize_db_symbol(symbol)
        if account_id is not None:
            scoped = self._get_latest_model_prediction_for_account_scope(
                symbol,
                account_id=account_id,
                prediction_date=prediction_date,
                horizon=horizon,
            )
            if scoped is not None:
                return scoped

        return self._get_latest_model_prediction_for_account_scope(
            symbol,
            account_id=None,
            prediction_date=prediction_date,
            horizon=horizon,
        )
