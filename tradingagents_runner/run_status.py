"""
Run Status 判定模块 - V2.1

职责：
  把 success / partial / failed 从"经验判断"变成系统规则。
  所有 status 由 evaluate_run_status() 统一产出。

规则：
  success：主链完成，核心数据充足，无关键错误
  partial：主链完成，但存在质量缺口
  failed：主链未完成或关键结果缺失
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RunStatusResult:
    run_status: str          # "success" | "partial" | "failed"
    status_reason: str      # 人类可读原因
    status_tags: List[str]   # 结构化标签列表
    is_success: bool         # 简写
    is_partial: bool
    is_failed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_status": self.run_status,
            "status_reason": self.status_reason,
            "status_tags": self.status_tags,
        }


def evaluate_run_status(
    data_completeness: Optional[Dict[str, Any]] = None,
    raw_output_quality: Optional[Dict[str, Any]] = None,
    runtime_errors: Optional[List[str]] = None,
    ta_executed: bool = True,
    db_write_ok: bool = True,
    parser_fallback_triggered: bool = False,
) -> RunStatusResult:
    """
    统一判定 run status。

    Parameters
    ----------
    data_completeness : dict
        来自 portfolio_snapshot.data_completeness
        键：has_balance, has_bar, bar_count, has_enough_bars, has_factors, etc.
    raw_output_quality : dict
        来自 runner 的 raw_output_quality
        键：technical_report_nonempty, fundamental_report_nonempty,
            raw_confidence_present, raw_risk_present, etc.
    runtime_errors : list[str], optional
        运行过程中的关键错误信息列表
    ta_executed : bool
        TA 图是否执行完成（未超时/未崩溃）
    db_write_ok : bool
        DB 写入是否成功
    parser_fallback_triggered : bool
        _parse_ta_result 是否触发了 fallback（说明原始路径文件缺失）

    Returns
    -------
    RunStatusResult
    """
    dc = data_completeness or {}
    roq = raw_output_quality or {}
    errors = runtime_errors or []

    # ── 收集标签 ─────────────────────────────────────────────────────────────
    tags: List[str] = []

    # Bar 充足性
    bar_count = dc.get("bar_count", 0)
    if bar_count < 20:
        tags.append("insufficient_bars")
    elif bar_count < 60:
        tags.append("minimum_only_bars")
    else:
        tags.append("good_bars")

    if not dc.get("has_enough_bars", False):
        tags.append("has_enough_bars=False")

    # 数据完整性
    if not dc.get("has_bar", False):
        tags.append("no_bar")
    if not dc.get("has_balance", False):
        tags.append("no_balance")
    if not dc.get("has_factors", False):
        tags.append("no_factors")

    # TA 输出质量
    tech_ok = bool(roq.get("technical_report_nonempty"))
    fund_ok = bool(roq.get("fundamental_report_nonempty"))
    conf_ok = bool(roq.get("raw_confidence_present"))
    action_ok = bool(roq.get("ta_decision_nondefault"))

    if not tech_ok:
        tags.append("missing_technical_report")
    if not fund_ok:
        tags.append("missing_fundamental_report")
    if not conf_ok:
        tags.append("missing_confidence")
    if not action_ok:
        tags.append("default_action_only")

    # 解析层
    if parser_fallback_triggered:
        tags.append("parser_fallback_triggered")

    # 运行时错误
    if errors:
        tags.append(f"errors({len(errors)})")

    # ── 判定规则 ─────────────────────────────────────────────────────────────

    # 1. failed：主链失败
    if not ta_executed:
        return RunStatusResult(
            run_status="failed",
            status_reason="TA图未执行完成（超时或崩溃）",
            status_tags=tags + ["ta_not_executed"],
            is_success=False,
            is_partial=False,
            is_failed=True,
        )

    if not db_write_ok:
        return RunStatusResult(
            run_status="failed",
            status_reason="数据库写入失败",
            status_tags=tags + ["db_write_failed"],
            is_success=False,
            is_partial=False,
            is_failed=True,
        )

    # 技术报告为空是最严重的质量退化
    if not tech_ok:
        return RunStatusResult(
            run_status="partial",
            status_reason="technical_report为空，TA输出退化",
            status_tags=tags,
            is_success=False,
            is_partial=True,
            is_failed=False,
        )

    # 2. partial：质量缺口
    quality_issues = []
    if bar_count < 60:
        quality_issues.append(f"bar_count={bar_count}(<60)")
    if not fund_ok:
        quality_issues.append("missing_fundamental_report")
    if not conf_ok:
        quality_issues.append("missing_confidence")
    if parser_fallback_triggered:
        quality_issues.append("parser_fallback")

    if quality_issues:
        return RunStatusResult(
            run_status="partial",
            status_reason="; ".join(quality_issues),
            status_tags=tags,
            is_success=False,
            is_partial=True,
            is_failed=False,
        )

    # 3. success：主链完整，质量达标
    return RunStatusResult(
        run_status="success",
        status_reason="主链完成，核心数据充足",
        status_tags=tags + ["clean_run"],
        is_success=True,
        is_partial=False,
        is_failed=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Human-readable summary
# ─────────────────────────────────────────────────────────────────────────────

def status_summary(result: RunStatusResult) -> str:
    """生成人类可读的 status 摘要。"""
    emoji = {
        "success": "✅",
        "partial": "⚠️",
        "failed": "❌",
    }
    e = emoji.get(result.run_status, "?")
    lines = [
        f"{e} run_status: {result.run_status}",
        f"   reason: {result.status_reason}",
    ]
    if result.status_tags:
        lines.append(f"   tags: {', '.join(result.status_tags)}")
    return "\n".join(lines)
