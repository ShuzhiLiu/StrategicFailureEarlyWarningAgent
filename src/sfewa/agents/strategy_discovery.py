"""Strategy discovery agent (L2.4).

When the case YAML omits `strategy_theme`, this agent infers 1-3 candidate
themes by reading the company's recent regulatory filings + light web
search. The top-1 candidate becomes the working `strategy_theme` for the
rest of the pipeline; the full candidate list is recorded in the run
audit trail (`discovered_strategies.json` artifact + `run_metadata.json`).

This is a *preprocessing* step, not a pipeline node. The discovery runs
once at case-load time inside `build_initial_state_from_case()`, and the
analytical pipeline downstream sees a populated `strategy_theme` exactly
as if a human had authored one.

Architecture:
    case YAML (no strategy_theme)
        → build_initial_state_from_case()
             → discover_strategies(...)            ← this module
                  → ToolLoopAgent (search + filings)
                  → returns {candidates, primary, rationale}
             → state["strategy_theme"] = primary
             → state["discovered_strategies"] = full payload
        → run_pipeline_v2(state)            ← unchanged

Audit-grade properties:
    - The discovery LLM has the same temporal-integrity instruction as
      retrieval ("do NOT use knowledge after cutoff_date").
    - The candidates list is preserved in the run artifacts so a reviewer
      can see WHY the primary theme was chosen.
    - The discovery agent's tool-call log is captured by the same CallLog
      that records the rest of the pipeline.
"""

from __future__ import annotations

import json
import re
from typing import Any

from liteagent import ToolLoopAgent

from sfewa import reporting
from sfewa.agents.agentic_retrieval import _make_filing_tool, _make_search_tool
from sfewa.llm import get_llm_for_role
from sfewa.prompts.strategy_discovery import (
    STRATEGY_DISCOVERY_SYSTEM,
    STRATEGY_DISCOVERY_USER,
)
from sfewa.tools.chat_log import get_call_log


# Discovery is a planning step, not exhaustive research. Smaller budget than
# the main retrieval agent (15 search queries → 8 here, plus the one filing
# tool call).
MAX_DISCOVERY_TOOL_CALLS = 8


def discover_strategies(
    *,
    company: str,
    cutoff_date: str,
    regions: list[str] | None = None,
    audit_meta: dict | None = None,
) -> dict[str, Any]:
    """Discover candidate strategy themes for a company.

    Args:
        company: Company name.
        cutoff_date: ISO YYYY-MM-DD; agent must not use post-cutoff info.
        regions: Optional region hints (used for filing-jurisdiction routing).
        audit_meta: Case-level audit metadata (jurisdiction, ticker).

    Returns:
        {
            "candidates": [{name, description, type, evidence_text, confidence}],
            "primary": str (matches one candidate's name),
            "rationale": str,
            "tool_calls": int,
            "iterations": int,
            "raw_response": str (the LLM's final content; useful for debugging),
        }

    On parse failure: returns a fallback payload with one candidate
    `primary corporate strategy` so the caller can still proceed. The
    pipeline behaves as if the user authored that theme.
    """
    audit_meta = audit_meta or {}
    explicit_jurisdiction = audit_meta.get("jurisdiction")
    explicit_ticker = audit_meta.get("ticker")
    cutoff_year = int(cutoff_date[:4])

    reporting.enter_node("strategy_discovery", {
        "company": company,
        "cutoff_date": cutoff_date,
        "jurisdiction": explicit_jurisdiction,
    })

    # Reuse the same tools the main retrieval agent uses. State is shared
    # via the `all_docs` list so the discovery agent's reads contribute to
    # the audit trail (call log) but don't pollute the main pipeline's
    # retrieved_docs (we deliberately discard `all_docs` after discovery
    # — the main retrieval node will re-search with the discovered theme
    # in scope).
    discovery_docs: list[dict] = []
    seen_links: set[str] = set()

    search_tool = _make_search_tool(seen_links, discovery_docs)
    filing_tool = _make_filing_tool(
        company,
        cutoff_date,
        regions or [],
        discovery_docs,
        explicit_jurisdiction=explicit_jurisdiction,
        ticker=explicit_ticker,
    )

    system_prompt = STRATEGY_DISCOVERY_SYSTEM.format(
        company=company,
        cutoff_date=cutoff_date,
        cutoff_year=cutoff_year,
    )
    user_msg = STRATEGY_DISCOVERY_USER.format(
        company=company,
        cutoff_date=cutoff_date,
    )

    # Discovery can use the retrieval-role LLM (non-thinking, fast).
    # Could also use a planner role if the org has a dedicated config —
    # the role-router falls through to default when missing.
    llm = get_llm_for_role("retrieval")

    agent = ToolLoopAgent(
        llm=llm,
        tools=[search_tool, filing_tool],
        system_prompt=system_prompt,
        max_iterations=MAX_DISCOVERY_TOOL_CALLS + 4,  # headroom for non-tool turns
        call_log=get_call_log(),
        node_name="strategy_discovery",
    )

    reporting.log_action("Starting discovery agent")
    result = agent.run(user_msg)

    parsed = _parse_discovery_output(result.content)
    parsed["tool_calls"] = result.tool_call_count
    parsed["iterations"] = result.iterations
    parsed["raw_response"] = (result.content or "")[:2000]

    reporting.exit_node("strategy_discovery", {
        "candidates": len(parsed.get("candidates", [])),
        "primary": parsed.get("primary"),
        "tool_calls": result.tool_call_count,
    })

    return parsed


# ── Output parsing ──


def _parse_discovery_output(content: str) -> dict[str, Any]:
    """Parse the discovery agent's final JSON response.

    Handles common LLM output quirks (markdown fences, leading prose,
    trailing comments). On parse failure, returns a fallback payload
    so the caller can still run the pipeline with a generic theme.
    """
    if not content:
        return _fallback_payload(reason="empty content from agent")

    # Strip <think>...</think> tags (some thinking-mode LLMs leak them)
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```\s*$", "", text.strip(), flags=re.MULTILINE)

    # Find the first {...} block. Crude but adequate — agents sometimes
    # prepend "Here is the JSON:" before the actual object.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return _fallback_payload(reason="no JSON object found in response")

    blob = match.group(0)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        return _fallback_payload(reason=f"JSON parse error: {e}")

    candidates = data.get("candidates")
    primary = data.get("primary")
    rationale = data.get("rationale", "")

    if not isinstance(candidates, list) or not candidates:
        return _fallback_payload(reason="no candidates in response")
    if not isinstance(primary, str) or not primary.strip():
        # Use the first candidate when no primary is named.
        primary = candidates[0].get("name", "primary corporate strategy")

    # Validate each candidate has the required minimum fields. Drop bad ones.
    cleaned: list[dict] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        cleaned.append({
            "name": name,
            "description": (c.get("description") or "").strip(),
            "type": c.get("type") or "declared_strategy",
            "evidence_text": (c.get("evidence_text") or "").strip()[:500],
            "confidence": float(c.get("confidence") or 0.5),
        })
    if not cleaned:
        return _fallback_payload(reason="all candidates failed validation")

    # Ensure `primary` matches one cleaned candidate; otherwise fall back to top-1.
    primary_match = next((c for c in cleaned if c["name"] == primary), None)
    if primary_match is None:
        primary = cleaned[0]["name"]

    return {
        "candidates": cleaned,
        "primary": primary,
        "rationale": (rationale or "").strip()[:500],
    }


def _fallback_payload(*, reason: str) -> dict[str, Any]:
    """Return a safe default that lets the pipeline proceed.

    The fallback theme is intentionally generic — the dimension generator
    in init_case will still produce reasonable per-perspective dimensions
    for any company even with a vague theme. The reason is recorded so a
    reviewer can see why discovery degraded.
    """
    return {
        "candidates": [{
            "name": "primary corporate strategy",
            "description": (
                "Generic fallback theme used when strategy discovery did "
                "not produce parseable output. SFEWA dimensions will be "
                "generated from the company's general activity."
            ),
            "type": "declared_strategy",
            "evidence_text": "",
            "confidence": 0.3,
        }],
        "primary": "primary corporate strategy",
        "rationale": f"Fallback: {reason}",
    }


__all__ = ["discover_strategies", "MAX_DISCOVERY_TOOL_CALLS"]
