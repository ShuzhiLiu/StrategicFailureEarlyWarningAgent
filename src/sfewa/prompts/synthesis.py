"""Prompt template for the risk synthesis and memo writer agent."""

from __future__ import annotations

SYNTHESIS_SYSTEM = """\
You are a Risk Synthesis Agent producing the final strategic risk assessment for {company}'s {strategy_theme}.

Your job: Synthesize all risk factors, adversarial challenges, and evidence into a structured risk memo.

INPUTS:
- Risk factors from three analyst teams (industry, company, peer)
- Adversarial challenges that questioned those risk factors
- Underlying evidence

OUTPUT REQUIREMENTS:
1. Determine overall_risk_level: "critical", "high", "medium", or "low"
2. Determine overall_confidence: float 0.0-1.0
3. Write a structured risk_memo with these sections:
   - Executive Summary (2-3 sentences)
   - Risk Factor Table (dimension | severity | confidence | key evidence)
   - Causal Narrative (the "failure mechanism" story — how do the risks connect?)
   - Adversarial Challenges & Resolutions (how challenges affected the assessment)
   - Evidence Gaps & Uncertainty
   - Conclusion

SCORING GUIDELINES:
- Adjust risk factor severity based on adversarial challenges (strong challenge → downgrade by one level)
- overall_risk_level: based on the most severe surviving risk factors
- overall_confidence: based on evidence quality, coverage, and adversarial outcomes
"""

SYNTHESIS_USER = """\
Synthesize the following into a final risk assessment:

RISK FACTORS:
{risk_factors_text}

ADVERSARIAL CHALLENGES:
{challenges_text}

EVIDENCE:
{evidence_text}

Return a JSON object with exactly these fields:
- overall_risk_level: string ("critical", "high", "medium", or "low")
- overall_confidence: float (0.0-1.0)
- risk_memo: string (the full structured memo in markdown format)

Respond with ONLY the JSON object, no other text.
"""


def format_challenges_for_synthesis(challenges: list[dict]) -> str:
    """Format adversarial challenges for the synthesis prompt."""
    if not challenges:
        return "(No adversarial challenges were raised)"

    parts = []
    for c in challenges:
        counter = ", ".join(c.get("counter_evidence", [])) or "none"
        parts.append(
            f"[{c.get('challenge_id', '?')}] targets {c.get('target_factor_id', '?')} | "
            f"{c.get('severity', '?').upper()}\n"
            f"  {c.get('challenge_text', '?')}\n"
            f"  Counter-evidence: {counter}"
        )
    return "\n\n".join(parts)
