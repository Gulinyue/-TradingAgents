"""
决策变更告警
功能：
  - 检测股票决策从 BUY→HOLD→SELL 的变化
  - 变化时通过飞书通知（或打印）
  - 保存历史决策轨迹
"""
import json
from datetime import date
from pathlib import Path
from runner import analyze

HISTORY_DIR = Path("/home/gulinyue/TradingAgents/results/decision_history")


def load_history(ticker: str) -> dict:
    """读取某只股票的历史决策"""
    f = HISTORY_DIR / f"{ticker.replace('.', '_')}_history.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {}


def save_history(ticker: str, trade_date: str, decision: str, metadata: dict = None):
    """保存决策到历史"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    f = HISTORY_DIR / f"{ticker.replace('.', '_')}_history.json"

    history = load_history(ticker)
    history[trade_date] = {
        "decision": decision,
        "metadata": metadata or {},
    }

    f.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def check_and_alert(ticker: str, trade_date: str = None) -> dict:
    """
    检测决策变化，有变化则告警。

    返回:
        dict {
            "ticker": str,
            "decision": str,
            "changed": bool,
            "previous_decision": str,
            "alert_message": str,
        }
    """
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    # 跑最新分析
    result = analyze(ticker, trade_date, save_result=True)
    new_decision = result["decision"]

    # 查历史
    history = load_history(ticker)
    prev = history.get(trade_date, {}).get("decision")

    if prev is None:
        # 首次分析
        changed = False
        alert_msg = f"🆕 首次分析 | {ticker} | {trade_date} | {new_decision}"
    elif prev != new_decision:
        changed = True
        alert_msg = (
            f"⚠️ 决策变更 | {ticker} | {trade_date}\n"
            f"  之前: {prev} → 现在: {new_decision}"
        )
    else:
        changed = False
        alert_msg = None

    # 保存历史
    save_history(ticker, trade_date, new_decision, result.get("analyst_signals", {}))

    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "decision": new_decision,
        "changed": changed,
        "previous_decision": prev,
        "alert_message": alert_msg,
        "full_result": result,
    }


def scan_and_alert_all(watchlist: list, trade_date: str = None) -> list:
    """
    对整个关注列表跑检测，返回所有告警（仅 changed=True）。
    """
    alerts = []
    for ticker in watchlist:
        try:
            alert = check_and_alert(ticker, trade_date)
            if alert["changed"] and alert["alert_message"]:
                alerts.append(alert)
                # TODO: 这里接飞书/邮件通知
                print(f"🚨 {alert['alert_message']}")
            else:
                print(f"✅ {ticker}: 无变化 ({alert['decision']})")
        except Exception as e:
            print(f"❌ {ticker} 分析失败: {e}")

    return alerts


if __name__ == "__main__":
    # 示例
    alerts = scan_and_alert_all(["002173.SZ"], "2026-03-27")
    if alerts:
        print("\n需要关注的变更：")
        for a in alerts:
            print(a["alert_message"])
    else:
        print("无决策变更")
