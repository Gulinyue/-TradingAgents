from tradingagents_runner.candidate_bucket import assign_candidate_bucket
from tradingagents_runner.ranking import rank_results


def test_high_score_enter_goes_to_execute():
    result = assign_candidate_bucket(
        {
            "final_action": "ENTER",
            "decision_rank_score": 0.82,
            "final_rank_score": 0.82,
            "hard_constraints_hit": [],
            "data_completeness": {"bar_quality_level": "good", "has_minimum_bars": True},
        }
    )

    assert result["candidate_bucket"] == "EXECUTE"
    assert result["bucket_priority"] == 1
    assert result["final_action"] == "ENTER"


def test_mid_score_hold_goes_to_candidate():
    result = assign_candidate_bucket(
        {
            "final_action": "HOLD",
            "decision_rank_score": 0.58,
            "final_rank_score": 0.58,
            "hard_constraints_hit": [],
            "data_completeness": {"bar_quality_level": "good", "has_minimum_bars": True},
        }
    )

    assert result["candidate_bucket"] == "CANDIDATE"
    assert result["bucket_priority"] == 2


def test_review_or_low_quality_goes_to_review():
    by_action = assign_candidate_bucket(
        {
            "final_action": "REVIEW",
            "decision_rank_score": 0.7,
            "final_rank_score": 0.7,
        }
    )
    by_quality = assign_candidate_bucket(
        {
            "final_action": "ENTER",
            "decision_rank_score": 0.7,
            "final_rank_score": 0.7,
            "data_completeness": {"bar_quality_level": "insufficient", "has_minimum_bars": False},
        }
    )

    assert by_action["candidate_bucket"] == "REVIEW"
    assert by_quality["candidate_bucket"] == "REVIEW"


def test_bucket_assignment_does_not_modify_final_action():
    result = assign_candidate_bucket(
        {
            "final_action": "HOLD",
            "decision_rank_score": 0.4,
            "final_rank_score": 0.4,
        }
    )

    assert result["final_action"] == "HOLD"


def test_no_ml_score_still_assigns_bucket():
    ranked = rank_results(
        [
            {
                "ticker": "NO_ML",
                "final_action": "HOLD",
                "decision": "HOLD",
                "decision_rank_score": 0.6,
                "hard_constraints_hit": [],
                "data_completeness": {"bar_quality_level": "good", "has_minimum_bars": True},
            }
        ]
    )

    item = ranked["ranked"][0]
    assert item["ranking_blend_applied"] is False
    assert item["final_rank_score"] == 0.6
    assert item["candidate_bucket"] == "CANDIDATE"


def test_mixed_batch_sorting_respects_bucket_then_score():
    ranked = rank_results(
        [
            {
                "ticker": "EXECUTE_HIGH",
                "final_action": "ENTER",
                "decision": "ENTER",
                "decision_rank_score": 0.72,
                "hard_constraints_hit": [],
                "data_completeness": {"bar_quality_level": "good", "has_minimum_bars": True},
            },
            {
                "ticker": "CANDIDATE_MID",
                "final_action": "HOLD",
                "decision": "HOLD",
                "decision_rank_score": 0.57,
                "hard_constraints_hit": [],
                "data_completeness": {"bar_quality_level": "good", "has_minimum_bars": True},
            },
            {
                "ticker": "REVIEW_LOW",
                "final_action": "ENTER",
                "decision": "ENTER",
                "decision_rank_score": 0.4,
                "hard_constraints_hit": [],
                "data_completeness": {"bar_quality_level": "good", "has_minimum_bars": True},
            },
            {
                "ticker": "EXECUTE_HIGHER",
                "final_action": "ADD",
                "decision": "ADD",
                "decision_rank_score": 0.78,
                "hard_constraints_hit": [],
                "data_completeness": {"bar_quality_level": "good", "has_minimum_bars": True},
            },
        ]
    )

    assert [item["ticker"] for item in ranked["ranked"]] == [
        "EXECUTE_HIGHER",
        "EXECUTE_HIGH",
        "CANDIDATE_MID",
        "REVIEW_LOW",
    ]
    assert ranked["summary"]["execute_count"] == 2
    assert ranked["summary"]["candidate_count"] == 1
    assert ranked["summary"]["review_count"] == 1
