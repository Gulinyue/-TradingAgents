"""
Portfolio Snapshot - V2 数据层

职责：只做"取数与聚合"，输出原始事实快照，不做策略判断。

调用路径：
  portfolio_snapshot.py → repositories.AccountSnapshotRepository
                            repositories.MarketRepository
                            repositories.ResearchV2Repository
  ↓
  portfolio_context.py → 组装决策语义对象
  ↓
  decision_policy.py → 唯一决策出口
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_repo_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(Path(__file__).parent))

from repositories import (
    AccountSnapshotRepository,
    AccountRepository,
    WatchlistRepository,
    MarketRepository,
    ResearchV2Repository,
    normalize_db_symbol,
)


def build_snapshot(
    account_code: str,
    symbol: str,
    trade_date: Optional[str] = None,
    watchlist_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    构建原始事实快照，供后续决策层使用。

    参数
    ----
    account_code : str
        账户代码
    symbol : str
        分析标的（.SH/.SZ/.SS 均接受）
    trade_date : str, optional
        交易日期
    watchlist_code : str, optional
        指定股票池

    返回
    ----
    dict（原始事实，不含策略判断）
        - account: 账户基本信息
        - balance: 最新资金余额快照
        - constraints: 账户约束配置
        - positions: 全部持仓列表
        - current_position: 当前股持仓（如有）
        - sector_exposure: 行业暴露列表
        - watchlist: 股票池（如有）
        - watchlist_members: 股票池成员
        - latest_bar: 最新行情（如有）
        - latest_factors: 最新因子（如有）
        - latest_prediction: 最新 ML 预测（如有）
        - data_completeness: 数据完整性标记
        - symbol: 规范化的标的代码
    """
    symbol = normalize_db_symbol(symbol)

    snapshot_repo = AccountSnapshotRepository()
    market_repo = MarketRepository()
    watchlist_repo = WatchlistRepository()
    research_repo = ResearchV2Repository()

    # ── 账户基本信息 ────────────────────────────────────────────
    account_repo = AccountRepository()
    account = account_repo.get_account_by_code(account_code)
    account_id = account["account_id"] if account else None

    # ── 资金余额 ────────────────────────────────────────────────
    balance = snapshot_repo.get_latest_account_balance(account_code)

    # ── 约束配置 ────────────────────────────────────────────────
    constraints = snapshot_repo.get_account_constraints(account_code)
    # 默认值兜底
    constraints = constraints or {
        "max_symbol_weight": 0.20,
        "max_sector_weight": 0.35,
        "min_cash_ratio": 0.05,
        "allow_add_on_profit_only": False,
        "allow_add_on_loss": False,
        "review_on_missing_balance": True,
    }

    # ── 全部持仓 ────────────────────────────────────────────────
    positions = snapshot_repo._fetch_all("""
        SELECT vp.*
        FROM core.v_latest_positions vp
        JOIN core.accounts a ON a.account_id = vp.account_id
        WHERE a.account_code = %s
        ORDER BY vp.market_value DESC NULLS LAST, vp.symbol ASC;
    """, (account_code,))

    # ── 当前股持仓 ────────────────────────────────────────────
    current_position = snapshot_repo._fetch_one("""
        SELECT vp.*
        FROM core.v_latest_positions vp
        JOIN core.accounts a ON a.account_id = vp.account_id
        WHERE a.account_code = %s AND vp.symbol = %s;
    """, (account_code, symbol))

    # ── 行业暴露 ────────────────────────────────────────────────
    sector_exposure = snapshot_repo.get_sector_exposure(account_code)

    # ── 股票池 ─────────────────────────────────────────────────
    watchlist = None
    watchlist_members: List[Dict[str, Any]] = []
    watchlist_symbols: List[str] = []

    if watchlist_code:
        watchlist = watchlist_repo.get_watchlist_by_code(watchlist_code)
        members = watchlist_repo.get_watchlist_members(watchlist_code)
        watchlist_members = members
        watchlist_symbols = [m["symbol"] for m in members]

    # ── 最新行情 ───────────────────────────────────────────────
    latest_bar = market_repo.get_latest_bar(symbol)
    latest_factors = market_repo.get_latest_factors(symbol, trade_date)

    # ── 最新 ML 预测 ─────────────────────────────────────────
    latest_prediction = research_repo.get_latest_model_prediction(symbol, account_id)

    # ── 数据完整性标记 ────────────────────────────────────────
    bar_count = market_repo.get_bar_count(symbol)
    data_completeness = {
        "has_balance": balance is not None,
        "has_bar": latest_bar is not None,
        "bar_count": bar_count,
        "has_enough_bars": bar_count >= 20,       # 20条以上才能支撑基础技术指标
        "has_factors": len(latest_factors) > 0,
        "has_prediction": latest_prediction is not None,
        "has_constraints": constraints.get("max_symbol_weight", 0) > 0,
        "review_required": (
            not balance and constraints.get("review_on_missing_balance", True)
        ),
    }

    return {
        "account": account,
        "account_id": account_id,
        "balance": balance,
        "constraints": constraints,
        "positions": positions,
        "current_position": current_position,
        "sector_exposure": sector_exposure,
        "watchlist": watchlist,
        "watchlist_members": watchlist_members,
        "watchlist_symbols": watchlist_symbols,
        "latest_bar": latest_bar,
        "bar_count": bar_count,
        "latest_factors": latest_factors,
        "latest_prediction": latest_prediction,
        "data_completeness": data_completeness,
        "symbol": symbol,
        "trade_date": trade_date,
        "watchlist_code": watchlist_code,
    }
