"""
TradingAgents 分析引擎 - 数据库集成版

V1 闭环：数据库读股票池 → 读账户持仓 → 生成 context →
调用 TradingAgents → 组合修正 → 写回 analysis_runs / analysis_decisions
"""
import json
import sys
import time
import traceback
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

# Resolve imports
_repo_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(Path(__file__).parent))

# .env loading (shared with db.py, idempotent)
import os as _os
from dotenv import load_dotenv as _load_dotenv

_env_path = _os.environ.get("ENV_FILE_PATH")
if _env_path:
    _load_dotenv(_env_path)
else:
    _load_dotenv(Path(__file__).parent.parent / ".env")


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

def get_default_config() -> Dict[str, Any]:
    from tradingagents.default_config import DEFAULT_CONFIG

    cfg = DEFAULT_CONFIG.copy()
    cfg["llm_provider"] = "anthropic"
    cfg["backend_url"] = "https://api.minimaxi.com/anthropic"
    cfg["deep_think_llm"] = "MiniMax-M2.7"
    cfg["quick_think_llm"] = "MiniMax-M2.7"
    cfg["max_debate_rounds"] = 1
    cfg["max_risk_discuss_rounds"] = 1

    # 数据源：Tushare 优先（A 股），yfinance 作为全局兜底
    # yfinance 对 A 股失效时会自然失败，不阻断；其他场景有 fallback
    cfg["data_vendors"] = {
        "core_stock_apis": "tushare,yfinance",
        "fundamental_data": "tushare,alpha_vantage",
        "news_data": "tushare,akshare,yfinance",
    }

    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Decision normalization
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_decision(raw) -> str:
    """将原始决策词归一化为 ENTER/ADD/HOLD/TRIM/EXIT/AVOID/REVIEW"""
    s = str(raw).upper().strip()
    if "BUY" in s or "买入" in s or "增持" in s or "ENTER" in s:
        return "ENTER"
    elif "ADD" in s or "加仓" in s:
        return "ADD"
    elif "SELL" in s or "卖出" in s or "减持" in s:
        return "SELL"
    elif "TRIM" in s or "减仓" in s:
        return "TRIM"
    elif "EXIT" in s or "清仓" in s:
        return "EXIT"
    elif "AVOID" in s or "回避" in s:
        return "AVOID"
    elif "HOLD" in s or "持有" in s or "观望" in s or "REVIEW" in s:
        return "REVIEW"
    return "REVIEW"  # 默认 REVIEW


def _parse_ta_result(ticker: str, trade_date: str) -> Dict[str, Any]:
    """
    从 TradingAgents 输出的 JSON 文件中解析结构化结果。
    优先读 results/ 下的结构化文件，兜底读旧格式。
    """
    result_dir = Path(__file__).parent.parent / "results"
    out_file = result_dir / f"{ticker.replace('.', '_')}_{trade_date}.json"

    if out_file.exists():
        try:
            return json.loads(out_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 兜底：读 TradingAgents 内部日志
    log_file = (
        result_dir
        / ticker.replace(".", "_")
        / "TradingAgentsStrategy_logs"
        / f"full_states_log_{trade_date}.json"
    )
    if log_file.exists():
        try:
            full = json.loads(log_file.read_text(encoding="utf-8"))
            ts_data = full.get(trade_date, {})
            raw_decision = ts_data.get("trader_investment_decision", "REVIEW")
            return {
                "decision": _normalize_decision(raw_decision),
                "decision_score": str(raw_decision).strip(),
                "technical_report": ts_data.get("technical_report", ""),
                "fundamental_report": ts_data.get("fundamentals_report", ""),
                "news_events": ts_data.get("news_events", []),
                "sentiment": ts_data.get("sentiment_report", ""),
                "risk_factors": ts_data.get("risk_factors", []),
                "raw_full_report": str(ts_data),
                "analyst_signals": {
                    "market": ts_data.get("market_report", ""),
                    "sentiment": ts_data.get("sentiment_report", ""),
                    "news": ts_data.get("news_report", ""),
                    "fundamentals": ts_data.get("fundamentals_report", ""),
                },
            }
        except Exception:
            pass

    return {
        "decision": "REVIEW",
        "decision_score": "UNKNOWN",
        "technical_report": "",
        "fundamental_report": "",
        "news_events": [],
        "sentiment": "",
        "risk_factors": [],
        "analyst_signals": {},
        "raw_full_report": "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main analyze function
# ─────────────────────────────────────────────────────────────────────────────

def analyze(
    ticker: str,
    trade_date: Optional[str] = None,
    *,
    config: Optional[Dict[str, Any]] = None,
    save_result: bool = True,
    result_dir: Optional[str] = None,
    # ── DB 集成参数 ───────────────────────────────────────────────
    account_code: Optional[str] = None,
    watchlist_code: Optional[str] = None,
    write_db: bool = True,
    save_local_artifacts: bool = True,
) -> dict:
    """
    对单只股票跑完整多 Agent 分析，可选读写数据库。

    参数
    ----
    ticker : str
        股票代码，如 "600519.SH"（.SH/.SZ/.SS 均支持）
    trade_date : str, optional
        分析日期，默认今天
    config : dict, optional
        覆盖默认 LLM 配置
    save_result : bool
        是否保存原始报告（向后兼容）
    result_dir : str, optional
        结果保存目录
    account_code : str, optional
        账户代码，如 "paper_main"。如不传则跳过 DB 持仓上下文
    watchlist_code : str, optional
        股票池代码，如 "core_holdings_focus"
    write_db : bool
        是否写 analysis_runs / analysis_decisions 到 DB
    save_local_artifacts : bool
        是否写本地 JSON 结果文件

    返回
    ----
    dict {
        "ticker", "trade_date",
        "decision": final_action,          # 经组合修正后的最终结论
        "raw_decision": original_action,  # TA 原始结论
        "confidence", "risk_level",
        "final_summary", "overlay_reason",
        "portfolio_context": {...},        # 组合上下文
        "analysis_run_id": int | None,   # DB run_id
        "ta_result": {...},               # TA 原始输出
    }
    """
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    if config is None:
        config = get_default_config()

    if result_dir is None:
        result_dir = Path(__file__).parent.parent / "results"
    result_dir = Path(result_dir)

    # ── DB 上下文（可选）─────────────────────────────────────────
    portfolio_context: Dict[str, Any] = {}
    research_repo = None
    account_repo = None
    run_id: Optional[int] = None
    account_id: Optional[int] = None

    if account_code and write_db:
        try:
            from repositories import ResearchRepository
            from portfolio_snapshot import build_snapshot
            from portfolio_context import build_context
            from decision_policy import decide

            research_repo = ResearchRepository()

            # 取 account_id
            from repositories import AccountRepository
            account_repo = AccountRepository()
            account = account_repo.get_account_by_code(account_code)
            account_id = account["account_id"] if account else None

            # 取 watchlist_id
            watchlist_id: Optional[int] = None
            if watchlist_code:
                from repositories import WatchlistRepository
                wl = WatchlistRepository().get_watchlist_by_code(watchlist_code)
                watchlist_id = wl["watchlist_id"] if wl else None

            # V2 三阶段链：snapshot → context → decide
            portfolio_snapshot = build_snapshot(
                account_code=account_code,
                symbol=ticker,
                trade_date=trade_date,
                watchlist_code=watchlist_code,
            )
            portfolio_context = build_context(portfolio_snapshot)

            # 写 analysis_run（先占位）
            runtime_meta = {
                "llm_provider": config.get("llm_provider"),
                "model": config.get("deep_think_llm"),
                "account_code": account_code,
                "watchlist_code": watchlist_code,
                "portfolio_snapshot": {
                    "is_held": portfolio_context.get("is_held"),
                    "total_equity": portfolio_context.get("total_equity"),
                    "portfolio_cash": portfolio_context.get("portfolio_cash"),
                    "holding_count": portfolio_context.get("holding_count"),
                    "cash_ratio_pct": portfolio_context.get("cash_ratio_pct"),
                    "sector_allocation": portfolio_context.get("sector_allocation"),
                    "hard_constraints_hit": portfolio_context.get("hard_constraints_hit"),
                    "soft_constraints_hit": portfolio_context.get("soft_constraints_hit"),
                    "is_core_holding": portfolio_context.get("is_core_holding"),
                },
            }

            run_id = research_repo.create_analysis_run(
                run_source="manual",
                triggered_by="runner.analyze",
                account_id=account_id,
                watchlist_id=watchlist_id,
                model_provider=config.get("llm_provider"),
                model_name=config.get("deep_think_llm"),
                model_version="v1",
                symbol_count=1,
                input_params={
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "watchlist_code": watchlist_code,
                },
                runtime_meta=runtime_meta,
            )

        except Exception as e:
            # DB 出错不阻断分析，降级
            write_db = False
            portfolio_context = {}
            err_msg = f"[DB context warning] {e}"

    # ── 调用 TradingAgents ──────────────────────────────────────
    start_ms = int(time.time() * 1000)

    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        ta = TradingAgentsGraph(debug=False, config=config)
        _, decision_raw = ta.propagate(ticker, trade_date)
        raw_action = _normalize_decision(decision_raw)
        ta_elapsed_ms = int(time.time() * 1000) - start_ms

    except Exception as e:
        ta_elapsed_ms = int(time.time() * 1000) - start_ms
        # TA 失败：写 DB 失败记录（如果开了 DB）
        if write_db and research_repo and run_id:
            research_repo.mark_run_failed(
                run_id,
                error_message=f"TradingAgents propagate failed: {e}",
                runtime_ms=ta_elapsed_ms,
                runtime_meta={"traceback": traceback.format_exc()},
            )
        raise

    # ── 解析 TA 原始结果 ────────────────────────────────────────
    ta_result = _parse_ta_result(ticker, trade_date)

    # ── V2 三阶段：组合约束决策 ─────────────────────────────────
    if portfolio_context:
        from decision_policy import decide

        policy_result = decide(
            raw_action=raw_action,
            raw_confidence=ta_result.get("confidence"),
            raw_risk_level=ta_result.get("risk_level"),
            raw_summary=ta_result.get("final_summary", ta_result.get("technical_report", "")),
            raw_decision_json={
                "ta_decision": raw_action,
                "ta_result": ta_result,
            },
            portfolio_ctx=portfolio_context,
        )
        final_action = policy_result["final_action"]
        raw_action_out = policy_result["raw_action"]
        confidence = ta_result.get("confidence")
        risk_level = ta_result.get("risk_level")
        decision_rank_score = policy_result["decision_rank_score"]
        candidate_bucket = policy_result["candidate_bucket"]
        overlay_reasons = policy_result["overlay_reasons"]
        hard_constraints_hit = policy_result["hard_constraints_hit"]
        soft_constraints_hit = policy_result["soft_constraints_hit"]
        rank_reason = policy_result["rank_reason"]
        final_summary = ta_result.get("final_summary", ta_result.get("technical_report", ""))
        decision_json = {
            **policy_result,
            "ta_decision": raw_action,
            "ta_result": ta_result,
            "portfolio_snapshot": {
                "is_held": portfolio_context.get("is_held"),
                "total_equity": portfolio_context.get("total_equity"),
                "portfolio_cash": portfolio_context.get("portfolio_cash"),
                "cash_ratio_pct": portfolio_context.get("cash_ratio_pct"),
                "current_weight_pct": portfolio_context.get("current_weight_pct"),
                "hard_constraints_hit": hard_constraints_hit,
                "soft_constraints_hit": soft_constraints_hit,
                "is_core_holding": portfolio_context.get("is_core_holding"),
            },
        }
    else:
        final_action = raw_action
        raw_action_out = raw_action
        final_summary = ta_result.get("technical_report", ta_result.get("fundamental_report", ""))
        confidence = ta_result.get("confidence")
        risk_level = ta_result.get("risk_level")
        decision_rank_score = None
        candidate_bucket = None
        overlay_reasons = []
        hard_constraints_hit = []
        soft_constraints_hit = []
        rank_reason = ""
        decision_json = {
            "ta_decision": raw_action,
            "ta_result": ta_result,
        }

    # ── 写 DB ─────────────────────────────────────────────────
    if write_db and research_repo and run_id:
        try:
            research_repo.insert_analysis_decision(
                run_id=run_id,
                symbol=ticker,
                account_id=account_id,
                action=final_action,
                confidence=confidence,
                risk_level=risk_level,
                score=decision_rank_score,
                rationale=ta_result.get("fundamental_report", ""),
                summary=final_summary,
                decision_json=decision_json,
            )
            research_repo.mark_run_success(
                run_id,
                runtime_ms=ta_elapsed_ms,
                runtime_meta={
                    "overlay_reasons": overlay_reasons,
                    "hard_constraints_hit": hard_constraints_hit,
                    "soft_constraints_hit": soft_constraints_hit,
                    "candidate_bucket": candidate_bucket,
                    "decision_rank_score": decision_rank_score,
                },
            )
        except Exception as e:
            # DB 写回失败，打印警告但不阻断返回
            print(f"[DB write warning] {e}")

    # ── 保存本地文件（向后兼容）────────────────────────────────
    if save_local_artifacts and save_result:
        result_dir.mkdir(parents=True, exist_ok=True)
        out_file = result_dir / f"{ticker.replace('.', '_')}_{trade_date}.json"
        out_file.write_text(
            json.dumps({
                "ticker": ticker,
                "trade_date": trade_date,
                "account_code": account_code,
                "watchlist_code": watchlist_code,
                "decision": final_action,
                "raw_decision": raw_action_out,
                "confidence": confidence,
                "risk_level": risk_level,
                "final_summary": final_summary,
                "overlay_reasons": overlay_reasons,
                "hard_constraints_hit": hard_constraints_hit,
                "soft_constraints_hit": soft_constraints_hit,
                "decision_rank_score": decision_rank_score,
                "candidate_bucket": candidate_bucket,
                "rank_reason": rank_reason,
                "portfolio_context": portfolio_context,
                "ta_result": ta_result,
                "analysis_run_id": run_id,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "account_code": account_code,
        "watchlist_code": watchlist_code,
        "decision": final_action,
        "raw_decision": raw_action_out,
        "confidence": confidence,
        "risk_level": risk_level,
        "final_summary": final_summary,
        "overlay_reasons": overlay_reasons,
        "hard_constraints_hit": hard_constraints_hit,
        "soft_constraints_hit": soft_constraints_hit,
        "decision_rank_score": decision_rank_score,
        "candidate_bucket": candidate_bucket,
        "rank_reason": rank_reason,
        "portfolio_context": portfolio_context,
        "analysis_run_id": run_id,
        "ta_result": ta_result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Convenience wrappers
# ─────────────────────────────────────────────────────────────────────────────

def analyze_single(
    ticker: str,
    trade_date: Optional[str] = None,
    account_code: str = "paper_main",
    watchlist_code: Optional[str] = None,
    **kwargs,
) -> dict:
    """单股分析快捷入口，指定账户。"""
    return analyze(
        ticker,
        trade_date,
        account_code=account_code,
        watchlist_code=watchlist_code,
        **kwargs,
    )


def quick_summary(result: dict) -> str:
    """将分析结果格式化为易读摘要。"""
    lines = [
        f"📊 {result['ticker']} | {result['trade_date']}",
        f"{'─' * 20}",
        f"🎯 最终决策：{result['decision']}",
        f"   原始信号：{result.get('raw_decision', 'N/A')}",
        f"   候选桶：{result.get('candidate_bucket', 'N/A')}",
    ]
    if result.get("decision_rank_score") is not None:
        lines.append(f"   排序分数：{result['decision_rank_score']:.4f}")
    if result.get("hard_constraints_hit"):
        lines.append(f"   ⚠️ 硬约束：{', '.join(result['hard_constraints_hit'])}")
    if result.get("soft_constraints_hit"):
        lines.append(f"   ⚡ 软约束：{', '.join(result['soft_constraints_hit'])}")
    if result.get("overlay_reasons"):
        lines.append(f"   修正原因：{result['overlay_reasons'][0]}")
    if result.get("confidence"):
        lines.append(f"   置信度：{result['confidence']}")
    if result.get("risk_level"):
        lines.append(f"   风险等级：{result['risk_level']}")
    if result.get("final_summary"):
        lines.append(f"   摘要：{result['final_summary'][:100]}")
    ctx = result.get("portfolio_context", {})
    if ctx:
        lines.append(
            f"   组合：¥{ctx.get('total_equity', 0):,.0f} | "
            f"现金 ¥{ctx.get('portfolio_cash', 0):,.0f} | "
            f"持仓 {ctx.get('holding_count', 0)} 只 | "
            f"is_held={ctx.get('is_held')}"
        )
    if result.get("analysis_run_id"):
        lines.append(f"   DB run_id：{result['analysis_run_id']}")
    return "\n".join(lines)
