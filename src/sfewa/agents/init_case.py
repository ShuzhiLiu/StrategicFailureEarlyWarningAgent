"""Case initialization node — loads config and initializes pipeline state.

When regions and peers are not provided, the LLM generates them from
the minimal input (company + strategy_theme + cutoff_date). This is the
Planner's first decision — scoping the analysis.
"""

from __future__ import annotations

import json

from liteagent import extract_json, strip_thinking

from sfewa import reporting
from sfewa.llm import get_llm_for_role
from sfewa.prompts.init_case import CASE_EXPANSION_SYSTEM, CASE_EXPANSION_USER
from sfewa.schemas.state import PipelineState
from sfewa.tools.chat_log import log_llm_call


def _format_dimensions(dims_data: dict) -> dict:
    """Convert LLM-generated dimensions into the format analysts expect.

    Returns dict mapping analyst key ("external", "internal", "comparative")
    to {"role_name": str, "dimensions_description": str, "scope_boundary": str}.
    """
    result = {}
    for key in ("external", "internal", "comparative"):
        group = dims_data.get(key, {})
        role_name = group.get("role_name", f"{key.title()} Analyst")
        scope = group.get("scope_boundary", "")
        dims = group.get("dimensions", [])
        # Format dimensions with depth guidance for the analyst prompt
        lines = []
        for d in dims:
            name = d.get("name", "unknown")
            desc = d.get("description", "")
            structural_hint = d.get("structural_hint", "")
            critical_assumption = d.get("critical_assumption", "")
            strategy_relevance = d.get("strategy_relevance", "primary")
            entry = f"- {name}: {desc}"
            entry += f"\n  [Strategy relevance: {strategy_relevance}]"
            if structural_hint:
                entry += f"\n  [Structural hint]: {structural_hint}"
            if critical_assumption:
                entry += f"\n  [Critical assumption to test]: {critical_assumption}"
            lines.append(entry)
        # Build dimension_relevance mapping for downstream nodes
        dim_relevance = {
            d.get("name", "unknown"): d.get("strategy_relevance", "primary")
            for d in dims
        }
        result[key] = {
            "role_name": role_name,
            "dimensions_description": "\n".join(lines),
            "scope_boundary": scope,
            "dimension_names": [d.get("name", "unknown") for d in dims],
            "dimension_relevance": dim_relevance,
        }
    return result


def _generate_case_context(
    company: str, strategy_theme: str, cutoff_date: str,
) -> dict:
    """Use LLM to generate regions, peers, and analysis dimensions."""
    llm = get_llm_for_role("retrieval")  # non-thinking, fast

    try:
        messages = [
            {"role": "system", "content": CASE_EXPANSION_SYSTEM},
            {"role": "user", "content": CASE_EXPANSION_USER.format(
                company=company,
                strategy_theme=strategy_theme,
                cutoff_date=cutoff_date,
            )},
        ]
        response = llm.invoke(messages)
        log_llm_call("init_case", messages, response, label="case_expansion")
        raw = response.content
        raw = strip_thinking(raw)

        parsed = extract_json(raw)
        if isinstance(parsed, dict):
            result = {
                "regions": parsed.get("regions", []),
                "peers": parsed.get("peers", []),
            }
            # Process analysis dimensions if provided
            if "analysis_dimensions" in parsed:
                result["analysis_dimensions"] = _format_dimensions(
                    parsed["analysis_dimensions"],
                )
            return result
    except Exception as e:
        reporting.log_action("LLM case expansion failed — using defaults", {
            "error": str(e)[:150],
        })

    # Fallback defaults
    return {
        "regions": ["global"],
        "peers": [],
    }


def init_case_node(state: PipelineState) -> dict:
    """Initialize the pipeline state from case configuration.

    If regions or peers are empty, uses LLM to generate them from
    (company, strategy_theme, cutoff_date).
    """
    company = state.get("company", "?")
    theme = state.get("strategy_theme", "?")
    cutoff = state.get("cutoff_date", "?")
    regions = state.get("regions", [])
    peers = state.get("peers", [])

    reporting.enter_node("init_case", {
        "case_id": state.get("case_id", "(auto)"),
        "company": company,
        "strategy_theme": theme,
        "cutoff_date": cutoff,
    })

    # LLM-driven case expansion: always generate dimensions, plus
    # regions/peers if not provided in config
    updates: dict = {}
    need_regions_peers = not regions or not peers

    reporting.log_action(
        "Generating analysis dimensions from case context (LLM)",
    )
    generated = _generate_case_context(company, theme, cutoff)

    if not regions:
        regions = generated["regions"]
        updates["regions"] = regions
        reporting.log_action("Generated regions", {
            "regions": ", ".join(regions),
        })

    if not peers:
        peers = generated["peers"]
        updates["peers"] = peers
        reporting.log_action("Generated peers", {
            "peers": ", ".join(
                p.get("company", p) if isinstance(p, dict) else str(p)
                for p in peers
            ),
        })

    if not need_regions_peers:
        reporting.log_action("Using provided regions and peers", {
            "regions": ", ".join(regions),
            "peers": len(peers),
        })

    # Store generated analysis dimensions
    if "analysis_dimensions" in generated:
        updates["analysis_dimensions"] = generated["analysis_dimensions"]
        for key, group in generated["analysis_dimensions"].items():
            dim_names = group.get("dimension_names", [])
            reporting.log_action(f"Dimensions [{key}]", {
                "role": group.get("role_name", "?"),
                "dimensions": ", ".join(dim_names),
            })
    else:
        reporting.log_action("No dimensions generated — using hardcoded defaults")

    result = {
        "current_stage": "init_case",
        "iteration_count": 0,
        "adversarial_pass_count": 0,
        "evidence": [],
        "risk_factors": [],
        "adversarial_challenges": [],
        "backtest_events": [],
        "retrieved_docs": [],
        "overall_risk_level": None,
        "overall_confidence": None,
        "risk_memo": None,
        "backtest_summary": None,
        "error": None,
        # Agentic routing fields
        "evidence_sufficient": None,
        "follow_up_queries": [],
        "adversarial_recommendation": None,
        **updates,
    }

    reporting.exit_node("init_case", next_node="retrieval")
    return result
