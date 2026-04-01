"""Risk Synthesis & Memo Writer agent node.

Synthesizes all risk factors, adversarial challenges, and evidence into
an overall risk assessment and structured memo.
Uses thinking mode for deep reasoning.
"""

from __future__ import annotations

import json
import re

from sfewa import reporting
from sfewa.context import build_pipeline_context
from sfewa.llm import get_llm_for_role
from sfewa.prompts.adversarial import format_risk_factors_for_review
from sfewa.prompts.analysis import format_evidence_for_analyst
from sfewa.prompts.synthesis import (
    SYNTHESIS_SYSTEM,
    SYNTHESIS_USER,
    format_challenges_for_synthesis,
)
from sfewa.schemas.state import PipelineState


def risk_synthesis_node(state: PipelineState) -> dict:
    """Synthesize risk assessment into overall risk level and memo.

    Uses thinking mode to:
    1. Weight risk factors by dimension importance
    2. Adjust for adversarial challenges
    3. Compute overall risk level and confidence
    4. Generate structured risk memo
    """
    raw_risk_factors = state.get("risk_factors", [])
    challenges = state.get("adversarial_challenges", [])
    evidence = state.get("evidence", [])
    company = state["company"]
    theme = state["strategy_theme"]

    # Deduplicate risk factors: if multiple passes produced factors for the
    # same dimension, keep only the LATEST one (last in list = most recent pass)
    seen_dims: dict[str, dict] = {}
    for rf in raw_risk_factors:
        dim = rf.get("dimension", "unknown")
        seen_dims[dim] = rf  # last writer wins per dimension
    risk_factors = list(seen_dims.values())

    reporting.enter_node("risk_synthesis", {
        "risk_factors_raw": len(raw_risk_factors),
        "risk_factors_deduped": len(risk_factors),
        "challenges": len(challenges),
        "evidence_items": len(evidence),
    })

    if not risk_factors:
        reporting.log_action("No risk factors to synthesize")
        reporting.exit_node("risk_synthesis", next_node="backtest")
        return {
            "overall_risk_level": "low",
            "overall_confidence": 0.0,
            "risk_memo": "No risk factors identified.",
            "current_stage": "risk_synthesis",
        }

    # Compute evidence statistics for calibration
    stance_supports = sum(1 for e in evidence if e.get("stance") == "supports_risk")
    stance_contradicts = sum(1 for e in evidence if e.get("stance") == "contradicts_risk")
    stance_neutral = sum(1 for e in evidence if e.get("stance") == "neutral")
    source_types = {}
    for e in evidence:
        st = e.get("source_type", "unknown")
        source_types[st] = source_types.get(st, 0) + 1
    source_summary = ", ".join(f"{k}: {v}" for k, v in sorted(source_types.items()))

    # Compute severity distribution for calibration
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for rf in risk_factors:
        sev = rf.get("severity", "medium").lower()
        if sev in severity_counts:
            severity_counts[sev] += 1
    total_factors = len(risk_factors)
    high_plus = severity_counts["critical"] + severity_counts["high"]
    high_plus_ratio = f"{high_plus}/{total_factors} ({high_plus/total_factors*100:.0f}%)" if total_factors > 0 else "0/0"

    # Format prompt with pipeline context injection
    rf_text = format_risk_factors_for_review(risk_factors)
    challenges_text = format_challenges_for_synthesis(challenges)
    evidence_text = format_evidence_for_analyst(evidence)
    pipeline_context = build_pipeline_context(state)

    system_msg = SYNTHESIS_SYSTEM.format(
        company=company,
        strategy_theme=theme,
    )
    if pipeline_context:
        system_msg += f"\n\n{pipeline_context}"
    user_msg = SYNTHESIS_USER.format(
        risk_factors_text=rf_text,
        challenges_text=challenges_text,
        evidence_text=evidence_text,
        evidence_count=len(evidence),
        stance_supports=stance_supports,
        stance_contradicts=stance_contradicts,
        stance_neutral=stance_neutral,
        source_summary=source_summary or "no sources",
        severity_critical=severity_counts["critical"],
        severity_high=severity_counts["high"],
        severity_medium=severity_counts["medium"],
        severity_low=severity_counts["low"],
        total_factors=total_factors,
        high_plus_ratio=high_plus_ratio,
    )

    # Call LLM with thinking mode
    llm = get_llm_for_role("synthesis")
    reporting.log_action("Calling LLM (thinking mode) for risk synthesis")

    result = {
        "overall_risk_level": None,
        "overall_confidence": None,
        "risk_memo": None,
        "current_stage": "risk_synthesis",
    }

    try:
        response = llm.invoke([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ])
        raw_text = response.content

        # Strip <think> blocks
        raw_text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text).strip()

        # Parse JSON object
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text)
        if match:
            raw_text = match.group(1).strip()
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1:
            raw_text = raw_text[start : end + 1]

        parsed = json.loads(raw_text)

        risk_level = parsed.get("overall_risk_level", "medium")
        confidence = parsed.get("overall_confidence", 0.5)
        memo = parsed.get("risk_memo", "")

        # Validate
        valid_levels = {"critical", "high", "medium", "low"}
        if risk_level not in valid_levels:
            risk_level = "medium"
        confidence = max(0.0, min(1.0, float(confidence)))

        result["overall_risk_level"] = risk_level
        result["overall_confidence"] = confidence
        result["risk_memo"] = memo

        reporting.log_action("Synthesis complete", {
            "risk_level": risk_level.upper(),
            "confidence": f"{confidence:.2f}",
            "memo_length": f"{len(memo)} chars",
        })

    except Exception as e:
        reporting.log_action("LLM call failed", {"error": str(e)[:200]})
        result["overall_risk_level"] = "medium"
        result["overall_confidence"] = 0.3
        result["risk_memo"] = f"Synthesis failed: {str(e)[:100]}"

    reporting.exit_node("risk_synthesis", next_node="backtest")
    return result
