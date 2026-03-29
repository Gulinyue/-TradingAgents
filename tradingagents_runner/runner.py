"""
TradingAgents 轻量封装 - 单股分析入口
用法：
    from runner import analyze
    result = analyze("002173.SZ", "2026-03-27")
    print(result["decision"])   # BUY / HOLD / SELL
    print(result["summary"])    # 中文摘要
"""
import os
import json
from datetime import datetime, date
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (set by ENV_FILE_PATH or default to script dir)
env_path = os.environ.get("ENV_FILE_PATH")
if env_path:
    load_dotenv(env_path)
else:
    # Default: .env next to this script
    load_dotenv(Path(__file__).parent.parent / ".env")


def get_default_config():
    """返回默认配置，可被覆盖"""
    from tradingagents.default_config import DEFAULT_CONFIG
    cfg = DEFAULT_CONFIG.copy()
    cfg["llm_provider"] = "anthropic"
    cfg["backend_url"] = "https://api.minimaxi.com/anthropic"
    cfg["deep_think_llm"] = "MiniMax-M2.7"
    cfg["quick_think_llm"] = "MiniMax-M2.7"
    cfg["max_debate_rounds"] = 1
    cfg["max_risk_discuss_rounds"] = 1
    return cfg


def analyze(
    ticker: str,
    trade_date: str = None,
    config: dict = None,
    save_result: bool = True,
    result_dir: str = None,
) -> dict:
    """
    对单只股票跑完整多 Agent 分析。

    参数:
        ticker: 股票代码，如 "002173.SZ"、"NVDA"
        trade_date: 分析日期，格式 "YYYY-MM-DD"，默认今天
        config: 可选，覆盖默认 LLM 配置
        save_result: 是否保存原始报告到 results/
        result_dir: 结果保存目录

    返回:
        dict {
            "ticker": str,
            "trade_date": str,
            "decision": str,        # BUY / HOLD / SELL
            "decision_score": str,  # 原始信号词
            "technical_report": str, # 技术面摘要
            "fundamental_report": str,# 基本面摘要
            "news_events": list,    # [{date, title, impact}]
            "sentiment": str,        # 舆情评价
            "risk_factors": list,    # 主要风险
            "raw_full_report": str,  # 完整原始报告
            "analyst_signals": dict, # 各 Agent 结论
        }
    """
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    if config is None:
        config = get_default_config()

    if result_dir is None:
        result_dir = Path(__file__).parent.parent / "results"
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    # 导入在函数内，避免全局 import 慢
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    # 加载图谱
    ta = TradingAgentsGraph(debug=False, config=config)

    # 执行分析
    _, decision_raw = ta.propagate(ticker, trade_date)
    decision = _normalize_decision(decision_raw)

    # 读取保存的完整报告
    report_file = (
        result_dir
        / ticker.replace(".", "_")
        / "TradingAgentsStrategy_logs"
        / f"full_states_log_{trade_date}.json"
    )

    analyst_signals = {}
    news_events = []
    risk_factors = []
    technical = ""
    fundamental = ""

    if report_file.exists():
        try:
            full = json.loads(report_file.read_text(encoding="utf-8"))
            ts_data = full.get(trade_date, {})
            analyst_signals = {
                "market": ts_data.get("market_report", "N/A")[:500],
                "sentiment": ts_data.get("sentiment_report", "N/A")[:500],
                "news": ts_data.get("news_report", "N/A")[:500],
                "fundamentals": ts_data.get("fundamentals_report", "N/A")[:500],
                "trader_decision": ts_data.get("trader_investment_decision", "N/A")[:500],
                "final_plan": ts_data.get("investment_plan", "N/A")[:500],
            }
        except Exception:
            pass

    # 读取原始 stdout 日志提取更多信息
    stdout_file = Path("/tmp/ta_v2_stdout.txt")
    if stdout_file.exists():
        raw_text = stdout_file.read_text(encoding="utf-8", errors="ignore")
    else:
        raw_text = ""

    result = {
        "ticker": ticker,
        "trade_date": trade_date,
        "decision": decision,
        "decision_score": str(decision_raw).strip(),
        "analyst_signals": analyst_signals,
        "news_events": news_events,
        "risk_factors": risk_factors,
        "technical_report": technical,
        "fundamental_report": fundamental,
        "raw_full_report": raw_text,
        "generated_at": datetime.now().isoformat(),
    }

    # 保存结果
    if save_result:
        out_file = result_dir / f"{ticker.replace('.', '_')}_{trade_date}.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    return result


def _normalize_decision(raw) -> str:
    """将原始决策词归一化为 BUY / HOLD / SELL"""
    s = str(raw).upper().strip()
    if "BUY" in s or "买入" in s or "增持" in s:
        return "BUY"
    elif "SELL" in s or "卖出" in s or "减持" in s or "减仓" in s:
        return "SELL"
    elif "HOLD" in s or "持有" in s or "观望" in s:
        return "HOLD"
    return "HOLD"  # 默认持有


def quick_summary(result: dict) -> str:
    """将分析结果格式化为易读摘要"""
    lines = [
        f"📊 {result['ticker']} | {result['trade_date']}",
        f"──" * 20,
        f"🎯 最终决策：{result['decision']}",
        f"📋 各 Agent 信号：",
    ]
    signals = result.get("analyst_signals", {})
    if signals:
        for name, content in signals.items():
            snippet = content[:100].replace("\n", " ").strip() if content else "N/A"
            lines.append(f"  · {name}: {snippet}...")

    return "\n".join(lines)
