# TradingAgents 使用速查

## 分析命令

```bash
conda activate tradingagents

# 单股分析
python tradingagents_runner/run.py analyze 002173.SZ 2026-03-27

# 批量对比（先建 stocks.txt）
python tradingagents_runner/run.py batch stocks.txt 2026-03-27

# 监控告警
python tradingagents_runner/run.py watch
```

## 定时任务

```bash
# 注册每日 09:05 自动扫描
python tradingagents_runner/scheduler.py daily

# 查看已注册任务
python tradingagents_runner/scheduler.py list
```

## Python 直接调用

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "tradingagents_runner"))

from runner import analyze

result = analyze("002173.SZ", "2026-03-27")
print(result["decision"])  # BUY / HOLD / SELL
```

## 修改关注股票池

编辑这两个文件的 `DEFAULT_WATCHLIST`：
- `tradingagents_runner/run.py`
- `tradingagents_runner/scheduler.py`

## A股代码格式（DB 标准：`.SH` / `.SZ`）

- 深市：`002173.SZ`
- 沪市：`600519.SH`
- 创业板：`300015.SZ`
- 科创板：`688xxx.SH`（科创板也属沪市）
- `.SS` 是 Tushare 旧别名，接口会自动转为 `.SH`
