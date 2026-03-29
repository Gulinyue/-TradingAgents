from langchain_core.messages import HumanMessage, RemoveMessage
import re


def _fix_chinese_stock_symbol(symbol: str) -> str:
    """Auto-fix Chinese A-share tickers that may have lost their exchange suffix.

    LLMs often strip exchange suffixes like .SZ or .SS when calling tools.
    This detects common Chinese A-share patterns and restores the correct suffix.
    """
    if '.' in symbol:
        return symbol
    if re.match(r'^[01369]\d{5}$', symbol):
        if symbol.startswith('6'):
            return f"{symbol}.SS"
        else:
            return f"{symbol}.SZ"
    return symbol

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
