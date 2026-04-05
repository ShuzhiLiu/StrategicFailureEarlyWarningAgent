"""Plain Python pipeline executor.

Uses liteagent.pipeline utilities (merge_state, run_parallel) for the
generic parts, with SFEWA-specific routing logic on top.

KEY DESIGN: LLM-driven routing makes this an AGENTIC system, not just a pipeline.
- Evidence quality gate: LLM decides if evidence is sufficient or needs more retrieval
- Adversarial reviewer: LLM recommends proceed vs reanalyze
- Dead-loop protection: iteration counters as safety bounds only
"""

from __future__ import annotations

from liteagent import merge_state, run_parallel

from sfewa import reporting
from sfewa.agents.adversarial import adversarial_review_node
from sfewa.agents.backtest import backtest_node
from sfewa.agents.company_analyst import company_analyst_node
from sfewa.agents.evidence_extraction import evidence_extraction_node
from sfewa.agents.industry_analyst import industry_analyst_node
from sfewa.agents.init_case import init_case_node
from sfewa.agents.peer_analyst import peer_analyst_node
from sfewa.agents.quality_gate import quality_gate_node
from sfewa.agents.retrieval import retrieval_node
from sfewa.agents.risk_synthesis import risk_synthesis_node
from sfewa.graph.routing import (
    MAX_ADVERSARIAL_PASSES,
    MAX_ITERATIONS,
    after_adversarial_review,
    route_after_quality_gate,
)

# Fields that accumulate across nodes (extend, not overwrite)
ACCUMULATING_FIELDS = {"evidence", "risk_factors", "adversarial_challenges", "backtest_events"}

_ANALYSTS = [industry_analyst_node, company_analyst_node, peer_analyst_node]


def _run_analysts_parallel(state: dict) -> list[dict]:
    """Fan-out 3 analysts in parallel, return their results."""
    return run_parallel(
        _ANALYSTS,
        state,
        on_error=lambda e, _: (
            reporting.log_action("Analyst failed", {"error": str(e)[:200]}),
            {},
        )[-1],
    )


def run_pipeline(state: dict) -> dict:
    """Execute the full analysis pipeline.

    Flow:
      init_case -> [retrieval -> extraction -> quality_gate]*
        --(LLM: sufficient)--> [industry | company | peer] analysts (parallel)
        --(LLM: insufficient)--> retrieval (follow-up loop)
      -> [adversarial_review -> extraction? -> analysts?]*
        --(LLM: proceed)--> risk_synthesis -> backtest -> END
        --(LLM: reanalyze)--> evidence_extraction (loop)
    """
    ACC = ACCUMULATING_FIELDS

    # -- Init --
    state = merge_state(state, init_case_node(state), accumulate=ACC)

    # -- Evidence gathering loop (quality gate drives) --
    for _ in range(MAX_ITERATIONS):
        state = merge_state(state, retrieval_node(state), accumulate=ACC)
        state = merge_state(state, evidence_extraction_node(state), accumulate=ACC)
        state = merge_state(state, quality_gate_node(state), accumulate=ACC)

        if route_after_quality_gate(state) == "fan_out":
            break

    # -- Parallel analyst fan-out --
    for result in _run_analysts_parallel(state):
        state = merge_state(state, result, accumulate=ACC)

    # -- Adversarial loop --
    for _ in range(MAX_ADVERSARIAL_PASSES):
        state = merge_state(state, adversarial_review_node(state), accumulate=ACC)

        if after_adversarial_review(state) == "risk_synthesis":
            break

        # Reanalyze: re-extract evidence + re-run analysts
        state = merge_state(state, evidence_extraction_node(state), accumulate=ACC)
        for result in _run_analysts_parallel(state):
            state = merge_state(state, result, accumulate=ACC)

    # -- Final synthesis --
    state = merge_state(state, risk_synthesis_node(state), accumulate=ACC)
    state = merge_state(state, backtest_node(state), accumulate=ACC)

    return state
