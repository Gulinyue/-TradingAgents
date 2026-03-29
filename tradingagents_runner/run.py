#!/usr/bin/env python3
"""
TradingAgents 分析工具 - 命令行入口
用法:
    python run.py 002173.SZ 2026-03-27           # 单股分析
    python run.py --batch stocks.txt             # 批量分析
    python run.py --watch                        # 监控关注列表并告警
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

# 确保 tradingagents 包 + tradingagents_runner 本地模块都可导入
runner_dir = Path(__file__).parent
project_root = runner_dir.parent
sys.path.insert(0, str(project_root))   # 找 tradingagents 包
sys.path.insert(0, str(runner_dir))       # 找 runner.py / batch.py 等本地模块

# 内部模块导入（不用包名前缀）
from runner import analyze, quick_summary, get_default_config
from batch import scan_comparison, print_comparison
from alerter import check_and_alert, scan_and_alert_all


DEFAULT_WATCHLIST = [
    "002173.SZ",
]


def cmd_analyze(ticker: str, trade_date: str = None):
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")
    result = analyze(ticker, trade_date)
    print("\n" + "=" * 50)
    print(quick_summary(result))
    print("=" * 50)
    return result


def cmd_batch(ticker_file: str, trade_date: str = None):
    tickers = [
        line.strip() for line in open(ticker_file)
        if line.strip() and not line.startswith("#")
    ]
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")
    comp = scan_comparison(tickers, trade_date)
    print(f"\n{'=' * 50}")
    print_comparison(comp)
    return comp


def cmd_watch(trade_date: str = None):
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")
    alerts = scan_and_alert_all(DEFAULT_WATCHLIST, trade_date)
    if not alerts:
        print(f"✅ {trade_date} 无决策变更")
    return alerts


def main():
    parser = argparse.ArgumentParser(description="TradingAgents 分析工具")
    sub = parser.add_subparsers(dest="cmd")

    # 单股分析
    p_analyze = sub.add_parser("analyze", help="分析单只股票")
    p_analyze.add_argument("ticker", help="股票代码，如 002173.SZ")
    p_analyze.add_argument("date", nargs="?", help="分析日期 YYYY-MM-DD")

    # 批量
    p_batch = sub.add_parser("batch", help="批量分析")
    p_batch.add_argument("file", help="股票列表文件（每行一个代码）")
    p_batch.add_argument("date", nargs="?", help="分析日期 YYYY-MM-DD")

    # 监控
    p_watch = sub.add_parser("watch", help="监控关注列表并告警")
    p_watch.add_argument("date", nargs="?", help="分析日期 YYYY-MM-DD")

    args = parser.parse_args()

    if args.cmd == "analyze":
        cmd_analyze(args.ticker, args.date)
    elif args.cmd == "batch":
        cmd_batch(args.file, args.date)
    elif args.cmd == "watch":
        cmd_watch(args.date)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
