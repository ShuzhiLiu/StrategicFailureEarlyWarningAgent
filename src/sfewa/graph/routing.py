"""Conditional edge routing functions for the LangGraph pipeline.

Patterns adopted:
- Dead-loop protection counters (TradingAgents-CN)
- Debate round limits for adversarial review (TradingAgents-CN)
- Separated evaluation routing — adversarial reviewer is never the same
  agent that generated the findings (Anthropic harness design)
"""

from __future__ import annotations

from sfewa.schemas.state import PipelineState

# ── Constants ──
MAX_EXTRACTION_ITERATIONS = 3
MAX_ADVERSARIAL_PASSES = 2
STRONG_CHALLENGE_THRESHOLD = 0.5  # ratio of strong challenges to factors


def should_continue_extraction(state: PipelineState) -> str:
    """Guard against infinite extraction loops.

    If extraction has run MAX_EXTRACTION_ITERATIONS times without producing
    evidence, route to error. Otherwise, proceed to fan-out.
    """
    iteration = state.get("iteration_count", 0)

    if iteration > MAX_EXTRACTION_ITERATIONS:
        return "error"

    return "fan_out"


def after_adversarial_review(state: PipelineState) -> str:
    """Decide whether to loop back for re-analysis or proceed to synthesis.

    Loop back if >50% of risk factors have strong adversarial challenges
    and we haven't exceeded the max adversarial passes.

    This implements a debate-style quality loop inspired by TradingAgents-CN's
    bull/bear researcher debate, but applied to risk factor validation.
    """
    challenges = state.get("adversarial_challenges", [])
    factors = state.get("risk_factors", [])
    pass_count = state.get("adversarial_pass_count", 0)

    if not factors:
        return "risk_synthesis"

    strong_challenges = sum(1 for c in challenges if c.get("severity") == "strong")
    challenge_ratio = strong_challenges / len(factors)

    if challenge_ratio > STRONG_CHALLENGE_THRESHOLD and pass_count < MAX_ADVERSARIAL_PASSES:
        return "evidence_extraction"

    return "risk_synthesis"
