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
- overall_risk_level: based on the DISTRIBUTION of factor severities AND adversarial adjustments:
  - "critical": Multiple CRITICAL factors, or ≥60% of factors at HIGH+ with strong evidence
  - "high": ≥30% of factors at HIGH+ AND at least one dimension shows a clear failure mechanism (connected causal chain across multiple risk dimensions)
  - "medium": Multiple MEDIUM factors across many dimensions (≥5 MEDIUM+) even without HIGH factors — systemic moderate risk across the board. Also: some HIGH factors balanced by MEDIUM/LOW factors, or evidence is thin/one-sided.
  - "low": No HIGH+ factors (after adversarial downgrades), AND the company is clearly executing well on its core strategy — a market leader whose identified risks are primarily about expansion barriers or manageable challenges, not threats to existing operations. MEDIUM factors about growth ceilings (e.g., tariff barriers to new markets) should not prevent a LOW rating if the core business is strong.
  Consider BOTH the severity distribution AND how the risk factors connect — if multiple dimensions point to the same underlying strategic problem, that increases the overall risk even if individual severities are MEDIUM. Conversely, if HIGH factors are about expansion barriers (not core business threats) or are contradicted by LOW factors in related dimensions, that REDUCES the overall risk.

IMPORTANT: Only downgrade a factor's severity if it received a STRONG adversarial challenge. Moderate and weak challenges should be noted in the memo but should NOT change the factor's severity. After applying only strong-challenge downgrades, use the resulting severity distribution to determine the overall risk level.
- overall_confidence: based on evidence quality, coverage, and adversarial outcomes

EVIDENCE SUFFICIENCY CALIBRATION:
- If the evidence base is THIN (fewer than 10 items), reduce confidence significantly and be cautious about HIGH/CRITICAL ratings
- A risk factor supported by only 1-2 evidence items should have confidence below 0.6
- If evidence is overwhelmingly one-sided (only supports_risk OR only contradicts_risk), flag this as a bias concern — real risk assessments need BOTH confirming and contradicting evidence
- If most evidence comes from a single source type, note this as a coverage gap
- A strong evidence base has 15+ items with mix of supports/contradicts/neutral from diverse sources
"""

SYNTHESIS_USER = """\
Synthesize the following into a final risk assessment:

EVIDENCE STATISTICS:
- Total evidence items: {evidence_count}
- Stance distribution: {stance_supports} supports_risk, {stance_contradicts} contradicts_risk, {stance_neutral} neutral
- Source diversity: {source_summary}

RISK FACTOR SEVERITY DISTRIBUTION:
- Critical: {severity_critical}
- High: {severity_high}
- Medium: {severity_medium}
- Low: {severity_low}
- Total factors: {total_factors}
- High+ ratio: {high_plus_ratio}

Use this distribution to calibrate the overall risk level. A company with mostly LOW/MEDIUM factors should NOT get an overall HIGH rating unless the HIGH factors represent truly dominant risks.

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
