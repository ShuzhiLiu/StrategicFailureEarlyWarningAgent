"""Plain Python pipeline executor.

Uses liteagent.pipeline utilities (merge_state, run_parallel) for the
generic parts, with SFEWA-specific routing logic on top.

KEY DESIGN: LLM-driven routing makes this an AGENTIC system, not just a pipeline.
- Evidence quality gate: LLM decides if evidence is sufficient or needs more retrieval
- Adversarial reviewer: LLM recommends proceed vs reanalyze
- Dead-loop protection: iteration counters as safety bounds only
"""

from __future__ import annotations

from collections import Counter

from liteagent import merge_state, run_parallel

from sfewa import reporting
from sfewa.tools.chat_log import log_event
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

# Severity ordinal for spread computation
_SEV_ORD = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _compute_analyst_agreement(risk_factors: list[dict]) -> dict:
    """Compute cross-analyst agreement metrics after parallel fan-out.

    Returns a dict with:
      - severity_concentration: float 0-1 (1 = all same severity, 0 = uniform)
      - depth_spread: int (max depth - min depth across all factors)
      - high_plus_agreement: int (number of HIGH+ factors)
      - summary: str (human-readable for injection into synthesis prompt)
    """
    if not risk_factors:
        return {"severity_concentration": 0.0, "depth_spread": 0, "high_plus_agreement": 0, "summary": "(no factors)"}

    severities = [f.get("severity", "medium").lower() for f in risk_factors]
    depths = [f.get("depth_of_analysis", 0) for f in risk_factors]

    # Severity concentration: Herfindahl index (sum of squared shares)
    n = len(severities)
    sev_counts = Counter(severities)
    hhi = sum((c / n) ** 2 for c in sev_counts.values())
    # Normalize: min HHI = 1/k (uniform), max = 1.0 (all same)
    # Map to 0-1 where 1 = perfect agreement
    k = len(sev_counts)
    if k <= 1:
        concentration = 1.0
    else:
        min_hhi = 1.0 / k
        concentration = (hhi - min_hhi) / (1.0 - min_hhi) if min_hhi < 1.0 else 1.0

    depth_spread = max(depths) - min(depths) if depths else 0
    high_plus = sum(1 for s in severities if s in ("high", "critical"))

    # Severity ordinal spread (how far apart are the ratings?)
    ordinals = [_SEV_ORD.get(s, 1) for s in severities]
    ordinal_range = max(ordinals) - min(ordinals) if ordinals else 0

    # Build summary
    sev_dist = ", ".join(f"{s.upper()}: {c}" for s, c in sorted(sev_counts.items(), key=lambda x: _SEV_ORD.get(x[0], 0), reverse=True))
    lines = [
        f"Severity distribution: {sev_dist}",
        f"Severity concentration: {concentration:.2f} (1.0 = all same, 0.0 = uniform spread)",
        f"Severity ordinal range: {ordinal_range} ({'tight' if ordinal_range <= 1 else 'wide — analysts disagree on risk magnitude'})",
        f"Depth range: {min(depths)}-{max(depths)} (spread={depth_spread})",
    ]

    if ordinal_range >= 2:
        lines.append(
            "⚠ ANALYST DISAGREEMENT: Severity ratings span 2+ levels. "
            "Confidence should reflect this uncertainty."
        )

    return {
        "severity_concentration": round(concentration, 3),
        "depth_spread": depth_spread,
        "ordinal_range": ordinal_range,
        "high_plus_agreement": high_plus,
        "summary": "\n".join(lines),
    }


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
    for iteration in range(MAX_ITERATIONS):
        state = merge_state(state, retrieval_node(state), accumulate=ACC)
        state = merge_state(state, evidence_extraction_node(state), accumulate=ACC)
        state = merge_state(state, quality_gate_node(state), accumulate=ACC)

        route = route_after_quality_gate(state)
        log_event("routing", "quality_gate", {
            "decision": route,
            "iteration": iteration + 1,
            "max_iterations": MAX_ITERATIONS,
        })
        if route == "fan_out":
            break

    # -- Parallel analyst fan-out --
    log_event("parallel_start", "fan_out", {"nodes": ["industry_analyst", "company_analyst", "peer_analyst"]})
    for result in _run_analysts_parallel(state):
        state = merge_state(state, result, accumulate=ACC)
    log_event("parallel_end", "fan_out", {"nodes": ["industry_analyst", "company_analyst", "peer_analyst"]})

    # -- Analyst agreement (confidence calibration signal) --
    agreement = _compute_analyst_agreement(state.get("risk_factors", []))
    state["analyst_agreement"] = agreement

    # -- Adversarial loop --
    for adv_pass in range(MAX_ADVERSARIAL_PASSES):
        state = merge_state(state, adversarial_review_node(state), accumulate=ACC)

        route = after_adversarial_review(state)
        log_event("routing", "adversarial_review", {
            "decision": route,
            "pass": adv_pass + 1,
            "max_passes": MAX_ADVERSARIAL_PASSES,
        })
        if route == "risk_synthesis":
            break

        # Reanalyze: re-extract evidence + re-run analysts
        state = merge_state(state, evidence_extraction_node(state), accumulate=ACC)
        for result in _run_analysts_parallel(state):
            state = merge_state(state, result, accumulate=ACC)

    # -- Final synthesis --
    state = merge_state(state, risk_synthesis_node(state), accumulate=ACC)
    state = merge_state(state, backtest_node(state), accumulate=ACC)

    return state


def run_pipeline_v2(state: dict) -> dict:
    """Pipeline with agentic retrieval (hybrid architecture).

    Replaces the retrieval -> extraction -> quality_gate loop with a single
    tool-loop agent that autonomously searches and assesses coverage.

    Flow:
      init_case -> agentic_retrieval -> evidence_extraction
        -> [industry | company | peer] analysts (parallel)
        -> [adversarial_review]*
        -> risk_synthesis -> backtest -> END
    """
    from sfewa.agents.agentic_retrieval import agentic_retrieval_node

    ACC = ACCUMULATING_FIELDS

    # -- Init --
    state = merge_state(state, init_case_node(state), accumulate=ACC)

    # -- Agentic retrieval (replaces retrieval + quality_gate loop) --
    state = merge_state(state, agentic_retrieval_node(state), accumulate=ACC)

    # -- Evidence extraction (unchanged — runs once on collected docs) --
    state = merge_state(state, evidence_extraction_node(state), accumulate=ACC)

    # -- Parallel analyst fan-out --
    log_event("parallel_start", "fan_out", {"nodes": ["industry_analyst", "company_analyst", "peer_analyst"]})
    for result in _run_analysts_parallel(state):
        state = merge_state(state, result, accumulate=ACC)
    log_event("parallel_end", "fan_out", {"nodes": ["industry_analyst", "company_analyst", "peer_analyst"]})

    # -- Analyst agreement (confidence calibration signal) --
    agreement = _compute_analyst_agreement(state.get("risk_factors", []))
    state["analyst_agreement"] = agreement

    # -- Adversarial loop --
    for adv_pass in range(MAX_ADVERSARIAL_PASSES):
        state = merge_state(state, adversarial_review_node(state), accumulate=ACC)

        route = after_adversarial_review(state)
        log_event("routing", "adversarial_review", {
            "decision": route,
            "pass": adv_pass + 1,
            "max_passes": MAX_ADVERSARIAL_PASSES,
        })
        if route == "risk_synthesis":
            break

        # Reanalyze: re-extract evidence + re-run analysts
        state = merge_state(state, evidence_extraction_node(state), accumulate=ACC)
        for result in _run_analysts_parallel(state):
            state = merge_state(state, result, accumulate=ACC)

    # -- Final synthesis (unchanged) --
    state = merge_state(state, risk_synthesis_node(state), accumulate=ACC)
    state = merge_state(state, backtest_node(state), accumulate=ACC)

    return state
