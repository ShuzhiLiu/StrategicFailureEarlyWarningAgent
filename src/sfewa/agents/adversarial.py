"""Adversarial Reviewer agent node.

Challenges risk factors by finding contradicting evidence and checking biases.
Uses thinking mode for deep multi-step reasoning.
"""

from __future__ import annotations

import json
import re

from sfewa import reporting
from sfewa.context import build_pipeline_context
from sfewa.llm import get_llm_for_role
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
    seen_dims: dict[str, dict] = {}
    for rf in raw_risk_factors:
        seen_dims[rf.get("dimension", "unknown")] = rf
    risk_factors = list(seen_dims.values())

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

    # Format prompt with pipeline context injection
    rf_text = format_risk_factors_for_review(risk_factors)
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
        response = llm.invoke([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ])
        raw_text = response.content

        # Strip <think> blocks
        raw_text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text).strip()

        # Parse JSON — now expects an object with "challenges" and "recommendation"
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text)
        if match:
            raw_text = match.group(1).strip()

        # Try parsing as object first (new format)
        start_obj = raw_text.find("{")
        end_obj = raw_text.rfind("}")
        start_arr = raw_text.find("[")

        if start_obj != -1 and end_obj != -1 and (start_arr == -1 or start_obj < start_arr):
            # Object format — new output with recommendation
            parsed = json.loads(raw_text[start_obj : end_obj + 1])
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
        elif start_arr != -1:
            # Fallback: array format (old output)
            end_arr = raw_text.rfind("]")
            if end_arr != -1:
                parsed = json.loads(raw_text[start_arr : end_arr + 1])
                if isinstance(parsed, list):
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

    # Report routing decision — now LLM-driven
    strong_count = severity_counts["strong"]

    # Validate recommendation: override to "proceed" if max passes reached
    if pass_count >= 2 and adversarial_recommendation == "reanalyze":
        adversarial_recommendation = "proceed"
        reporting.log_action("Max adversarial passes — overriding to proceed")

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
