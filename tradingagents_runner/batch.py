"""
批量股票扫描
用法：
    from batch import scan
    results = scan(["002173.SZ", "600519.SS", "NVDA"], dates=["2026-03-27"])
    for r in results:
        print(r["ticker"], r["decision"])
"""
import concurrent.futures
from datetime import date, timedelta
from pathlib import Path
from runner import analyze, _normalize_decision


def scan(
    tickers: list,
    dates: list = None,
    max_workers: int = 3,
    result_dir: str = None,
) -> list:
    """
    批量扫描多只股票。

    参数:
        tickers: 股票代码列表
        dates: 分析日期列表，默认 [今天]
        max_workers: 并发数（避免 API 限速）
        result_dir: 结果保存目录

    返回:
        list[dict]，每个元素同 runner.analyze() 的返回值
    """
    if dates is None:
        dates = [date.today().strftime("%Y-%m-%d")]

    tasks = [(t, d) for t in tickers for d in dates]

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(analyze, t, d, None, True, result_dir): (t, d)
            for t, d in tasks
        }
        for future in concurrent.futures.as_completed(futures):
            ticker, d = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append({
                    "ticker": ticker,
                    "trade_date": d,
                    "decision": "ERROR",
                    "error": str(e),
                })

    return results


def scan_comparison(
    tickers: list,
    trade_date: str = None,
) -> dict:
    """
    横向对比多只股票，输出简洁对比表。

    返回:
        dict {
            "date": str,
            "stocks": list[{
                "ticker": str,
                "decision": str,
                "signal_strength": str,
            }],
            "summary": str,
        }
    """
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    results = scan(tickers, [trade_date], max_workers=2)

    stocks = []
    buy_count = sell_count = hold_count = 0

    for r in results:
        dec = r.get("decision", "HOLD")
        if dec == "BUY":
            buy_count += 1
        elif dec == "SELL":
            sell_count += 1
        else:
            hold_count += 1

        stocks.append({
            "ticker": r["ticker"],
            "decision": dec,
            "decision_score": r.get("decision_score", ""),
        })

    # 按 BUY > SELL > HOLD 排序
    priority = {"BUY": 0, "SELL": 1, "HOLD": 2, "ERROR": 3}
    stocks.sort(key=lambda x: priority.get(x["decision"], 3))

    summary = (
        f"共 {len(stocks)} 只股票 | "
        f"🟢 BUY: {buy_count} | "
        f"🔴 SELL: {sell_count} | "
        f"🟡 HOLD: {hold_count}"
    )

    return {
        "date": trade_date,
        "stocks": stocks,
        "summary": summary,
    }


def print_comparison(comp: dict):
    """打印对比结果"""
    print(f"📅 {comp['date']}")
    print(comp["summary"])
    print("──" * 30)
    print(f"{'代码':<15} {'决策':<8} {'原始信号'}")
    print("──" * 30)
    for s in comp["stocks"]:
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(s["decision"], "⚪")
        print(f"{s['ticker']:<15} {emoji} {s['decision']:<6} {s.get('decision_score', '')}")
    print()


if __name__ == "__main__":
    # 示例：扫描A股医疗板块
    demo = scan_comparison(
        ["002173.SZ", "300003.SZ", "300015.SZ"],
        "2026-03-27"
    )
    print_comparison(demo)
