from tradingagents_runner.ranking import enrich_with_final_rank_score, rank_results


def test_v31_ranking_with_ml_score():
    result = enrich_with_final_rank_score(
        {
            "ticker": "600519.SH",
            "decision_rank_score": 0.8,
            "ml_score": 0.6,
        }
    )

    assert result["normalized_ml_score"] == 0.6
    assert result["final_rank_score"] == 0.76
    assert result["ranking_blend_applied"] is True


def test_v31_ranking_without_ml_score_falls_back_to_v2():
    result = enrich_with_final_rank_score(
        {
            "ticker": "600036.SH",
            "decision_rank_score": 0.8,
        }
    )

    assert result["normalized_ml_score"] is None
    assert result["final_rank_score"] == 0.8
    assert result["ranking_blend_applied"] is False


def test_v31_ranking_mixed_batch_orders_by_final_rank_score():
    ranked = rank_results(
        [
            {
                "ticker": "AAA",
                "decision": "ENTER",
                "raw_decision": "ENTER",
                "decision_rank_score": 0.7,
                "candidate_bucket": "EXECUTE",
            },
            {
                "ticker": "BBB",
                "decision": "ENTER",
                "raw_decision": "ENTER",
                "decision_rank_score": 0.68,
                "ml_score": 1.0,
                "candidate_bucket": "EXECUTE",
            },
            {
                "ticker": "CCC",
                "decision": "REVIEW",
                "raw_decision": "REVIEW",
                "decision_rank_score": 0.5,
                "ml_score": 0.1,
                "candidate_bucket": "CANDIDATE",
            },
        ]
    )

    assert [item["ticker"] for item in ranked["ranked"]] == ["BBB", "AAA", "CCC"]
    assert ranked["ranked"][0]["final_rank_score"] == 0.744
    assert ranked["ranked"][1]["final_rank_score"] == 0.7
    assert ranked["summary"]["ml_applied_count"] == 2
