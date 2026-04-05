"""Evidence Quality Gate — LLM-driven routing decision.

This is the key agentic node: instead of hardcoded thresholds, an LLM
observes the extracted evidence and autonomously decides:
  - "sufficient" → proceed to analysts
  - "insufficient" → generate follow-up queries and loop back to retrieval

This transforms the pipeline from a static workflow into a dynamic agent
that reasons about its own information state.
"""

from __future__ import annotations

import json

from liteagent import extract_json, strip_thinking

from sfewa import reporting
from sfewa.llm import get_llm_for_role
from sfewa.schemas.state import PipelineState
from sfewa.tools.chat_log import log_llm_call

QUALITY_GATE_SYSTEM = """\
You are an Evidence Quality Gate for strategic risk analysis of {company}'s {strategy_theme}.

Your job: evaluate whether the current evidence base is SUFFICIENT for a multi-dimensional risk assessment, or whether targeted follow-up retrieval is needed.

A sufficient evidence base should cover:
1. The company's own strategic plans, targets, and financial results
2. Financial performance indicators (revenue, profit, segment data)
3. Competitive landscape (at least 1-2 named competitors with specific data)
4. Market/industry trends relevant to the strategy
5. Regional market conditions (at least 2 geographic markets)
6. Policy/regulatory environment (subsidies, tariffs, mandates)
7. Both SUPPORTING and CONTRADICTING signals (not one-sided)
8. Forward-looking signals (analyst forecasts, announced plans, technology roadmaps)

EVALUATION CRITERIA:
- Minimum 8 evidence items for a basic assessment
- At least 2 different source types (not all from one source)
- Stance balance: need BOTH supports_risk AND contradicts_risk items. If one stance outnumbers the other by more than 3:1, the evidence is ONE-SIDED and insufficient — a fair assessment needs the other perspective
- Dimension coverage: evidence should touch at least 4 of the 9 risk dimensions
- Regional coverage: evidence should reference at least 2 geographic regions. If all evidence is about one country, that's a gap.
- Forward-looking content: at least some evidence should be about future plans, forecasts, or trajectory — not all backward-looking financial results. If there are no forward-looking items, flag this as a gap.

If evidence is insufficient, generate 3-5 TARGETED follow-up search queries to fill the specific gaps you identified. These queries should:
- Target the specific missing dimensions or perspectives
- If the stance is imbalanced (too much supports_risk), search for the company's POSITIVE results: financial performance, market share gains, successful product launches, growth metrics
- If the stance is imbalanced (too much contradicts_risk), search for EXTERNAL challenges: competitor advantages, market headwinds, analyst concerns
- If regional coverage is thin, search for country-specific market data (e.g., "EV sales China 2024", "Europe EV market share 2024")
- If forward-looking content is missing, search for forecasts and roadmaps (e.g., "EV market forecast 2025 2030", "battery cost projection 2024")
- If competitor data is missing, search for specific named competitors' results
- Use year hints to stay before the cutoff date {cutoff_date}
- Be specific enough to return useful results

CRITICAL: Do NOT generate queries about post-cutoff events. Only seek pre-cutoff information.
"""

QUALITY_GATE_USER = """\
EVIDENCE SUMMARY ({evidence_count} items):
- Stance: {supports} supports_risk, {contradicts} contradicts_risk, {neutral} neutral
- Source types: {source_types}
- Entities mentioned: {entities}
- Claim types: {claim_types}

EVIDENCE ITEMS:
{evidence_brief}

Is this evidence base sufficient for a comprehensive risk assessment?

Return a JSON object with:
- decision: "sufficient" or "insufficient"
- reasoning: string (2-3 sentences explaining why)
- gaps: list of strings (what's missing — empty if sufficient)
- follow_up_queries: list of strings (search queries to fill gaps — empty if sufficient)

Respond with ONLY the JSON object.
"""


def quality_gate_node(state: PipelineState) -> dict:
    """LLM-driven evidence quality assessment.

    Evaluates the extracted evidence and decides:
    - Sufficient → set evidence_sufficient=True, proceed to analysts
    - Insufficient → set evidence_sufficient=False, provide follow_up_queries,
      loop back to retrieval
    """
    evidence = state.get("evidence", [])
    company = state["company"]
    theme = state["strategy_theme"]
    cutoff = state["cutoff_date"]
    iteration = state.get("iteration_count", 0)

    reporting.enter_node("quality_gate", {
        "evidence_items": len(evidence),
        "iteration": iteration,
    })

    # Dead-loop protection: max 3 retrieval loops
    if iteration >= 3:
        reporting.log_action(
            "Max iterations reached — proceeding with available evidence",
        )
        reporting.exit_node("quality_gate", next_node="fan-out analysts")
        return {
            "evidence_sufficient": True,
            "follow_up_queries": [],
            "current_stage": "quality_gate",
        }

    # Compute evidence statistics for the LLM
    stance_counts = {"supports_risk": 0, "contradicts_risk": 0, "neutral": 0}
    source_types: dict[str, int] = {}
    entities: set[str] = set()
    claim_types: set[str] = set()

    for e in evidence:
        stance = e.get("stance", "neutral")
        if stance in stance_counts:
            stance_counts[stance] += 1
        st = e.get("source_type", "unknown")
        source_types[st] = source_types.get(st, 0) + 1
        if e.get("entity"):
            entities.add(e["entity"])
        if e.get("claim_type"):
            claim_types.add(e["claim_type"])

    # Brief summary of evidence for LLM
    evidence_brief = []
    for e in evidence[:30]:  # cap at 30 to keep prompt manageable
        evidence_brief.append(
            f"[{e.get('evidence_id', '?')}] ({e.get('stance', '?')}) "
            f"{e.get('claim_type', '?')} — {e.get('claim_text', '')[:100]}",
        )

    system_msg = QUALITY_GATE_SYSTEM.format(
        company=company,
        strategy_theme=theme,
        cutoff_date=cutoff,
    )
    user_msg = QUALITY_GATE_USER.format(
        evidence_count=len(evidence),
        supports=stance_counts["supports_risk"],
        contradicts=stance_counts["contradicts_risk"],
        neutral=stance_counts["neutral"],
        source_types=", ".join(f"{k}: {v}" for k, v in sorted(source_types.items())),
        entities=", ".join(sorted(entities)[:10]),
        claim_types=", ".join(sorted(claim_types)),
        evidence_brief="\n".join(evidence_brief),
    )

    llm = get_llm_for_role("retrieval")  # fast, non-thinking
    reporting.log_action("LLM evaluating evidence sufficiency")

    try:
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        response = llm.invoke(messages)
        log_llm_call("quality_gate", messages, response, label="quality_gate")
        raw = strip_thinking(response.content)

        try:
            parsed = extract_json(raw)
        except json.JSONDecodeError:
            parsed = {}

        decision = parsed.get("decision", "sufficient")
        reasoning = parsed.get("reasoning", "")
        gaps = parsed.get("gaps", [])
        queries = parsed.get("follow_up_queries", [])

        is_sufficient = decision == "sufficient"

        reporting.log_action("Quality gate decision", {
            "decision": decision.upper(),
            "reasoning": reasoning[:120],
        })
        if gaps:
            for gap in gaps[:5]:
                reporting.log_item(f"Gap: {gap}", style="dim")
        if queries:
            for q in queries[:5]:
                reporting.log_item(f"Follow-up: {q}", style="dim")

        if is_sufficient:
            reporting.exit_node("quality_gate", next_node="fan-out analysts")
        else:
            reporting.exit_node("quality_gate", next_node="retrieval (follow-up)")

        return {
            "evidence_sufficient": is_sufficient,
            "follow_up_queries": queries[:5] if not is_sufficient else [],
            "current_stage": "quality_gate",
        }

    except Exception as e:
        reporting.log_action("Quality gate LLM failed — defaulting to proceed", {
            "error": str(e)[:150],
        })
        reporting.exit_node("quality_gate", next_node="fan-out analysts")
        return {
            "evidence_sufficient": True,
            "follow_up_queries": [],
            "current_stage": "quality_gate",
        }
