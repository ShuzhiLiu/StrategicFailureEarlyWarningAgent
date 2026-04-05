"""Adversarial Reviewer agent node.

Challenges risk factors by finding contradicting evidence and checking biases.
Uses thinking mode for deep multi-step reasoning.
"""

from __future__ import annotations

import json

from liteagent import dedup_by_key, extract_json, strip_thinking

from sfewa import reporting
from sfewa.context import build_pipeline_context
from sfewa.llm import get_llm_for_role
from sfewa.tools.chat_log import log_llm_call
from sfewa.prompts.adversarial import (
    ADVERSARIAL_SYSTEM,
    ADVERSARIAL_USER,
    format_risk_factors_for_review,
)
from sfewa.prompts.analysis import format_evidence_for_analyst
from sfewa.schemas.state import PipelineState


def adversarial_review_node(state: PipelineState) -> dict:
    """Challenge the current risk assessment with adversarial analysis.

    Uses thinking mode (CoT reasoning) to:
    1. For each risk factor, find contradicting evidence
    2. Check for selection bias, industry-vs-company confusion, temporal bias
    3. Rate each challenge as strong/moderate/weak
    """
    raw_risk_factors = state.get("risk_factors", [])
    evidence = state.get("evidence", [])
    company = state["company"]
    theme = state["strategy_theme"]
    pass_count = state.get("adversarial_pass_count", 0) + 1

    # Deduplicate: keep latest factor per dimension (handles multi-pass accumulation)
    risk_factors = dedup_by_key(raw_risk_factors, "dimension")

    reporting.enter_node("adversarial_review", {
        "risk_factors": len(risk_factors),
        "evidence_items": len(evidence),
        "pass": f"{pass_count}/2",
    })

    if not risk_factors:
        reporting.log_action("No risk factors to challenge")
        reporting.exit_node("adversarial_review", {"challenges": 0})
        return {
            "adversarial_challenges": [],
            "adversarial_pass_count": pass_count,
            "current_stage": "adversarial_review",
        }

    # Extract dimension_relevance from analysis_dimensions for depth gate check
    dimension_relevance: dict[str, str] = {}
    analysis_dims = state.get("analysis_dimensions", {})
    for group in analysis_dims.values():
        if isinstance(group, dict) and "dimension_relevance" in group:
            dimension_relevance.update(group["dimension_relevance"])

    # Format prompt with pipeline context injection
    rf_text = format_risk_factors_for_review(risk_factors, dimension_relevance)
    evidence_text = format_evidence_for_analyst(evidence)
    pipeline_context = build_pipeline_context(state)

    system_msg = ADVERSARIAL_SYSTEM.format(
        company=company,
        strategy_theme=theme,
    )
    if pipeline_context:
        system_msg += f"\n\n{pipeline_context}"
    user_msg = ADVERSARIAL_USER.format(
        risk_factors_text=rf_text,
        evidence_text=evidence_text,
    )

    # Call LLM with thinking mode
    llm = get_llm_for_role("adversarial")
    reporting.log_action("Calling LLM (thinking mode) for adversarial review")

    challenges: list[dict] = []
    adversarial_recommendation = "proceed"  # default: proceed to synthesis
    try:
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        response = llm.invoke(messages)
        log_llm_call("adversarial_review", messages, response, label="adversarial")
        raw_text = strip_thinking(response.content)

        try:
            parsed = extract_json(raw_text)
        except json.JSONDecodeError:
            parsed = {}

        if isinstance(parsed, dict):
            # Object format -- new output with recommendation
            if isinstance(parsed.get("challenges"), list):
                challenges = parsed["challenges"]
            rec = parsed.get("recommendation", {})
            if isinstance(rec, dict):
                adversarial_recommendation = rec.get("action", "proceed")
                rec_reasoning = rec.get("reasoning", "")
                reporting.log_action("Adversarial recommendation", {
                    "action": adversarial_recommendation.upper(),
                    "reasoning": rec_reasoning[:120],
                })
        elif isinstance(parsed, list):
            # Fallback: array format (old output)
            challenges = parsed

    except Exception as e:
        reporting.log_action("LLM call failed", {"error": str(e)[:200]})
        return {
            "adversarial_challenges": [],
            "adversarial_pass_count": pass_count,
            "adversarial_recommendation": "proceed",
            "current_stage": "adversarial_review",
        }

    # Validate challenges
    valid_challenges: list[dict] = []
    for c in challenges:
        required = ["challenge_id", "target_factor_id", "challenge_text", "severity"]
        if all(c.get(f) for f in required):
            if not isinstance(c.get("counter_evidence"), list):
                c["counter_evidence"] = []
            if "resolution" not in c:
                c["resolution"] = None
            valid_challenges.append(c)

    # Count severity distribution
    severity_counts = {"strong": 0, "moderate": 0, "weak": 0}
    for c in valid_challenges:
        sev = c.get("severity", "weak")
        if sev in severity_counts:
            severity_counts[sev] += 1

    reporting.log_action("Challenges generated", severity_counts)
    for c in valid_challenges:
        reporting.log_challenge(
            c["challenge_id"],
            c["target_factor_id"],
            c["severity"],
            c["challenge_text"][:80],
        )

    # Report routing decision -- now LLM-driven
    strong_count = severity_counts["strong"]

    # Validate recommendation: override to "proceed" if max passes reached
    if pass_count >= 2 and adversarial_recommendation == "reanalyze":
        adversarial_recommendation = "proceed"
        reporting.log_action("Max adversarial passes -- overriding to proceed")

    next_node = "risk_synthesis" if adversarial_recommendation == "proceed" else "evidence_extraction (reanalyze)"

    reporting.exit_node("adversarial_review", {
        "challenges": len(valid_challenges),
        "strong": strong_count,
        "moderate": severity_counts["moderate"],
        "weak": severity_counts["weak"],
        "llm_recommendation": adversarial_recommendation,
    }, next_node=next_node)

    return {
        "adversarial_challenges": valid_challenges,
        "adversarial_pass_count": pass_count,
        "adversarial_recommendation": adversarial_recommendation,
        "current_stage": "adversarial_review",
    }
