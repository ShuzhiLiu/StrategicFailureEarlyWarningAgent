"""Agentic retrieval node using tool-loop agent.

Replaces the 3-pass retrieval + quality gate loop with a single autonomous
agent that searches, assesses coverage, identifies gaps, and loops until
satisfied. The agent decides WHAT to search and WHEN to stop.

After the agent finishes searching, the pipeline runs evidence_extraction
as a separate node (keeps extraction debuggable and deterministic).

Pipeline flow comparison:
  v1: init_case -> [retrieval -> extraction -> quality_gate]* -> fan-out ...
  v2: init_case -> agentic_retrieval -> extraction -> fan-out ...
"""

from __future__ import annotations

import time

from liteagent import Tool, ToolLoopAgent

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS  # type: ignore[no-redef]

from sfewa import reporting
from sfewa.llm import get_llm_for_role
from sfewa.prompts.agentic_retrieval import (
    AGENTIC_RETRIEVAL_SYSTEM,
    AGENTIC_RETRIEVAL_USER,
)
from sfewa.agents.retrieval import (
    _search_web,
    _search_news,
    _deduplicate,
    _to_doc,
)
from sfewa.schemas.state import PipelineState
from sfewa.tools.chat_log import get_call_log
from sfewa.tools.corpus_loader import load_edinet_corpus


# Maximum search queries the agent is allowed to make
MAX_SEARCH_QUERIES = 15

# Stop accumulating docs beyond this (extraction can't handle 400+ docs in one batch)
MAX_DOCS = 150


def _make_search_tool(
    seen_links: set[str],
    all_docs: list[dict],
) -> Tool:
    """Create a search tool with shared accumulation state.

    Each call runs DuckDuckGo text + news search, deduplicates against
    previously seen links, and appends new docs to the shared list.
    The LLM sees a concise summary; the node has access to full data.
    """
    ddgs = DDGS()
    call_count = [0]

    def search(query: str) -> str:
        """Search the web (text + news) for a query."""
        call_count[0] += 1

        if call_count[0] > MAX_SEARCH_QUERIES:
            return (
                f"Search budget exhausted ({MAX_SEARCH_QUERIES} queries). "
                f"Total documents: {len(all_docs)}. Please finish."
            )

        if len(all_docs) >= MAX_DOCS:
            return (
                f"Document cap reached ({len(all_docs)} docs). "
                f"This is sufficient for extraction. Please finish."
            )

        # Rate limiting between queries
        if call_count[0] > 1:
            time.sleep(3)

        results: list[dict] = []
        try:
            # Lower max_results than v1 pipeline — forces agent to make
            # more diverse queries instead of drowning in one topic
            web = _search_web(query, max_results=8, ddgs_instance=ddgs)
            results.extend(web)
        except Exception:
            pass

        time.sleep(2)

        try:
            news = _search_news(query, max_results=6, ddgs_instance=ddgs)
            results.extend(news)
        except Exception:
            pass

        unique = _deduplicate(results, seen_links)
        docs = [_to_doc(r, source="agentic") for r in unique]
        all_docs.extend(docs)

        reporting.log_action(f"Search [{call_count[0]}]: {query[:60]}", {
            "new": len(unique),
            "total": len(all_docs),
        })

        if not unique:
            return (
                f"No new results for: {query}\n"
                f"Total accumulated: {len(all_docs)} documents."
            )

        lines = [f"Found {len(unique)} new results (total: {len(all_docs)}):"]
        for d in docs[:8]:
            title = d["title"][:70]
            snippet = d["snippet"][:120]
            lines.append(f"- {title}")
            if snippet:
                lines.append(f"  {snippet}")
        if len(docs) > 8:
            lines.append(f"  ... and {len(docs) - 8} more")

        return "\n".join(lines)

    return Tool(
        name="search",
        description=(
            "Search the web (text + news) for a query. "
            "Returns titles and snippets. Use specific, targeted queries."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
            },
            "required": ["query"],
        },
        fn=search,
    )


def _make_edinet_tool(
    company: str,
    all_docs: list[dict],
) -> Tool:
    """Create an EDINET loading tool."""

    loaded = [False]

    def load_edinet() -> str:
        """Load EDINET regulatory filings for the company."""
        if loaded[0]:
            return "EDINET filings already loaded."

        if "honda" not in company.lower():
            return "No EDINET filings available for this company."

        docs = load_edinet_corpus()
        if not docs:
            return "No EDINET filings found."

        loaded[0] = True
        all_docs.extend(docs)

        reporting.log_action("EDINET corpus loaded", {"docs": len(docs)})

        lines = [f"Loaded {len(docs)} EDINET filing chunks:"]
        for d in docs[:5]:
            lines.append(f"- {d.get('title', 'N/A')[:80]}")
        if len(docs) > 5:
            lines.append(f"  ... and {len(docs) - 5} more chunks")
        lines.append(
            "\nThese are official regulatory filings — primary sources. "
            "Now search the web for external perspectives."
        )
        return "\n".join(lines)

    return Tool(
        name="load_edinet",
        description=(
            "Load EDINET regulatory filings for the company (if available). "
            "Call once at the start for primary source data."
        ),
        parameters={"type": "object", "properties": {}},
        fn=load_edinet,
    )


def _format_dimensions(analysis_dims: dict) -> str:
    """Format analysis dimensions for the agent prompt."""
    lines = []
    for group_key, group_val in analysis_dims.items():
        if not isinstance(group_val, dict):
            continue
        dims = group_val.get("dimensions", [])
        if not dims:
            continue
        dim_names = [
            d.get("name", "?") if isinstance(d, dict) else str(d)
            for d in dims
        ]
        lines.append(f"  {group_key}: {', '.join(dim_names)}")
    return "\n".join(lines) if lines else "  (dimensions will be generated)"


def agentic_retrieval_node(state: PipelineState) -> dict:
    """Agentic retrieval: tool-loop agent for evidence gathering.

    The agent autonomously:
    1. Loads EDINET filings if available (primary sources)
    2. Generates and runs search queries
    3. Assesses coverage from results (titles, snippets)
    4. Identifies gaps and searches more
    5. Stops when coverage targets are met or budget exhausted

    Returns retrieved_docs for downstream extraction.
    """
    company = state["company"]
    theme = state["strategy_theme"]
    cutoff = state["cutoff_date"]
    regions = state.get("regions", [])
    peers = state.get("peers", [])
    analysis_dims = state.get("analysis_dimensions", {})

    reporting.enter_node("agentic_retrieval", {
        "company": company,
        "theme": theme,
        "cutoff_date": cutoff,
    })

    # Shared state for tools to accumulate results
    all_docs: list[dict] = []
    seen_links: set[str] = set()

    # Build tools
    search_tool = _make_search_tool(seen_links, all_docs)
    edinet_tool = _make_edinet_tool(company, all_docs)

    # Format case context for the prompt
    peer_names = ", ".join(
        p.get("company", str(p)) if isinstance(p, dict) else str(p)
        for p in peers[:7]
    ) or "(none specified — will be generated)"

    region_str = ", ".join(regions) or "(none specified — will be generated)"
    dims_str = _format_dimensions(analysis_dims)

    cutoff_year = int(cutoff[:4])
    prior_year = cutoff_year - 1

    has_edinet = "honda" in company.lower()
    edinet_note = (
        "EDINET filings are available for this company. "
        "Call load_edinet() FIRST to get primary source data."
        if has_edinet
        else "No EDINET filings available — rely on web search."
    )

    system_prompt = AGENTIC_RETRIEVAL_SYSTEM.format(
        company=company,
        strategy_theme=theme,
        cutoff_date=cutoff,
        cutoff_year=cutoff_year,
        prior_year=prior_year,
        regions=region_str,
        peers=peer_names,
        dimensions=dims_str,
        edinet_note=edinet_note,
        max_queries=MAX_SEARCH_QUERIES,
    )
    user_msg = AGENTIC_RETRIEVAL_USER.format(
        company=company,
        strategy_theme=theme,
        cutoff_date=cutoff,
    )

    # Run the tool-loop agent
    llm = get_llm_for_role("retrieval")
    agent = ToolLoopAgent(
        llm=llm,
        tools=[search_tool, edinet_tool],
        system_prompt=system_prompt,
        max_iterations=MAX_SEARCH_QUERIES + 5,  # some headroom for non-search turns
        call_log=get_call_log(),
        node_name="agentic_retrieval",
    )

    reporting.log_action("Starting tool-loop agent")
    result = agent.run(user_msg)

    # Count doc sources
    edinet_count = sum(1 for d in all_docs if d.get("source") == "edinet")
    web_count = len(all_docs) - edinet_count

    reporting.log_action("Agent finished", {
        "tool_calls": result.tool_call_count,
        "iterations": result.iterations,
        "hit_limit": result.hit_limit,
    })

    if result.content:
        # Log the agent's coverage summary (first 200 chars)
        reporting.log_action("Agent summary", {
            "text": result.content[:200],
        })

    reporting.exit_node("agentic_retrieval", {
        "total_docs": len(all_docs),
        "edinet": edinet_count,
        "web": web_count,
        "search_queries": result.tool_call_count,
    }, next_node="evidence_extraction")

    return {
        "retrieved_docs": all_docs,
        "current_stage": "agentic_retrieval",
    }
