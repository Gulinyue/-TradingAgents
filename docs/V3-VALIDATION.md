# TradingAgents V3.1 Validation

## Scope

V3.1 only adds host-side model prediction writeback and VM-side ranking fusion.

Boundary kept unchanged:

- `TradingAgentsGraph` unchanged
- `decision_policy.py` action semantics unchanged
- ML does not modify `final_action`
- when `ml_score` is missing, ranking falls back to pure V2

## Stable Rules

Validated V3.1 rules:

- `research.model_predictions` writes succeeded in real PostgreSQL integration
- prediction reads must satisfy `prediction_date <= trade_date`
- ranking may only change `final_rank_score`, not `final_action`
- account-scoped predictions are preferred over global predictions
- when account-scoped predictions are absent, reads must fall back to global predictions
- all of `with ML / without ML / mixed batch` must work without changing actions

## Prediction Scope Contract

`research.model_predictions` supports two scopes:

- account-scoped prediction: `account_id IS NOT NULL`
- global prediction: `account_id IS NULL`

Read contract:

- prefer account-scoped prediction
- fall back to global prediction when account-scoped prediction is missing

## Validation Matrix

### 1. With ML score

Input:

- `decision_rank_score = 0.80`
- `ml_score = 0.60`

Expected:

- `normalized_ml_score = 0.60`
- `final_rank_score = 0.8 * 0.80 + 0.2 * 0.60 = 0.76`
- `final_action` unchanged

### 2. Without ML score

Input:

- `decision_rank_score = 0.80`
- `ml_score = null`

Expected:

- `normalized_ml_score = null`
- `final_rank_score = 0.80`
- `ranking_blend_applied = false`
- behavior matches V2

### 3. Mixed batch

Input:

- some symbols with ML
- some symbols without ML

Expected:

- ranking sorts by `final_rank_score`
- symbols without ML still participate using `decision_rank_score`
- `candidate_bucket` and `final_action` remain unchanged

## Regression Coverage

- `tests/test_v31_ranking.py`
- `tests/test_prediction_scope.py`

## Rollback

Rollback is file-local:

- revert `tradingagents_runner/repositories.py`
- revert `tradingagents_runner/portfolio_snapshot.py`
- revert `tradingagents_runner/ranking.py`
- revert `tradingagents_runner/runner.py`
- revert `docs/V3-VALIDATION.md`
