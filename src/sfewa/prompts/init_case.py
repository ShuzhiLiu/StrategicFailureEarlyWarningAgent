"""Prompt template for the init_case agent — LLM-driven case expansion.

When the user provides only (company, strategy_theme, cutoff_date),
the init_case agent uses the LLM to generate regions, peers, and
analysis dimensions tailored to the specific company and strategy.
"""

from __future__ import annotations

CASE_EXPANSION_SYSTEM = """\
You are a strategic analysis planning agent. Given a company and strategy theme, \
design a comprehensive analytical framework: geographic scope, competitor set, \
and multi-dimensional risk analysis perspectives.

Your job is to provide focused, actionable context tailored to this SPECIFIC \
company and strategy — not a generic template. The analysis dimensions should \
capture the full range of strategic risks relevant to this company's situation.
"""

CASE_EXPANSION_USER = """\
Company: {company}
Strategy theme: {strategy_theme}
Analysis cutoff: {cutoff_date}

Design a comprehensive strategic risk analysis framework for this company. Identify:

1. **regions**: 3-5 geographic regions most relevant to this strategy.

2. **peers**: 5-7 competitor companies most relevant for benchmarking.

3. **analysis_dimensions**: 9-12 analysis dimensions organized into 3 analyst perspectives. \
Each dimension should be specific to THIS company and strategy — not generic.

The 3 analyst perspectives are:
- **external**: External environment (market dynamics, policy, macroeconomic forces, industry trends). 2-4 dimensions.
- **internal**: Company internal strategy (financial positioning, execution, R&D, partnerships, organizational capability, product strategy). 3-5 dimensions.
- **comparative**: Competitive positioning (direct competitors, geographic coverage, technology gaps, supply chain, ecosystem advantages). 2-4 dimensions.

For EACH dimension, provide:
- name: short snake_case identifier (e.g., "battery_cost_trajectory", "clinical_pipeline_strength", "platform_ecosystem")
- description: 2-3 sentences explaining WHAT to analyze, WHAT data to look for, and what makes this dimension critical for THIS company's strategy. Include guidance on both current state AND future trajectory.
- structural_hint: 1 sentence describing what STRUCTURAL FORCES (reinforcing loops, systemic dependencies) might drive risk on this dimension. This guides deep analysis when surface-level evidence is concerning.
- critical_assumption: 1 sentence describing the KEY ASSUMPTION the company's strategy depends on for this dimension. This is what a pre-mortem analysis should challenge.

CRITICAL: Dimensions must be SPECIFIC to this strategy theme. Examples:
- For an EV company: battery_technology, charging_infrastructure, platform_architecture, supply_chain_vertical_integration
- For a pharma company: clinical_pipeline, regulatory_approval_track, patent_cliff_exposure, pricing_pressure
- For a tech company: ai_model_capability, compute_infrastructure, developer_ecosystem, data_moat

Think about what perspectives would give the DEEPEST insight into whether this company's strategy could fail. Consider:
- Technology investment and R&D effectiveness
- Partnership and alliance strategy
- Supply chain and manufacturing capability
- Customer/market adoption patterns
- Regulatory and policy landscape
- Financial sustainability of the strategy
- Organizational capability to execute
- Competitive dynamics and market positioning

Return a JSON object with:
- "regions": array of region strings
- "peers": array of company name strings
- "analysis_dimensions": object with 3 keys ("external", "internal", "comparative"), each containing:
  - "role_name": string (human-readable analyst role, e.g., "External Environment Analyst")
  - "dimensions": array of objects, each with "name" (string), "description" (string), "structural_hint" (string), and "critical_assumption" (string)
  - "scope_boundary": string (what this analyst should NOT analyze — covered by the other two)

Respond with ONLY the JSON object, no other text.
"""
