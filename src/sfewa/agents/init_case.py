"""Case initialization node — loads config and initializes pipeline state.

When regions and peers are not provided, the LLM generates them from
the minimal input (company + strategy_theme + cutoff_date). This is the
Planner's first decision — scoping the analysis.
"""

from __future__ import annotations

import json
import re

from sfewa import reporting
from sfewa.llm import get_llm_for_role
from sfewa.prompts.init_case import CASE_EXPANSION_SYSTEM, CASE_EXPANSION_USER
from sfewa.schemas.state import PipelineState


def _generate_case_context(
    company: str, strategy_theme: str, cutoff_date: str,
) -> dict:
    """Use LLM to generate regions and peers from minimal input."""
    llm = get_llm_for_role("retrieval")  # non-thinking, fast

    try:
        response = llm.invoke([
            {"role": "system", "content": CASE_EXPANSION_SYSTEM},
            {"role": "user", "content": CASE_EXPANSION_USER.format(
                company=company,
                strategy_theme=strategy_theme,
                cutoff_date=cutoff_date,
            )},
        ])
        raw = response.content
        raw = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()

        # Extract JSON object
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            parsed = json.loads(match.group())
            return {
                "regions": parsed.get("regions", []),
                "peers": parsed.get("peers", []),
            }
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

    # LLM-driven case expansion if regions or peers not provided
    updates: dict = {}
    if not regions or not peers:
        reporting.log_action(
            "Generating regions and peers from case context (LLM)",
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
    else:
        reporting.log_action("Using provided regions and peers", {
            "regions": ", ".join(regions),
            "peers": len(peers),
        })

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
