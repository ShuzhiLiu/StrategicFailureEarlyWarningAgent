"""Case initialization node — loads config and initializes pipeline state."""

from __future__ import annotations

from sfewa import reporting
from sfewa.schemas.state import PipelineState


def init_case_node(state: PipelineState) -> dict:
    """Initialize the pipeline state from case configuration.

    This node validates the case config and sets up initial state values.
    The case config fields (case_id, company, etc.) should already be set
    by the caller when invoking the graph.
    """
    reporting.enter_node("init_case", {
        "case_id": state.get("case_id", "?"),
        "company": state.get("company", "?"),
        "strategy_theme": state.get("strategy_theme", "?"),
        "cutoff_date": state.get("cutoff_date", "?"),
        "regions": ", ".join(state.get("regions", [])),
        "peers": len(state.get("peers", [])),
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
    }

    reporting.exit_node("init_case", next_node="retrieval")
    return result
