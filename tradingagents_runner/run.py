#!/usr/bin/env python3
"""
TradingAgents 分析工具 - 命令行入口

用法:
    # 单股分析（无 DB）
    python run.py analyze 002173.SZ 2026-03-27

    # 单股分析（带 DB 持仓上下文）
    python run.py analyze 002173.SZ 2026-03-27 \
        --account-code paper_main \
        --watchlist-code default_a_share

    # 从 DB 股票池读取列表（覆盖硬编码）
    python run.py batch --from-db-watchlist core_holdings_focus \
        --account-code paper_main \
        --date 2026-03-27

    # 监控模式
    python run.py watch --from-db-watchlist core_holdings_focus \
        --account-code paper_main
"""
import argparse
import sys
from datetime import date
from pathlib import Path

runner_dir = Path(__file__).parent
project_root = runner_dir.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(runner_dir))

from runner import analyze, quick_summary, get_default_config
from batch import scan_comparison, print_comparison
from alerter import scan_and_alert_all


def _resolve_watchlist_symbols(
    watchlist_code: str,
) -> list:
    """从 DB 读取股票池代码列表。"""
    try:
        from repositories import WatchlistRepository
        wr = WatchlistRepository()
        symbols = wr.get_symbols_by_watchlist_code(watchlist_code)
        print(f"[DB] 股票池 '{watchlist_code}' 共 {len(symbols)} 只: {symbols}")
        return symbols
    except Exception as e:
        print(f"[DB warning] 无法从 DB 读取股票池: {e}")
        return []


def cmd_analyze(
    ticker: str,
    trade_date: str = None,
    *,
    account_code: str = None,
    watchlist_code: str = None,
    write_db: bool = True,
    verbose: bool = False,
):
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    print(f"[Runner] ticker={ticker} date={trade_date} "
          f"account={account_code} watchlist={watchlist_code} write_db={write_db}")

    result = analyze(
        ticker,
        trade_date,
        account_code=account_code,
        watchlist_code=watchlist_code,
        write_db=write_db,
        save_local_artifacts=True,
    )

    print("\n" + "=" * 60)
    print(quick_summary(result))
    print("=" * 60)

    if verbose:
        from runner import _parse_ta_result
        ta = result.get("ta_result", {})
        print("\n[TA 原始结果]")
        print(f"  decision: {ta.get('decision', 'N/A')}")
        print(f"  confidence: {ta.get('confidence', 'N/A')}")
        print(f"  risk_level: {ta.get('risk_level', 'N/A')}")
        signals = ta.get("analyst_signals", {})
        if signals:
            for k, v in signals.items():
                snippet = (v or "")[:200].replace("\n", " ").strip()
                print(f"  {k}: {snippet}")

    return result


def cmd_batch(
    ticker_file: str = None,
    trade_date: str = None,
    *,
    from_db_watchlist: str = None,
    account_code: str = None,
    watchlist_code: str = None,
    write_db: bool = True,
    verbose: bool = False,
):
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    # 股票来源优先级：DB 股票池 > 文件 > 硬编码
    if from_db_watchlist:
        tickers = _resolve_watchlist_symbols(from_db_watchlist)
        if not tickers:
            print("[Error] 股票池为空，退出")
            return
    elif ticker_file:
        with open(ticker_file) as f:
            tickers = [
                line.strip() for line in f
                if line.strip() and not line.startswith("#")
            ]
        print(f"[File] 读取 {len(tickers)} 只: {tickers}")
    else:
        print("[Warning] 既无 --from-db-watchlist 也无 --file，使用默认列表")
        tickers = []

    results = []
    for ticker in tickers:
        print(f"\n>>> 分析 {ticker} ({trade_date})")
        try:
            result = analyze(
                ticker,
                trade_date,
                account_code=account_code,
                watchlist_code=watchlist_code or from_db_watchlist,
                write_db=write_db,
                save_local_artifacts=True,
            )
            results.append(result)
            print(quick_summary(result))
        except Exception as e:
            print(f"[Error] {ticker} 分析失败: {e}")
            results.append({"ticker": ticker, "error": str(e)})

    # 汇总
    if results:
        print(f"\n{'=' * 60}")
        print(f"批量分析完成: {len(results)} 只")
        for r in results:
            if "error" in r:
                print(f"  {r['ticker']}: ERROR - {r['error']}")
            else:
                print(f"  {r['ticker']}: {r['decision']} "
                      f"(raw: {r.get('raw_decision','?')}) "
                      f"conf={r.get('confidence','?')} "
                      f"run_id={r.get('analysis_run_id','?')}")

    return results


def cmd_watch(
    trade_date: str = None,
    *,
    from_db_watchlist: str = None,
    account_code: str = None,
    watchlist_code: str = None,
    write_db: bool = True,
):
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    if from_db_watchlist:
        tickers = _resolve_watchlist_symbols(from_db_watchlist)
        watchlist_code = from_db_watchlist
    else:
        print("[Warning] watch 模式需要 --from-db-watchlist")
        return []

    alerts = scan_and_alert_all(tickers, trade_date)
    if not alerts:
        print(f"✅ {trade_date} 无决策变更")
    return alerts


def main():
    parser = argparse.ArgumentParser(
        description="TradingAgents 分析工具 (DB 集成版)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run.py analyze 600036.SH 2026-03-29 \\
      --account-code paper_main \\
      --watchlist-code default_a_share

  python run.py batch --from-db-watchlist core_holdings_focus \\
      --account-code paper_main

  python run.py watch --from-db-watchlist core_holdings_focus \\
      --account-code paper_main
""",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── analyze ──────────────────────────────────────────────────
    p_analyze = sub.add_parser("analyze", help="分析单只股票")
    p_analyze.add_argument("ticker", help="股票代码，如 600036.SH")
    p_analyze.add_argument("date", nargs="?", help="分析日期 YYYY-MM-DD")
    p_analyze.add_argument("--account-code", help="账户代码，如 paper_main")
    p_analyze.add_argument("--watchlist-code", help="股票池代码，如 default_a_share")
    p_analyze.add_argument("--no-db", dest="no_db", action="store_true",
                           help="跳过数据库写入")
    p_analyze.add_argument("-v", "--verbose", action="store_true",
                           help="打印 TA 原始分析详情")

    # ── batch ───────────────────────────────────────────────────
    p_batch = sub.add_parser("batch", help="批量分析")
    p_batch.add_argument("file", nargs="?", help="股票列表文件（每行一个代码）")
    p_batch.add_argument("date", nargs="?", help="分析日期 YYYY-MM-DD")
    p_batch.add_argument("--from-db-watchlist", dest="from_db_watchlist",
                         help="从 DB 股票池读取列表，覆盖 --file")
    p_batch.add_argument("--account-code", help="账户代码")
    p_batch.add_argument("--watchlist-code", help="股票池代码")
    p_batch.add_argument("--no-db", dest="no_db", action="store_true",
                         help="跳过数据库写入")

    # ── watch ───────────────────────────────────────────────────
    p_watch = sub.add_parser("watch", help="监控并告警")
    p_watch.add_argument("date", nargs="?", help="分析日期 YYYY-MM-DD")
    p_watch.add_argument("--from-db-watchlist", dest="from_db_watchlist",
                         required=True, help="从 DB 股票池读取列表")
    p_watch.add_argument("--account-code", help="账户代码")
    p_watch.add_argument("--watchlist-code", help="股票池代码")
    p_watch.add_argument("--no-db", dest="no_db", action="store_true",
                         help="跳过数据库写入")

    args = parser.parse_args()

    write_db = not getattr(args, "no_db", False)

    if args.cmd == "analyze":
        cmd_analyze(
            args.ticker,
            args.date,
            account_code=getattr(args, "account_code", None),
            watchlist_code=getattr(args, "watchlist_code", None),
            write_db=write_db,
            verbose=getattr(args, "verbose", False),
        )
    elif args.cmd == "batch":
        cmd_batch(
            getattr(args, "file", None),
            args.date,
            from_db_watchlist=getattr(args, "from_db_watchlist", None),
            account_code=getattr(args, "account_code", None),
            watchlist_code=getattr(args, "watchlist_code", None),
            write_db=write_db,
        )
    elif args.cmd == "watch":
        cmd_watch(
            args.date,
            from_db_watchlist=getattr(args, "from_db_watchlist", None),
            account_code=getattr(args, "account_code", None),
            watchlist_code=getattr(args, "watchlist_code", None),
            write_db=write_db,
        )


if __name__ == "__main__":
    main()
