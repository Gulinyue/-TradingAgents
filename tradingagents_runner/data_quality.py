"""
数据质量判断模块 - v1

职责：
  - 统一定义 bar 数阈值
  - 判断 has_minimum_bars / has_enough_bars
  - 返回 bar_quality_level
  - bar_health 统计

阈值标准（v1）：
  - insufficient : 0 ~ 19 bars   → 最低可分析标准未达
  - minimum_only : 20 ~ 59 bars → 最低可运行，但不推荐做复杂分析
  - good         : 60 ~ 119 bars → 推荐标准，支撑常见技术指标
  - full         : >= 120 bars   → 稳定研究标准，支持因子/ML特征

使用方式：
  from data_quality import assess_bar_quality, BAR_THRESHOLDS

  bar_count = 45
  quality = assess_bar_quality(bar_count)
  # -> {"level": "minimum_only", "has_minimum": True, "has_enough": False, ...}
"""

from dataclasses import dataclass
from typing import Dict, Any

# ─────────────────────────────────────────────────────────────────────────────
# 阈值常量
# ─────────────────────────────────────────────────────────────────────────────

MIN_BAR_COUNT = 20       # 最低可分析标准
GOOD_BAR_COUNT = 60      # 推荐标准（主目标）
FULL_BAR_COUNT = 120     # 稳定研究标准

BAR_THRESHOLDS = {
    "minimum": MIN_BAR_COUNT,
    "good": GOOD_BAR_COUNT,
    "full": FULL_BAR_COUNT,
}


# ─────────────────────────────────────────────────────────────────────────────
# Quality assessment
# ─────────────────────────────────────────────────────────────────────────────

def assess_bar_quality(bar_count: int) -> Dict[str, Any]:
    """
    评估 bar 数据的质量等级。

    参数
    ----
    bar_count : int
        该股票当前已有的日线 bar 数量

    返回
    ----
    dict
        - level: str  ("insufficient" | "minimum_only" | "good" | "full")
        - has_minimum_bars: bool  (bar_count >= 20)
        - has_enough_bars: bool   (bar_count >= 60)
        - has_full_bars: bool     (bar_count >= 120)
        - bar_count: int
        - minimum_bar_count: int
        - good_bar_count: int
        - full_bar_count: int
        - quality_label: str  (中文简短描述)
    """
    bc = int(bar_count) if bar_count is not None else 0

    if bc >= FULL_BAR_COUNT:
        level = "full"
        label = "✓ 充足（稳定研究级）"
    elif bc >= GOOD_BAR_COUNT:
        level = "good"
        label = "✓ 良好（推荐标准）"
    elif bc >= MIN_BAR_COUNT:
        level = "minimum_only"
        label = "⚠ 勉强（最低可运行）"
    else:
        level = "insufficient"
        label = "✗ 不足（数据退化风险）"

    return {
        "level": level,
        "has_minimum_bars": bc >= MIN_BAR_COUNT,
        "has_enough_bars": bc >= GOOD_BAR_COUNT,
        "has_full_bars": bc >= FULL_BAR_COUNT,
        "bar_count": bc,
        "minimum_bar_count": MIN_BAR_COUNT,
        "good_bar_count": GOOD_BAR_COUNT,
        "full_bar_count": FULL_BAR_COUNT,
        "quality_label": label,
        # 缺多少达到 good 标准
        "bars_to_good": max(0, GOOD_BAR_COUNT - bc),
        "bars_to_full": max(0, FULL_BAR_COUNT - bc),
    }


def format_bar_quality_report(bar_count: int) -> str:
    """生成单只股票 bar 质量报告字符串。"""
    q = assess_bar_quality(bar_count)
    return (
        f"bars={q['bar_count']} "
        f"({q['quality_label']}) "
        f"| 距good还差{q['bars_to_good']} bars "
        f"| 距full还差{q['bars_to_full']} bars"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bar health overview（给快照/上下文层用）
# ─────────────────────────────────────────────────────────────────────────────

def get_bar_health_for_symbols(
    bar_counts_by_symbol: Dict[str, int]
) -> Dict[str, Any]:
    """
    批量评估一组股票的整体 bar 健康度。

    参数
    ----
    bar_counts_by_symbol : dict
        { symbol: bar_count, ... }

    返回
    ----
    dict
        - total: int
        - insufficient: int
        - minimum_only: int
        - good: int
        - full: int
        - coverage_good: float  (good+full 占比)
        - coverage_minimum: float
        - symbols_by_level: dict
    """
    by_level = {
        "insufficient": [],
        "minimum_only": [],
        "good": [],
        "full": [],
    }

    for sym, bc in bar_counts_by_symbol.items():
        q = assess_bar_quality(bc)
        by_level[q["level"]].append(sym)

    total = len(bar_counts_by_symbol)
    good_full = len(by_level["good"]) + len(by_level["full"])
    min_plus = good_full + len(by_level["minimum_only"])

    return {
        "total": total,
        "insufficient": len(by_level["insufficient"]),
        "minimum_only": len(by_level["minimum_only"]),
        "good": len(by_level["good"]),
        "full": len(by_level["full"]),
        "coverage_good": round(good_full / total, 4) if total else 0.0,
        "coverage_minimum": round(min_plus / total, 4) if total else 0.0,
        "symbols_by_level": by_level,
    }
