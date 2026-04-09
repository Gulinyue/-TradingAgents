from typing import Any, Dict, List, Optional


DEFAULT_BUCKET_CONFIG: Dict[str, Any] = {
    "execute_actions": {"ENTER", "ADD", "HOLD"},
    "candidate_actions": {"ENTER", "ADD", "HOLD", "REVIEW"},
    "review_actions": {"REVIEW", "AVOID", "EXIT"},
    "execute_min_score": 0.65,
    "candidate_min_score": 0.45,
    "review_quality_levels": {"insufficient"},
    "warning_quality_levels": {"minimum_only"},
    "bucket_priority": {
        "EXECUTE": 1,
        "CANDIDATE": 2,
        "REVIEW": 3,
    },
}


def _normalize_action(result: Dict[str, Any]) -> str:
    action = (
        result.get("final_action")
        or result.get("decision")
        or result.get("action")
        or ""
    )
    return str(action).upper().strip()


def _get_data_completeness(result: Dict[str, Any]) -> Dict[str, Any]:
    data_completeness = result.get("data_completeness")
    if isinstance(data_completeness, dict):
        return data_completeness

    portfolio_context = result.get("portfolio_context") or {}
    nested = portfolio_context.get("data_completeness")
    if isinstance(nested, dict):
        return nested

    portfolio_snapshot = result.get("portfolio_snapshot") or {}
    nested = portfolio_snapshot.get("data_completeness")
    if isinstance(nested, dict):
        return nested

    return {}


def _has_blocking_constraints(result: Dict[str, Any]) -> bool:
    return bool(result.get("hard_constraints_hit") or [])


def _has_quality_blocker(data_completeness: Dict[str, Any], config: Dict[str, Any]) -> bool:
    quality_level = str(data_completeness.get("bar_quality_level") or "").lower()
    if quality_level in config["review_quality_levels"]:
        return True
    if data_completeness.get("review_required") is True:
        return True
    if data_completeness.get("has_minimum_bars") is False:
        return True
    return False


def _has_quality_warning(data_completeness: Dict[str, Any], config: Dict[str, Any]) -> bool:
    quality_level = str(data_completeness.get("bar_quality_level") or "").lower()
    return quality_level in config["warning_quality_levels"]


def _build_reason(parts: List[str]) -> str:
    return "; ".join(parts) if parts else "default candidate bucket policy"


def assign_candidate_bucket(
    result: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = dict(DEFAULT_BUCKET_CONFIG)
    if config:
        cfg.update(config)

    enriched = dict(result)
    action = _normalize_action(enriched)
    final_rank_score = enriched.get("final_rank_score")
    decision_rank_score = enriched.get("decision_rank_score")
    score = final_rank_score if final_rank_score is not None else decision_rank_score
    score = float(score) if score is not None else None
    data_completeness = _get_data_completeness(enriched)
    blocking_constraints = _has_blocking_constraints(enriched)
    quality_blocker = _has_quality_blocker(data_completeness, cfg)
    quality_warning = _has_quality_warning(data_completeness, cfg)
    reasons: List[str] = []

    if action in cfg["review_actions"]:
        reasons.append(f"final_action={action}")
        bucket = "REVIEW"
    elif quality_blocker:
        reasons.append("data_quality_below_minimum")
        bucket = "REVIEW"
    elif blocking_constraints:
        reasons.append("hard_constraints_blocking")
        bucket = "REVIEW"
    elif score is None:
        reasons.append("score_missing")
        bucket = "CANDIDATE"
    elif action in cfg["execute_actions"] and score >= cfg["execute_min_score"] and not quality_warning:
        reasons.append(f"final_rank_score>={cfg['execute_min_score']:.2f}")
        bucket = "EXECUTE"
    elif action in cfg["candidate_actions"] and score >= cfg["candidate_min_score"]:
        reasons.append("mid_score_or_waiting_confirmation")
        if quality_warning:
            reasons.append("data_quality_warning")
        bucket = "CANDIDATE"
    else:
        reasons.append("score_too_low_or_action_not_executable")
        if quality_warning:
            reasons.append("data_quality_warning")
        bucket = "REVIEW"

    enriched["candidate_bucket"] = bucket
    enriched["bucket_reason"] = _build_reason(reasons)
    enriched["bucket_priority"] = cfg["bucket_priority"][bucket]
    return enriched
