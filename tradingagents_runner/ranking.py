"""
Ranking - V3.2

Responsibilities:
- Keep final action untouched.
- Blend ML score into ranking only.
- Produce candidate bucket outputs for batch sorting and downstream reporting.
"""

from typing import Any, Dict, List, Optional

try:
    from tradingagents_runner.candidate_bucket import assign_candidate_bucket
except ImportError:
    from candidate_bucket import assign_candidate_bucket


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
    Normalize host-side ML outputs to 0~1.
    Priority:
    1. result["normalized_ml_score"]
    2. result["ml_score"]
    3. result["latest_prediction"]["score"]
    4. result["latest_prediction"]["label"]
    """
    for key in ("normalized_ml_score", "ml_score"):
        value = result.get(key)
        if value is not None:
            return _normalize_scalar_score(value)

    prediction = result.get("latest_prediction") or {}
    if prediction.get("score") is not None:
        return _normalize_scalar_score(prediction["score"])

    label = str(prediction.get("label") or "").strip().lower()
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
    Produce V3.1 final rank score.
    This function never changes the action. If no ML score exists, it fully falls
    back to V2.1 decision_rank_score.
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


def enrich_with_ranking_fields(
    result: Dict[str, Any],
    *,
    decision_weight: float = 0.8,
    ml_weight: float = 0.2,
    bucket_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    enriched = enrich_with_final_rank_score(
        result,
        decision_weight=decision_weight,
        ml_weight=ml_weight,
    )
    return assign_candidate_bucket(enriched, config=bucket_config)


def _sort_score(result: Dict[str, Any], sort_by: str) -> float:
    value = result.get(sort_by)
    if value is not None:
        return float(value)
    fallback = result.get("decision_rank_score")
    return float(fallback) if fallback is not None else 0.0


def rank_results(
    results: List[Dict[str, Any]],
    sort_by: str = "final_rank_score",
    top_n: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Rank analyze() outputs using:
    1. bucket_priority
    2. final_rank_score desc
    3. decision_rank_score desc
    """
    if not results:
        return {
            "ranked": [],
            "buckets": {"EXECUTE": [], "CANDIDATE": [], "REVIEW": []},
            "summary": {
                "total": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "execute_count": 0,
                "candidate_count": 0,
                "review_count": 0,
                "bucket_distribution": {
                    "EXECUTE": 0,
                    "CANDIDATE": 0,
                    "REVIEW": 0,
                },
                "avg_score": 0.0,
                "avg_decision_rank_score": 0.0,
                "ml_applied_count": 0,
            },
        }

    enriched_results = [enrich_with_ranking_fields(result) for result in results]
    valid = [result for result in enriched_results if result.get("decision_rank_score") is not None]
    invalid = [result for result in enriched_results if result.get("decision_rank_score") is None]

    sorted_results = sorted(
        valid,
        key=lambda result: (
            result.get("bucket_priority", 99),
            -_sort_score(result, sort_by),
            -(float(result.get("decision_rank_score") or 0.0)),
        ),
    )

    if top_n is not None:
        sorted_results = sorted_results[:top_n]

    buckets: Dict[str, List[Dict[str, Any]]] = {
        "EXECUTE": [],
        "CANDIDATE": [],
        "REVIEW": [],
    }
    for result in sorted_results:
        bucket = result.get("candidate_bucket", "CANDIDATE")
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append(result)

    final_scores = [
        float(result["final_rank_score"])
        for result in valid
        if result.get("final_rank_score") is not None
    ]
    decision_scores = [
        float(result["decision_rank_score"])
        for result in valid
        if result.get("decision_rank_score") is not None
    ]

    return {
        "ranked": sorted_results,
        "buckets": buckets,
        "summary": {
            "total": len(results),
            "valid_count": len(valid),
            "invalid_count": len(invalid),
            "execute_count": len(buckets["EXECUTE"]),
            "candidate_count": len(buckets["CANDIDATE"]),
            "review_count": len(buckets["REVIEW"]),
            "bucket_distribution": {
                bucket: len(items) for bucket, items in buckets.items()
            },
            "avg_score": round(sum(final_scores) / len(final_scores), 4) if final_scores else 0.0,
            "avg_decision_rank_score": round(sum(decision_scores) / len(decision_scores), 4)
            if decision_scores else 0.0,
            "ml_applied_count": sum(
                1 for result in valid if result.get("ranking_blend_applied")
            ),
        },
    }


def format_ranking_summary(ranked: List[Dict[str, Any]]) -> str:
    if not ranked:
        return "No ranked results"

    lines = []
    for index, result in enumerate(ranked, 1):
        ticker = result.get("ticker", "?")
        action = result.get("decision") or result.get("final_action") or "?"
        raw = result.get("raw_decision", "?")
        score = result.get("final_rank_score")
        if score is None:
            score = result.get("decision_rank_score", 0)
        bucket = result.get("candidate_bucket", "?")
        hard = result.get("hard_constraints_hit", [])
        soft = result.get("soft_constraints_hit", [])
        ml_score = result.get("normalized_ml_score")

        tags = []
        if hard:
            tags.append("hard=" + ",".join(hard))
        if soft:
            tags.append("soft=" + ",".join(soft))
        if ml_score is not None:
            tags.append(f"ML={ml_score:.3f}")
        tag_str = " | " + " ".join(tags) if tags else ""

        reason = (result.get("bucket_reason") or result.get("rank_reason") or "")[:40]
        reason_str = f" [{reason}]" if reason else ""

        lines.append(
            f"  {index:2d}. {ticker:<12s} {action:<8s} (raw:{raw}) "
            f"score={float(score):.3f} bucket={bucket}{tag_str}{reason_str}"
        )

    return "\n".join(lines)


def format_bucket_summary(summary: Dict[str, Any]) -> str:
    lines = [
        f"total {summary['total']} | valid {summary['valid_count']} | invalid {summary['invalid_count']}",
        f"  EXECUTE:   {summary['execute_count']:3d}",
        f"  CANDIDATE: {summary['candidate_count']:3d}",
        f"  REVIEW:    {summary['review_count']:3d}",
        f"  final_avg: {summary['avg_score']:.4f}",
        f"  decision_avg: {summary['avg_decision_rank_score']:.4f}",
        f"  ml_blended: {summary['ml_applied_count']:3d}",
    ]
    return "\n".join(lines)
