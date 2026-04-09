from tradingagents_runner.repositories import ResearchV2Repository


class StubResearchRepository(ResearchV2Repository):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _fetch_one(self, sql: str, params: tuple = ()):
        self.calls.append((sql, params))
        if self.responses:
            return self.responses.pop(0)
        return None


def test_account_prediction_is_preferred_over_global_prediction():
    repo = StubResearchRepository(
        [
            {"prediction_id": 10, "account_id": 1, "symbol": "600519.SH"},
            {"prediction_id": 99, "account_id": None, "symbol": "600519.SH"},
        ]
    )

    row = repo.get_latest_model_prediction(
        "600519.SH",
        account_id=1,
        prediction_date="2026-04-09",
        horizon="D1",
    )

    assert row["prediction_id"] == 10
    assert len(repo.calls) == 1
    assert "account_id = %s" in repo.calls[0][0]
    assert repo.calls[0][1] == ("600519.SH", 1, "2026-04-09", "D1")


def test_global_prediction_is_used_as_fallback_when_account_prediction_missing():
    repo = StubResearchRepository(
        [
            None,
            {"prediction_id": 99, "account_id": None, "symbol": "600519.SH"},
        ]
    )

    row = repo.get_latest_model_prediction(
        "600519.SH",
        account_id=1,
        prediction_date="2026-04-09",
        horizon="D1",
    )

    assert row["prediction_id"] == 99
    assert len(repo.calls) == 2
    assert "account_id = %s" in repo.calls[0][0]
    assert "account_id IS NULL" in repo.calls[1][0]
    assert repo.calls[0][1] == ("600519.SH", 1, "2026-04-09", "D1")
    assert repo.calls[1][1] == ("600519.SH", "2026-04-09", "D1")
