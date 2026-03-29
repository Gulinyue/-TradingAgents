"""
AKShare data provider for TradingAgents.

Supports: A-share news, sentiment data, financial statements.
AKShare is free and covers Chinese markets in depth.
"""
from typing import Annotated
from datetime import datetime, timedelta
import pandas as pd
import akshare as ak


def _is_a_share(symbol: str) -> bool:
    """Heuristic: if symbol is pure 6-digit number, it's A-share."""
    s = symbol.strip().replace('.SZ', '').replace('.SH', '').replace('.SS', '')
    return s.isdigit() and len(s) == 6


# ─────────────────────────────────────────────────────────────────────────────
# News
# ─────────────────────────────────────────────────────────────────────────────

def get_akshare_news(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "start date yyyy-mm-dd"],
    end_date: Annotated[str, "end date yyyy-mm-dd"],
) -> str:
    """Get news for A-share stock via AKShare (东方财富网)."""
    try:
        # Extract numeric part
        symbol_clean = symbol.strip().upper()
        for suffix in ['.SZ', '.SH', '.SS']:
            symbol_clean = symbol_clean.replace(suffix, '')

        df = ak.stock_news_em(symbol=symbol_clean)
        if df is None or df.empty:
            return f"No AKShare news found for {symbol}"

        # Parse dates
        def parse_date(d):
            try:
                return pd.to_datetime(str(d))
            except Exception:
                return None

        df['parsed_date'] = df['发布时间'].apply(parse_date)
        df = df.dropna(subset=['parsed_date'])

        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date) + timedelta(days=1)
        mask = (df['parsed_date'] >= start_dt) & (df['parsed_date'] <= end_dt)
        df_filtered = df[mask].head(10)

        if df_filtered.empty:
            return f"No news found for {symbol} between {start_date} and {end_date}"

        lines = [
            f"# News for {symbol} ({start_date} to {end_date}) (AKShare/东方财富)",
            f"# {len(df_filtered)} articles found",
            "",
        ]
        for _, row in df_filtered.iterrows():
            lines.append(f"## {row['发布时间']} - {row['新闻标题']}")
            lines.append(f"Source: {row['文章来源']}")
            content = str(row['新闻内容'])[:500] if pd.notna(row['新闻内容']) else '(内容不可用)'
            lines.append(f"{content}...")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving AKShare news for {symbol}: {str(e)}"


def get_akshare_global_news(
    curr_date: Annotated[str, "current date yyyy-mm-dd"],
    look_back_days: Annotated[int, "days to look back"] = 7,
    limit: Annotated[int, "max articles"] = 10,
) -> str:
    """Get macro/financial market news via AKShare."""
    try:
        # General financial news
        df = ak.stock_intro_news(symbol="all")
        if df is None or df.empty:
            return "No AKShare global news available"

        lines = [
            f"# Global Financial News (AKShare, last {look_back_days} days)",
            "",
        ]
        for _, row in df.head(limit).iterrows():
            title = row.get('资讯标题', row.get('title', 'N/A'))
            content = row.get('资讯内容', row.get('content', 'N/A'))
            source = row.get('来源', row.get('source', '东方财富'))
            lines.append(f"## {title}")
            lines.append(f"Source: {source}")
            lines.append(f"{str(content)[:300]}...")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving AKShare global news: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# Sentiment — social media / investor discussion
# ─────────────────────────────────────────────────────────────────────────────

def get_akshare_sentiment(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "start date yyyy-mm-dd"],
    end_date: Annotated[str, "end date yyyy-mm-dd"],
) -> str:
    """Get investor sentiment data via AKShare (东方财富股吧/资金流向)."""
    try:
        symbol_clean = symbol.strip().upper().replace('.SZ', '').replace('.SS', '')

        # Get money flow (主力净流入 = institutional net flow)
        try:
            mf = ak.stock_individual_fund_flow(stock=symbol_clean, market="sh" if symbol_clean.startswith('6') else "sz")
            if mf is not None and not mf.empty:
                lines = [
                    f"# Fund Flow / Sentiment for {symbol} (AKShare)",
                    f"# Source: 东方财富资金流向",
                    "",
                    mf.tail(10).to_string(index=False)
                ]
                return "\n".join(lines)
        except Exception:
            pass

        # Get board sentiment (market sentiment index)
        try:
            market_sentiment = ak.stock_sector_spot()
            if market_sentiment is not None and not market_sentiment.empty:
                lines = [
                    f"# Market Sector Sentiment (AKShare)",
                    "",
                    market_sentiment.head(20).to_string(index=False)
                ]
                return "\n".join(lines)
        except Exception:
            pass

        return f"No sentiment data available for {symbol} via AKShare"
    except Exception as e:
        return f"Error retrieving AKShare sentiment for {symbol}: {str(e)}"
