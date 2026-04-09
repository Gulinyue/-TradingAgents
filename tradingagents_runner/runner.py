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

# Resolve imports (must come before module imports below)
_repo_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(Path(__file__).parent))

from serialization import deep_serialize, json_dumps_safe
from run_status import evaluate_run_status

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
        "technical_indicators": "yfinance",
        "fundamental_data": "tushare,alpha_vantage",
        "news_data": "tushare,akshare,yfinance",
    }

    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Decision normalization
# ─────────────────────────────────────────────────────────────────────────────

def _deep_float(obj):
    """Recursively convert Decimal → float, leave other types intact. Safe for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _deep_float(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_deep_float(x) for x in obj]
    elif isinstance(obj, float):
        return obj
    elif isinstance(obj, (int, bool)):
        return obj
    elif hasattr(obj, "__float__"):  # Decimal 等
        return float(obj)
    return obj


def _normalize_decision(raw) -> str:
    """将原始决策文本归一化为 ENTER/ADD/HOLD/TRIM/EXIT/AVOID/REVIEW"""
    import re
    s = str(raw)

    # 优先：提取显式评级标签 "Rating: **ACTION**" 或 "FINAL TRANSACTION PROPOSAL: **ACTION**
    rating_match = re.search(r'(?:Rating[:\s]+|FINAL\s+TRANSACTION\s+PROPOSAL[:\s*]+)\*?\*?([A-Z]+)\*?\*?', s, re.IGNORECASE)
    if rating_match:
        action = rating_match.group(1).upper()
        if action in ("ENTER", "BUY"):
            return "ENTER"
        if action == "ADD":
            return "ADD"
        if action in ("HOLD", "NEUTRAL"):
            return "HOLD"
        if action in ("SELL", "REDUCE"):
            return "SELL"
        if action == "TRIM":
            return "TRIM"
        if action in ("EXIT", "LIQUIDATE"):
            return "EXIT"
        if action == "AVOID":
            return "AVOID"
        if action in ("REVIEW", "SCAN"):
            return "REVIEW"

    # 其次：用单词边界匹配（排除被 **markdown** 包裹的误匹配）
    # 清理 markdown bold/italic
    clean = re.sub(r'\*\*(.*?)\*\*', r'\1', s)  # **HOLD** -> HOLD
    clean = re.sub(r'\*(.*?)\*', r'\1', clean)   # *HOLD* -> HOLD
    clean_upper = clean.upper()

    def has_word(patterns):
        """English: word boundary match. Chinese: substring match."""
        for p in patterns:
            if p.isascii():
                if re.search(r'\b' + re.escape(p) + r'\b', clean_upper):
                    return True
            else:
                if p in clean_upper:
                    return True
        return False

    if has_word(["BUY", "买入", "增持", "ENTER"]):
        return "ENTER"
    elif has_word(["ADD", "加仓"]) and "DO NOT ADD" not in clean_upper:
        return "ADD"
    elif has_word(["SELL", "卖出", "减持"]):
        return "SELL"
    elif has_word(["TRIM", "减仓"]):
        return "TRIM"
    elif has_word(["EXIT", "清仓", "平仓"]):
        return "EXIT"
    elif has_word(["AVOID", "回避", "规避"]):
        return "AVOID"
    elif has_word(["HOLD", "持有", "观望"]):
        return "HOLD"
    elif has_word(["REVIEW", "复核", "待定", "SCAN"]):
        return "REVIEW"
    return "REVIEW"  # 默认


def _parse_ta_result(ticker: str, trade_date: str) -> tuple:
    """
    返回 (result_dict, fallback_triggered: bool)
    fallback_triggered=True 表示走了 eval_results fallback 路径。
    """
    """
    从 TradingAgents 输出的 JSON 文件中解析结构化结果。
    优先读 results/ 下的结构化文件，再按以下顺序兜底：
      1. eval_results/{ticker}.{exchange}/TradingAgentsStrategy_logs/full_states_log_{date}.json
      2. results/{ticker_dotted}/TradingAgentsStrategy_logs/full_states_log_{date}.json
    """
    result_dir = Path(__file__).parent.parent / "results"
    out_file = result_dir / f"{ticker.replace('.', '_')}_{trade_date}.json"

    # 优先级1：results/600519_SH_2026-03-29.json（结构化输出）
    if out_file.exists():
        try:
            return json.loads(out_file.read_text(encoding="utf-8")), False
        except Exception:
            pass

    # 优先级2：eval_results/ fallback
    eval_results_dir = Path(__file__).parent.parent / "eval_results"
    log_file_candidates = [
        eval_results_dir / ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{trade_date}.json",
        result_dir / ticker.replace(".", "_") / "TradingAgentsStrategy_logs" / f"full_states_log_{trade_date}.json",
    ]

    for log_file in log_file_candidates:
        if not log_file.exists():
            continue
        try:
            full = json.loads(log_file.read_text(encoding="utf-8"))
            ts_data = full.get(trade_date, {})
            raw_decision = (
                ts_data.get("final_trade_decision")
                or ts_data.get("trader_investment_decision")
                or ts_data.get("judge_decision", "")
            )
            return {
                "decision": _normalize_decision(raw_decision),
                "decision_score": str(raw_decision).strip()[:200],
                "technical_report": ts_data.get("technical_report") or ts_data.get("market_report", ""),
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
            }, True   # fallback triggered
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
    }, True   # fallback triggered（无文件可读）


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
    portfolio_snapshot: Dict[str, Any] = {}
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
    ta_result, parser_fallback_triggered = _parse_ta_result(ticker, trade_date)

    # ── V2 三阶段：组合约束决策 ─────────────────────────────────
    latest_prediction = portfolio_snapshot.get("latest_prediction") if portfolio_snapshot else None
    ml_score = latest_prediction.get("score") if latest_prediction else None
    normalized_ml_score = None
    final_rank_score = decision_rank_score = None
    ranking_blend_applied = False

    if portfolio_context:
        from decision_policy import decide
        from ranking import enrich_with_final_rank_score

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
        ranked_result = enrich_with_final_rank_score({
            "decision_rank_score": decision_rank_score,
            "ml_score": ml_score,
            "latest_prediction": latest_prediction,
        })
        normalized_ml_score = ranked_result.get("normalized_ml_score")
        final_rank_score = ranked_result.get("final_rank_score")
        ranking_blend_applied = ranked_result.get("ranking_blend_applied", False)
        decision_json = {
            **policy_result,
            "ml_score": ml_score,
            "normalized_ml_score": normalized_ml_score,
            "final_rank_score": final_rank_score,
            "ranking_blend_applied": ranking_blend_applied,
            "latest_prediction": latest_prediction,
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
        final_rank_score = None
        normalized_ml_score = None
        ranking_blend_applied = False
        decision_json = {
            "ml_score": ml_score,
            "normalized_ml_score": normalized_ml_score,
            "final_rank_score": final_rank_score,
            "ranking_blend_applied": ranking_blend_applied,
            "latest_prediction": latest_prediction,
            "ta_decision": raw_action,
            "ta_result": ta_result,
        }

    # ── V2 质量评估 ───────────────────────────────────────────
    # data_completeness（来自 portfolio_snapshot）
    snap = portfolio_snapshot if "portfolio_snapshot" in dir() else {}
    dc = (snap.get("data_completeness") or {}) if snap else {}
    bar_count = dc.get("bar_count", 0)

    data_completeness = {
        "has_enough_bars": bar_count >= 60,
        "bar_count": bar_count,
        "has_balance": dc.get("has_balance", False),
        "has_factors": dc.get("has_factors", False),
        "has_prediction": dc.get("has_prediction", False),
        "has_minimum_bars": bar_count >= 20,
        "bar_quality_level": "full" if bar_count >= 120 else ("good" if bar_count >= 60 else ("minimum_only" if bar_count >= 20 else "insufficient")),
    }

    # raw_output_quality（来自 TA 原始输出）
    raw_output_quality = {
        "raw_confidence_present": confidence is not None,
        "raw_risk_present": risk_level is not None,
        "technical_report_nonempty": bool(ta_result.get("technical_report", "").strip()),
        "fundamental_report_nonempty": bool(ta_result.get("fundamental_report", "").strip()),
        "raw_decision_score_known": ta_result.get("decision_score", "") not in ("", "UNKNOWN"),
        "ta_decision_nondefault": raw_action not in ("REVIEW", "UNKNOWN", ""),
    }

    # ── 标准化状态判定 ──────────────────────────────────────────
    status_result = evaluate_run_status(
        data_completeness=data_completeness,
        raw_output_quality=raw_output_quality,
        ta_executed=True,   # 走到这里说明 TA 没抛异常
        db_write_ok=True,   # write_db 失败不影响 status，只打 warning
        parser_fallback_triggered=parser_fallback_triggered,
    )
    run_status = status_result.run_status
    status_reason = status_result.status_reason
    status_tags = status_result.status_tags

    # ── 写 DB ─────────────────────────────────────────────────
    if write_db and research_repo and run_id:
        try:
            # 把质量评估写进 decision_json（deep_serialize 处理 Decimal 等）
            enriched_decision_json = {
                **decision_json,
                "data_completeness": data_completeness,
                "raw_output_quality": raw_output_quality,
                "run_status": run_status,
            }
            enriched_decision_json = deep_serialize(enriched_decision_json)

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
                decision_json=enriched_decision_json,
            )

            runtime_meta_final = deep_serialize({
                "overlay_reasons": overlay_reasons,
                "hard_constraints_hit": hard_constraints_hit,
                "soft_constraints_hit": soft_constraints_hit,
                "candidate_bucket": candidate_bucket,
                "decision_rank_score": decision_rank_score,
                "final_rank_score": final_rank_score,
                "normalized_ml_score": normalized_ml_score,
                "ranking_blend_applied": ranking_blend_applied,
                "data_completeness": data_completeness,
                "raw_output_quality": raw_output_quality,
                "run_status": run_status,
                "status_reason": status_reason,
                "status_tags": status_tags,
            })
            research_repo.update_run_status(
                run_id,
                run_status,
                runtime_ms=ta_elapsed_ms,
                runtime_meta=runtime_meta_final,
            )
        except Exception as e:
            # DB 写回失败，打印警告但不阻断返回
            print(f"[DB write warning] {e}")

    # ── 保存本地文件（向后兼容）────────────────────────────────
    if save_local_artifacts and save_result:
        result_dir.mkdir(parents=True, exist_ok=True)
        out_file = result_dir / f"{ticker.replace('.', '_')}_{trade_date}.json"

        out_file.write_text(
            json_dumps_safe({
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
                "final_rank_score": final_rank_score,
                "ml_score": ml_score,
                "normalized_ml_score": normalized_ml_score,
                "ranking_blend_applied": ranking_blend_applied,
                "latest_prediction": latest_prediction,
                "candidate_bucket": candidate_bucket,
                "rank_reason": rank_reason,
                "portfolio_context": portfolio_context,
                "ta_result": ta_result,
                "analysis_run_id": run_id,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, indent=2),
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
        "final_rank_score": final_rank_score,
        "ml_score": ml_score,
        "normalized_ml_score": normalized_ml_score,
        "ranking_blend_applied": ranking_blend_applied,
        "latest_prediction": latest_prediction,
        "candidate_bucket": candidate_bucket,
        "rank_reason": rank_reason,
        "portfolio_context": portfolio_context,
        "analysis_run_id": run_id,
        "ta_result": ta_result,
        "run_status": run_status,
        "status_reason": status_reason,
        "status_tags": status_tags,
        "parser_fallback_triggered": parser_fallback_triggered,
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
    if result.get("final_rank_score") is not None:
        lines.append(f"   最终排序分：{result['final_rank_score']:.4f}")
    elif result.get("decision_rank_score") is not None:
        lines.append(f"   排序分数：{result['decision_rank_score']:.4f}")
    if result.get("normalized_ml_score") is not None:
        lines.append(f"   ML 分数：{result['normalized_ml_score']:.4f}")
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
