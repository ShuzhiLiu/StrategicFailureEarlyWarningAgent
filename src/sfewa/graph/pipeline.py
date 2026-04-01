"""Main LangGraph StateGraph assembly.

This module wires all agent nodes into the pipeline graph.

KEY DESIGN: LLM-driven routing makes this an AGENTIC system, not just a pipeline.
- Evidence quality gate: LLM decides if evidence is sufficient or needs more retrieval
- Adversarial reviewer: LLM recommends proceed vs reanalyze
- Dead-loop protection: iteration counters as safety bounds only

Architecture patterns:
- Fan-out parallel analysts via Send API (LangGraph)
- LLM-driven quality gate for evidence sufficiency (agentic routing)
- Adversarial review with LLM-recommended loop-back
- Separated evaluation — adversarial reviewer never self-evaluates
- Dead-loop protection via iteration counters (safety bounds)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

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
from sfewa.graph.routing import after_adversarial_review, route_after_quality_gate
from sfewa.schemas.state import PipelineState


def build_pipeline() -> StateGraph:
    """Build the full analysis pipeline graph.

    Flow:
      init_case -> retrieval -> evidence_extraction -> quality_gate
        --(LLM decides: sufficient)--> [industry | company | peer] analysts (parallel)
        --(LLM decides: insufficient)--> retrieval (follow-up loop)
        -> adversarial_review
        --(LLM recommends: proceed)--> risk_synthesis -> backtest -> END
        --(LLM recommends: reanalyze)--> evidence_extraction (loop)
    """
    workflow = StateGraph(PipelineState)

    # ── Register nodes ──
    workflow.add_node("init_case", init_case_node)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("evidence_extraction", evidence_extraction_node)
    workflow.add_node("quality_gate", quality_gate_node)
    workflow.add_node("industry_analyst", industry_analyst_node)
    workflow.add_node("company_analyst", company_analyst_node)
    workflow.add_node("peer_analyst", peer_analyst_node)
    workflow.add_node("adversarial_review", adversarial_review_node)
    workflow.add_node("risk_synthesis", risk_synthesis_node)
    workflow.add_node("backtest", backtest_node)

    # ── Linear edges ──
    workflow.add_edge(START, "init_case")
    workflow.add_edge("init_case", "retrieval")
    workflow.add_edge("retrieval", "evidence_extraction")
    workflow.add_edge("evidence_extraction", "quality_gate")

    # ── LLM-driven quality gate: sufficient → fan-out, insufficient → retrieval ──
    def route_after_gate(state: PipelineState) -> list[Send] | str:
        route = route_after_quality_gate(state)
        if route == "retrieval":
            return "retrieval"
        # Fan-out to 3 parallel analysts
        return [
            Send("industry_analyst", state),
            Send("company_analyst", state),
            Send("peer_analyst", state),
        ]

    workflow.add_conditional_edges(
        "quality_gate",
        route_after_gate,
        ["industry_analyst", "company_analyst", "peer_analyst", "retrieval"],
    )

    # ── All analysts converge -> adversarial review ──
    workflow.add_edge("industry_analyst", "adversarial_review")
    workflow.add_edge("company_analyst", "adversarial_review")
    workflow.add_edge("peer_analyst", "adversarial_review")

    # ── LLM-driven adversarial routing ──
    workflow.add_conditional_edges(
        "adversarial_review",
        after_adversarial_review,
        {
            "evidence_extraction": "evidence_extraction",
            "risk_synthesis": "risk_synthesis",
        },
    )

    # ── Final stages ──
    workflow.add_edge("risk_synthesis", "backtest")
    workflow.add_edge("backtest", END)

    return workflow


def compile_pipeline():
    """Build and compile the pipeline, returning a runnable graph."""
    workflow = build_pipeline()
    return workflow.compile()
