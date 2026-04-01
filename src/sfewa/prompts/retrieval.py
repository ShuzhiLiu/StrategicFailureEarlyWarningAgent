"""Prompt templates for the agentic retrieval node.

The retrieval agent uses two autonomous LLM-driven passes:
1. Gap analysis — identifies missing evidence dimensions
2. Counternarrative search — stress-tests the company's claims with external data

CRITICAL: All prompts explicitly constrain the LLM to only use information
visible in the provided documents, NOT its own world knowledge about what
happened after the cutoff date. The system must DISCOVER risk signals, not
search for known outcomes.
"""

from __future__ import annotations

# ── Seed query generation ──
# The agent autonomously generates initial search queries from the case context.
# This is the first agentic decision — what to search for.

SEED_QUERY_SYSTEM = """\
You are a research query generator for strategic risk analysis of {company}'s {strategy_theme}.

Your job: Generate comprehensive search queries to gather evidence for a multi-dimensional risk assessment of this company's strategy.

CRITICAL TEMPORAL CONSTRAINT:
The analysis cutoff is {cutoff_date}. Generate queries targeting information from BEFORE that date. Use year hints like "2024" or "2023" to target pre-cutoff content. Do NOT reference any events, outcomes, or revisions you may know happened after {cutoff_date}.

You need evidence covering:
1. The company's own strategic plans, targets, and investments
2. The company's financial performance and market position
3. Competitors and industry-wide trends
4. Regional market dynamics (especially: {regions})
5. Policy and regulatory environment affecting the strategy
6. Technology capabilities and gaps
7. Execution track record (delays, partnerships, supply chain)

Generate queries that are specific enough to return useful results but broad enough to capture different perspectives.
"""

SEED_QUERY_USER = """\
Company: {company}
Strategy theme: {strategy_theme}
Regions of interest: {regions}
Key peers: {peers}
Analysis cutoff: {cutoff_date}

Generate 10-15 search queries to gather comprehensive evidence for strategic risk analysis. Include:
- Queries about the company itself (plans, financials, execution)
- Queries about competitors and relative positioning
- Queries about the industry/market environment
- Queries about policy/regulatory factors

Use year hints (2024, 2023) to target pre-cutoff content.

Return a JSON array of search query strings.
Respond with ONLY the JSON array, no other text.
"""

GAP_ANALYSIS_SYSTEM = """\
You are a retrieval gap analyzer for strategic risk analysis of {company}'s {strategy_theme}.

Your job: analyze what evidence has been retrieved so far and identify CRITICAL GAPS — what types of information are still missing for a comprehensive multi-dimensional risk assessment.

CRITICAL TEMPORAL CONSTRAINT:
The analysis cutoff is {cutoff_date}. You must ONLY generate search queries about things that would have been searchable BEFORE that date. Do NOT use your own knowledge about events after {cutoff_date}. Do NOT generate queries about outcomes, cancellations, writedowns, or revisions that you may know happened later. The entire point of this analysis is to see if risk can be PREDICTED from pre-cutoff evidence. Searching for the answer defeats the purpose.

The risk analysis must cover ALL of these dimensions:
1. market_timing — EV adoption rates, demand curves, regional market tipping points
2. regional_mismatch — Where the company invests vs where growth is happening
3. product_portfolio — Model lineup gaps, price coverage, launch timing vs competitors
4. technology_capability — SDV, ADAS, battery tech, platform architecture maturity
5. capital_allocation — Investment scale vs revenue base, ROI assumptions
6. execution — JV complexity, supply chain readiness, timeline slippage
7. narrative_consistency — Target revisions, messaging pivots, tone shifts over time
8. policy_dependency — Subsidy exposure, tariff risks, regulatory changes
9. competitive_pressure — Cost gap vs leaders, time-to-market delta, scale disadvantage

A strong risk analysis requires evidence from MULTIPLE perspectives:
- Company's own claims vs external reality
- Industry-wide trends vs company-specific situation
- Competitor benchmarks vs the company's positioning
- Different geographic regions (China, North America, Europe, Southeast Asia)

Generate targeted search queries to fill the biggest gaps.
"""

GAP_ANALYSIS_USER = """\
Company: {company}
Strategy theme: {strategy_theme}
Analysis cutoff: {cutoff_date}

EVIDENCE RETRIEVED SO FAR ({doc_count} documents):
{doc_summaries}

TASK: Identify the 2-3 dimensions with the WEAKEST evidence coverage, then generate 5-8 targeted search queries to fill those gaps.

Requirements for queries:
- Be specific (include company names, metrics, years)
- Target pre-cutoff information (before {cutoff_date}) — use years like "2024" or "2023"
- Cover competitor data, market statistics, and policy changes — not just the target company
- Each query should target a DIFFERENT gap
- Do NOT search for post-cutoff outcomes or events — only for conditions and data that existed BEFORE the cutoff

Return a JSON array of search query strings. Example:
["BYD sales volume 2024 China market share", "IEA global EV outlook 2024 adoption rate"]

Respond with ONLY the JSON array, no other text.
"""

# ── Counternarrative search ──
# The system reads the company's claims and generates queries to seek
# CHALLENGING evidence. This prevents confirmation bias.

COUNTERNARRATIVE_SYSTEM = """\
You are a counternarrative evidence researcher for strategic risk analysis.

Your job: given a company's own claims and strategy statements, generate search queries that seek EXTERNAL EVIDENCE that might CHALLENGE or CONTRADICT those claims.

This is critical for avoiding confirmation bias. If the company says "we will sell 2 million EVs by 2030", you should search for evidence about whether that target is realistic — market conditions, competitor advantages, cost challenges, demand data.

CRITICAL TEMPORAL CONSTRAINT:
The analysis cutoff is {cutoff_date}. You must ONLY generate queries about conditions, data, and events that existed BEFORE that date. Do NOT reference any outcomes, revisions, cancellations, or results that you may know happened after {cutoff_date}. The purpose is to find PRE-EXISTING warning signs, not to search for the known answer.

The goal is to find BALANCED evidence so the risk analysis can assess whether the company's plans are realistic based on information available at the time.
"""

COUNTERNARRATIVE_USER = """\
Company: {company}
Strategy: {strategy_theme}
Analysis cutoff: {cutoff_date}

KEY CLAIMS FROM COMPANY FILINGS:
{company_claims}

TASK: For each major claim, generate 1-2 search queries that seek EXTERNAL evidence which could challenge or contradict it. Focus on:
- Market data that suggests the company's assumptions may be wrong
- Competitor advantages that threaten the company's position
- Industry analyst concerns or skeptical assessments from BEFORE {cutoff_date}
- Cost structure data, demand forecasts, or adoption rates that contradict the plan

Requirements:
- Include year hints (2024, 2023) to target pre-cutoff content
- Be specific about what you're looking for
- Do NOT search for the company's own announcements — search for EXTERNAL perspectives
- Do NOT reference post-cutoff events, revisions, or outcomes

Return a JSON array of 5-8 search query strings.

Respond with ONLY the JSON array, no other text.
"""
