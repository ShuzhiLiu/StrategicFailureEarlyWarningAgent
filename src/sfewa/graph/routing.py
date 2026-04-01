"""Conditional edge routing functions for the LangGraph pipeline.

KEY DESIGN: Routing decisions are LLM-DRIVEN, not hardcoded.
- Evidence quality gate: LLM decides if evidence is sufficient
- Adversarial routing: LLM recommends proceed vs reanalyze
- Dead-loop protection: iteration counters as safety bounds (not primary logic)

This makes the system genuinely agentic — the LLM observes its own outputs
and decides what to do next, rather than following a predetermined path.
"""

from __future__ import annotations

from sfewa.schemas.state import PipelineState

# ── Safety bounds (dead-loop protection only) ──
MAX_ITERATIONS = 3
MAX_ADVERSARIAL_PASSES = 2


def route_after_quality_gate(state: PipelineState) -> str:
    """LLM-driven routing after evidence quality assessment.

    The quality_gate node set `evidence_sufficient` based on LLM analysis.
    This function reads that decision and routes accordingly.
    """
    sufficient = state.get("evidence_sufficient", True)
    iteration = state.get("iteration_count", 0)

    # Safety bound: never loop more than MAX_ITERATIONS times
    if iteration >= MAX_ITERATIONS:
        return "fan_out"

    if sufficient:
        return "fan_out"
    else:
        return "retrieval"  # loop back with follow-up queries


def after_adversarial_review(state: PipelineState) -> str:
    """LLM-driven routing after adversarial review.

    The adversarial_review node set `adversarial_recommendation` based on
    its own assessment of risk factor quality.
    """
    recommendation = state.get("adversarial_recommendation", "proceed")
    pass_count = state.get("adversarial_pass_count", 0)

    # Safety bound
    if pass_count >= MAX_ADVERSARIAL_PASSES:
        return "risk_synthesis"

    if recommendation == "reanalyze":
        return "evidence_extraction"
    else:
        return "risk_synthesis"
