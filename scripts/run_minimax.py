#!/usr/bin/env python3
"""
TradingAgents + MiniMax (Anthropic API 兼容) 示例
用法: python scripts/run_minimax.py [ticker] [date]
"""
import os
import sys

# 设置 MiniMax API Key（替换为你的）
MINIMAX_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not MINIMAX_API_KEY:
    print("⚠️  请先设置环境变量 ANTHROPIC_API_KEY（MiniMax API Key）")
    print("   export ANTHROPIC_API_KEY=your_key_here")
    sys.exit(1)

# 设置 MiniMax Anthropic 兼容端点
os.environ["ANTHROPIC_BASE_URL"] = "https://api.minimaxi.com/anthropic"

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    date = sys.argv[2] if len(sys.argv) > 2 else "2026-03-15"

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "anthropic"
    config["backend_url"] = "https://api.minimaxi.com/anthropic"
    config["deep_think_llm"] = "MiniMax-M2.7"      # 深度思考模型
    config["quick_think_llm"] = "MiniMax-M2.7"     # 快速任务模型
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["max_rer_limit"] = 100

    print(f"🚀 TradingAgents + MiniMax (Anthropic API 兼容)")
    print(f"   Ticker: {ticker} | Date: {date}")
    print(f"   Provider: {config['llm_provider']}")
    print(f"   Deep model: {config['deep_think_llm']}")
    print(f"   Quick model: {config['quick_think_llm']}")
    print(f"   Endpoint: {config['backend_url']}")
    print(f"   API Key: {MINIMAX_API_KEY[:8]}...{MINIMAX_API_KEY[-4:]}")
    print()

    ta = TradingAgentsGraph(debug=True, config=config)
    print("📊 开始分析...\n")
    _, decision = ta.propagate(ticker, date)
    print(f"\n📋 最终决策:\n{decision}")

if __name__ == "__main__":
    main()
