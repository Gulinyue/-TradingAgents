"""
Batch Summary 模块 - V2.1

职责：
  跑完 batch 自动产出一份结构化摘要，不需人工整理。
  支持 JSON 和 Markdown 两种格式。
"""
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

from run_status import evaluate_run_status, RunStatusResult


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

def build_batch_summary(
    run_results: List[Dict[str, Any]],
    account_code: str = "",
    watchlist_code: str = "",
    batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从 batch 运行的单票结果列表，生成结构化摘要。

    Parameters
    ----------
    run_results : list[dict]
        每只股票的运行结果，必须包含：
        - symbol: str
        - action: str
        - final_action: str
        - status: str
        - runtime_ms: int
        - bar_count: int
        - candidate_bucket: str
        - decision_rank_score: float
        - hard_constraints_hit: list[str]
        - soft_constraints_hit: list[str]
        - status_reason: str
        - technical_report_len: int
        - error: str (or None)
    account_code, watchlist_code: 上下文信息
    batch_id: 批次唯一标识

    Returns
    -------
    dict — 结构化摘要
    """
    n = len(run_results)
    if n == 0:
        return {"error": "no run results"}

    # ── 基础计数 ────────────────────────────────────────────────────────────
    statuses = Counter(r.get("status", "?") for r in run_results)
    actions = Counter(r.get("final_action", "?") for r in run_results)
    buckets = Counter(r.get("candidate_bucket", "?") for r in run_results)

    success_count = statuses.get("success", 0)
    partial_count = statuses.get("partial", 0)
    failed_count = statuses.get("failed", 0) + statuses.get("error", 0)

    # ── 约束命中统计 ────────────────────────────────────────────────────────
    hard_hit_counter = Counter()
    soft_hit_counter = Counter()
    for r in run_results:
        for h in r.get("hard_constraints_hit", []):
            hard_hit_counter[h] += 1
        for s in r.get("soft_constraints_hit", []):
            soft_hit_counter[s] += 1

    # ── 质量分布 ────────────────────────────────────────────────────────────
    tech_ok = sum(1 for r in run_results if r.get("technical_report_len", 0) > 100)
    bars_ok = sum(1 for r in run_results if r.get("bar_count", 0) >= 60)
    errors = [r["symbol"] for r in run_results if r.get("error")]

    # ── 排序分数 TOP ────────────────────────────────────────────────────────
    ranked = sorted(
        [r for r in run_results if r.get("decision_rank_score") is not None],
        key=lambda r: r.get("decision_rank_score", 0),
        reverse=True,
    )
    top_candidates = [
        {
            "symbol": r["symbol"],
            "score": round(r.get("decision_rank_score", 0), 4),
            "action": r.get("final_action", "?"),
            "bucket": r.get("candidate_bucket", "?"),
        }
        for r in ranked[:5]
    ]

    # ── 动作分布（不含 REVIEW 的可执行动作统计）─────
    actionable = [r for r in run_results if r.get("final_action") != "REVIEW"]
    action_dist_excl_review = Counter(r.get("final_action", "?") for r in actionable)

    # ── Runtime ─────────────────────────────────────────────────────────────
    runtimes = [r.get("runtime_ms", 0) for r in run_results if r.get("runtime_ms")]
    avg_runtime_s = round(sum(runtimes) / len(runtimes) / 1000, 1) if runtimes else 0

    # ── 软约束最多命中原因 ─────────────────────────────────────────────────
    top_soft = [
        {"constraint": k, "count": v, "pct": round(v / n * 100, 1)}
        for k, v in soft_hit_counter.most_common(5)
    ]

    return {
        "batch_id": batch_id or datetime.utcnow().strftime("%Y%m%d%H%M%S"),
        "generated_at": datetime.utcnow().isoformat(),
        "context": {
            "account_code": account_code,
            "watchlist_code": watchlist_code,
            "total_symbols": n,
        },
        "counts": {
            "success": success_count,
            "partial": partial_count,
            "failed": failed_count,
            "errors": len(errors),
        },
        "action_distribution": dict(actions),
        "action_distribution_excl_review": dict(action_dist_excl_review),
        "bucket_distribution": dict(buckets),
        "status_distribution": dict(statuses),
        "runtime": {
            "avg_seconds": avg_runtime_s,
            "total_seconds": round(sum(runtimes) / 1000, 1) if runtimes else 0,
        },
        "quality": {
            "technical_report_ok": tech_ok,
            "bars_ok": bars_ok,
            "tech_ok_pct": round(tech_ok / n * 100, 1),
            "bars_ok_pct": round(bars_ok / n * 100, 1),
        },
        "top_ranked_candidates": top_candidates,
        "constraint_hits": {
            "hard": dict(hard_hit_counter),
            "soft": dict(soft_hit_counter),
            "soft_top": top_soft,
        },
        "errors": errors,
        "per_symbol": [
            {
                "symbol": r["symbol"],
                "action": r.get("final_action", "?"),
                "bucket": r.get("candidate_bucket", "?"),
                "score": r.get("decision_rank_score"),
                "status": r.get("status", "?"),
                "tech_len": r.get("technical_report_len", 0),
                "bars": r.get("bar_count", 0),
                "error": r.get("error"),
            }
            for r in run_results
        ],
    }


def render_batch_summary_markdown(summary: Dict[str, Any]) -> str:
    """将 batch 摘要渲染为 Markdown 格式。"""
    ctx = summary.get("context", {})
    cnt = summary.get("counts", {})
    act = summary.get("action_distribution", {})
    bkt = summary.get("bucket_distribution", {})
    qual = summary.get("quality", {})
    top = summary.get("top_ranked_candidates", [])
    soft = summary.get("constraint_hits", {}).get("soft_top", [])
    rt = summary.get("runtime", {})

    lines = [
        "# Batch Summary",
        "",
        f"**Batch ID:** `{summary.get('batch_id', '?')}`  "
        f"**Generated:** {summary.get('generated_at', '')}",
        "",
        f"**Account:** `{ctx.get('account_code', '?')}`  "
        f"**Watchlist:** `{ctx.get('watchlist_code', '?')}`  "
        f"**Total:** `{ctx.get('total_symbols', 0)}` 只",
        "",
        "---",
        "",
        "## 状态概览",
        "",
        "| 状态 | 数量 | 占比 |",
        "|-----|-----|-----|",
    ]

    n = ctx.get("total_symbols", 1) or 1
    for st, label in [("success", "✅ Success"), ("partial", "⚠️ Partial"), ("failed", "❌ Failed")]:
        c = cnt.get(st, 0)
        pct = round(c / n * 100, 1)
        lines.append(f"| {label} | {c} | {pct}% |")

    lines += [
        "",
        "## 动作分布",
        "",
        "| 动作 | 数量 |",
        "|-----|-----|",
    ]
    for a, c in sorted(act.items(), key=lambda x: -x[1]):
        lines.append(f"| {a} | {c} |")

    if top:
        lines += [
            "",
            "## TOP 候选（按分数）",
            "",
            "| 股票 | 动作 | Bucket | 分数 |",
            "|-----|-----|-------|-----|",
        ]
        for r in top:
            lines.append(
                f"| {r['symbol']} | {r['action']} | {r['bucket']} | {r['score']} |"
            )

    if soft:
        lines += [
            "",
            "## 软约束命中（TOP 5）",
            "",
            "| 约束 | 次数 | 占比 |",
            "|-----|-----|-----|",
        ]
        for s in soft:
            lines.append(f"| {s['constraint']} | {s['count']} | {s['pct']}% |")

    lines += [
        "",
        "## 质量指标",
        "",
        f"- 技术报告充足（>100 chars）：{qual.get('technical_report_ok', 0)}/{n} ({qual.get('tech_ok_pct', 0)}%)",
        f"- Bar 充足（≥60）：{qual.get('bars_ok', 0)}/{n} ({qual.get('bars_ok_pct', 0)}%)",
        f"- 平均运行时长：{rt.get('avg_seconds', 0)}s",
        "",
        "## 单票详情",
        "",
        "| 股票 | 动作 | Bucket | 分数 | Status | Tech len | Bars |",
        "|-----|-----|-------|-----|--------|---------|-----|",
    ]

    for r in summary.get("per_symbol", []):
        err = f"⚠️ {r.get('error', '')[:30]}" if r.get("error") else ""
        lines.append(
            f"| {r['symbol']} | {r.get('action','?')} | "
            f"{r.get('bucket','?')} | {r.get('score','?')} | "
            f"{r.get('status','?')} | {r.get('tech_len',0)} | "
            f"{r.get('bars',0)} | {err}"
        )

    return "\n".join(lines)


def render_batch_summary_json(summary: Dict[str, Any]) -> Dict[str, Any]:
    """直接返回 JSON-safe 的摘要 dict（供外部消费）。"""
    return summary  # 已经是 JSON-safe（输入已 deep_serialize）
