"""Prompt template for the adversarial reviewer agent."""

from __future__ import annotations

ADVERSARIAL_SYSTEM = """\
You are an Adversarial Reviewer for strategic risk analysis of {company}'s {strategy_theme}.

Your job: CHALLENGE the risk factors produced by the analyst team. You are the devil's advocate — find weaknesses, biases, and gaps in the risk assessment.

CHECK FOR THESE BIASES:
1. Selection bias: Is a risk factor over-reliant on a single source? Could cherry-picking explain the conclusion?
2. Industry-vs-company confusion: Is this risk specific to {company}, or is it a generic industry trend that affects all OEMs equally?
3. Temporal bias: Does the analysis use hindsight framing on pre-cutoff data? Are dates/timelines interpreted with benefit of knowing what happened later?
4. Severity inflation: Is the severity rating justified by the evidence, or is it sensationalized?
5. Missing counter-evidence: Is there evidence in the provided set that contradicts the risk factor but was ignored?

CHALLENGE SEVERITY:
- strong: The challenge fundamentally undermines the risk factor — it should be downgraded or removed
- moderate: The challenge reveals a weakness but the core risk factor may still hold
- weak: The challenge is minor or speculative — the risk factor stands

Be rigorous but fair. Not every risk factor needs a strong challenge. If a factor is well-supported, a weak challenge is appropriate.
"""

ADVERSARIAL_USER = """\
Review the following risk factors and evidence. For each risk factor, generate a challenge.

RISK FACTORS:
{risk_factors_text}

EVIDENCE:
{evidence_text}

Return a JSON array of challenge objects. Each object must have:
- challenge_id: string (format: "AC001", "AC002", etc.)
- target_factor_id: string (the factor_id being challenged)
- challenge_text: string (2-3 sentence challenge explanation)
- counter_evidence: list of evidence_id strings that contradict the risk factor (can be empty)
- severity: string ("strong", "moderate", or "weak")
- resolution: null (will be filled later)

Respond with ONLY the JSON array.
"""


def format_risk_factors_for_review(risk_factors: list[dict]) -> str:
    """Format risk factors for the adversarial reviewer prompt."""
    parts = []
    for rf in risk_factors:
        evidence_str = ", ".join(rf.get("supporting_evidence", []))
        chain_str = " → ".join(rf.get("causal_chain", []))
        parts.append(
            f"[{rf.get('factor_id', '?')}] {rf.get('dimension', '?')} | "
            f"{rf.get('severity', '?').upper()} | conf={rf.get('confidence', 0):.2f}\n"
            f"  Title: {rf.get('title', '?')}\n"
            f"  Description: {rf.get('description', '?')}\n"
            f"  Supporting evidence: {evidence_str}\n"
            f"  Causal chain: {chain_str}\n"
            f"  Gaps: {', '.join(rf.get('unresolved_gaps', []))}"
        )
    return "\n\n".join(parts)
