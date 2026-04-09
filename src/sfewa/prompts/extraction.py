"""Prompt template for evidence extraction from retrieved documents."""

from __future__ import annotations

EXTRACTION_SYSTEM = """\
You are an evidence extraction agent for strategic risk analysis.

Your task: Extract structured evidence claims from the provided documents about {company}'s {strategy_theme}.
Documents include official regulatory filings (EDINET), company disclosures, and web search results.

CRITICAL RULES:
1. TEMPORAL CUTOFF: The analysis cutoff date is {cutoff_date}. For documents with a "Published" date shown, use that exact date. For web search snippets, determine publication date from the text (look for dates like "May 20, 2025", "Mar 12, 2026", "3 weeks ago", etc.). If a document was published AFTER {cutoff_date}, mark it with published_at AFTER the cutoff — we will filter it out. DATE ESTIMATION: If you cannot determine the exact date, use clues from the content: if it discusses "FY2024 results" or "2024 sales data", use a date in late 2024 or early 2025. If it discusses "2023" events, use a 2023 date. Only assign a post-cutoff date if there is clear evidence the content was published after {cutoff_date} (explicit dates, references to events you know happened after the cutoff). When uncertain, prefer a pre-cutoff estimate — the temporal filter will catch true violations.
2. Extract ONLY claims that are explicitly stated or directly supported by the snippet text. Do not infer claims beyond what the text says.
3. For span_text, use the closest exact quote from the snippet that supports the claim.
4. Each claim should be a single, specific, factual assertion — not a summary paragraph.
5. For financial_metric claims, ALWAYS include the fiscal year or reporting period in the claim_text (e.g., "FY2024 net profit was 40.25 billion yuan" not just "net profit was 40.25 billion yuan"). This prevents confusion when comparing metrics across different periods.

CLAIM TYPES (pick the most specific one):
- target_statement: Quantitative targets set by the company (e.g., "30% market share by 2030")
- investment_commitment: Capital allocation plans (e.g., "10 trillion yen committed to strategy")
- product_launch_plan: Specific product/model timelines
- technology_capability: Proprietary technology, patents, vertical integration, in-house supply chain, R&D achievements, technology partnerships/supply relationships (e.g., "company's proprietary X technology", "company supplies key platform/components to competitor", "vertical integration covers core value chain from A to B")
- market_outlook: Market size, adoption rates, demand trends
- risk_disclosure: Acknowledged risks or challenges
- competitive_positioning: Competitor actions, market share, relative standing
- strategic_revision: Changes to previously announced plans
- policy_change: Government/regulatory changes affecting strategy
- financial_metric: Revenue, profit, sales volumes, writedowns

STANCE (relative to {company}'s {strategy_theme} risk):
- supports_risk: This claim suggests the strategy faces problems. Includes: declining sales, competitor advantages, execution delays, market headwinds, risk disclosures by the company itself, overly ambitious targets with unclear execution path, large capital commitments with uncertain returns.
- contradicts_risk: This claim suggests the strategy is on track and sound. Includes: strong sales growth, successful launches, healthy financials that support the investment, partnerships on schedule.
- neutral: Factual claim that could go either way, or purely descriptive statements about plans without clear risk signal.

NOTE: A company's OWN risk disclosure (e.g., "we face challenges in...") should be classified as supports_risk — the company itself is acknowledging the problem. Similarly, very ambitious targets should be neutral or supports_risk if there is no evidence the company can achieve them, not contradicts_risk just because the company stated them confidently.

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
    """Format retrieved docs into a numbered text block for the prompt.

    EDINET docs include published_at and source_type metadata.
    Web search docs have only title/URL/snippet.
    """
    parts = []
    for i, doc in enumerate(docs, 1):
        lines = [f"[{i}] Title: {doc.get('title', 'N/A')}"]
        lines.append(f"    URL: {doc.get('link', 'N/A')}")

        # Show known metadata (EDINET docs have these)
        if doc.get("published_at"):
            lines.append(f"    Published: {doc['published_at']}")
        if doc.get("source_type"):
            lines.append(f"    Source type: {doc['source_type']}")
        if doc.get("credibility_tier"):
            lines.append(f"    Credibility: {doc['credibility_tier']}")

        lines.append(f"    Content: {doc.get('snippet', 'N/A')}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
