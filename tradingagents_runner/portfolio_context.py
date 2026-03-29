"""
Portfolio Context Builder - V2 语义层

职责：把原始事实快照整理成决策可读对象，不产生 final_action。

调用路径：
  portfolio_snapshot.py → build_snapshot() [原始事实]
  ↓
  portfolio_context.py → build_context() [决策语义]
  ↓
  decision_policy.py → decide() [唯一决策出口]

V1 兼容性：
  build_portfolio_context() 保留，供 V1 模式（不传 account_code）降级使用。
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_repo_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(Path(__file__).parent))


def build_context(
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """
    把 portfolio_snapshot 的原始事实整理成决策语义对象。

    参数
    ----
    snapshot : dict
        build_snapshot() 的输出

    返回
    ----
    dict（决策语义对象，供 decision_policy.py 使用）
        - account_id / account_code / account_name
        - balance: { total_equity, portfolio_cash, available_cash, nav, as_of_date }
        - constraints: { max_symbol_weight, max_sector_weight, min_cash_ratio, ... }
        - position: { is_held, qty, weight, avg_cost, last_price, unrealized_pnl, pnl_pct }
        - holding: { count, symbols, sectors }
        - sector_exposure: [{ sector, weight, holding_symbols }, ...]
        - cash_ratio / market_weight
        - is_core_holding / watchlist_tag / watchlist_priority
        - data_completeness: { has_balance, has_bar, has_factors, review_required }
        - is_sector_concentrated / is_symbol_overweight
        - symbol / sector / trade_date
    """
    balance = snapshot.get("balance") or {}
    constraints = snapshot.get("constraints") or {}
    positions = snapshot.get("positions") or []
    current_pos = snapshot.get("current_position")
    sector_exp = snapshot.get("sector_exposure") or []
    watchlist = snapshot.get("watchlist") or {}
    watchlist_members = snapshot.get("watchlist_members") or []
    watchlist_symbols = snapshot.get("watchlist_symbols") or []
    data_comp = snapshot.get("data_completeness") or {}
    symbol = snapshot.get("symbol", "")
    trade_date = snapshot.get("trade_date")
    account = snapshot.get("account") or {}

    account_id = snapshot.get("account_id")
    account_code = account.get("account_code") or ""
    account_name = account.get("account_name") or ""

    # ── 基础数值 ───────────────────────────────────────────────
    total_equity = float(balance.get("total_equity") or 0)
    portfolio_cash = float(balance.get("available_cash") or 0)
    total_market_value = float(balance.get("market_value") or 0)
    nav = float(balance.get("nav") or 1.0)
    cash_ratio = (portfolio_cash / total_equity) if total_equity > 0 else 0.0
    market_weight = 1.0 - cash_ratio

    # ── 当前持仓 ────────────────────────────────────────────────
    is_held = current_pos is not None and float(current_pos.get("position_qty") or 0) > 0
    current_weight = (
        float(current_pos.get("weight") or 0) if current_pos else 0.0
    )
    # weight 列是百分比数值（0.15 = 15%），不需要再除100
    current_weight_pct = current_weight * 100 if current_weight <= 1 else current_weight
    unrealized_pnl = float(current_pos.get("unrealized_pnl") or 0) if current_pos else 0.0
    avg_cost = float(current_pos.get("avg_cost") or 0) if current_pos else 0.0
    last_price = float(current_pos.get("last_price") or 0) if current_pos else 0.0
    pnl_pct = (
        round((last_price - avg_cost) / avg_cost * 100, 4)
        if avg_cost > 0 and last_price > 0 else 0.0
    )

    # ── 持仓汇总 ────────────────────────────────────────────────
    holding_symbols = [p["symbol"] for p in positions if float(p.get("position_qty") or 0) > 0]
    holding_count = len(holding_symbols)
    holding_sectors = {p.get("sector") for p in positions if p.get("sector")}
    holding_industries = {p.get("industry") for p in positions if p.get("industry")}

    # ── 当前股票所属行业 ────────────────────────────────────────
    if current_pos:
        current_sector = current_pos.get("sector")
        current_industry = current_pos.get("industry")
    else:
        # 从持仓表反查
        current_sector = None
        current_industry = None
        for p in positions:
            if p["symbol"] == symbol:
                current_sector = p.get("sector")
                current_industry = p.get("industry")
                break

    # ── 同板块/行业持仓 ─────────────────────────────────────────
    same_sector_symbols = [
        p["symbol"] for p in positions
        if p.get("sector") == current_sector and p["symbol"] != symbol
    ]
    same_industry_symbols = [
        p["symbol"] for p in positions
        if p.get("industry") == current_industry and p["symbol"] != symbol
    ]

    # ── 行业暴露 ────────────────────────────────────────────────
    sector_allocation: Dict[str, float] = {}
    for s in sector_exp:
        sector_allocation[s["sector"]] = float(s["sector_weight_pct"])

    # ── 约束命中检查（硬约束）────────────────────────────────────
    max_symbol_w = float(constraints.get("max_symbol_weight") or 0.20)
    max_sector_w = float(constraints.get("max_sector_weight") or 0.35)
    min_cash_r = float(constraints.get("min_cash_ratio") or 0.05)

    is_symbol_overweight = current_weight_pct >= (max_symbol_w * 100)
    current_sector_w = sector_allocation.get(current_sector or "", 0.0) if current_sector else 0.0
    is_sector_concentrated = current_sector_w >= (max_sector_w * 100)
    is_cash_insufficient = cash_ratio < min_cash_r

    # ── 股票池来源 ──────────────────────────────────────────────
    watchlist_tag = None
    watchlist_priority = None
    is_core_holding = False

    for m in watchlist_members:
        if m["symbol"] == symbol:
            watchlist_tag = m.get("tag")
            watchlist_priority = m.get("priority")
            is_core_holding = (
                watchlist.get("watchlist_code") == "core_holdings_focus"
                and watchlist_tag in ("holding", "core")
            )
            break

    # ── 风险标记 ────────────────────────────────────────────────
    hard_constraints_hit = []
    if is_symbol_overweight:
        hard_constraints_hit.append("symbol_overweight")
    if is_sector_concentrated:
        hard_constraints_hit.append("sector_concentrated")
    if is_cash_insufficient:
        hard_constraints_hit.append("cash_insufficient")

    soft_constraints_hit = []
    if data_comp.get("review_required"):
        soft_constraints_hit.append("data_incomplete")
    if data_comp.get("has_factors") is False:
        soft_constraints_hit.append("no_factors")
    if data_comp.get("has_bar") is False:
        soft_constraints_hit.append("no_bar")
    if data_comp.get("has_prediction"):
        soft_constraints_hit.append("has_ml_prediction")

    return {
        # 账户
        "account_id": account_id,
        "account_code": account_code,
        "account_name": account_name,
        # 资金
        "total_equity": total_equity,
        "portfolio_cash": portfolio_cash,
        "total_market_value": total_market_value,
        "nav": nav,
        "cash_ratio": round(cash_ratio * 100, 4),
        "cash_ratio_pct": round(cash_ratio * 100, 4),
        "market_weight_pct": round(market_weight * 100, 4),
        "as_of_date": str(balance.get("as_of_date")) if balance.get("as_of_date") else None,
        # 约束
        "constraints": {
            "max_symbol_weight_pct": round(max_symbol_w * 100, 4),
            "max_sector_weight_pct": round(max_sector_w * 100, 4),
            "min_cash_ratio_pct": round(min_cash_r * 100, 4),
            "allow_add_on_profit_only": constraints.get("allow_add_on_profit_only", False),
            "allow_add_on_loss": constraints.get("allow_add_on_loss", False),
            "review_on_missing_balance": constraints.get("review_on_missing_balance", True),
        },
        # 当前持仓状态
        "is_held": is_held,
        "current_position": current_pos,
        "position_qty": float(current_pos.get("position_qty") or 0) if current_pos else 0.0,
        "current_weight_pct": round(current_weight_pct, 4),
        "current_weight": round(current_weight, 8),
        "avg_cost": avg_cost,
        "last_price": last_price,
        "unrealized_pnl": unrealized_pnl,
        "pnl_pct": pnl_pct,
        "current_sector": current_sector,
        "current_industry": current_industry,
        # 持仓汇总
        "holding_symbols": holding_symbols,
        "holding_count": holding_count,
        "holding_sectors": list(holding_sectors),
        "holding_industries": list(holding_industries),
        # 同板块/行业
        "same_sector_symbols": same_sector_symbols,
        "same_industry_symbols": same_industry_symbols,
        "same_sector_count": len(same_sector_symbols),
        "same_industry_count": len(same_industry_symbols),
        # 行业暴露
        "sector_allocation": sector_allocation,
        "current_sector_weight_pct": round(current_sector_w, 4),
        # 硬约束命中
        "hard_constraints_hit": hard_constraints_hit,
        "is_symbol_overweight": is_symbol_overweight,
        "is_sector_concentrated": is_sector_concentrated,
        "is_cash_insufficient": is_cash_insufficient,
        # 软约束命中
        "soft_constraints_hit": soft_constraints_hit,
        # 股票池来源
        "watchlist_code": watchlist.get("watchlist_code"),
        "watchlist_name": watchlist.get("name"),
        "watchlist_tag": watchlist_tag,
        "watchlist_priority": watchlist_priority,
        "is_core_holding": is_core_holding,
        "watchlist_symbols": watchlist_symbols,
        # 数据完整性
        "data_completeness": data_comp,
        "review_required": bool(data_comp.get("review_required")),
        # 分析标的
        "symbol": symbol,
        "trade_date": trade_date,
    }


# ─────────────────────────────────────────────────────────────────────────────
# V1 兼容函数（不推荐新代码使用）
# ─────────────────────────────────────────────────────────────────────────────

def build_portfolio_context(
    account_code: str,
    symbol: str,
    trade_date: Optional[str] = None,
    watchlist_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    V1 兼容接口，内部调用 build_snapshot + build_context。
    保留向后兼容，不产生 final_action。
    """
    from portfolio_snapshot import build_snapshot

    snapshot = build_snapshot(
        account_code=account_code,
        symbol=symbol,
        trade_date=trade_date,
        watchlist_code=watchlist_code,
    )
    return build_context(snapshot)
