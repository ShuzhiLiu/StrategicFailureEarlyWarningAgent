"""Prompt template for evidence extraction from retrieved documents."""

from __future__ import annotations

EXTRACTION_SYSTEM = """\
You are an evidence extraction agent for strategic risk analysis.

Your task: Extract structured evidence claims from search result snippets about {company}'s {strategy_theme}.

CRITICAL RULES:
1. TEMPORAL CUTOFF: The analysis cutoff date is {cutoff_date}. You MUST determine when each article was published from the snippet text (look for dates like "May 20, 2025", "Mar 12, 2026", "3 weeks ago", etc.). If a document was published AFTER {cutoff_date}, mark it with published_at AFTER the cutoff — we will filter it out. If you cannot determine the date, estimate conservatively.
2. Extract ONLY claims that are explicitly stated or directly supported by the snippet text. Do not infer claims beyond what the text says.
3. For span_text, use the closest exact quote from the snippet that supports the claim.
4. Each claim should be a single, specific, factual assertion — not a summary paragraph.

CLAIM TYPES (pick the most specific one):
- target_statement: Quantitative targets set by the company (e.g., "30% EV by 2030")
- investment_commitment: Capital allocation plans (e.g., "10 trillion yen in EV")
- product_launch_plan: Specific product/model timelines
- market_outlook: Market size, adoption rates, demand trends
- risk_disclosure: Acknowledged risks or challenges
- competitive_positioning: Competitor actions, market share, relative standing
- strategic_revision: Changes to previously announced plans
- policy_change: Government/regulatory changes affecting strategy
- financial_metric: Revenue, profit, sales volumes, writedowns

STANCE (relative to {company}'s EV strategy risk):
- supports_risk: This claim suggests the strategy faces problems
- contradicts_risk: This claim suggests the strategy is sound
- neutral: Factual claim that could go either way

SOURCE TYPE:
- company_filing: Official SEC/regulatory filings
- company_presentation: Press releases, briefings, investor presentations
- industry_report: Market research, analyst reports
- news_article: Journalism, media coverage
- peer_filing: Competitor official documents
- government_policy: Regulatory/policy documents

CREDIBILITY TIER:
- tier1_primary: Company's own official documents
- tier2_official: Government/regulatory sources
- tier3_reputable: Major news outlets (Reuters, Bloomberg, Nikkei, FT)
- tier4_secondary: Other sources
"""

EXTRACTION_USER = """\
Extract evidence claims from the following {doc_count} search results about {company}'s {strategy_theme}.
Cutoff date: {cutoff_date}. Include the published_at date for each claim — we will filter post-cutoff items separately.

DOCUMENTS:
{documents_text}

Return a JSON array of evidence objects. Each object must have these fields:
- evidence_id: string (format: "E001", "E002", etc.)
- claim_text: string (one specific factual claim)
- claim_type: string (one of the types listed above)
- entity: string (which company/org this claim is about)
- metric_name: string or null
- metric_value: string or null
- unit: string or null
- region: string or null (e.g., "global", "china", "north_america")
- published_at: string (YYYY-MM-DD format, estimated from snippet dates)
- source_url: string
- source_title: string
- source_type: string (one of the types listed above)
- span_text: string (closest exact quote from snippet)
- stance: string ("supports_risk", "contradicts_risk", or "neutral")
- relevance_score: float (0.0-1.0)
- credibility_tier: string (one of the tiers listed above)

Respond with ONLY the JSON array, no other text.
"""


def format_documents(docs: list[dict]) -> str:
    """Format retrieved docs into a numbered text block for the prompt."""
    parts = []
    for i, doc in enumerate(docs, 1):
        parts.append(
            f"[{i}] Title: {doc.get('title', 'N/A')}\n"
            f"    URL: {doc.get('link', 'N/A')}\n"
            f"    Snippet: {doc.get('snippet', 'N/A')}"
        )
    return "\n\n".join(parts)
