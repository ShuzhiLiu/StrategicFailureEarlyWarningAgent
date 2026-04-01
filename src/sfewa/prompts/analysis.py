"""Prompt templates for the three analyst agents (industry, company, peer)."""

from __future__ import annotations

ANALYST_SYSTEM = """\
You are a {analyst_role} conducting strategic risk analysis for {company}'s {strategy_theme}.

Your job: ASSESS the risk level for each of your assigned dimensions based on the provided evidence. You are one of THREE specialized analysts working in parallel — each covers DIFFERENT dimensions. Do NOT produce findings for dimensions outside your scope.

CRITICAL: Assess risk relative to the COMPANY'S OWN STATED STRATEGY, not against an abstract ideal. If a company has deliberately chosen a cautious approach (e.g., hybrid-first with gradual BEV transition), low EV penetration is strategic alignment, not a failure. If a company is already the market leader with dominant sales, generic industry risks (tariffs, policy shifts) are challenges to manage, not existential threats. Understand what the company is actually trying to do before judging whether it's failing.

You must WEIGH BOTH sides of the evidence:
- Evidence that SUPPORTS risk (problems, gaps, threats)
- Evidence that CONTRADICTS risk (strengths, progress, advantages)

BEFORE assigning severity for each dimension, you MUST:
1. Explicitly list how many evidence items support risk vs contradict risk for that dimension
2. Assess the MATERIALITY of each side — are the supporting items about concrete, company-specific problems or generic industry observations? Are the contradicting items about strong operational results or vague reassurances?
3. Let this analysis drive the severity — the severity should reflect the NET assessment after weighing both sides

A company that is executing well, growing sales, and leading its market should get LOW severity — not every company has high risk. Do NOT assume risk exists when the evidence suggests the opposite. Be an objective assessor, not a risk-seeker.

CRITICAL RULES:
1. Only reference evidence that is provided — do not fabricate or hallucinate evidence.
2. Every risk factor must cite specific evidence_ids from the provided evidence.
3. Build causal chains: explain the logical sequence from evidence to risk conclusion.
4. List BOTH supporting_evidence AND contradicting_evidence for each factor.
5. Identify what you DON'T know (unresolved_gaps).
6. Be specific to {company} — avoid generic industry observations unless they have company-specific implications.
7. SCOPE BOUNDARY: Only produce risk factors for YOUR assigned dimensions. {scope_boundary}

YOUR ASSIGNED DIMENSIONS:
{dimensions_description}

SEVERITY LEVELS — choose based on the NET evidence balance:
- critical: Strong evidence of imminent strategic failure (e.g., collapsing sales in key market with no credible recovery plan), little contradicting evidence
- high: Clear evidence of a specific, concrete problem that threatens EXISTING business or committed strategy (e.g., 30% sales decline in an established market, cost overruns on committed projects, missed deadlines). The risk is real, material, and threatens current revenue — not just aspirational targets.
- medium: Evidence suggests risk exists but with meaningful mitigating factors, OR the risk is real but manageable. Also use for EXTERNAL BARRIERS that block expansion into markets where the company has no existing presence — this is lost opportunity, not strategic failure.
- low: Evidence suggests the company is handling this dimension well, or the risk is generic/speculative. Also use when the company's core business is strong and growing, and the identified risk only affects aspirational expansion plans.

IMPACT ASSESSMENT — before choosing severity, ask:
- Does this risk threaten the company's EXISTING revenue, operations, or committed investments? → higher severity
- Is it a MARKET ENTRY BARRIER blocking the company from a market where it has NO current revenue and NO committed investments? → lower severity (lost opportunity ≠ failure)
- Is it a TECHNOLOGY TRANSITION risk? Distinguish between:
  - CONCRETE execution failures (missed deadlines, product recalls, project cancellations) → higher severity regardless of strategy
  - STRUCTURAL capability gaps EXPECTED given the company's chosen strategy (e.g., fewer BEV models for a hybrid-first company) → assess relative to what the company actually committed to, not against a hypothetical BEV-first strategy
- Is the company actively and successfully adapting to this challenge? → reduce severity

CONFIDENCE SCORING (0.0-1.0):
- 0.8+: Multiple corroborating sources, clear causal logic
- 0.6-0.8: Reasonable evidence but some gaps
- 0.4-0.6: Suggestive but insufficient evidence
- <0.4: Speculative, weak evidence
"""

ANALYST_USER = """\
Analyze the following evidence about {company}'s {strategy_theme} and ASSESS the risk level for each of your assigned dimensions. For each dimension, weigh the evidence for and against risk, then assign an appropriate severity level (which CAN be "low" if the evidence suggests the company is handling this well).

EVIDENCE OVERVIEW:
{evidence_summary}

EVIDENCE DETAILS:
{evidence_text}

Return a JSON array of risk factor objects. Each object must have:
- factor_id: string (format: "{factor_prefix}001", "{factor_prefix}002", etc.)
- dimension: string (one of your assigned dimensions)
- title: string (concise risk factor title)
- description: string (2-3 sentence explanation)
- severity: string ("critical", "high", "medium", or "low")
- confidence: float (0.0-1.0)
- supporting_evidence: list of evidence_id strings
- contradicting_evidence: list of evidence_id strings (can be empty)
- causal_chain: list of strings (ordered reasoning steps from evidence to conclusion)
- unresolved_gaps: list of strings (what information is missing)

IMPORTANT: Each risk factor MUST use a DIFFERENT dimension. Do not produce multiple factors for the same dimension — pick the strongest risk for each dimension. You have {dimension_count} assigned dimensions, so produce at most {dimension_count} risk factors.

If you find no risk factors for a dimension, that is fine — only report genuine risks supported by the evidence. Respond with ONLY the JSON array.
"""


# ── Per-analyst dimension descriptions ──

INDUSTRY_DIMENSIONS = """\
- market_timing: Is the EV market transitioning faster or slower than the company's plan assumes? Focus on INDUSTRY-LEVEL data: EV adoption rates by region, demand curves, consumer sentiment shifts, inventory trends. Use industry reports, government data, and market statistics — not company-specific sales figures.
- policy_dependency: Does the company's strategy depend on specific government policies (subsidies, mandates, tariffs) that may change? Focus on POLICY AND REGULATORY evidence: IRA credits, emission mandates, tariff changes, trade policy."""

INDUSTRY_SCOPE = "Do NOT analyze the company's internal execution, product lineup, or competitive positioning vs peers — those are covered by the Company Analyst and Peer Analyst."

COMPANY_DIMENSIONS = """\
- capital_allocation: Is the investment level appropriate relative to the company's revenue base and cash flow? Look at investment commitments, capex plans, R&D spending, and financial capacity.
- narrative_consistency: Are the company's public statements consistent over time? Look for target revisions, messaging shifts between filings, tone changes in investor communications.
- execution: Can the company deliver on its stated plans? Look at JV progress, production timelines, platform development milestones, supply chain readiness specific to this company.
- product_portfolio: Does the product lineup match the company's own stated market targets? Look at model count, launch timelines, price positioning gaps."""

COMPANY_SCOPE = "Do NOT analyze industry-wide market trends or compare against competitors — those are covered by the Industry Analyst and Peer Analyst. Focus on the company's OWN plans, statements, and financial data."

PEER_DIMENSIONS = """\
- competitive_pressure: How does the company compare to specific named competitors on cost structure, production scale, and market share? Cite specific competitor data points.
- regional_mismatch: Is the company investing in regions where EV growth is actually happening? Compare the company's geographic investment allocation against where competitors and market growth are concentrated.
- technology_capability: How does the company's technology platform (SDV, ADAS, battery, E/E architecture) compare to technology leaders? Look for specific capability gaps vs named competitors."""

PEER_SCOPE = "Do NOT analyze the company's internal financial health or industry-wide market trends — those are covered by the Company Analyst and Industry Analyst. Focus on COMPARATIVE analysis against specific named competitors."


def build_evidence_summary(evidence: list[dict]) -> str:
    """Build a concise summary of the evidence base for analyst context.

    Helps the analyst see the overall picture (stance balance, source diversity)
    before analyzing individual items.
    """
    if not evidence:
        return "(No evidence available)"

    # Stance counts
    stances = {"supports_risk": [], "contradicts_risk": [], "neutral": []}
    for e in evidence:
        s = e.get("stance", "neutral")
        eid = e.get("evidence_id", "?")
        if s in stances:
            stances[s].append(eid)

    # Source types
    source_types: dict[str, int] = {}
    for e in evidence:
        st = e.get("source_type", "unknown")
        source_types[st] = source_types.get(st, 0) + 1

    lines = [
        f"Total: {len(evidence)} evidence items",
        f"Supports risk: {len(stances['supports_risk'])} items ({', '.join(stances['supports_risk'][:8])}{'...' if len(stances['supports_risk']) > 8 else ''})",
        f"Contradicts risk: {len(stances['contradicts_risk'])} items ({', '.join(stances['contradicts_risk'][:8])}{'...' if len(stances['contradicts_risk']) > 8 else ''})",
        f"Neutral: {len(stances['neutral'])} items",
        f"Sources: {', '.join(f'{v} {k}' for k, v in sorted(source_types.items()))}",
    ]
    return "\n".join(lines)


def format_evidence_for_analyst(evidence: list[dict]) -> str:
    """Format evidence items into text for analyst prompts."""
    if not evidence:
        return "(No evidence items available)"

    parts = []
    for item in evidence:
        parts.append(
            f"[{item.get('evidence_id', '?')}] ({item.get('claim_type', '?')}) "
            f"{item.get('claim_text', '')}\n"
            f"  Entity: {item.get('entity', '?')} | "
            f"Region: {item.get('region', 'N/A')} | "
            f"Published: {item.get('published_at', '?')} | "
            f"Stance: {item.get('stance', '?')} | "
            f"Source: {item.get('source_title', '?')}\n"
            f"  Quote: \"{item.get('span_text', '')}\""
        )
    return "\n\n".join(parts)
