"""
市场历史数据回填脚本 - v1

职责：
  1. 读取目标 symbol 列表（持仓 + 股票池）
  2. 计算每个 symbol 当前已有的 bar 数
  3. 对不足阈值的 symbol 拉足量历史数据
  4. Upsert 到 market.market_bars_daily
  5. 输出统计报告

数据源优先级：Tushare（主） → AKShare（备用）
幂等写入：ON CONFLICT (symbol, trade_date) DO UPDATE
来源追踪：source = 'tushare_backfill'

用法：
  python backfill_market_bars.py          # 默认回填到 60 bars
  python backfill_market_bars.py --target 120  # 回填到 120 bars
  python backfill_market_bars.py --dry-run
"""
import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Resolve imports
_repo_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

_env_path = os.environ.get("ENV_FILE_PATH")
if _env_path:
    load_dotenv(_env_path)
else:
    load_dotenv(_repo_root / ".env")

import psycopg2
import pandas as pd
import tushare as ts
import akshare as ak


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://ta_app_rw:TaAppRW2026!@localhost:6543/tradingagents",
)

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")

# 回填参数
TARGET_BARS_MIN = 20    # 最低可分析
TARGET_BARS_GOOD = 60   # 推荐标准（主目标）
TARGET_BARS_FULL = 120  # 稳定研究标准

# 估算：120 个交易日大约覆盖 6 个月（含周末/假期）
TRADING_DAYS_ESTIMATE = 120
LOOKBACK_MONTHS = 10     # 向前拉 10 个月，基本覆盖 120 个交易日


# ─────────────────────────────────────────────────────────────────────────────
# Tushare API
# ─────────────────────────────────────────────────────────────────────────────

def _get_tushare_pro():
    if not TUSHARE_TOKEN:
        raise RuntimeError("TUSHARE_TOKEN not set")
    return ts.pro_api(TUSHARE_TOKEN)


def _normalize_ts_code(symbol: str) -> str:
    """标准化 symbol：沪市→.SH，深市→.SZ，与 DB 内部标准一致。"""
    s = symbol.strip().upper()
    if s.endswith(".SS"):
        s = s[:-3] + ".SH"
    if "." in s:
        return s
    if s.isdigit() and len(s) == 6:
        return f"{s}.SH" if s.startswith("6") else f"{s}.SZ"
    return s


def fetch_tushare_bars(symbol: str, lookback_months: int = 10) -> Optional[pd.DataFrame]:
    """
    通过 Tushare Pro 获取日线 OHLCV 数据。

    返回 DataFrame，列：trade_date, open, high, low, close, volume, amount
    或 None（失败时）。
    """
    try:
        pro = _get_tushare_pro()
        ts_code = _normalize_ts_code(symbol)

        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_months * 31)

        df = pro.daily(
            ts_code=ts_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )

        if df is None or df.empty:
            return None

        # 重命名并选择目标列
        df = df.rename(columns={"ts_code": "ts_code_raw"})
        df = df.rename(columns={
            "vol": "volume",
        })

        # Tushare 返回的 amount 单位是千元，volume 单位是手
        # 保持原样写入，amount 不做转换
        df["symbol"] = ts_code
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        # 按日期升序排序（ oldest → newest ）
        df = df.sort_values("trade_date").reset_index(drop=True)

        return df[["symbol", "trade_date", "open", "high", "low", "close",
                   "volume", "amount"]]
    except Exception as e:
        print(f"    [Tushare 错误] {symbol}: {e}")
        return None


def fetch_akshare_bars(symbol: str, lookback_months: int = 10) -> Optional[pd.DataFrame]:
    """
    通过 AKShare 获取 A 股日线 OHLCV 数据作为备用源。

    返回 DataFrame，列：trade_date, open, high, low, close, volume, amount
    或 None（失败时）。
    """
    try:
        # AKShare A 股日线接口
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_months * 31)

        # 格式：akshare 用 000001.SZ / 600519.SH
        akshare_code = symbol.strip().upper()
        if not akshare_code.startswith(("0", "3", "6")):
            return None

        df = ak.stock_zh_a_hist(
            symbol=akshare_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="qfq",
        )

        if df is None or df.empty:
            return None

        # AKShare 返回列名：日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, 成交额, ...
        df = df.rename(columns={
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        })

        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
        df = df.dropna(subset=["trade_date"])
        df["symbol"] = _normalize_ts_code(symbol)

        # 按日期升序排序
        df = df.sort_values("trade_date").reset_index(drop=True)

        return df[["symbol", "trade_date", "open", "high", "low", "close",
                   "volume", "amount"]]
    except Exception as e:
        print(f"    [AKShare 错误] {symbol}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_db_conn():
    return psycopg2.connect(DB_URL)


def get_bar_count(conn, symbol: str) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM market.market_bars_daily WHERE symbol = %s",
        (symbol,),
    )
    row = cur.fetchone()
    cur.close()
    return int(row[0]) if row else 0


def get_bar_range(conn, symbol: str) -> tuple:
    cur = conn.cursor()
    cur.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM market.market_bars_daily WHERE symbol = %s",
        (symbol,),
    )
    row = cur.fetchone()
    cur.close()
    return (row[0], row[1]) if row and row[0] else (None, None)


def upsert_bars(conn, df: pd.DataFrame, source: str = "tushare_backfill") -> int:
    """
    将 DataFrame upsert 到 market.market_bars_daily。

    幂等写入：ON CONFLICT (symbol, trade_date) DO UPDATE
    保留策略：COALESCE(EXCLUDED.xxx, existing.xxx) — 不覆盖已有非空值
    amount/volume 为 0 视同空值处理

    返回实际插入/更新的行数。
    """
    if df is None or df.empty:
        return 0

    cur = conn.cursor()

    inserted = 0
    for _, row in df.iterrows():
        trade_date = row["trade_date"]
        if isinstance(trade_date, str):
            trade_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
        elif isinstance(trade_date, datetime):
            trade_date = trade_date.date()

        # amount/vol = 0 视同 None
        amount = row.get("amount")
        volume = row.get("volume")
        if amount == 0:
            amount = None
        if volume == 0:
            volume = None

        cur.execute("""
            INSERT INTO market.market_bars_daily
                (symbol, trade_date, open, high, low, close, volume, amount, source, extra)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
            ON CONFLICT (symbol, trade_date) DO UPDATE SET
                open       = COALESCE(NULLIF(EXCLUDED.open, 0),       market.market_bars_daily.open),
                high       = COALESCE(NULLIF(EXCLUDED.high, 0),       market.market_bars_daily.high),
                low        = COALESCE(NULLIF(EXCLUDED.low, 0),        market.market_bars_daily.low),
                close      = COALESCE(NULLIF(EXCLUDED.close, 0),      market.market_bars_daily.close),
                volume     = COALESCE(NULLIF(EXCLUDED.volume, 0),     market.market_bars_daily.volume),
                amount     = COALESCE(NULLIF(EXCLUDED.amount, 0),     market.market_bars_daily.amount),
                source     = EXCLUDED.source,
                extra      = COALESCE(EXCLUDED.extra, market.market_bars_daily.extra)
            WHERE
                market.market_bars_daily.symbol = EXCLUDED.symbol
                  AND market.market_bars_daily.trade_date = EXCLUDED.trade_date;
        """, (
            row["symbol"],
            trade_date,
            row.get("open") or 0,
            row.get("high") or 0,
            row.get("low") or 0,
            row.get("close") or 0,
            volume,
            amount,
            source,
        ))
        inserted += 1

    conn.commit()
    cur.close()
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# Target symbol 收集
# ─────────────────────────────────────────────────────────────────────────────

def collect_target_symbols(conn, account_code: str = "paper_main") -> List[Dict[str, Any]]:
    """
    按优先级收集目标 symbol：
    1. 当前账户持仓
    2. core_holdings_focus
    3. default_a_share
    """
    cur = conn.cursor()
    symbols = []
    seen = set()

    def add_symbol(symbol, source):
        sym = symbol.strip().upper()
        if sym.endswith(".SS"):
            sym = sym[:-3] + ".SH"
        if sym not in seen:
            seen.add(sym)
            symbols.append({"symbol": sym, "source": source})

    # 1. 当前持仓
    cur.execute("""
        SELECT DISTINCT p.symbol
        FROM core.positions p
        JOIN core.accounts a ON a.account_id = p.account_id
        WHERE a.account_code = %s
    """, (account_code,))
    for (sym,) in cur.fetchall():
        add_symbol(sym, "position")

    # 2. core_holdings_focus
    cur.execute("""
        SELECT m.symbol
        FROM core.watchlist_members m
        JOIN core.watchlists w ON w.watchlist_id = m.watchlist_id
        WHERE w.watchlist_code = 'core_holdings_focus' AND w.is_active = TRUE
    """)
    for (sym,) in cur.fetchall():
        add_symbol(sym, "core_holdings_focus")

    # 3. default_a_share
    cur.execute("""
        SELECT m.symbol
        FROM core.watchlist_members m
        JOIN core.watchlists w ON w.watchlist_id = m.watchlist_id
        WHERE w.watchlist_code = 'default_a_share' AND w.is_active = TRUE
    """)
    for (sym,) in cur.fetchall():
        add_symbol(sym, "default_a_share")

    cur.close()
    return symbols


# ─────────────────────────────────────────────────────────────────────────────
# 主回填逻辑
# ─────────────────────────────────────────────────────────────────────────────

def backfill_symbol(
    conn,
    symbol: str,
    target_bars: int,
    lookback_months: int = 10,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    回填单个 symbol，返回结果摘要。
    """
    result = {
        "symbol": symbol,
        "before_bars": get_bar_count(conn, symbol),
        "before_range": get_bar_range(conn, symbol),
        "tushare_bars": 0,
        "akshare_bars": 0,
        "after_bars": 0,
        "after_range": (None, None),
        "status": "skipped",
        "error": None,
    }

    if result["before_bars"] >= target_bars:
        result["status"] = "already_sufficient"
        return result

    # 优先 Tushare
    df = fetch_tushare_bars(symbol, lookback_months=lookback_months)
    if df is not None and not df.empty:
        result["tushare_bars"] = len(df)
        source = "tushare_backfill"
        if dry_run:
            result["status"] = "dry_run_tushare"
        else:
            try:
                inserted = upsert_bars(conn, df, source=source)
                result["status"] = f"tushare_inserted_{inserted}"
            except Exception as e:
                result["error"] = str(e)
                result["status"] = "tushare_error"
    else:
        # 备用 AKShare
        df_ak = fetch_akshare_bars(symbol, lookback_months=lookback_months)
        if df_ak is not None and not df_ak.empty:
            result["akshare_bars"] = len(df_ak)
            source = "akshare_backfill"
            if dry_run:
                result["status"] = "dry_run_akshare"
            else:
                try:
                    inserted = upsert_bars(conn, df_ak, source=source)
                    result["status"] = f"akshare_inserted_{inserted}"
                except Exception as e:
                    result["error"] = str(e)
                    result["status"] = "akshare_error"
        else:
            result["status"] = "no_data"

    # 验证
    result["after_bars"] = get_bar_count(conn, symbol)
    result["after_range"] = get_bar_range(conn, symbol)

    return result


def run_backfill(
    target_bars: int = TARGET_BARS_GOOD,
    lookback_months: int = LOOKBACK_MONTHS,
    dry_run: bool = False,
    account_code: str = "paper_main",
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """
    批量回填入口。
    """
    conn = get_db_conn()
    try:
        symbols = collect_target_symbols(conn, account_code)
        if verbose:
            print(f"\n{'='*60}")
            print(f"市场数据回填 v1")
            print(f"目标 bar 数：{target_bars}")
            print(f"回填查找窗口：{lookback_months} 个月")
            print(f"模式：{'DRY RUN（不写入）' if dry_run else 'LIVE（写入数据库）'}")
            print(f"目标股票数：{len(symbols)}")
            print(f"{'='*60}\n")

        results = []
        for item in symbols:
            sym = item["symbol"]
            src = item["source"]
            before = get_bar_count(conn, sym)

            if verbose:
                print(f"处理 [{sym}]（来源：{src}）当前 {before} bars ...", end=" ", flush=True)

            if before >= target_bars:
                if verbose:
                    print(f"✓ 已满足（{before} ≥ {target_bars}）")
                results.append({
                    "symbol": sym,
                    "before_bars": before,
                    "after_bars": before,
                    "status": "already_sufficient",
                })
                continue

            res = backfill_symbol(conn, sym, target_bars, lookback_months, dry_run)
            results.append(res)

            if verbose:
                if res["error"]:
                    print(f"✗ {res['status']}: {res['error']}")
                elif "tushare" in res["status"] or "akshare" in res["status"]:
                    print(
                        f"✓ {res['status']} | "
                        f"Tushare:{res['tushare_bars']} AKShare:{res['akshare_bars']} | "
                        f"最终 {res['after_bars']} bars "
                        f"({res['before_range'][0]} ~ {res['after_range'][1]})"
                    )
                else:
                    print(f"⚠ {res['status']}")

            # 防频率限制
            time.sleep(0.3)

        return results
    finally:
        conn.close()


def print_summary(results: List[Dict[str, Any]], target_bars: int):
    print(f"\n{'='*60}")
    print("回填结果汇总")
    print(f"{'='*60}")

    sufficient = [r for r in results if r.get("after_bars", 0) >= target_bars]
    insufficient = [r for r in results if r.get("after_bars", 0) < target_bars]

    print(f"\n总股票数：{len(results)}")
    print(f"✓ 达标（≥{target_bars} bars）：{len(sufficient)}")
    print(f"⚠ 未达标（<{target_bars} bars）：{len(insufficient)}")

    if sufficient:
        print(f"\n达标股票：")
        for r in sufficient:
            print(f"  {r['symbol']}: {r['after_bars']} bars")

    if insufficient:
        print(f"\n未达标股票：")
        for r in insufficient:
            print(f"  {r['symbol']}: {r['after_bars']} bars （{r['status']}）")

    print(f"\n详细结果：")
    for r in results:
        bar_delta = r.get("after_bars", 0) - r.get("before_bars", 0)
        delta = r.get("after_bars", 0) - r.get("before_bars", 0)
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        print(
            f"  {r['symbol']:12s} | {r.get('before_bars', 0):3d} → {r.get('after_bars', 0):3d} bars "
            f"({delta_str:>5s}) | {r['status']}"
        )

    print(f"\n{'='*60}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="市场历史数据回填脚本 v1")
    parser.add_argument(
        "--target",
        type=int,
        default=TARGET_BARS_GOOD,
        choices=[TARGET_BARS_MIN, TARGET_BARS_GOOD, TARGET_BARS_FULL],
        help=f"目标 bar 数（默认 {TARGET_BARS_GOOD}）",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=LOOKBACK_MONTHS,
        help=f"向前回溯月数（默认 {LOOKBACK_MONTHS}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只拉数据，不写入数据库",
    )
    parser.add_argument(
        "--account",
        default="paper_main",
        help="账户代码（默认 paper_main）",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="减少输出",
    )
    args = parser.parse_args()

    results = run_backfill(
        target_bars=args.target,
        lookback_months=args.lookback,
        dry_run=args.dry_run,
        account_code=args.account,
        verbose=not args.quiet,
    )

    if not args.quiet:
        print_summary(results, args.target)

    # 返回码：0=全部达标，1=有未达标
    insufficient = [r for r in results if r.get("after_bars", 0) < args.target]
    sys.exit(0 if not insufficient else 1)


if __name__ == "__main__":
    main()
