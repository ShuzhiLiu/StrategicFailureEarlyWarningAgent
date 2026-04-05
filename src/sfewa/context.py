"""Pipeline context injection -- inspired by Claude Code's TODO state injection.

Each node receives a brief summary of what happened in prior nodes, making
downstream nodes context-aware. This prevents information loss across
the pipeline and enables better decision-making.

Uses liteagent.state utilities (dedup_by_key, count_by) for common patterns.
"""

from __future__ import annotations

from liteagent import count_by, dedup_by_key
from sfewa.schemas.state import PipelineState


def build_pipeline_context(state: PipelineState) -> str:
    """Build a brief summary of pipeline history for injection into node prompts.

    Returns a concise string summarizing what has happened so far in the pipeline.
    Designed to be prepended to system prompts for context-awareness.
    """
    parts: list[str] = []
    iteration = state.get("iteration_count", 0)
    adv_pass = state.get("adversarial_pass_count", 0)

    # Retrieval summary
    docs = state.get("retrieved_docs", [])
    if docs:
        source_counts = count_by(docs, "source")
        parts.append(
            f"Retrieved {len(docs)} documents "
            f"({', '.join(f'{v} {k}' for k, v in sorted(source_counts.items()))})"
        )

    # Evidence summary
    evidence = state.get("evidence", [])
    if evidence:
        stances = count_by(evidence, "stance")
        parts.append(
            f"Extracted {len(evidence)} evidence items "
            f"(stance: {stances.get('supports_risk', 0)} supports, "
            f"{stances.get('contradicts_risk', 0)} contradicts, "
            f"{stances.get('neutral', 0)} neutral)"
        )

    # Quality gate decision
    if state.get("evidence_sufficient") is not None:
        sufficient = state["evidence_sufficient"]
        if sufficient:
            parts.append("Quality gate: evidence sufficient")
        else:
            follow_up = state.get("follow_up_queries", [])
            parts.append(
                f"Quality gate: evidence insufficient -- "
                f"looped back with {len(follow_up)} follow-up queries"
            )

    # Iteration context
    if iteration > 1:
        parts.append(f"Retrieval iterations: {iteration}")

    # Risk factors summary (deduped)
    risk_factors = state.get("risk_factors", [])
    if risk_factors:
        deduped = dedup_by_key(risk_factors, "dimension")
        sev_counts = count_by(deduped, "severity")
        sev_str = ", ".join(f"{v} {k}" for k, v in sorted(sev_counts.items()))
        parts.append(f"Risk factors: {len(deduped)} ({sev_str})")

    # Adversarial summary
    challenges = state.get("adversarial_challenges", [])
    if challenges:
        sev = count_by(challenges, "severity")
        parts.append(
            f"Adversarial challenges: {len(challenges)} "
            f"({sev.get('strong', 0)} strong, {sev.get('moderate', 0)} moderate, {sev.get('weak', 0)} weak)"
        )

    if adv_pass > 1:
        parts.append(f"Adversarial passes: {adv_pass}")

    rec = state.get("adversarial_recommendation")
    if rec:
        parts.append(f"Adversarial recommendation: {rec}")

    if not parts:
        return ""

    return "PIPELINE CONTEXT (what has happened so far):\n" + "\n".join(f"- {p}" for p in parts)
