"""
Batch Summary - V3.2

Build a structured batch summary with candidate bucket distribution.
"""

from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional


def _ranked_sort_key(result: Dict[str, Any]) -> tuple:
    final_rank_score = result.get("final_rank_score")
    decision_rank_score = result.get("decision_rank_score", 0) or 0
    return (
        result.get("bucket_priority", 99),
        -(float(final_rank_score) if final_rank_score is not None else float(decision_rank_score)),
        -float(decision_rank_score),
    )


def build_batch_summary(
    run_results: List[Dict[str, Any]],
    account_code: str = "",
    watchlist_code: str = "",
    batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    n = len(run_results)
    if n == 0:
        return {"error": "no run results"}

    statuses = Counter(result.get("status", "?") for result in run_results)
    actions = Counter(result.get("final_action", "?") for result in run_results)
    buckets = Counter(result.get("candidate_bucket", "?") for result in run_results)

    success_count = statuses.get("success", 0)
    partial_count = statuses.get("partial", 0)
    failed_count = statuses.get("failed", 0) + statuses.get("error", 0)

    hard_hit_counter = Counter()
    soft_hit_counter = Counter()
    for result in run_results:
        for item in result.get("hard_constraints_hit", []):
            hard_hit_counter[item] += 1
        for item in result.get("soft_constraints_hit", []):
            soft_hit_counter[item] += 1

    tech_ok = sum(1 for result in run_results if result.get("technical_report_len", 0) > 100)
    bars_ok = sum(1 for result in run_results if result.get("bar_count", 0) >= 60)
    errors = [result["symbol"] for result in run_results if result.get("error")]

    ranked = sorted(
        [result for result in run_results if result.get("decision_rank_score") is not None],
        key=_ranked_sort_key,
    )
    top_candidates = [
        {
            "symbol": result["symbol"],
            "score": round(
                result.get("final_rank_score")
                if result.get("final_rank_score") is not None
                else result.get("decision_rank_score", 0),
                4,
            ),
            "action": result.get("final_action", "?"),
            "bucket": result.get("candidate_bucket", "?"),
        }
        for result in ranked[:5]
    ]

    actionable = [result for result in run_results if result.get("final_action") != "REVIEW"]
    action_dist_excl_review = Counter(result.get("final_action", "?") for result in actionable)

    runtimes = [result.get("runtime_ms", 0) for result in run_results if result.get("runtime_ms")]
    avg_runtime_s = round(sum(runtimes) / len(runtimes) / 1000, 1) if runtimes else 0

    top_soft = [
        {"constraint": key, "count": value, "pct": round(value / n * 100, 1)}
        for key, value in soft_hit_counter.most_common(5)
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
        "execute_count": buckets.get("EXECUTE", 0),
        "candidate_count": buckets.get("CANDIDATE", 0),
        "review_count": buckets.get("REVIEW", 0),
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
                "symbol": result["symbol"],
                "action": result.get("final_action", "?"),
                "bucket": result.get("candidate_bucket", "?"),
                "score": result.get("final_rank_score")
                if result.get("final_rank_score") is not None
                else result.get("decision_rank_score"),
                "status": result.get("status", "?"),
                "tech_len": result.get("technical_report_len", 0),
                "bars": result.get("bar_count", 0),
                "error": result.get("error"),
            }
            for result in run_results
        ],
    }


def render_batch_summary_markdown(summary: Dict[str, Any]) -> str:
    ctx = summary.get("context", {})
    cnt = summary.get("counts", {})
    act = summary.get("action_distribution", {})
    qual = summary.get("quality", {})
    top = summary.get("top_ranked_candidates", [])
    soft = summary.get("constraint_hits", {}).get("soft_top", [])
    runtime = summary.get("runtime", {})

    lines = [
        "# Batch Summary",
        "",
        f"**Batch ID:** `{summary.get('batch_id', '?')}`  "
        f"**Generated:** {summary.get('generated_at', '')}",
        "",
        f"**Account:** `{ctx.get('account_code', '?')}`  "
        f"**Watchlist:** `{ctx.get('watchlist_code', '?')}`  "
        f"**Total:** `{ctx.get('total_symbols', 0)}`",
        "",
        "## Status",
        "",
        "| Status | Count | Pct |",
        "|-----|-----|-----|",
    ]

    total = ctx.get("total_symbols", 1) or 1
    for status, label in [("success", "Success"), ("partial", "Partial"), ("failed", "Failed")]:
        count = cnt.get(status, 0)
        lines.append(f"| {label} | {count} | {round(count / total * 100, 1)}% |")

    lines += [
        "",
        "## Action Distribution",
        "",
        "| Action | Count |",
        "|-----|-----|",
    ]
    for action, count in sorted(act.items(), key=lambda item: -item[1]):
        lines.append(f"| {action} | {count} |")

    lines += [
        "",
        "## Bucket Distribution",
        "",
        f"- EXECUTE: {summary.get('execute_count', 0)}",
        f"- CANDIDATE: {summary.get('candidate_count', 0)}",
        f"- REVIEW: {summary.get('review_count', 0)}",
    ]

    if top:
        lines += [
            "",
            "## Top Candidates",
            "",
            "| Symbol | Action | Bucket | Score |",
            "|-----|-----|-------|-----|",
        ]
        for result in top:
            lines.append(
                f"| {result['symbol']} | {result['action']} | {result['bucket']} | {result['score']} |"
            )

    if soft:
        lines += [
            "",
            "## Soft Constraints Top 5",
            "",
            "| Constraint | Count | Pct |",
            "|-----|-----|-----|",
        ]
        for item in soft:
            lines.append(f"| {item['constraint']} | {item['count']} | {item['pct']}% |")

    lines += [
        "",
        "## Quality",
        "",
        f"- technical_report_ok: {qual.get('technical_report_ok', 0)}/{total} ({qual.get('tech_ok_pct', 0)}%)",
        f"- bars_ok: {qual.get('bars_ok', 0)}/{total} ({qual.get('bars_ok_pct', 0)}%)",
        f"- avg_runtime_seconds: {runtime.get('avg_seconds', 0)}",
        "",
        "## Per Symbol",
        "",
        "| Symbol | Action | Bucket | Score | Status | Tech len | Bars |",
        "|-----|-----|-------|-----|--------|---------|-----|",
    ]

    for result in summary.get("per_symbol", []):
        lines.append(
            f"| {result['symbol']} | {result.get('action', '?')} | {result.get('bucket', '?')} | "
            f"{result.get('score', '?')} | {result.get('status', '?')} | "
            f"{result.get('tech_len', 0)} | {result.get('bars', 0)} |"
        )

    return "\n".join(lines)


def render_batch_summary_json(summary: Dict[str, Any]) -> Dict[str, Any]:
    return summary
