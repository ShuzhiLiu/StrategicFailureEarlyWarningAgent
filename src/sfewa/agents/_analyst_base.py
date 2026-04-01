"""Shared implementation for the three analyst agent nodes.

Each analyst (industry, company, peer) uses the same LLM call pattern,
differing only in role description, assigned dimensions, and factor_id prefix.
"""

from __future__ import annotations

import json
import re

from sfewa import reporting
from sfewa.context import build_pipeline_context
from sfewa.llm import get_llm_for_role
from sfewa.prompts.analysis import (
    ANALYST_SYSTEM,
    ANALYST_USER,
    build_evidence_summary,
    format_evidence_for_analyst,
)
from sfewa.schemas.state import PipelineState


def _parse_risk_factors_json(text: str) -> list[dict]:
    """Extract JSON array from LLM response."""
    text = text.strip()
    # Strip <think> blocks
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    # Strip markdown fences
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def _validate_risk_factor(item: dict) -> dict | None:
    """Validate a risk factor dict. Returns None if invalid."""
    required = ["factor_id", "dimension", "title", "description", "severity", "confidence"]
    for field in required:
        if field not in item or not item[field]:
            return None

    # Ensure lists exist
    for list_field in ["supporting_evidence", "contradicting_evidence", "causal_chain", "unresolved_gaps"]:
        if not isinstance(item.get(list_field), list):
            item[list_field] = []

    # Clamp confidence
    try:
        item["confidence"] = max(0.0, min(1.0, float(item["confidence"])))
    except (TypeError, ValueError):
        item["confidence"] = 0.5

    return item


def run_analyst(
    state: PipelineState,
    *,
    node_name: str,
    role_name: str,
    llm_role: str,
    dimensions_description: str,
    factor_prefix: str,
    scope_boundary: str = "",
) -> dict:
    """Shared analyst implementation.

    Args:
        state: Pipeline state.
        node_name: Node name for reporting (e.g., "industry_analyst").
        role_name: Human-readable role (e.g., "Industry & Market Analyst").
        llm_role: Key for get_llm_for_role (e.g., "industry_analyst").
        dimensions_description: Text describing assigned risk dimensions.
        factor_prefix: Prefix for factor IDs (e.g., "IND" → "IND001").
        scope_boundary: Instructions about what NOT to analyze (other analysts' scope).
    """
    evidence = state.get("evidence", [])
    company = state["company"]
    theme = state["strategy_theme"]

    reporting.enter_node(node_name, {
        "evidence_items": len(evidence),
        "role": role_name,
    })

    if not evidence:
        reporting.log_action("No evidence available — skipping analysis")
        reporting.exit_node(node_name, {"risk_factors": 0})
        return {"risk_factors": []}

    # Format prompt with pipeline context injection
    evidence_text = format_evidence_for_analyst(evidence)
    pipeline_context = build_pipeline_context(state)
    system_msg = ANALYST_SYSTEM.format(
        analyst_role=role_name,
        company=company,
        strategy_theme=theme,
        dimensions_description=dimensions_description,
        scope_boundary=scope_boundary,
    )
    if pipeline_context:
        system_msg += f"\n\n{pipeline_context}"
    # Count assigned dimensions from the description (each starts with "- ")
    dimension_count = dimensions_description.count("\n- ") + (1 if dimensions_description.startswith("- ") else 0)
    evidence_summary = build_evidence_summary(evidence)
    user_msg = ANALYST_USER.format(
        company=company,
        strategy_theme=theme,
        evidence_summary=evidence_summary,
        evidence_text=evidence_text,
        factor_prefix=factor_prefix,
        dimension_count=dimension_count,
    )

    # Call LLM
    llm = get_llm_for_role(llm_role)
    reporting.log_action("Calling LLM for risk analysis")

    risk_factors: list[dict] = []
    try:
        response = llm.invoke([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ])
        raw_text = response.content
        parsed = _parse_risk_factors_json(raw_text)
        if isinstance(parsed, list):
            risk_factors = parsed
    except Exception as e:
        reporting.log_action("LLM call failed", {"error": str(e)[:200]})
        return {"risk_factors": []}

    # Validate
    valid_factors: list[dict] = []
    for item in risk_factors:
        cleaned = _validate_risk_factor(item)
        if cleaned:
            valid_factors.append(cleaned)

    reporting.log_action("Risk factors extracted", {
        "raw": len(risk_factors),
        "valid": len(valid_factors),
    })

    for rf in valid_factors:
        reporting.log_risk_factor(
            rf["factor_id"],
            rf["dimension"],
            rf["severity"],
            rf["confidence"],
            rf["title"],
        )

    reporting.exit_node(node_name, {
        "risk_factors": len(valid_factors),
    }, next_node="adversarial_review (waiting for peers)")

    return {"risk_factors": valid_factors}
