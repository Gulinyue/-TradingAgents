"""
定时任务注册 - 使用 OpenClaw 内建 cron
用法：
    python scheduler.py register daily    # 每天早上 9 点运行
    python scheduler.py register weekly   # 每周一早上 9 点运行
    python scheduler.py list             # 查看已注册任务
    python scheduler.py unregister <id>  # 删除任务
"""
import argparse
import json
import subprocess
import sys
from datetime import date

# 你的关注股票池（替换成你的）
DEFAULT_WATCHLIST = [
    "002173.SZ",   # 创新医疗
    # "600519.SS",  # 贵州茅台
    # "300750.SZ",  # 宁德时代
    # "NVDA",       # 英伟达
]

RESULT_DIR = "/home/gulinyue/TradingAgents/results"


def build_cron_message(watchlist: list, trade_date: str = None) -> str:
    """构建 cron 任务要执行的指令"""
    import json
    msg = (
        f"from tradingagents_runner.batch import scan_comparison, print_comparison; "
        f"comp = scan_comparison({json.dumps(watchlist)}, '{trade_date or date.today().strftime('%Y-%m-%d')}'); "
        f"print_comparison(comp)"
    )
    return msg


def register_daily():
    """每天 09:05 (等开盘) 执行一次扫描"""
    watchlist = DEFAULT_WATCHLIST
    trade_date = (date.today()).strftime("%Y-%m-%d")
    msg = build_cron_message(watchlist, trade_date)

    cmd = [
        "openclaw", "cron", "add",
        "--name", f"daily-stock-scan",
        "--schedule", "at 09:05 * * *",
        "--session", "isolated",
        "--message", msg,
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    return result.returncode == 0


def register_weekly():
    """每周一 09:10 执行一次"""
    msg = build_cron_message(DEFAULT_WATCHLIST)

    cmd = [
        "openclaw", "cron", "add",
        "--name", "weekly-stock-scan",
        "--schedule", "at 09:10 * * 1",
        "--session", "isolated",
        "--message", msg,
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    return result.returncode == 0


def list_crons():
    """列出已注册的 cron 任务"""
    cmd = ["openclaw", "cron", "list"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="TradingAgents 定时任务管理")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出已注册任务")
    sub.add_parser("daily", help="注册每日 09:05 扫描")
    sub.add_parser("weekly", help="注册每周一 09:10 扫描")

    args = parser.parse_args()

    if args.cmd == "list":
        list_crons()
    elif args.cmd == "daily":
        ok = register_daily()
        sys.exit(0 if ok else 1)
    elif args.cmd == "weekly":
        ok = register_weekly()
        sys.exit(0 if ok else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
