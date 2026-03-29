"""
Portfolio Context Builder.

生成组合上下文，供 TradingAgents 分析使用。
也包含组合修正层 apply_portfolio_overlay()。
"""
import sys
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# Resolve imports relative to project root
_repo_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(Path(__file__).parent))

from repositories import (
    AccountRepository,
    WatchlistRepository,
    MarketRepository,
    normalize_db_symbol,
)


def build_portfolio_context(
    account_code: str,
    symbol: str,
    trade_date: Optional[str] = None,
    watchlist_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    生成单股分析的完整组合上下文。

    参数
    ----
    account_code : str
        账户代码，如 "paper_main"
    symbol : str
        分析标的，如 "600519.SH"（.SH/.SZ/.SS 均可，内部统一）
    trade_date : str, optional
        交易日期，格式 YYYY-MM-DD
    watchlist_code : str, optional
        指定股票池代码，若不传则从账户关联的默认池取

    返回
    ----
    dict，包含：
        - account: 账户基本信息
        - balance: 最新资金快照
        - positions: 全部持仓（不含当前股）
        - current_position: 当前股持仓（如有）
        - watchlists: 关联股票池
        - portfolio_summary: 组合级统计
        - is_held: 是否已持仓
        - holding_symbols: 持仓代码列表
        - same_sector_symbols: 同板块持仓代码
        - same_industry_symbols: 同行业持仓代码
        - sector_allocation: 行业分布
        - watchlist_symbols: 股票池代码列表
    """
    ar = AccountRepository()
    wr = WatchlistRepository()

    symbol = normalize_db_symbol(symbol)

    # ── 账户信息 ────────────────────────────────────────────────
    account = ar.get_account_by_code(account_code)
    if account is None:
        raise ValueError(f"Account not found: {account_code}")

    # ── 最新资金快照 ────────────────────────────────────────────
    balance = _get_latest_balance(account_code)

    # ── 当前股持仓 ──────────────────────────────────────────────
    current_position = ar.get_latest_position_for_symbol(account_code, symbol)

    # ── 全部持仓 ────────────────────────────────────────────────
    all_positions = ar.get_latest_positions(account_code)

    # ── 组合统计 ────────────────────────────────────────────────
    holding_symbols = [p["symbol"] for p in all_positions]
    is_held = current_position is not None and current_position.get("position_qty", 0) > 0

    # 持仓市值 / 总权益
    total_market_value = sum(
        float(p.get("market_value") or 0) for p in all_positions
    )
    total_equity = float(balance.get("total_equity", 0)) if balance else 0.0
    portfolio_cash = float(balance.get("available_cash", 0)) if balance else 0.0

    # 同板块 / 同行业持仓
    current_sector = current_position.get("sector") if current_position else None
    current_industry = current_position.get("industry") if current_position else None

    same_sector_symbols = []
    same_industry_symbols = []
    sector_allocation: Dict[str, float] = {}

    for p in all_positions:
        sym = p["symbol"]
        sec = p.get("sector")
        ind = p.get("industry")
        mkt_val = float(p.get("market_value") or 0)
        w = (mkt_val / total_market_value * 100) if total_market_value > 0 else 0.0

        if sec:
            sector_allocation[sec] = sector_allocation.get(sec, 0.0) + w

        if sec and sec == current_sector and sym != symbol:
            same_sector_symbols.append(sym)
        if ind and ind == current_industry and sym != symbol:
            same_industry_symbols.append(sym)

    # ── 股票池 ─────────────────────────────────────────────────
    watchlists: List[Dict[str, Any]] = []
    watchlist_symbols: List[str] = []

    if watchlist_code:
        wl = wr.get_watchlist_by_code(watchlist_code)
        members = wr.get_watchlist_members(watchlist_code)
        if wl:
            watchlists.append(wl)
            watchlist_symbols = [m["symbol"] for m in members]
    else:
        # TODO: 从 account.metadata 读默认 watchlist_code，或遍历所有池
        pass

    # ── 拼接输出 ───────────────────────────────────────────────
    return {
        "account_code": account_code,
        "account_name": account.get("account_name"),
        "account_type": account.get("account_type"),
        "base_currency": account.get("base_currency"),
        # 资金
        "total_equity": total_equity,
        "portfolio_cash": portfolio_cash,
        "total_market_value": total_market_value,
        "nav": float(balance.get("nav", 0)) if balance else None,
        "as_of_date": balance.get("as_of_date") if balance else None,
        # 持仓状态
        "is_held": is_held,
        "current_position": current_position,
        "holding_symbols": holding_symbols,
        "holding_count": len(holding_symbols),
        # 同板块/行业
        "same_sector_symbols": same_sector_symbols,
        "same_industry_symbols": same_industry_symbols,
        "sector_allocation": sector_allocation,
        # 股票池
        "watchlists": watchlists,
        "watchlist_symbols": watchlist_symbols,
        "watchlist_code": watchlist_code,
        # 分析标的
        "symbol": symbol,
        "trade_date": trade_date,
        # 持仓权重（当前股）
        "current_weight": (
            float(current_position["market_value"]) / total_market_value * 100
            if is_held and total_market_value > 0
            else 0.0
        ),
    }


def _get_latest_balance(account_code: str) -> Optional[Dict[str, Any]]:
    """取账户最新资金快照，没有则返回 None。"""
    sys.path.insert(0, str(Path(__file__).parent))
    from db import get_conn
    from psycopg2.extras import RealDictCursor

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    balance_id,
                    account_id,
                    as_of_date,
                    cash,
                    available_cash,
                    frozen_cash,
                    market_value,
                    total_equity,
                    nav,
                    total_units,
                    currency
                FROM core.account_balances
                WHERE account_id = (
                    SELECT account_id FROM core.accounts WHERE account_code = %s
                )
                ORDER BY as_of_date DESC
                LIMIT 1;
                """,
                (account_code,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def apply_portfolio_overlay(
    raw_action: str,
    raw_confidence: Optional[float],
    raw_risk_level: Optional[str],
    raw_summary: str,
    raw_decision_json: Dict[str, Any],
    portfolio_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    组合修正层：根据持仓上下文调整 TradingAgents 原始结论。

    参数
    ----
    raw_action : str
        TradingAgents 原始建议（BUY/SELL/HOLD 等）
    raw_confidence : float, optional
        原始置信度
    raw_risk_level : str, optional
        原始风险等级（LOW/MEDIUM/HIGH/CRITICAL）
    raw_summary : str
        原始摘要文本
    raw_decision_json : dict
        原始决策 JSON（含分析理由等）
    portfolio_context : dict
        build_portfolio_context() 输出

    返回
    ----
    dict，包含修正后的：
        - action, confidence, risk_level, summary
        - overlay_reason: 修正原因
        - final_summary: 最终摘要
    """
    symbol = portfolio_context.get("symbol", "")
    is_held = portfolio_context.get("is_held", False)
    current_qty = (
        float(portfolio_context.get("current_position", {}).get("position_qty") or 0)
        if portfolio_context.get("current_position")
        else 0.0
    )
    same_sector = portfolio_context.get("same_sector_symbols", [])
    same_industry = portfolio_context.get("same_industry_symbols", [])
    sector_alloc: Dict[str, float] = portfolio_context.get("sector_allocation", {})

    # 原始值
    final_action = raw_action
    final_confidence = raw_confidence
    final_risk_level = raw_risk_level
    overlay_reason = ""
    notes: List[str] = []

    # ── 规则 1：已持仓 + 原始偏多 → BUY 转 ADD/HOLD ─────────────
    if is_held and raw_action == "BUY":
        if current_qty > 0:
            final_action = "ADD"
            overlay_reason = "already_held"
            notes.append(f"已在仓 (qty={current_qty:.0f})，BUY 修正为 ADD")

    # ── 规则 2：已持仓 + 原始中性 → 维持 HOLD ──────────────────
    if is_held and raw_action in ("BUY", "HOLD"):
        # HOLD 本身就是最优，继续
        overlay_reason = overlay_reason or ("already_held" if is_held else "")
        if raw_action == "BUY" and current_qty > 0:
            final_action = "ADD"
            notes.append(f"已在仓，BUY → ADD")

    # ── 规则 3：未持仓 + 同板块重仓 → BUY 转 REVIEW ─────────────
    if not is_held and raw_action == "BUY":
        # 行业集中度检查：同行业持仓 > 30%
        industry_symbols = same_industry
        if industry_symbols:
            max_industry_w = max(
                sector_alloc.get(
                    portfolio_context.get("current_position", {}).get("industry") or "", 0.0
                )
                for _ in [1]
            )
            # 简单版：同板块已有票 → REVIEW
            if same_sector:
                final_action = "REVIEW"
                overlay_reason = "sector_concentration"
                notes.append(
                    f"同板块已有持仓 {same_sector}，BUY 降为 REVIEW 谨慎评估"
                )
            elif industry_symbols:
                final_action = "REVIEW"
                overlay_reason = "industry_concentration"
                notes.append(
                    f"同行业已有持仓 {industry_symbols}，BUY 降为 REVIEW"
                )

    # ── 规则 4：已持仓 + 原始偏空 → 维持但降级 ─────────────────
    if is_held and raw_action == "SELL":
        # SELL 在持仓情况下等价于 TRIM 或 EXIT
        if current_qty > 0:
            final_action = "TRIM"
            overlay_reason = "reduce_existing_position"
            notes.append(f"已有仓位，原始 SELL 修正为 TRIM")

    # ── 规则 5：原始建议中性且已有盈利仓位 → 倾向 HOLD ─────────
    if is_held and raw_action == "HOLD":
        unrealized = float(
            portfolio_context.get("current_position", {}).get("unrealized_pnl") or 0
        )
        if unrealized > 0:
            notes.append(f"持仓已盈利 ¥{unrealized:.2f}，维持 HOLD")
        overlay_reason = overlay_reason or ("existing_profitable_holding" if unrealized > 0 else "")

    # ── 规则 6：来自核心持仓关注池 → 摘要注明 ───────────────────
    in_core_pool = (
        symbol in portfolio_context.get("watchlist_symbols", [])
        and portfolio_context.get("watchlist_code") == "core_holdings_focus"
    )
    if in_core_pool:
        notes.append("来自核心持仓关注池")

    # ── 汇总 final_summary ─────────────────────────────────────
    if notes:
        final_summary = raw_summary
        if raw_summary and not raw_summary.endswith("。"):
            raw_summary += "。"
        final_summary = raw_summary + " [组合修正] " + "；".join(notes)
    else:
        final_summary = raw_summary

    # ── 风险等级修正 ────────────────────────────────────────────
    # 已持仓 + 同板块 → 风险升一级
    if is_held and same_sector and final_risk_level in (None, "LOW"):
        final_risk_level = "MEDIUM"
        notes.append("同板块已有持仓，风险升为 MEDIUM")

    return {
        "action": final_action,
        "confidence": final_confidence,
        "risk_level": final_risk_level,
        "overlay_reason": overlay_reason,
        "final_summary": final_summary,
        "decision_json": {
            **raw_decision_json,
            "overlay_applied": True,
            "overlay_rules": notes,
            "portfolio_context": {
                "is_held": is_held,
                "current_qty": current_qty,
                "same_sector_symbols": same_sector,
                "same_industry_symbols": same_industry,
                "watchlist_code": portfolio_context.get("watchlist_code"),
                "watchlist_symbols": portfolio_context.get("watchlist_symbols"),
            },
        },
    }
