"""
Ranking - V2 批量排序

职责：只排序，不改 action。

职责边界（绝对不允许越过）：
  ranking.py 只读 decision_policy.py 的输出，不修改任何 action。

输入：多个 analyze() 结果（含 decision_rank_score / candidate_bucket）
输出：排序后的列表 + bucket 分组
"""
from typing import Any, Dict, List, Optional


def rank_results(
    results: List[Dict[str, Any]],
    sort_by: str = "score",
    top_n: Optional[int] = None,
) -> Dict[str, Any]:
    """
    对批量分析结果排序并分组。

    参数
    ----
    results : list[dict]
        多个 analyze() 返回结果
    sort_by : str
        排序字段，默认 "score"（即 decision_rank_score）
    top_n : int, optional
        只返回 top N

    返回
    ----
    dict {
        "ranked": list[dict],           # 排序后的结果
        "buckets": {
            "EXECUTE": list[dict],
            "CANDIDATE": list[dict],
            "AVOID": list[dict],
        },
        "summary": {
            "total": int,
            "execute_count": int,
            "candidate_count": int,
            "avoid_count": int,
            "avg_score": float,
        }
    }
    """
    if not results:
        return {
            "ranked": [],
            "buckets": {"EXECUTE": [], "CANDIDATE": [], "AVOID": []},
            "summary": {"total": 0, "execute_count": 0, "candidate_count": 0, "avoid_count": 0, "avg_score": 0.0},
        }

    # 过滤无效结果（无 score）
    valid = [r for r in results if r.get("decision_rank_score") is not None]
    invalid = [r for r in results if r.get("decision_rank_score") is None]

    # 按 score 降序
    sorted_results = sorted(
        valid,
        key=lambda r: r.get(sort_by, 0) or 0,
        reverse=True,
    )

    if top_n is not None:
        sorted_results = sorted_results[:top_n]

    # 按 bucket 分组
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "EXECUTE": [],
        "CANDIDATE": [],
        "AVOID": [],
    }
    for r in sorted_results:
        b = r.get("candidate_bucket", "CANDIDATE")
        if b not in buckets:
            buckets[b] = []
        buckets[b].append(r)

    # 统计
    all_scores = [r.get("decision_rank_score", 0) for r in valid]
    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0

    return {
        "ranked": sorted_results,
        "buckets": buckets,
        "summary": {
            "total": len(results),
            "valid_count": len(valid),
            "execute_count": len(buckets["EXECUTE"]),
            "candidate_count": len(buckets["CANDIDATE"]),
            "avoid_count": len(buckets["AVOID"]),
            "avg_score": round(avg_score, 4),
        },
    }


def format_ranking_summary(ranked: List[Dict[str, Any]]) -> str:
    """格式化排序摘要。"""
    if not ranked:
        return "无分析结果"

    lines = []
    for i, r in enumerate(ranked, 1):
        ticker = r.get("ticker", "?")
        action = r.get("decision", "?")
        raw = r.get("raw_decision", "?")
        score = r.get("decision_rank_score", 0)
        bucket = r.get("candidate_bucket", "?")
        hard = r.get("hard_constraints_hit", [])
        soft = r.get("soft_constraints_hit", [])

        tags = []
        if hard:
            tags.append("⚠️" + ",".join(hard))
        if soft:
            tags.append("⚡" + ",".join(soft))
        tag_str = " | " + " ".join(tags) if tags else ""

        reason = r.get("rank_reason", "")[:40]
        reason_str = f" [{reason}]" if reason else ""

        lines.append(
            f"  {i:2d}. {ticker:<12s} {action:<8s} (raw:{raw}) "
            f"score={score:.3f} bucket={bucket}{tag_str}{reason_str}"
        )

    return "\n".join(lines)


def format_bucket_summary(summary: Dict[str, Any]) -> str:
    """格式化分组统计。"""
    lines = [
        f"总计 {summary['total']} 只 | 有效 {summary['valid_count']} 只",
        f"  EXECUTE:   {summary['execute_count']:3d} 只",
        f"  CANDIDATE: {summary['candidate_count']:3d} 只",
        f"  AVOID:     {summary['avoid_count']:3d} 只",
        f"  平均分:    {summary['avg_score']:.4f}",
    ]
    return "\n".join(lines)
