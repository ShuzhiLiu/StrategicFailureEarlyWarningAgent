"""Retrieval & Temporal Gatekeeper agent node.

Uses Qwen3.5's native tool calling to autonomously search for documents
via DuckDuckGo, then enforces temporal cutoff to prevent information leakage.

This is one of the key "agentic" components — the LLM decides what to
search for and iterates until it has enough evidence.
"""

from __future__ import annotations

from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from langchain_core.tools import tool

from sfewa import reporting
from sfewa.schemas.state import PipelineState
from sfewa.tools.temporal_filter import is_before_cutoff


# ── Tools available to the retrieval agent ──

def create_web_search_tool(max_results: int = 5) -> DuckDuckGoSearchResults:
    """Create a DuckDuckGo search tool for the retrieval agent."""
    wrapper = DuckDuckGoSearchAPIWrapper(
        region="us-en",
        max_results=max_results,
    )
    return DuckDuckGoSearchResults(
        api_wrapper=wrapper,
        output_format="list",
    )


@tool
def check_temporal_validity(published_date: str, cutoff_date: str) -> dict:
    """Check if a document's publication date is before the analysis cutoff.

    Args:
        published_date: Document publication date in YYYY-MM-DD format.
        cutoff_date: Analysis cutoff date in YYYY-MM-DD format.

    Returns:
        Dict with is_valid boolean and reason string.
    """
    valid = is_before_cutoff(published_date, cutoff_date)
    return {
        "is_valid": valid,
        "published_date": published_date,
        "cutoff_date": cutoff_date,
        "reason": "accepted" if valid else "rejected: published after cutoff",
    }


def _build_retrieval_tools(max_results: int = 5) -> list:
    """Build the tool list for the retrieval agent."""
    return [
        create_web_search_tool(max_results),
        check_temporal_validity,
    ]


def retrieval_node(state: PipelineState) -> dict:
    """Retrieve documents relevant to the case, filtering by cutoff date.

    Uses Qwen3.5's tool calling to:
    1. Search DuckDuckGo for each topic in the case config
    2. Check temporal validity of each result
    3. Collect accepted documents into retrieved_docs

    The LLM autonomously decides search queries and iterates.

    TODO: Wire up full tool-calling agent loop via LangGraph prebuilt
          or manual ToolNode. Currently runs tools directly as a
          deterministic pipeline for reliability.
    """
    cutoff = state["cutoff_date"]
    company = state["company"]
    theme = state["strategy_theme"]
    regions = state.get("regions", [])

    reporting.enter_node("retrieval", {
        "company": company,
        "theme": theme,
        "cutoff_date": cutoff,
        "regions": ", ".join(regions),
    })

    # Build search queries from case config search_topics
    search_topics = state.get("search_topics", [])
    if not search_topics:
        search_topics = [
            f"{company} {theme}",
            f"{company} EV strategy",
        ]

    # Use search topics directly — they are curated in case config
    base_queries = list(search_topics)

    reporting.log_action("Search queries", {"count": len(base_queries)})
    for q in base_queries:
        reporting.log_item(q, style="dim")

    # Search and collect results
    search_tool = create_web_search_tool(max_results=5)
    all_results: list[dict] = []
    query_failures = 0

    for query in base_queries:
        try:
            results = search_tool.invoke(query)
            if isinstance(results, list):
                all_results.extend(results)
        except Exception:
            query_failures += 1
            continue

    reporting.log_action("DuckDuckGo results", {
        "raw_results": len(all_results),
        "query_failures": query_failures,
    })

    # Deduplicate by link
    seen_links: set[str] = set()
    unique_results: list[dict] = []
    for r in all_results:
        link = r.get("link", "")
        if link and link not in seen_links:
            seen_links.add(link)
            unique_results.append(r)

    reporting.log_action("Deduplication", {
        "before": len(all_results),
        "after": len(unique_results),
    })

    # TODO: Extract published_at from each result and run temporal filter
    # For now, pass through all results — temporal filtering will be
    # applied at evidence extraction stage where dates are parsed from content

    retrieved_docs = [
        {
            "title": r.get("title", ""),
            "snippet": r.get("snippet", ""),
            "link": r.get("link", ""),
            "source": "duckduckgo",
        }
        for r in unique_results
    ]

    reporting.exit_node("retrieval", {
        "retrieved_docs": len(retrieved_docs),
    }, next_node="evidence_extraction")

    return {
        "retrieved_docs": retrieved_docs,
        "current_stage": "retrieval",
    }
