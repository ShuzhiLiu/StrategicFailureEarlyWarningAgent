"""Prompt template for the init_case agent — LLM-driven case expansion.

When the user provides only (company, strategy_theme, cutoff_date),
the init_case agent uses the LLM to generate regions and peers.
"""

from __future__ import annotations

CASE_EXPANSION_SYSTEM = """\
You are a strategic analysis planning agent. Given a company and strategy theme, \
identify the key geographic regions and competitor companies relevant to the analysis.

Your job is to provide focused, actionable context — not an exhaustive list. \
Pick the regions and peers that matter MOST for this specific strategy theme.
"""

CASE_EXPANSION_USER = """\
Company: {company}
Strategy theme: {strategy_theme}
Analysis cutoff: {cutoff_date}

Based on this company and strategy, identify:

1. **regions**: 3-5 geographic regions most relevant to this strategy \
(e.g., "north_america", "china", "europe", "japan", "southeast_asia", "global"). \
Pick regions where the company has significant operations OR where competitive \
dynamics for this strategy are strongest.

2. **peers**: 5-7 competitor companies most relevant for benchmarking this strategy. \
For each peer, provide just the company name.

Return a JSON object with exactly two fields:
- "regions": array of region strings
- "peers": array of company name strings

Respond with ONLY the JSON object, no other text.
"""
