"""Shared implementation for the three analyst agent nodes.

Each analyst (industry, company, peer) uses the same LLM call pattern,
differing only in role description, assigned dimensions, and factor_id prefix.

Iteration 39 additions:
- Depth-severity consistency validation (programmatic flags for adversarial)
- Evidence citation cross-validation (phantom/mismatched citation detection)
- Toulmin-structured output fields (claim, warrant, strongest_counter)
- Self-consistency sampling (N=3 samples, modal severity per dimension)
"""

from __future__ import annotations

import json
from collections import Counter
from statistics import median

from liteagent import extract_json, strip_thinking

from sfewa import reporting
from sfewa.context import build_pipeline_context
from sfewa.llm import get_llm_for_role
from sfewa.tools.chat_log import log_llm_call
from sfewa.prompts.analysis import (
    ANALYST_SYSTEM,
    ANALYST_USER,
    build_evidence_summary,
    format_evidence_for_analyst,
)
from sfewa.schemas.state import PipelineState

# Number of samples for self-consistency. Set to 1 to disable.
ANALYST_SAMPLES = 3


def _parse_risk_factors_json(text: str) -> list[dict]:
    """Extract JSON array from LLM response."""
    text = strip_thinking(text)
    parsed = extract_json(text)
    if isinstance(parsed, list):
        return parsed
    # LLM may wrap array in a dict like {"risk_factors": [...]}
    if isinstance(parsed, dict):
        for key in ("risk_factors", "factors", "items"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
        # Fallback: any key with a list value
        for value in parsed.values():
            if isinstance(value, list):
                return value
    raise json.JSONDecodeError("Expected JSON array", text, 0)


def check_depth_consistency(factor: dict) -> list[str]:
    """Check that depth_of_analysis is consistent with severity and structural fields.

    Returns a list of violation strings (empty = clean). These are injected as
    [CONSISTENCY VIOLATION] flags into the adversarial review prompt alongside
    the existing [EVIDENCE IMBALANCE] flags.
    """
    violations: list[str] = []
    depth = factor.get("depth_of_analysis", 0)
    severity = factor.get("severity", "medium").lower()
    forces = factor.get("structural_forces", {})
    assumption = factor.get("key_assumption_at_risk")

    reinforcing = forces.get("reinforcing_loops", []) if isinstance(forces, dict) else []
    balancing = forces.get("balancing_loops", []) if isinstance(forces, dict) else []

    # Depth 2 should not produce HIGH/CRITICAL
    if depth <= 2 and severity in ("high", "critical"):
        violations.append(
            f"DEPTH_SEVERITY_MISMATCH: depth={depth} but severity={severity} "
            f"(Layer 2 analysis should produce LOW or MEDIUM)"
        )

    # Depth 4 should have key_assumption populated
    if depth >= 4 and not assumption:
        violations.append(
            "MISSING_ASSUMPTION: depth=4 but key_assumption_at_risk is empty "
            "(Layer 4 requires pre-mortem assumption challenge)"
        )

    # Depth 3+ should have structural forces
    if depth >= 3 and not reinforcing and not balancing:
        violations.append(
            "MISSING_FORCES: depth>=3 but no reinforcing or balancing loops "
            "(Layer 3 requires structural force identification)"
        )

    return violations


def validate_citations(
    factor: dict,
    evidence_map: dict[str, dict],
) -> list[str]:
    """Check that cited evidence_ids exist and stance alignment is reasonable.

    Returns a list of violation strings. These are injected as
    [CITATION VIOLATION] flags into the adversarial review prompt.

    Args:
        factor: A risk factor dict with supporting_evidence / contradicting_evidence.
        evidence_map: Mapping of evidence_id → evidence item dict.
    """
    violations: list[str] = []

    supporting = factor.get("supporting_evidence", [])
    phantom_supporting: list[str] = []
    mismatched: list[str] = []

    for eid in supporting:
        if eid not in evidence_map:
            phantom_supporting.append(eid)
        elif evidence_map[eid].get("stance") == "contradicts_risk":
            mismatched.append(eid)

    for eid in phantom_supporting:
        violations.append(f"PHANTOM_CITATION: {eid} cited as supporting but not in evidence")

    # STANCE_MISMATCH: only flag when mismatch is significant relative to total
    # supporting citations. A single mismatch out of 8 is a minor error; ALL
    # mismatched is a fundamental citation problem.
    if mismatched and supporting:
        mismatch_ratio = len(mismatched) / len(supporting)
        if mismatch_ratio > 0.5:
            # Majority mismatched → STRONG-worthy (fundamental citation error)
            violations.append(
                f"STANCE_MISMATCH: {len(mismatched)}/{len(supporting)} supporting "
                f"citations have contradicts_risk stance ({', '.join(mismatched)})"
            )
        elif len(mismatched) >= 2:
            # Multiple mismatches but minority → moderate-worthy (notable error)
            violations.append(
                f"MINOR_STANCE_MISMATCH: {len(mismatched)}/{len(supporting)} supporting "
                f"citations have contradicts_risk stance ({', '.join(mismatched)})"
            )
        # Single mismatch out of many → not flagged (noise)

    for eid in factor.get("contradicting_evidence", []):
        if eid not in evidence_map:
            violations.append(f"PHANTOM_CITATION: {eid} cited as contradicting but not in evidence")

    # HIGH/CRITICAL should have at least 2 supporting citations
    severity = factor.get("severity", "medium").lower()
    supporting_count = len(factor.get("supporting_evidence", []))
    if severity in ("high", "critical") and supporting_count < 2:
        violations.append(
            f"THIN_EVIDENCE: severity={severity} with only {supporting_count} supporting citation(s)"
        )

    return violations


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

    # Ensure Iceberg Model fields have defaults
    if "depth_of_analysis" not in item:
        item["depth_of_analysis"] = 0
    else:
        try:
            item["depth_of_analysis"] = int(item["depth_of_analysis"])
        except (TypeError, ValueError):
            item["depth_of_analysis"] = 0

    if not isinstance(item.get("structural_forces"), dict):
        item["structural_forces"] = {"reinforcing_loops": [], "balancing_loops": []}
    else:
        for key in ("reinforcing_loops", "balancing_loops"):
            if not isinstance(item["structural_forces"].get(key), list):
                item["structural_forces"][key] = []

    if "key_assumption_at_risk" not in item:
        item["key_assumption_at_risk"] = None

    # Toulmin fields (iter 39) — defaults for backward compatibility
    if not isinstance(item.get("claim"), str) or not item["claim"].strip():
        item["claim"] = ""
    if not isinstance(item.get("warrant"), str):
        item["warrant"] = ""
    if not isinstance(item.get("strongest_counter"), str):
        item["strongest_counter"] = ""

    # Clamp confidence
    try:
        item["confidence"] = max(0.0, min(1.0, float(item["confidence"])))
    except (TypeError, ValueError):
        item["confidence"] = 0.5

    return item


def _consensus_factors(
    all_samples: list[list[dict]],
    node_name: str,
) -> list[dict]:
    """Pick consensus factors from N samples using modal severity + median depth.

    For each dimension appearing across samples:
      1. Compute modal severity (most frequent)
      2. Compute median depth
      3. Select the sample factor closest to (modal_severity, median_depth)

    If first 2 samples agree on severity for all dimensions, returns immediately
    (Dynamic Self-Consistency early-stop).
    """
    # Group factors by dimension across all samples
    dim_factors: dict[str, list[dict]] = {}
    for sample in all_samples:
        for f in sample:
            dim = f.get("dimension", "?")
            dim_factors.setdefault(dim, []).append(f)

    consensus: list[dict] = []
    for dim, factors in dim_factors.items():
        severities = [f.get("severity", "medium").lower() for f in factors]
        depths = [f.get("depth_of_analysis", 0) for f in factors]

        # Modal severity
        sev_counter = Counter(severities)
        modal_sev = sev_counter.most_common(1)[0][0]
        # Median depth
        med_depth = int(median(depths))

        # Pick the factor closest to consensus
        best = factors[0]
        best_dist = 999
        for f in factors:
            f_sev = f.get("severity", "medium").lower()
            f_depth = f.get("depth_of_analysis", 0)
            dist = (0 if f_sev == modal_sev else 1) + abs(f_depth - med_depth)
            if dist < best_dist:
                best_dist = dist
                best = f

        # Override with consensus values
        best = dict(best)  # shallow copy to avoid mutating original
        best["severity"] = modal_sev
        best["depth_of_analysis"] = med_depth
        consensus.append(best)

    reporting.log_action("Self-consistency consensus", {
        "dimensions": len(consensus),
        "samples": len(all_samples),
    })

    return consensus


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

    # Call LLM (with self-consistency sampling when ANALYST_SAMPLES > 1)
    llm = get_llm_for_role(llm_role)
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    n_samples = ANALYST_SAMPLES
    if n_samples > 1:
        reporting.log_action(f"Self-consistency: sampling {n_samples}x")

    all_samples: list[list[dict]] = []
    for sample_idx in range(n_samples):
        try:
            response = llm.invoke(messages)
            label = f"risk_analysis_s{sample_idx + 1}" if n_samples > 1 else "risk_analysis"
            log_llm_call(node_name, messages, response, label=label)
            raw_text = response.content
            parsed = _parse_risk_factors_json(raw_text)
            if isinstance(parsed, list):
                validated = []
                for item in parsed:
                    cleaned = _validate_risk_factor(item)
                    if cleaned:
                        validated.append(cleaned)
                all_samples.append(validated)
        except Exception as e:
            reporting.log_action(f"LLM call failed (sample {sample_idx + 1})", {"error": str(e)[:200]})

        # Dynamic early-stop: if first 2 samples agree on severity for all dimensions
        if sample_idx == 1 and len(all_samples) == 2 and n_samples > 2:
            dims_0 = {f.get("dimension"): f.get("severity", "").lower() for f in all_samples[0]}
            dims_1 = {f.get("dimension"): f.get("severity", "").lower() for f in all_samples[1]}
            if dims_0 == dims_1 and dims_0:
                reporting.log_action("Self-consistency early-stop: first 2 samples agree")
                break

    if not all_samples:
        return {"risk_factors": []}

    # Pick consensus or single-sample result
    if len(all_samples) == 1 or n_samples == 1:
        valid_factors = all_samples[0]
    else:
        valid_factors = _consensus_factors(all_samples, node_name)

    reporting.log_action("Risk factors extracted", {
        "valid": len(valid_factors),
        "samples": len(all_samples),
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
