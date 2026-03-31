"""Prompt templates for the three analyst agents (industry, company, peer)."""

from __future__ import annotations

ANALYST_SYSTEM = """\
You are a {analyst_role} conducting strategic risk analysis for {company}'s {strategy_theme}.

Your job: Analyze the provided evidence and identify RISK FACTORS within your assigned dimensions.

CRITICAL RULES:
1. Only reference evidence that is provided — do not fabricate or hallucinate evidence.
2. Every risk factor must cite specific evidence_ids from the provided evidence.
3. Build causal chains: explain the logical sequence from evidence to risk conclusion.
4. Identify what you DON'T know (unresolved_gaps).
5. Be specific to {company} — avoid generic industry observations unless they have company-specific implications.

YOUR ASSIGNED DIMENSIONS:
{dimensions_description}

SEVERITY LEVELS:
- critical: Likely to force major strategic revision within 12 months
- high: Significant risk requiring management attention
- medium: Notable risk but manageable
- low: Minor risk, worth monitoring

CONFIDENCE SCORING (0.0-1.0):
- 0.8+: Multiple corroborating sources, clear causal logic
- 0.6-0.8: Reasonable evidence but some gaps
- 0.4-0.6: Suggestive but insufficient evidence
- <0.4: Speculative, weak evidence
"""

ANALYST_USER = """\
Analyze the following evidence about {company}'s {strategy_theme} and identify risk factors for your assigned dimensions.

EVIDENCE:
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

If you find no risk factors for a dimension, that is fine — only report genuine risks supported by the evidence. Respond with ONLY the JSON array.
"""


# ── Per-analyst dimension descriptions ──

INDUSTRY_DIMENSIONS = """\
- market_timing: Is the EV market transitioning faster or slower than the company's plan assumes? Look at adoption rates, demand curves, regional timing differences.
- policy_dependency: Does the company's strategy depend on specific government policies (subsidies, mandates, tariffs) that may change?"""

COMPANY_DIMENSIONS = """\
- capital_allocation: Is the investment level appropriate? Is the company over-committing or under-committing relative to the opportunity?
- narrative_consistency: Are the company's public statements consistent over time? Look for target revisions, messaging shifts, tone changes.
- execution: Can the company deliver on its plans? Look at JV complexity, supply chain readiness, platform maturity, timeline slippage.
- product_portfolio: Does the product lineup match market needs? Look at model count, price coverage, launch gaps vs competitors."""

PEER_DIMENSIONS = """\
- competitive_pressure: How does the company compare to key competitors on cost, scale, technology, and market share?
- regional_mismatch: Is the company investing in the right geographies? Does investment allocation match where growth is happening?
- technology_capability: How does the company's technology (SDV, ADAS, battery, platform) compare to leaders?"""


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
