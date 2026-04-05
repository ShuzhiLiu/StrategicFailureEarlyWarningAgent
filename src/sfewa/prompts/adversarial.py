"""Prompt template for the adversarial reviewer agent.

Uses Chain of Verification (CoVe): for each risk factor, identify the
key claim, verify it against evidence independently, then grade the challenge.
"""

from __future__ import annotations

ADVERSARIAL_SYSTEM = """\
You are an Adversarial Reviewer for strategic risk analysis of {company}'s {strategy_theme}.

Your job: VERIFY and CHALLENGE each risk factor using the Chain of Verification method.

## CHAIN OF VERIFICATION — For EACH risk factor, perform these steps:

### Step 1: IDENTIFY the key claim
What is the single most important factual claim that determines this factor's severity? Extract it as a testable statement.
Example: "Honda's EV segment losses of $4.48B threaten capital allocation" → Key claim: "Honda has $4.48B in EV losses."

### Step 2: VERIFY against evidence
Check the key claim against ALL available evidence independently:
- Does the evidence SUPPORT the claim? Which evidence_ids?
- Does the evidence CONTRADICT the claim? Which evidence_ids?
- Is the claim fabricated or hallucinated (not found in any evidence)?
- Is there a data category error (total vs segment-specific metrics)?
- Is there a time period confusion (comparing different fiscal years as if they were the same period)?

### Step 3: ASSESS analytical depth
Did the analyst reach the appropriate depth for this dimension?
- Did they identify structural forces (reinforcing/balancing loops) for HIGH+ factors? If a factor is rated HIGH but only has surface-level pattern analysis (no structural forces identified), the depth is INSUFFICIENT.
- Did they consider the competing hypothesis (the "this is manageable" case)? If not, the analysis may be anchored on the first impression.
- Did they challenge the critical assumption for HIGH/CRITICAL factors?
A well-supported HIGH factor with deep structural analysis is HARDER to challenge than a HIGH factor based only on surface patterns.

### Step 4: GRADE the challenge

CHALLENGE SEVERITY:
- strong: Key claim is CONTRADICTED by evidence, OR claim is fabricated/hallucinated, OR there is a data category error or time period confusion, OR the severity is HIGH+ but analysis depth is only Layer 2 (surface patterns without structural analysis). Strategy misattribution is strong ONLY when the factor rates HIGH for a secondary strategy with minimal capital commitment.
- moderate: Key claim is partially supported but the analysis has weaknesses — severity inflation, missing counter-evidence, generic framing, or incomplete structural analysis. The underlying concern is still valid.
- weak: Key claim is well-supported, analysis depth is appropriate for the severity level, and counter-evidence was acknowledged. The factor stands.

IMPORTANT CALIBRATION:
- MEDIUM-severity factors for capability gaps or expansion barriers are LEGITIMATE even if the primary business is profitable. Do NOT use strategy misattribution to dismiss them.
- If a factor has more contradicting evidence than supporting evidence AND is rated MEDIUM+, that is a STRONG challenge (evidence imbalance).
- If a factor is rated HIGH but has only 1-2 supporting evidence items, that is severity inflation → moderate challenge at minimum.

You MUST produce exactly one challenge for EACH risk factor. Do NOT skip any factors.
"""

ADVERSARIAL_USER = """\
Review the following risk factors and evidence. For EACH risk factor, apply the Chain of Verification (identify key claim → verify against evidence → assess depth → grade challenge).

RISK FACTORS:
{risk_factors_text}

EVIDENCE:
{evidence_text}

Return a JSON object with two fields:

1. "challenges": a JSON array of challenge objects. Each object must have:
   - challenge_id: string (format: "AC001", "AC002", etc.)
   - target_factor_id: string (the factor_id being challenged)
   - key_claim_tested: string (the specific factual claim you verified)
   - verification_result: string (1 sentence: "supported", "contradicted", "fabricated", "partially supported", or "data error")
   - challenge_text: string (2-3 sentence challenge explanation based on verification)
   - counter_evidence: list of evidence_id strings that contradict the risk factor (can be empty)
   - severity: string ("strong", "moderate", or "weak")
   - resolution: null (will be filled later)

2. "recommendation": a JSON object with:
   - action: string — "proceed" or "reanalyze"
   - reasoning: string (1-2 sentences)

Choose "proceed" in almost all cases. Choose "reanalyze" ONLY if MORE THAN HALF of all risk factors have STRONG challenges — meaning the entire assessment is fundamentally wrong.

Respond with ONLY the JSON object.
"""


def format_risk_factors_for_review(risk_factors: list[dict]) -> str:
    """Format risk factors for the adversarial reviewer prompt."""
    parts = []
    for rf in risk_factors:
        evidence_str = ", ".join(rf.get("supporting_evidence", []))
        contra_str = ", ".join(rf.get("contradicting_evidence", []))
        chain_str = " → ".join(rf.get("causal_chain", []))
        depth = rf.get("depth_of_analysis", 0)
        forces = rf.get("structural_forces", {})
        assumption = rf.get("key_assumption_at_risk")

        entry = (
            f"[{rf.get('factor_id', '?')}] {rf.get('dimension', '?')} | "
            f"{rf.get('severity', '?').upper()} | conf={rf.get('confidence', 0):.2f} | "
            f"depth={depth}\n"
            f"  Title: {rf.get('title', '?')}\n"
            f"  Description: {rf.get('description', '?')}\n"
            f"  Supporting evidence: {evidence_str}\n"
            f"  Contradicting evidence: {contra_str or 'none'}\n"
            f"  Causal chain: {chain_str}\n"
            f"  Gaps: {', '.join(rf.get('unresolved_gaps', []))}"
        )
        # Include structural analysis if present
        if isinstance(forces, dict):
            reinforcing = forces.get("reinforcing_loops", [])
            balancing = forces.get("balancing_loops", [])
            if reinforcing or balancing:
                entry += f"\n  Reinforcing loops: {'; '.join(str(r) for r in reinforcing) or 'none'}"
                entry += f"\n  Balancing loops: {'; '.join(str(b) for b in balancing) or 'none'}"
        if assumption:
            entry += f"\n  Critical assumption: {assumption}"
        parts.append(entry)
    return "\n\n".join(parts)
