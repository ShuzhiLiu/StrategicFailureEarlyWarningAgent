"""Main LangGraph StateGraph assembly.

This module wires all agent nodes into the pipeline graph.

Architecture patterns adopted:
- Fan-out parallel analysts via Send API (LangGraph)
- Adversarial review with loop-back (inspired by TradingAgents-CN bull/bear debate)
- Separated evaluation — adversarial reviewer never self-evaluates
  (Anthropic harness design: "separating generation from evaluation")
- Dead-loop protection via iteration counters (TradingAgents-CN)
- File-based artifact handoffs for audit trail (Anthropic harness design)
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
from sfewa.agents.retrieval import retrieval_node
from sfewa.agents.risk_synthesis import risk_synthesis_node
from sfewa.graph.routing import after_adversarial_review, should_continue_extraction
from sfewa.schemas.state import PipelineState


def build_pipeline() -> StateGraph:
    """Build the full analysis pipeline graph.

    Flow:
      init_case -> retrieval -> evidence_extraction (with tool-call loop guard)
        -> [industry | company | peer] analysts (parallel fan-out)
        -> adversarial_review (with loop-back if too many strong challenges)
        -> risk_synthesis -> backtest -> END
    """
    workflow = StateGraph(PipelineState)

    # ── Register nodes ──
    workflow.add_node("init_case", init_case_node)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("evidence_extraction", evidence_extraction_node)
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

    # ── Dead-loop guard on extraction + fan-out to analysts ──
    # Send API requires returning Send objects from a conditional edge function.
    def route_after_extraction(state: PipelineState) -> list[Send] | str:
        route = should_continue_extraction(state)
        if route == "error":
            return END
        # Fan-out to 3 parallel analysts
        return [
            Send("industry_analyst", state),
            Send("company_analyst", state),
            Send("peer_analyst", state),
        ]

    workflow.add_conditional_edges(
        "evidence_extraction",
        route_after_extraction,
        ["industry_analyst", "company_analyst", "peer_analyst"],
    )

    # ── All analysts converge -> adversarial review ──
    workflow.add_edge("industry_analyst", "adversarial_review")
    workflow.add_edge("company_analyst", "adversarial_review")
    workflow.add_edge("peer_analyst", "adversarial_review")

    # ── Adversarial review -> synthesis or loop back ──
    # Inspired by TradingAgents-CN's debate loop with max rounds
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
