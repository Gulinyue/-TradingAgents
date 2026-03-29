"""
定时任务注册 - 使用 OpenClaw 内建 cron

用法：
    python scheduler.py register daily \
        --account-code paper_main \
        --watchlist-code core_holdings_focus

    python scheduler.py register daily \
        --account-code paper_main \
        --watchlist-code default_a_share \
        --no-db

    python scheduler.py list
    python scheduler.py unregister <name>
"""
import argparse
import subprocess
import sys
from datetime import date

# OpenClaw cron session name for scheduler jobs
SCHEDULER_SESSION = "isolated"


def register_daily(
    watchlist_code: str = None,
    account_code: str = None,
    write_db: bool = True,
):
    """每天 09:05 执行一次扫描"""
    return _register(
        name="daily-stock-scan",
        schedule="at 09:05 * * *",
        watchlist_code=watchlist_code,
        account_code=account_code,
        write_db=write_db,
    )


def register_weekly(
    watchlist_code: str = None,
    account_code: str = None,
    write_db: bool = True,
):
    """每周一 09:10 执行一次扫描"""
    return _register(
        name="weekly-stock-scan",
        schedule="at 09:10 * * 1",
        watchlist_code=watchlist_code,
        account_code=account_code,
        write_db=write_db,
    )


def _register(
    name: str,
    schedule: str,
    watchlist_code: str = None,
    account_code: str = None,
    write_db: bool = True,
):
    """构建并注册 OpenClaw cron 任务。"""
    trade_date = date.today().strftime("%Y-%m-%d")

    # 构建 Python 执行语句
    parts = [
        "from tradingagents_runner.run import cmd_batch",
        f"cmd_batch(None, '{trade_date}',",
        f"from_db_watchlist={repr(watchlist_code)},",
        f"account_code={repr(account_code)},",
        f"write_db={write_db})",
    ]
    msg = " ".join(parts)

    cmd = [
        "openclaw", "cron", "add",
        "--name", name,
        "--schedule", schedule,
        "--session", SCHEDULER_SESSION,
        "--message", msg,
    ]

    print(f"[Scheduler] Registering cron: {name}")
    print(f"[Scheduler] Schedule: {schedule}")
    if watchlist_code:
        print(f"[Scheduler] watchlist: {watchlist_code}")
    if account_code:
        print(f"[Scheduler] account: {account_code}")
    print(f"[Scheduler] write_db: {write_db}")
    print(f"[Scheduler] Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    return result.returncode == 0


def list_crons():
    """列出已注册的 cron 任务。"""
    cmd = ["openclaw", "cron", "list"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    return result.returncode == 0


def unregister(name: str):
    """删除指定的 cron 任务（通过 name 匹配）。"""
    cmd = ["openclaw", "cron", "remove", name]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="TradingAgents 定时任务管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 每日扫描，账户+股票池从 DB 读取，写 DB
  python scheduler.py register daily \\
      --account-code paper_main \\
      --watchlist-code core_holdings_focus

  # 每周扫描，不写 DB（只生成报告）
  python scheduler.py register weekly \\
      --account-code paper_main \\
      --watchlist-code default_a_share \\
      --no-db

  # 列出已注册任务
  python scheduler.py list

  # 删除任务
  python scheduler.py unregister daily-stock-scan
""",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── register daily ─────────────────────────────────────────
    p_daily = sub.add_parser("register", help="注册定时任务（需要子命令）")
    sub_daily = p_daily.add_subparsers(dest="freq")

    freq_daily = sub_daily.add_parser("daily", help="每天 09:05 执行")
    freq_daily.add_argument("--account-code", help="账户代码，如 paper_main")
    freq_daily.add_argument("--watchlist-code", help="股票池代码，如 core_holdings_focus")
    freq_daily.add_argument("--no-db", dest="no_db", action="store_true",
                            help="跳过数据库写入")

    freq_weekly = sub_daily.add_parser("weekly", help="每周一 09:10 执行")
    freq_weekly.add_argument("--account-code", help="账户代码")
    freq_weekly.add_argument("--watchlist-code", help="股票池代码")
    freq_weekly.add_argument("--no-db", dest="no_db", action="store_true",
                             help="跳过数据库写入")

    # ── list ─────────────────────────────────────────────────────
    sub.add_parser("list", help="列出已注册的 cron 任务")

    # ── unregister ───────────────────────────────────────────────
    p_unreg = sub.add_parser("unregister", help="删除定时任务")
    p_unreg.add_argument("name", help="任务名称（通过 'list' 查看）")

    args = parser.parse_args()
    write_db = not getattr(args, "no_db", False)

    if args.cmd == "register":
        if args.freq == "daily":
            ok = register_daily(
                watchlist_code=getattr(args, "watchlist_code", None),
                account_code=getattr(args, "account_code", None),
                write_db=write_db,
            )
        elif args.freq == "weekly":
            ok = register_weekly(
                watchlist_code=getattr(args, "watchlist_code", None),
                account_code=getattr(args, "account_code", None),
                write_db=write_db,
            )
        sys.exit(0 if ok else 1)

    elif args.cmd == "list":
        list_crons()

    elif args.cmd == "unregister":
        ok = unregister(args.name)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
