"""
Ranking - V2 批量排序

职责：只排序，不改 action。

职责边界（绝对不允许越过）：
  ranking.py 只读 decision_policy.py 的输出，不修改任何 action。

输入：多个 analyze() 结果（含 decision_rank_score / candidate_bucket）
输出：排序后的列表 + bucket 分组
"""
from typing import Any, Dict, List, Optional


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, round(float(value), 4)))


def _normalize_scalar_score(value: Any) -> Optional[float]:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None

    if 0.0 <= score <= 1.0:
        return _clip01(score)
    if -1.0 <= score <= 1.0:
        return _clip01((score + 1.0) / 2.0)
    return None


def normalize_ml_score(result: Dict[str, Any]) -> Optional[float]:
    """
    将宿主机模型输出归一化到 0~1。

    支持优先级：
    1. result["normalized_ml_score"]
    2. result["ml_score"]
    3. result["latest_prediction"]["score"]
    4. result["latest_prediction"]["label"]
    """
    for key in ("normalized_ml_score", "ml_score"):
        value = result.get(key)
        if value is not None:
            return _normalize_scalar_score(value)

    pred = result.get("latest_prediction") or {}
    if pred.get("score") is not None:
        return _normalize_scalar_score(pred["score"])

    label = str(pred.get("label") or "").strip().lower()
    if label in {"bullish", "buy", "up", "positive", "long"}:
        return 1.0
    if label in {"neutral", "hold", "flat"}:
        return 0.5
    if label in {"bearish", "sell", "down", "negative", "short"}:
        return 0.0
    return None


def enrich_with_final_rank_score(
    result: Dict[str, Any],
    *,
    decision_weight: float = 0.8,
    ml_weight: float = 0.2,
) -> Dict[str, Any]:
    """
    基于 V2 decision_rank_score 叠加 ML 分。

    关键边界：
    - 只产生排序分，不改任何 action
    - 没有 ML 分时完全回退到 V2
    """
    enriched = dict(result)
    decision_rank_score = enriched.get("decision_rank_score")
    normalized_ml_score = normalize_ml_score(enriched)

    enriched["normalized_ml_score"] = normalized_ml_score

    if decision_rank_score is None:
        enriched["final_rank_score"] = None
        enriched["ranking_blend_applied"] = False
        return enriched

    if normalized_ml_score is None:
        enriched["final_rank_score"] = round(float(decision_rank_score), 4)
        enriched["ranking_blend_applied"] = False
        return enriched

    enriched["final_rank_score"] = round(
        decision_weight * float(decision_rank_score) + ml_weight * normalized_ml_score,
        4,
    )
    enriched["ranking_blend_applied"] = True
    return enriched


def rank_results(
    results: List[Dict[str, Any]],
    sort_by: str = "final_rank_score",
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

    enriched_results = [enrich_with_final_rank_score(r) for r in results]

    # 过滤无效结果（无基础 decision score）
    valid = [r for r in enriched_results if r.get("decision_rank_score") is not None]
    invalid = [r for r in enriched_results if r.get("decision_rank_score") is None]

    # 按最终排序分降序
    sorted_results = sorted(
        valid,
        key=lambda r: r.get(sort_by) if r.get(sort_by) is not None else (r.get("decision_rank_score", 0) or 0),
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
    all_final_scores = [r.get("final_rank_score", 0) for r in valid]
    all_decision_scores = [r.get("decision_rank_score", 0) for r in valid]
    avg_score = sum(all_final_scores) / len(all_final_scores) if all_final_scores else 0.0
    avg_decision_score = (
        sum(all_decision_scores) / len(all_decision_scores)
        if all_decision_scores else 0.0
    )
    ml_applied_count = sum(1 for r in valid if r.get("ranking_blend_applied"))

    return {
        "ranked": sorted_results,
        "buckets": buckets,
        "summary": {
            "total": len(results),
            "valid_count": len(valid),
            "invalid_count": len(invalid),
            "execute_count": len(buckets["EXECUTE"]),
            "candidate_count": len(buckets["CANDIDATE"]),
            "avoid_count": len(buckets["AVOID"]),
            "avg_score": round(avg_score, 4),
            "avg_decision_rank_score": round(avg_decision_score, 4),
            "ml_applied_count": ml_applied_count,
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
        score = r.get("final_rank_score")
        if score is None:
            score = r.get("decision_rank_score", 0)
        bucket = r.get("candidate_bucket", "?")
        hard = r.get("hard_constraints_hit", [])
        soft = r.get("soft_constraints_hit", [])
        ml_score = r.get("normalized_ml_score")

        tags = []
        if hard:
            tags.append("⚠️" + ",".join(hard))
        if soft:
            tags.append("⚡" + ",".join(soft))
        if ml_score is not None:
            tags.append(f"ML={ml_score:.3f}")
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
        f"总计 {summary['total']} 只 | 有效 {summary['valid_count']} 只 | 无效 {summary['invalid_count']} 只",
        f"  EXECUTE:   {summary['execute_count']:3d} 只",
        f"  CANDIDATE: {summary['candidate_count']:3d} 只",
        f"  AVOID:     {summary['avoid_count']:3d} 只",
        f"  最终均分:  {summary['avg_score']:.4f}",
        f"  决策均分:  {summary['avg_decision_rank_score']:.4f}",
        f"  ML 融合:   {summary['ml_applied_count']:3d} 只",
    ]
    return "\n".join(lines)
