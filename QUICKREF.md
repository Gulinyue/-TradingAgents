# TradingAgents 使用速查

## 分析命令

```bash
conda activate tradingagents

# 单股分析
python /home/gulinyue/TradingAgents/tradingagents_runner/run.py analyze 002173.SZ 2026-03-27

# 批量对比（先建 stocks.txt）
python /home/gulinyue/TradingAgents/tradingagents_runner/run.py batch stocks.txt 2026-03-27

# 监控告警
python /home/gulinyue/TradingAgents/tradingagents_runner/run.py watch
```

## 定时任务

```bash
# 注册每日 09:05 自动扫描
python /home/gulinyue/TradingAgents/tradingagents_runner/scheduler.py daily

# 查看已注册任务
python /home/gulinyue/TradingAgents/tradingagents_runner/scheduler.py list
```

## Python 直接调用

```python
import sys
from pathlib import Path
sys.path.insert(0, "/home/gulinyue/TradingAgents")
sys.path.insert(0, "/home/gulinyue/TradingAgents/tradingagents_runner")

from runner import analyze, quick_summary

result = analyze("002173.SZ", "2026-03-27")
print(result["decision"])  # BUY / HOLD / SELL
```

## 修改关注股票池

编辑这两个文件的 `DEFAULT_WATCHLIST`：
- `/home/gulinyue/TradingAgents/tradingagents_runner/run.py`
- `/home/gulinyue/TradingAgents/tradingagents_runner/scheduler.py`

## A股代码格式

- 深市：`002173.SZ`
- 沪市：`600519.SS`
- 创业板：`300015.SZ`
- 科创板：`688xxx.SS`
