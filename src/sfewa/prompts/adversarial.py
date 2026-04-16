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
If the factor includes a "Key claim" field, use it directly. Otherwise, extract the single most important factual claim that determines this factor's severity as a testable statement.
Example: "Honda's EV segment losses of $4.48B threaten capital allocation" → Key claim: "Honda has $4.48B in EV losses."
If the factor includes a "Warrant" field, verify the warrant's reasoning: does the evidence actually imply the claim through the stated mechanism?

### Step 2: VERIFY against evidence
Check the key claim against ALL available evidence independently:
- Does the evidence SUPPORT the claim? Which evidence_ids?
- Does the evidence CONTRADICT the claim? Which evidence_ids?
- Is the claim fabricated or hallucinated (not found in any evidence)?
- Is there a data category error (total vs segment-specific metrics)?
- Is there a time period confusion (comparing different fiscal years as if they were the same period)?

### Step 3: ASSESS analytical depth AND strategy relevance
Did the analyst reach the appropriate depth for this dimension?
- Did they identify structural forces (reinforcing/balancing loops) for HIGH+ factors? If a factor is rated HIGH but only has surface-level pattern analysis (no structural forces identified), the depth is INSUFFICIENT.
- Did they consider the competing hypothesis (the "this is manageable" case)? If not, the analysis may be anchored on the first impression.
- Did they challenge the critical assumption for HIGH/CRITICAL factors?
A well-supported HIGH factor with deep structural analysis is HARDER to challenge than a HIGH factor based only on surface patterns.

**DEPTH GATE VIOLATION CHECK**: If a dimension is tagged [Strategy relevance: secondary] AND the factor severity is HIGH or CRITICAL, verify that the analyst explicitly justified why this secondary risk undermines the primary strategy. If no such justification exists → this is a STRONG challenge (depth gate violation). The analyst bypassed the strategy-relative depth gate without explanation.

### Step 4: GRADE the challenge

CHALLENGE SEVERITY:
- strong: Key claim is CONTRADICTED by evidence, OR claim is fabricated/hallucinated, OR there is a data category error or time period confusion, OR the severity is HIGH+ but analysis depth is only Layer 2 (surface patterns without structural analysis), OR the dimension is [Strategy relevance: secondary] AND severity is HIGH/CRITICAL without explicit justification for depth gate override (depth gate violation), OR the factor is flagged [EVIDENCE IMBALANCE], OR the factor is flagged [DEPTH_SEVERITY_MISMATCH], [PHANTOM_CITATION], or [STANCE_MISMATCH] (see programmatic flags below).
- moderate: Key claim is partially supported but the analysis has weaknesses — severity inflation, missing counter-evidence, generic framing, or incomplete structural analysis. The underlying concern is still valid.
- weak: Key claim is well-supported, analysis depth is appropriate for the severity level, and counter-evidence was acknowledged. The factor stands.

IMPORTANT CALIBRATION:
- MEDIUM-severity factors for capability gaps or expansion barriers are LEGITIMATE even if the primary business is profitable. Do NOT use strategy misattribution to dismiss them.
- If a factor is rated HIGH but has only 1-2 supporting evidence items, that is severity inflation → moderate challenge at minimum.

**PROGRAMMATIC FLAG RULES**: Factors may carry programmatic flags computed from their own data. Trust these flags — they are deterministic checks, not judgment calls.

- [EVIDENCE IMBALANCE]: Supporting evidence count ≤ contradicting evidence count. For HIGH/CRITICAL factors → STRONG challenge (severity not justified). For MEDIUM → minimum moderate.
- [DEPTH_SEVERITY_MISMATCH]: Analysis depth is inconsistent with severity (e.g., depth=2 but severity=HIGH). → STRONG challenge.
- [MISSING_FORCES]: Depth ≥ 3 but no structural forces identified. → minimum moderate challenge.
- [MISSING_ASSUMPTION]: Depth = 4 but no key assumption articulated. → minimum moderate challenge.
- [PHANTOM_CITATION]: Cited evidence_id does not exist in the evidence base. → STRONG challenge (fabricated citation).
- [STANCE_MISMATCH]: MAJORITY (>50%) of supporting citations have contradicts_risk stance. → STRONG challenge (fundamental citation error — the factor's evidence base contradicts its own claim).
- [MINOR_STANCE_MISMATCH]: Multiple supporting citations have contradicts_risk stance but are a minority. → minimum moderate challenge (notable error but factor may still be valid based on remaining citations).
- [THIN_EVIDENCE]: HIGH/CRITICAL severity with fewer than 2 supporting citations. → minimum moderate challenge.

You MUST produce exactly one challenge for EACH risk factor. Do NOT skip any factors.
"""

ADVERSARIAL_USER = """\
Review the following risk factors and evidence. For EACH risk factor, apply the Chain of Verification (identify key claim → verify against evidence → assess depth → grade challenge).

EVIDENCE STANCE OVERVIEW:
{evidence_stance_summary}

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


# ── Phase 2: Independent Verification Search ──

VERIFICATION_SYSTEM = """\
You are an independent verification agent for strategic risk analysis of \
{company}'s {strategy_theme}.

Your mission: search the web for evidence that CONTRADICTS the key claims \
listed below. The risk analysts already found supporting evidence — you are \
the adversarial check, looking specifically for COUNTER-EVIDENCE.

## CLAIMS TO VERIFY

{claims_text}

## SEARCH STRATEGY

For each claim:
1. Search with specific queries targeting contradicting evidence
2. Include year constraints ({prior_year}-{cutoff_year}) for temporal relevance
3. Look for: company rebuttals, positive financial metrics, alternative data, \
analyst upgrades, or anything that weakens the claim
4. Try 1-2 search queries per claim

TEMPORAL RULE: Ignore any information published after {cutoff_date}.

Search budget: {max_queries} queries maximum.

After all searches, provide a STRUCTURED SUMMARY of findings. For each claim:
- The claim you verified (quote it)
- What you searched for
- What you found (key titles and snippets)
- Verdict: "contradicted" (clear counter-evidence), "weakened" (partial), \
or "not contradicted" (nothing found)
"""

VERIFICATION_USER = """\
Begin searching for counter-evidence to the claims listed above. \
After completing your searches, provide your structured findings summary.\
"""


# ── Phase 3: Challenge Refinement ──

REFINEMENT_SYSTEM = """\
You are refining adversarial challenges for {company}'s {strategy_theme} \
risk analysis after independent web verification.\
"""

REFINEMENT_USER = """\
ORIGINAL CHALLENGES (from preliminary review):
{original_challenges_json}

ORIGINAL RECOMMENDATION:
{original_recommendation_json}

INDEPENDENT VERIFICATION FINDINGS:
{verification_findings}

## REFINEMENT RULES

1. For each challenge where verification found CONTRADICTING evidence:
   - Append " [Independently verified: <key finding>]" to challenge_text
   - If the contradiction is clear and specific → upgrade severity to "strong"
   - Update verification_result to note the independent finding

2. For challenges where verification found NO contradicting evidence:
   - Severity stays the same

3. For challenges NOT covered by verification (LOW/MEDIUM factors):
   - Keep completely unchanged

4. Re-evaluate recommendation:
   - Count total STRONG challenges after refinement
   - If > 50% STRONG → change action to "reanalyze"
   - Otherwise → keep original recommendation

Return the COMPLETE JSON object with "challenges" and "recommendation" fields.
Include ALL challenges (verified and unverified). Same field structure as original.
Respond with ONLY the JSON object.
"""


def format_claims_for_verification(claims: list[dict]) -> str:
    """Format extracted claims into text for the verification agent prompt."""
    lines = []
    for i, c in enumerate(claims, 1):
        lines.append(
            f"{i}. [{c['challenge_id']}] Factor {c['factor_id']} "
            f"(rated {c['factor_severity'].upper()}, "
            f"challenge: {c['current_severity']}):\n"
            f'   "{c["claim"]}"'
        )
    return "\n\n".join(lines)


def build_evidence_stance_summary(
    evidence: list[dict],
    risk_factors: list[dict],
) -> str:
    """Build evidence stance summary with calibration guidance for the adversarial.

    Highlights mismatches between overall evidence balance and severity distribution.
    """
    # Count stances
    stances = {"supports_risk": 0, "contradicts_risk": 0, "neutral": 0}
    for e in evidence:
        s = e.get("stance", "neutral")
        if s in stances:
            stances[s] += 1

    total = len(evidence)
    sup = stances["supports_risk"]
    con = stances["contradicts_risk"]
    neu = stances["neutral"]

    # Count severity distribution
    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for rf in risk_factors:
        s = rf.get("severity", "medium").lower()
        if s in sev_counts:
            sev_counts[s] += 1

    high_plus = sev_counts["critical"] + sev_counts["high"]
    total_factors = len(risk_factors)

    lines = [
        f"Total evidence: {total} items",
        f"  Supports risk: {sup} ({sup*100//total if total else 0}%)",
        f"  Contradicts risk: {con} ({con*100//total if total else 0}%)",
        f"  Neutral: {neu} ({neu*100//total if total else 0}%)",
        f"Risk factor severity: {sev_counts['critical']}C + {sev_counts['high']}H + {sev_counts['medium']}M + {sev_counts['low']}L",
        f"  HIGH+ factors: {high_plus}/{total_factors} ({high_plus*100//total_factors if total_factors else 0}%)",
    ]

    # Calibration warning if severity doesn't match evidence balance
    if total_factors > 0 and con > 0:
        high_ratio = high_plus / total_factors
        sup_con_ratio = sup / con if con > 0 else 999
        # Warn when majority HIGH factors but evidence is roughly balanced or
        # contradicts-leaning. sup:con < 1.5 means evidence doesn't clearly
        # favor risk; combined with 40%+ HIGH factors, suggests inflation.
        if high_ratio >= 0.4 and sup_con_ratio < 1.5:
            lines.append(
                f"\n⚠ CALIBRATION CHECK: {high_plus}/{total_factors} factors "
                f"({high_ratio:.0%}) are HIGH+, but evidence is roughly balanced "
                f"({sup} supports vs {con} contradicts, ratio {sup_con_ratio:.1f}:1). "
                f"When evidence does not clearly favor risk, HIGH severity requires "
                f"especially strong supporting evidence per factor. Cross-check each "
                f"HIGH factor: does its key claim rely on directly supporting evidence, "
                f"or on reinterpretation of neutral sources? If the latter, consider "
                f"upgrading the challenge to STRONG."
            )

    return "\n".join(lines)


def format_risk_factors_for_review(
    risk_factors: list[dict],
    dimension_relevance: dict[str, str] | None = None,
    evidence: list[dict] | None = None,
) -> str:
    """Format risk factors for the adversarial reviewer prompt.

    Args:
        risk_factors: List of risk factor dicts.
        dimension_relevance: Optional mapping of dimension name to "primary"/"secondary".
        evidence: Optional evidence list for citation cross-validation.
    """
    from sfewa.agents._analyst_base import check_depth_consistency, validate_citations

    # Build evidence lookup for citation validation
    evidence_map: dict[str, dict] = {}
    if evidence:
        for e in evidence:
            eid = e.get("evidence_id", "")
            if eid:
                evidence_map[eid] = e

    parts = []
    relevance_map = dimension_relevance or {}
    for rf in risk_factors:
        supporting = rf.get("supporting_evidence", [])
        contradicting = rf.get("contradicting_evidence", [])
        evidence_str = ", ".join(supporting)
        contra_str = ", ".join(contradicting)
        chain_str = " → ".join(rf.get("causal_chain", []))
        depth = rf.get("depth_of_analysis", 0)
        forces = rf.get("structural_forces", {})
        assumption = rf.get("key_assumption_at_risk")
        dim_name = rf.get("dimension", "?")
        relevance = relevance_map.get(dim_name, "primary")

        # -- Programmatic flags (injected for adversarial review) --
        flags: list[str] = []

        # Evidence imbalance check (existing)
        if len(supporting) <= len(contradicting) and len(contradicting) > 0:
            flags.append(
                f"EVIDENCE IMBALANCE: {len(supporting)} supporting "
                f"vs {len(contradicting)} contradicting"
            )

        # Depth-severity consistency check (iter 39)
        for v in check_depth_consistency(rf):
            flags.append(v)

        # Citation cross-validation (iter 39)
        if evidence_map:
            for v in validate_citations(rf, evidence_map):
                flags.append(v)

        flags_str = ""
        if flags:
            flags_str = " " + " ".join(f"[{f}]" for f in flags)

        # Toulmin fields (iter 39)
        claim = rf.get("claim", "")
        warrant = rf.get("warrant", "")
        strongest_counter = rf.get("strongest_counter", "")

        entry = (
            f"[{rf.get('factor_id', '?')}] {dim_name} | "
            f"{rf.get('severity', '?').upper()} | conf={rf.get('confidence', 0):.2f} | "
            f"depth={depth} | [Strategy relevance: {relevance}]{flags_str}\n"
            f"  Title: {rf.get('title', '?')}"
        )
        # Include Toulmin fields when available
        if claim:
            entry += f"\n  Key claim: {claim}"
        if warrant:
            entry += f"\n  Warrant: {warrant}"
        if strongest_counter:
            entry += f"\n  Strongest counter: {strongest_counter}"
        entry += (
            f"\n  Description: {rf.get('description', '?')}\n"
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
