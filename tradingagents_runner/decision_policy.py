"""
Decision Policy - V2 唯一决策出口

职责：接收 raw_action 和 portfolio_context，产出 final_action。

职责边界（绝对不允许越过）：
  portfolio_snapshot.py  = 取数据（原始事实）
  portfolio_context.py   = 组装上下文（决策语义对象）
  decision_policy.py     = 唯一决策出口（final_action / reasons / score）
  ranking.py            = 排序（只读 decision，不改 action）
  runner.py             = 编排（调用以上四者，不自行修正 action）

七类动作：ENTER / ADD / HOLD / TRIM / EXIT / AVOID / REVIEW
"""
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# 动作定义
# ─────────────────────────────────────────────────────────────────────────────

VALID_ACTIONS = {"ENTER", "ADD", "HOLD", "TRIM", "EXIT", "AVOID", "REVIEW"}


def _normalize_action(raw: Any) -> str:
    """将任意动作词归一化为七类动作之一。"""
    s = str(raw).upper().strip()
    if any(k in s for k in ("BUY", "买入", "增持", "ENTER", "做多")):
        return "ENTER"
    if any(k in s for k in ("ADD", "加仓")):
        return "ADD"
    if any(k in s for k in ("SELL", "卖出", "减仓", "TRIM")):
        return "SELL"
    if any(k in s for k in ("HOLD", "持有", "观望")):
        return "HOLD"
    if any(k in s for k in ("EXIT", "清仓", "平仓")):
        return "EXIT"
    if any(k in s for k in ("AVOID", "回避", "规避")):
        return "AVOID"
    if any(k in s for k in ("REVIEW", "复核", "待定", "SCAN")):
        return "REVIEW"
    return "REVIEW"  # 默认


def _is_bullish(action: str) -> bool:
    return action in ("ENTER", "ADD")


def _is_bearish(action: str) -> bool:
    return action in ("EXIT", "AVOID")


# ─────────────────────────────────────────────────────────────────────────────
# 硬约束检查
# ─────────────────────────────────────────────────────────────────────────────

def _check_hard_constraints(portfolio_ctx: Dict[str, Any]) -> Dict[str, bool]:
    """
    检查硬约束，返回触发标记字典。
    """
    c = portfolio_ctx.get("constraints", {})
    max_sym_w = c.get("max_symbol_weight_pct", 20.0)
    max_sec_w = c.get("max_sector_weight_pct", 35.0)
    min_cash_r = c.get("min_cash_ratio_pct", 5.0)

    return {
        "cash_insufficient": portfolio_ctx.get("cash_ratio_pct", 0) < min_cash_r,
        "symbol_overweight": portfolio_ctx.get("current_weight_pct", 0) >= max_sym_w,
        "sector_concentrated": portfolio_ctx.get("is_sector_concentrated", False),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 软约束检查
# ─────────────────────────────────────────────────────────────────────────────

def _check_soft_constraints(portfolio_ctx: Dict[str, Any]) -> Dict[str, bool]:
    """
    检查软约束，返回触发标记字典。
    """
    dc = portfolio_ctx.get("data_completeness") or {}
    return {
        "data_incomplete": dc.get("review_required", False),
        "no_factors": dc.get("has_factors") is False,
        "no_bar": dc.get("has_bar") is False,
        "has_ml_prediction": dc.get("has_prediction", False),
        "high_concentration": portfolio_ctx.get("is_sector_concentrated", False),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 核心决策函数
# ─────────────────────────────────────────────────────────────────────────────

def decide(
    raw_action: str,
    raw_confidence: Optional[float],
    raw_risk_level: Optional[str],
    raw_summary: str,
    raw_decision_json: Optional[Dict[str, Any]],
    portfolio_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """
    V2 唯一决策出口。

    参数
    ----
    raw_action : str
        TA 原始结论
    raw_confidence : float, optional
        TA 原始置信度
    raw_risk_level : str, optional
        TA 原始风险等级
    raw_summary : str
        TA 原始摘要
    raw_decision_json : dict, optional
        TA 原始决策 JSON
    portfolio_ctx : dict
        portfolio_context.build_context() 输出

    返回
    ----
    dict {
        "raw_action": str,
        "final_action": str,
        "overlay_applied": bool,
        "overlay_reasons": list[str],
        "hard_constraints_hit": list[str],
        "soft_constraints_hit": list[str],
        "decision_rank_score": float,    # 0~1，越高越应执行
        "candidate_bucket": str,         # EXECUTE / CANDIDATE / AVOID
        "rank_reason": str,
    }
    """
    raw = _normalize_action(raw_action)
    is_held = portfolio_ctx.get("is_held", False)
    hard = _check_hard_constraints(portfolio_ctx)
    soft = _check_soft_constraints(portfolio_ctx)
    is_core = portfolio_ctx.get("is_core_holding", False)

    hard_hit = [k for k, v in hard.items() if v]
    soft_hit = [k for k, v in soft.items() if v]
    reasons: List[str] = []
    final = raw
    overlay_applied = False

    # ── 第一优先级：硬降级 ───────────────────────────────────
    # 现金不足：所有看多动作降为 REVIEW 或 AVOID
    if hard.get("cash_insufficient"):
        overlay_applied = True
        if raw in ("ENTER", "ADD"):
            final = "AVOID"
            reasons.append("cash_insufficient: 现金不足，禁止新建/加仓")
        elif raw == "HOLD":
            final = "HOLD"  # 已有仓位不强制清
            reasons.append("cash_insufficient: 现金不足，维持现有持仓")

    # 单票超限：ADD → HOLD
    if hard.get("symbol_overweight"):
        overlay_applied = True
        if final == "ADD":
            final = "HOLD"
            reasons.append("symbol_overweight: 单票权重已达上限")
        elif final == "ENTER":
            final = "REVIEW"
            reasons.append("symbol_overweight: 目标仓位超限，降为 REVIEW")

    # 行业超配：ENTER → REVIEW / ADD → HOLD
    if hard.get("sector_concentrated"):
        overlay_applied = True
        if final == "ENTER":
            final = "REVIEW"
            reasons.append("sector_concentrated: 行业已超配，新建仓降为 REVIEW")
        elif final == "ADD":
            final = "HOLD"
            reasons.append("sector_concentrated: 行业超配，ADD 降为 HOLD")

    # ── 第二优先级：持仓语义修正 ───────────────────────────────
    if not hard_hit:  # 无硬约束时执行
        if is_held:
            # 已有持仓
            if _is_bullish(raw):
                if final == "ENTER":
                    final = "ADD"
                    reasons.append("already_held: 已有持仓，ENTER → ADD")
                    overlay_applied = True
            if _is_bearish(raw):
                if final == "EXIT":
                    final = "TRIM"
                    reasons.append("reduce_position: 已有持仓，EXIT → TRIM")
                    overlay_applied = True
        else:
            # 未持仓
            if raw == "SELL":
                final = "AVOID"
                reasons.append("not_held: 未持仓，SELL → AVOID")
                overlay_applied = True

    # ── 第三优先级：软约束保守化 ──────────────────────────────
    if soft.get("data_incomplete"):
        reasons.append("data_incomplete: 数据不完整，动作保持保守")
        # REVIEW 本身已经是保守动作，不需要降级
    if soft.get("no_bar"):
        reasons.append("no_bar: 无行情数据，动作保持保守")

    # ── 核心持仓池特殊标注 ────────────────────────────────────
    if is_core and raw in ("ENTER", "ADD", "HOLD"):
        reasons.append("core_holding_pool: 来自核心持仓关注池")

    # ── 计算决策排序分数 ──────────────────────────────────────
    score = _compute_rank_score(
        raw_action=raw,
        final_action=final,
        confidence=raw_confidence,
        hard_hit=hard_hit,
        soft_hit=soft_hit,
        is_held=is_held,
        is_core=is_core,
        ctx=portfolio_ctx,
    )

    # ── 决定候选桶 ───────────────────────────────────────────
    bucket = _assign_bucket(final, hard_hit, soft_hit)

    # ── 汇总 final_summary / rank_reason ────────────────────
    rank_reason = _build_rank_reason(raw, final, hard_hit, soft_hit, is_core)

    return {
        "raw_action": raw,
        "final_action": final,
        "overlay_applied": overlay_applied,
        "overlay_reasons": reasons,
        "hard_constraints_hit": hard_hit,
        "soft_constraints_hit": soft_hit,
        "decision_rank_score": score,
        "candidate_bucket": bucket,
        "rank_reason": rank_reason,
    }


def _compute_rank_score(
    raw_action: str,
    final_action: str,
    confidence: Optional[float],
    hard_hit: List[str],
    soft_hit: List[str],
    is_held: bool,
    is_core: bool,
    ctx: Dict[str, Any],
) -> float:
    """
    计算 0~1 的决策排序分数，越高越应执行。

    逻辑：
    - 执行类动作（ENTER/ADD/HOLD）分数较高
    - 被硬约束降级后分数降低
    - 软约束存在时分数降低
    - 核心池加分
    """
    score = 0.5

    # 基础动作分
    action_scores = {
        "ENTER": 0.90,
        "ADD": 0.85,
        "HOLD": 0.70,
        "TRIM": 0.50,
        "REVIEW": 0.40,
        "EXIT": 0.30,
        "AVOID": 0.10,
    }
    score = action_scores.get(final_action, 0.5)

    # 置信度加权
    if confidence is not None:
        score = score * (0.5 + 0.5 * confidence)

    # 硬约束惩罚
    score -= len(hard_hit) * 0.20

    # 软约束惩罚
    score -= len(soft_hit) * 0.05

    # 核心池加分
    if is_core:
        score += 0.05

    # 已有盈利持仓（HOLD 强化）
    if is_held and final_action == "HOLD":
        pnl = ctx.get("unrealized_pnl", 0)
        if pnl > 0:
            score += 0.05

    return max(0.0, min(1.0, round(score, 4)))


def _assign_bucket(
    final_action: str,
    hard_hit: List[str],
    soft_hit: List[str],
) -> str:
    """分配候选桶。"""
    if final_action == "AVOID":
        return "AVOID"
    if hard_hit or final_action in ("REVIEW",):
        return "CANDIDATE"
    if final_action in ("ENTER", "ADD", "HOLD", "TRIM"):
        return "EXECUTE"
    return "CANDIDATE"


def _build_rank_reason(
    raw_action: str,
    final_action: str,
    hard_hit: List[str],
    soft_hit: List[str],
    is_core: bool,
) -> str:
    parts = []
    if raw_action != final_action:
        parts.append(f"原始信号 {raw_action} → {final_action}")
    if hard_hit:
        parts.append(f"硬约束触发: {', '.join(hard_hit)}")
    if soft_hit:
        parts.append(f"软约束: {', '.join(soft_hit)}")
    if is_core:
        parts.append("核心持仓池标的")
    return "; ".join(parts) if parts else "无修正"
