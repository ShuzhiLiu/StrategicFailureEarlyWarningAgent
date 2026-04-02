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
from sfewa.tools.chat_log import log_llm_call
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
            "risk_score": 0,
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

    # ── Apply STRONG adversarial downgrades programmatically ──
    # Build a map of factor_id → severity for the downgrade step
    DOWNGRADE = {"critical": "high", "high": "medium", "medium": "low", "low": "low"}
    strong_targets: set[str] = set()
    for c in challenges:
        if c.get("severity", "").lower() == "strong":
            strong_targets.add(c.get("target_factor_id", ""))

    # Apply downgrades and track post-adversarial severity
    post_adversarial: list[dict] = []
    for rf in risk_factors:
        fid = rf.get("factor_id", "")
        orig_sev = rf.get("severity", "medium").lower()
        if fid in strong_targets:
            new_sev = DOWNGRADE.get(orig_sev, orig_sev)
            post_adversarial.append({"factor_id": fid, "dimension": rf.get("dimension", "?"), "original": orig_sev, "post": new_sev})
        else:
            post_adversarial.append({"factor_id": fid, "dimension": rf.get("dimension", "?"), "original": orig_sev, "post": orig_sev})

    # ── Compute base_score in code (not by LLM) ──
    SEVERITY_POINTS = {"critical": 25, "high": 15, "medium": 8, "low": 2}
    total_factors = len(risk_factors)
    points = sum(SEVERITY_POINTS.get(pa["post"], 8) for pa in post_adversarial)
    # Normalize against HIGH (15) as realistic max — CRITICAL is rare
    base_score = round(points / (15 * total_factors) * 100) if total_factors > 0 else 0
    base_score = max(0, min(100, base_score))

    # Compute post-adversarial severity distribution for display
    post_sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for pa in post_adversarial:
        if pa["post"] in post_sev_counts:
            post_sev_counts[pa["post"]] += 1

    post_adversarial_dist = (
        f"{post_sev_counts['critical']} CRITICAL, {post_sev_counts['high']} HIGH, "
        f"{post_sev_counts['medium']} MEDIUM, {post_sev_counts['low']} LOW"
    )
    high_plus = post_sev_counts["critical"] + post_sev_counts["high"]
    high_plus_ratio = f"{high_plus}/{total_factors} ({high_plus/total_factors*100:.0f}%)" if total_factors > 0 else "0/0"

    # Log the computation for debugging
    downgrades_applied = [pa for pa in post_adversarial if pa["original"] != pa["post"]]
    reporting.log_action("Base score computed", {
        "points": points,
        "base_score": base_score,
        "post_adversarial": post_adversarial_dist,
        "downgrades": len(downgrades_applied),
    })

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
        base_score=base_score,
        post_adversarial_distribution=post_adversarial_dist,
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
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        response = llm.invoke(messages)
        log_llm_call("risk_synthesis", messages, response, label="synthesis")
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

        risk_score = parsed.get("risk_score", 50)
        confidence = parsed.get("overall_confidence", 0.5)
        memo = parsed.get("risk_memo", "")

        # Validate and derive categorical label from score
        risk_score = max(0, min(100, int(risk_score)))
        confidence = max(0.0, min(1.0, float(confidence)))

        if risk_score >= 80:
            risk_level = "critical"
        elif risk_score >= 60:
            risk_level = "high"
        elif risk_score >= 40:
            risk_level = "medium"
        else:
            risk_level = "low"

        result["risk_score"] = risk_score
        result["overall_risk_level"] = risk_level
        result["overall_confidence"] = confidence
        result["risk_memo"] = memo

        reporting.log_action("Synthesis complete", {
            "risk_score": f"{risk_score}/100",
            "risk_level": risk_level.upper(),
            "confidence": f"{confidence:.2f}",
            "memo_length": f"{len(memo)} chars",
        })

    except Exception as e:
        reporting.log_action("LLM call failed", {"error": str(e)[:200]})
        result["risk_score"] = 50
        result["overall_risk_level"] = "medium"
        result["overall_confidence"] = 0.3
        result["risk_memo"] = f"Synthesis failed: {str(e)[:100]}"

    reporting.exit_node("risk_synthesis", next_node="backtest")
    return result
