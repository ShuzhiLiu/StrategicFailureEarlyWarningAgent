"""Adversarial Reviewer agent node.

Challenges risk factors by finding contradicting evidence and checking biases.
Uses thinking mode for deep multi-step reasoning.
"""

from __future__ import annotations

import json
import re

from sfewa import reporting
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
    risk_factors = state.get("risk_factors", [])
    evidence = state.get("evidence", [])
    company = state["company"]
    theme = state["strategy_theme"]
    pass_count = state.get("adversarial_pass_count", 0) + 1

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

    # Format prompt
    rf_text = format_risk_factors_for_review(risk_factors)
    evidence_text = format_evidence_for_analyst(evidence)

    system_msg = ADVERSARIAL_SYSTEM.format(
        company=company,
        strategy_theme=theme,
    )
    user_msg = ADVERSARIAL_USER.format(
        risk_factors_text=rf_text,
        evidence_text=evidence_text,
    )

    # Call LLM with thinking mode
    llm = get_llm_for_role("adversarial")
    reporting.log_action("Calling LLM (thinking mode) for adversarial review")

    challenges: list[dict] = []
    try:
        response = llm.invoke([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ])
        raw_text = response.content

        # Strip <think> blocks
        raw_text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text).strip()

        # Parse JSON
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text)
        if match:
            raw_text = match.group(1).strip()
        start = raw_text.find("[")
        end = raw_text.rfind("]")
        if start != -1 and end != -1:
            raw_text = raw_text[start : end + 1]

        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            challenges = parsed

    except Exception as e:
        reporting.log_action("LLM call failed", {"error": str(e)[:200]})
        return {
            "adversarial_challenges": [],
            "adversarial_pass_count": pass_count,
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

    # Report routing decision
    strong_count = severity_counts["strong"]
    total_factors = len(risk_factors)
    ratio = strong_count / total_factors if total_factors > 0 else 0

    reporting.exit_node("adversarial_review", {
        "challenges": len(valid_challenges),
        "strong": strong_count,
        "moderate": severity_counts["moderate"],
        "weak": severity_counts["weak"],
    }, next_node="risk_synthesis" if ratio <= 0.5 or pass_count >= 2 else "loop back",
       reason=f"strong/total = {strong_count}/{total_factors} = {ratio:.1%}")

    return {
        "adversarial_challenges": valid_challenges,
        "adversarial_pass_count": pass_count,
        "current_stage": "adversarial_review",
    }
