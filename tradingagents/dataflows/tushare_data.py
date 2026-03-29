"""
Tushare Pro data provider for TradingAgents.

Supports: A-share stock data, fundamentals, financial statements, news.
"""
from typing import Annotated
from datetime import datetime, timedelta
import pandas as pd
import tushare as ts
import os
from dotenv import load_dotenv
from .config import get_config

# Lazy-init Tushare pro API
_pro_api = None

def _get_pro():
    """Get or initialize Tushare Pro API."""
    global _pro_api
    if _pro_api is None:
        env_path = os.environ.get("ENV_FILE_PATH")
        if env_path:
            load_dotenv(env_path)
        else:
            from pathlib import Path
            load_dotenv(Path(__file__).parent.parent.parent / ".env")
        token = os.environ.get('TUSHARE_TOKEN')
        if not token:
            raise RuntimeError("TUSHARE_TOKEN not set in .env")
        _pro_api = ts.pro_api(token)
    return _pro_api


def _normalize_ts_code(symbol: str) -> str:
    """Normalize A-share symbol to .SH / .SZ (DB internal standard).
    
    DB standard: .SH (Shanghai) / .SZ (Shenzhen)
    Accepts input: .SH, .SZ, .SS (Tushare legacy alias for Shanghai)
    """
    s = symbol.strip().upper()
    if '.' in s:
        # Already has suffix: normalize .SS -> .SH
        return s.replace('.SS', '.SH')
    # Pure digit: infer exchange
    if s.isdigit():
        if len(s) == 6:
            if s.startswith('6'):
                return f"{s}.SH"
            else:
                return f"{s}.SZ"
    return s


def _is_a_share(ts_code: str) -> bool:
    """Check if ts_code is an A-share (.SH or .SZ)."""
    return ts_code.endswith('.SH') or ts_code.endswith('.SZ')


# ─────────────────────────────────────────────────────────────────────────────
# Stock Price Data
# ─────────────────────────────────────────────────────────────────────────────

def get_tushare_stock_data(
    symbol: Annotated[str, "ticker symbol, e.g. 002173 or 002173.SZ"],
    start_date: Annotated[str, "start date yyyy-mm-dd"],
    end_date: Annotated[str, "end date yyyy-mm-dd"],
) -> str:
    """Get OHLCV daily data via Tushare Pro (A-share focused)."""
    try:
        pro = _get_pro()
        ts_code = _normalize_ts_code(symbol)
        df = pro.daily(
            ts_code=ts_code,
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
        )
        if df is None or df.empty:
            return f"No Tushare data found for '{symbol}' between {start_date} and {end_date}"

        # Format nicely
        lines = [
            f"# Stock data for {ts_code} from {start_date} to {end_date} (Tushare)",
            f"# Total records: {len(df)}",
            "",
            df.to_string(index=False)
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving Tushare stock data for {symbol}: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# Technical Indicators — use yfinance + stockstats (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

# get_indicators remains via yfinance/stockstats


# ─────────────────────────────────────────────────────────────────────────────
# Fundamentals
# ─────────────────────────────────────────────────────────────────────────────

def get_tushare_fundamentals(
    symbol: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date yyyy-mm-dd"],
) -> str:
    """Get company fundamentals overview via Tushare."""
    try:
        pro = _get_pro()
        ts_code = _normalize_ts_code(symbol)

        # Get stock basic info
        basic = pro.stock_basic(
            ts_code=ts_code, list_status='L',
            fields='ts_code,name,industry,market,list_date,is_hs'
        )
        if basic is None or basic.empty:
            return f"No fundamentals found for symbol '{symbol}'"

        info = basic.iloc[0].to_dict()

        # Get latest financials
        try:
            fin = pro.fina_indicator(ts_code=ts_code, start_date='20250101')
            if fin is not None and not fin.empty:
                latest = fin.iloc[0]
            else:
                latest = {}
        except Exception:
            latest = {}

        lines = [
            f"# Company Fundamentals for {ts_code}",
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Data source: Tushare Pro",
            "",
            f"Name: {info.get('name', 'N/A')}",
            f"Industry: {info.get('industry', 'N/A')}",
            f"Market: {info.get('market', 'N/A')}",
            f"List Date: {info.get('list_date', 'N/A')}",
        ]

        # Add financial indicators if available
        if latest is not None:
            key_fields = [
                ('pe', 'P/E Ratio'),
                ('pb', 'P/B Ratio'),
                ('roe', 'ROE'),
                ('net_profit_ratio', 'Net Profit Margin'),
                ('gross_profit_margin', 'Gross Profit Margin'),
                ('debt_to_assets', 'Debt to Assets'),
                ('total_revenue', 'Total Revenue'),
                ('net_profit', 'Net Profit'),
            ]
            for field, label in key_fields:
                val = latest.get(field)
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    lines.append(f"{label}: {val}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving Tushare fundamentals for {symbol}: {str(e)}"


def get_tushare_balance_sheet(
    symbol: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "annual or quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date yyyy-mm-dd"] = None,
) -> str:
    """Get balance sheet via Tushare."""
    try:
        pro = _get_pro()
        ts_code = _normalize_ts_code(symbol)
        period = (curr_date or datetime.now().strftime('%Y%m%d'))[:4]

        df = pro.balancesheet(ts_code=ts_code, start_date=f'{int(period)-2}0101')
        if df is None or df.empty:
            return f"No balance sheet data found for {symbol}"

        # Select key columns
        key_cols = [c for c in [
            'borr_owbank_fina', 'borrow_from_central_bank', 'deposit_in_interbank',
            'prec_metals_lend', 'derivative_fin_assets', 'nbuyback_sell_assets',
            'total_assets', 'total_liab', 'total_hldr_eqy_incl_min_int',
            'notes_payable', 'accounts_payable', 'advance_receipts',
            'total_current_assets', 'total_current_liab',
        ] if c in df.columns]

        if not key_cols:
            return f"No readable balance sheet columns for {symbol}\n{df.head().to_string()}"

        display_df = df[['ann_date', 'end_date'] + key_cols].tail(8)
        return (
            f"# Balance Sheet for {ts_code} (Tushare)\n"
            f"# Last {len(display_df)} periods\n\n"
            f"{display_df.to_string(index=False)}"
        )
    except Exception as e:
        return f"Error retrieving balance sheet for {symbol}: {str(e)}"


def get_tushare_income_statement(
    symbol: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "annual or quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date yyyy-mm-dd"] = None,
) -> str:
    """Get income statement via Tushare."""
    try:
        pro = _get_pro()
        ts_code = _normalize_ts_code(symbol)
        period = (curr_date or datetime.now().strftime('%Y%m%d'))[:4]

        df = pro.income(ts_code=ts_code, start_date=f'{int(period)-2}0101')
        if df is None or df.empty:
            return f"No income statement data found for {symbol}"

        key_cols = [c for c in [
            'revenue', 'total_profits', 'operate_profit', 'total_expense',
            'n_income', 'n_income_attr_p', 'basic_eps', 'diluted_eps',
        ] if c in df.columns]

        if not key_cols:
            return f"No readable income statement columns for {symbol}\n{df.head().to_string()}"

        display_df = df[['ann_date', 'end_date'] + key_cols].tail(8)
        return (
            f"# Income Statement for {ts_code} (Tushare)\n"
            f"# Last {len(display_df)} periods\n\n"
            f"{display_df.to_string(index=False)}"
        )
    except Exception as e:
        return f"Error retrieving income statement for {symbol}: {str(e)}"


def get_tushare_cashflow(
    symbol: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "annual or quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date yyyy-mm-dd"] = None,
) -> str:
    """Get cash flow statement via Tushare."""
    try:
        pro = _get_pro()
        ts_code = _normalize_ts_code(symbol)
        period = (curr_date or datetime.now().strftime('%Y%m%d'))[:4]

        df = pro.cashflow(ts_code=ts_code, start_date=f'{int(period)-2}0101')
        if df is None or df.empty:
            return f"No cash flow data found for {symbol}"

        key_cols = [c for c in [
            'n_cashflow_act', 'investing_cash_flow', 'cashflow_from_fin_act',
            'end_Cash_equ', 'begin_Cash_equ', 'free_cashflow',
        ] if c in df.columns]

        if not key_cols:
            return f"No readable cash flow columns for {symbol}\n{df.head().to_string()}"

        display_df = df[['ann_date', 'end_date'] + key_cols].tail(8)
        return (
            f"# Cash Flow Statement for {ts_code} (Tushare)\n"
            f"# Last {len(display_df)} periods\n\n"
            f"{display_df.to_string(index=False)}"
        )
    except Exception as e:
        return f"Error retrieving cash flow for {symbol}: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# News — delegated to AKShare (see akshare_data.py)
# ─────────────────────────────────────────────────────────────────────────────

def get_tushare_news(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "start date yyyy-mm-dd"],
    end_date: Annotated[str, "end date yyyy-mm-dd"],
) -> str:
    """News via Tushare. Falls back to AKShare news."""
    try:
        pro = _get_pro()
        ts_code = _normalize_ts_code(symbol)
        start_str = start_date.replace('-', '')
        end_str = end_date.replace('-', '')

        # Tushare news API
        df = pro.news(src='eastmoney', start_date=start_str, end_date=end_str)
        if df is None or df.empty:
            return "No news found via Tushare"

        # Filter news related to the stock
        symbol_plain = ts_code.replace('.SZ', '').replace('.SH', '')
        related = df[df['content'].str.contains(symbol_plain, na=False)]
        if related.empty:
            return "No news found for this ticker in the specified period"

        lines = [f"# News for {ts_code} ({start_date} to {end_date}) (Tushare)", ""]
        for _, row in related.head(10).iterrows():
            lines.append(f"## {row['datetime']} - {row['title']}")
            lines.append(f"Source: {row['src']}")
            content = str(row['content'])[:500]
            lines.append(f"{content}...")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving news via Tushare: {str(e)}\n(Fallback: use AKShare news)"


def get_tushare_global_news(
    curr_date: Annotated[str, "current date yyyy-mm-dd"],
    look_back_days: Annotated[int, "days to look back"] = 7,
    limit: Annotated[int, "max articles"] = 10,
) -> str:
    """Global/macro news via Tushare."""
    try:
        pro = _get_pro()
        start_str = (datetime.strptime(curr_date, '%Y-%m-%d') -
                     timedelta(days=look_back_days)).strftime('%Y%m%d')
        end_str = curr_date.replace('-', '')

        df = pro.news(src='eastmoney', start_date=start_str, end_date=end_str)
        if df is None or df.empty:
            return "No global news found"

        lines = [f"# Global News ({curr_date}, last {look_back_days} days) (Tushare)", ""]
        for _, row in df.head(limit).iterrows():
            lines.append(f"## {row['datetime']} - {row['title']}")
            lines.append(f"Source: {row['src']}")
            content = str(row['content'])[:300]
            lines.append(f"{content}...")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving global news: {str(e)}"


def get_tushare_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """Get insider (director) transactions via Tushare."""
    try:
        pro = _get_pro()
        ts_code = _normalize_ts_code(ticker)
        df = pro.daily_basic(ts_code=ts_code)
        if df is None or df.empty:
            return f"No insider transaction data found for {ticker}"
        lines = [
            f"# Daily Basic Info for {ts_code} (Tushare)",
            f"# Last trading day data (includes institutional activity indicators)",
            "",
            df.tail(5).to_string(index=False)
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving insider transactions for {ticker}: {str(e)}"
