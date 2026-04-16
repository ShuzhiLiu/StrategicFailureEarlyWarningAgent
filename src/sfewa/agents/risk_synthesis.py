"""Risk Synthesis & Memo Writer agent node.

Synthesizes all risk factors, adversarial challenges, and evidence into
an overall risk assessment and structured memo.
Uses thinking mode for deep reasoning.
"""

from __future__ import annotations

import json
import re

from liteagent import dedup_by_key, count_by, extract_json, strip_thinking

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


def _build_structural_summary(risk_factors: list[dict]) -> str:
    """Build a summary of structural forces from risk factor analysis.

    Extracts reinforcing loops, balancing loops, and key assumptions from
    the Iceberg Model layered analysis output.
    """
    lines = []
    total_reinforcing = 0
    total_balancing = 0

    for rf in risk_factors:
        dim = rf.get("dimension", "?")
        depth = rf.get("depth_of_analysis", 0)
        forces = rf.get("structural_forces", {})
        assumption = rf.get("key_assumption_at_risk")

        reinforcing = forces.get("reinforcing_loops", []) if isinstance(forces, dict) else []
        balancing = forces.get("balancing_loops", []) if isinstance(forces, dict) else []
        total_reinforcing += len(reinforcing)
        total_balancing += len(balancing)

        if depth >= 3 or reinforcing or balancing or assumption:
            entry = f"[{dim}] depth={depth}"
            if reinforcing:
                entry += f"\n  Reinforcing: {'; '.join(str(r) for r in reinforcing[:3])}"
            if balancing:
                entry += f"\n  Balancing: {'; '.join(str(b) for b in balancing[:3])}"
            if assumption:
                entry += f"\n  Critical assumption: {assumption}"
            lines.append(entry)

    summary = f"Total loops: {total_reinforcing} reinforcing, {total_balancing} balancing\n"
    if lines:
        summary += "\n".join(lines)
    else:
        summary += "(No structural forces reported — analysts stayed at Layer 1-2 for all dimensions)"
    return summary


def risk_synthesis_node(state: PipelineState) -> dict:
    """Synthesize risk assessment into overall risk level and memo.

    Uses thinking mode to:
    1. Weight risk factors by dimension importance
    2. Adjust for adversarial challenges
    3. Compute overall risk level and confidence
    4. Generate structured risk memo
    """
    raw_risk_factors = state.get("risk_factors", [])
    raw_challenges = state.get("adversarial_challenges", [])
    evidence = state.get("evidence", [])
    company = state["company"]
    theme = state["strategy_theme"]

    # Deduplicate risk factors: if multiple passes produced factors for the
    # same dimension, keep only the LATEST one (last in list = most recent pass)
    risk_factors = dedup_by_key(raw_risk_factors, "dimension")
    # Deduplicate challenges: cross-pass accumulation creates duplicates
    challenges = dedup_by_key(raw_challenges, "target_factor_id")

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
    stance_counts = count_by(evidence, "stance")
    stance_supports = stance_counts.get("supports_risk", 0)
    stance_contradicts = stance_counts.get("contradicts_risk", 0)
    stance_neutral = stance_counts.get("neutral", 0)
    source_types = count_by(evidence, "source_type")
    source_summary = ", ".join(f"{k}: {v}" for k, v in sorted(source_types.items()))

    # -- Apply evidence-gated STRONG adversarial downgrades --
    # STRONG challenges only downgrade factors with WEAK evidence support.
    # Well-supported factors (≥3 valid citations after excluding phantoms
    # and stance-mismatched) survive STRONG challenges — the challenge is
    # noted in the memo but does not mechanically reduce severity. This
    # prevents Toulmin-driven STRONG inflation from over-penalizing
    # companies with genuinely strong evidence.
    DOWNGRADE = {"critical": "high", "high": "medium", "medium": "low", "low": "low"}
    EVIDENCE_GATE_MIN_VALID = 3       # minimum valid supporting citations to resist

    strong_targets: set[str] = set()
    for c in challenges:
        if c.get("severity", "").lower() == "strong":
            strong_targets.add(c.get("target_factor_id", ""))

    # Build evidence lookup for citation quality assessment
    evidence_map: dict[str, dict] = {}
    for e in evidence:
        eid = e.get("evidence_id", "")
        if eid:
            evidence_map[eid] = e

    # Apply downgrades and track post-adversarial severity
    post_adversarial: list[dict] = []
    resisted: list[str] = []
    for rf in risk_factors:
        fid = rf.get("factor_id", "")
        orig_sev = rf.get("severity", "medium").lower()
        if fid in strong_targets:
            # Evidence gate: count valid supporting citations
            # Exclude phantoms (not in evidence) and stance-mismatched
            # (cited as supporting but evidence contradicts risk)
            supporting = rf.get("supporting_evidence", [])
            valid_sup = 0
            for eid in supporting:
                if eid in evidence_map and evidence_map[eid].get("stance") != "contradicts_risk":
                    valid_sup += 1
            if valid_sup >= EVIDENCE_GATE_MIN_VALID:
                # Well-supported factor resists downgrade
                post_adversarial.append({"factor_id": fid, "dimension": rf.get("dimension", "?"), "original": orig_sev, "post": orig_sev})
                resisted.append(f"{fid}({valid_sup}sup)")
            else:
                new_sev = DOWNGRADE.get(orig_sev, orig_sev)
                post_adversarial.append({"factor_id": fid, "dimension": rf.get("dimension", "?"), "original": orig_sev, "post": new_sev})
        else:
            post_adversarial.append({"factor_id": fid, "dimension": rf.get("dimension", "?"), "original": orig_sev, "post": orig_sev})

    # -- Compute base_score in code (not by LLM) --
    SEVERITY_POINTS = {"critical": 25, "high": 15, "medium": 8, "low": 2}
    total_factors = len(risk_factors)
    points = sum(SEVERITY_POINTS.get(pa["post"], 8) for pa in post_adversarial)
    base_score = round(points / (15 * total_factors) * 100) if total_factors > 0 else 0
    base_score = max(0, min(100, base_score))

    # Compute post-adversarial severity distribution for display
    post_sev_counts = count_by(post_adversarial, "post")
    post_adversarial_dist = (
        f"{post_sev_counts.get('critical', 0)} CRITICAL, {post_sev_counts.get('high', 0)} HIGH, "
        f"{post_sev_counts.get('medium', 0)} MEDIUM, {post_sev_counts.get('low', 0)} LOW"
    )
    high_plus = post_sev_counts.get("critical", 0) + post_sev_counts.get("high", 0)
    high_plus_ratio = f"{high_plus}/{total_factors} ({high_plus/total_factors*100:.0f}%)" if total_factors > 0 else "0/0"

    # Log the computation for debugging
    downgrades_applied = [pa for pa in post_adversarial if pa["original"] != pa["post"]]
    reporting.log_action("Base score computed", {
        "points": points,
        "base_score": base_score,
        "post_adversarial": post_adversarial_dist,
        "downgrades": len(downgrades_applied),
        "resisted": len(resisted),
    })
    if resisted:
        reporting.log_action("Evidence-gated: factors resisted STRONG downgrade", {
            "factors": resisted,
        })

    # Extract dimension_relevance for synthesis context
    dimension_relevance: dict[str, str] = {}
    analysis_dims = state.get("analysis_dimensions", {})
    for group in analysis_dims.values():
        if isinstance(group, dict) and "dimension_relevance" in group:
            dimension_relevance.update(group["dimension_relevance"])

    # Format prompt with pipeline context injection
    rf_text = format_risk_factors_for_review(risk_factors, dimension_relevance, evidence)
    challenges_text = format_challenges_for_synthesis(challenges)
    evidence_text = format_evidence_for_analyst(evidence)
    pipeline_context = build_pipeline_context(state)

    # Analyst agreement (computed in pipeline after fan-out)
    agreement = state.get("analyst_agreement", {})
    agreement_summary = agreement.get("summary", "(not available)")

    system_msg = SYNTHESIS_SYSTEM.format(
        company=company,
        strategy_theme=theme,
    )
    if pipeline_context:
        system_msg += f"\n\n{pipeline_context}"
    structural_summary = _build_structural_summary(risk_factors)
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
        structural_summary=structural_summary,
        analyst_agreement_summary=agreement_summary,
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
        raw_text = strip_thinking(response.content)

        # Sanitize invalid JSON escapes (e.g. \* from markdown in memo)
        raw_text = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', raw_text)

        try:
            parsed = extract_json(raw_text)
        except json.JSONDecodeError:
            parsed = {}

        risk_score = parsed.get("risk_score", 50)
        confidence = parsed.get("overall_confidence", 0.5)
        memo = parsed.get("risk_memo", "")

        # Validate and derive categorical label from score
        risk_score = max(0, min(100, int(risk_score)))
        confidence = max(0.0, min(1.0, float(confidence)))

        # Clamp LLM adjustment to ±15 of programmatic base score.
        # The base score is deterministic; the LLM adjustment is qualitative.
        # This is a safety bound (like MAX_ITERATIONS), not a hardcoded override.
        raw_llm_score = risk_score
        risk_score = max(base_score - 15, min(base_score + 15, risk_score))
        if raw_llm_score != risk_score:
            reporting.log_action("Score clamped", {
                "raw_llm": raw_llm_score,
                "base": base_score,
                "clamped": risk_score,
            })

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
