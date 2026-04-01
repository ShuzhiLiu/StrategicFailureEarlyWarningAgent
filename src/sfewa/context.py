"""Pipeline context injection — inspired by Claude Code's TODO state injection.

Each node receives a brief summary of what happened in prior nodes, making
downstream nodes context-aware. This prevents information loss across
the pipeline and enables better decision-making.

Example: the synthesis agent knows the quality gate found evidence thin
on technology_capability, so it weighs that dimension's confidence lower.
"""

from __future__ import annotations

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
        source_counts: dict[str, int] = {}
        for d in docs:
            s = d.get("source", "unknown")
            source_counts[s] = source_counts.get(s, 0) + 1
        parts.append(
            f"Retrieved {len(docs)} documents "
            f"({', '.join(f'{v} {k}' for k, v in sorted(source_counts.items()))})"
        )

    # Evidence summary
    evidence = state.get("evidence", [])
    if evidence:
        stances = {"supports_risk": 0, "contradicts_risk": 0, "neutral": 0}
        for e in evidence:
            s = e.get("stance", "neutral")
            if s in stances:
                stances[s] += 1
        parts.append(
            f"Extracted {len(evidence)} evidence items "
            f"(stance: {stances['supports_risk']} supports, "
            f"{stances['contradicts_risk']} contradicts, "
            f"{stances['neutral']} neutral)"
        )

    # Quality gate decision
    if state.get("evidence_sufficient") is not None:
        sufficient = state["evidence_sufficient"]
        if sufficient:
            parts.append("Quality gate: evidence sufficient")
        else:
            follow_up = state.get("follow_up_queries", [])
            parts.append(
                f"Quality gate: evidence insufficient — "
                f"looped back with {len(follow_up)} follow-up queries"
            )

    # Iteration context
    if iteration > 1:
        parts.append(f"Retrieval iterations: {iteration}")

    # Risk factors summary (deduped)
    risk_factors = state.get("risk_factors", [])
    if risk_factors:
        seen: dict[str, dict] = {}
        for rf in risk_factors:
            seen[rf.get("dimension", "?")] = rf
        deduped = list(seen.values())
        sev_counts = {}
        for rf in deduped:
            s = rf.get("severity", "?")
            sev_counts[s] = sev_counts.get(s, 0) + 1
        sev_str = ", ".join(f"{v} {k}" for k, v in sorted(sev_counts.items()))
        parts.append(f"Risk factors: {len(deduped)} ({sev_str})")

    # Adversarial summary
    challenges = state.get("adversarial_challenges", [])
    if challenges:
        sev = {"strong": 0, "moderate": 0, "weak": 0}
        for c in challenges:
            s = c.get("severity", "weak")
            if s in sev:
                sev[s] += 1
        parts.append(
            f"Adversarial challenges: {len(challenges)} "
            f"({sev['strong']} strong, {sev['moderate']} moderate, {sev['weak']} weak)"
        )

    if adv_pass > 1:
        parts.append(f"Adversarial passes: {adv_pass}")

    rec = state.get("adversarial_recommendation")
    if rec:
        parts.append(f"Adversarial recommendation: {rec}")

    if not parts:
        return ""

    return "PIPELINE CONTEXT (what has happened so far):\n" + "\n".join(f"- {p}" for p in parts)
