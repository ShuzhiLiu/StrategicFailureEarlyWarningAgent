"""Retrieval & Temporal Gatekeeper agent node.

Agentic multi-source retrieval with three autonomous passes:

Pass 1 — Seed retrieval:
  EDINET filings (Honda's official regulatory disclosures, Tier 1 primary)
  + DuckDuckGo web search using curated topics from case config

Pass 2 — LLM-driven gap analysis:
  LLM analyzes retrieved docs, identifies which risk dimensions lack evidence,
  generates targeted follow-up queries, runs additional searches

Pass 3 — Counternarrative search:
  LLM reads the company's key claims from EDINET filings, then generates
  queries that specifically seek CHALLENGING external evidence. This prevents
  confirmation bias — the system stress-tests its own evidence base.

These three passes demonstrate core agentic capabilities:
- Autonomous decision-making about what to search for
- Self-awareness of evidence bias (mostly company-positive from filings)
- Active seeking of counterevidence to build balanced analysis
"""

from __future__ import annotations

import json
import re

from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

from sfewa import reporting
from sfewa.llm import get_llm_for_role
from sfewa.prompts.retrieval import (
    COUNTERNARRATIVE_SYSTEM,
    COUNTERNARRATIVE_USER,
    GAP_ANALYSIS_SYSTEM,
    GAP_ANALYSIS_USER,
    SEED_QUERY_SYSTEM,
    SEED_QUERY_USER,
)
from sfewa.schemas.state import PipelineState
from sfewa.tools.corpus_loader import load_edinet_corpus


def _create_search_tool(max_results: int = 5) -> DuckDuckGoSearchResults:
    """Create a DuckDuckGo search tool."""
    wrapper = DuckDuckGoSearchAPIWrapper(
        region="us-en",
        max_results=max_results,
    )
    return DuckDuckGoSearchResults(
        api_wrapper=wrapper,
        output_format="list",
    )


def _run_web_searches(
    queries: list[str],
    search_tool: DuckDuckGoSearchResults,
) -> tuple[list[dict], int]:
    """Run a batch of search queries. Returns (results, failure_count)."""
    all_results: list[dict] = []
    failures = 0
    for query in queries:
        try:
            results = search_tool.invoke(query)
            if isinstance(results, list):
                all_results.extend(results)
        except Exception:
            failures += 1
    return all_results, failures


def _deduplicate(results: list[dict], seen_links: set[str]) -> list[dict]:
    """Deduplicate search results by link. Updates seen_links in place."""
    unique: list[dict] = []
    for r in results:
        link = r.get("link", "")
        if link and link not in seen_links:
            seen_links.add(link)
            unique.append(r)
    return unique


def _to_doc(result: dict, source: str = "duckduckgo") -> dict:
    """Convert a raw search result to a retrieved_doc dict."""
    return {
        "title": result.get("title", ""),
        "snippet": result.get("snippet", ""),
        "link": result.get("link", ""),
        "source": source,
    }


def _llm_generate_queries(
    system_msg: str,
    user_msg: str,
    max_queries: int = 10,
) -> list[str]:
    """Call LLM and parse a JSON array of search query strings."""
    llm = get_llm_for_role("retrieval")

    try:
        response = llm.invoke([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ])
        raw = response.content
        raw = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()

        match = re.search(r"\[[\s\S]*?\]", raw)
        if match:
            queries = json.loads(match.group())
            if isinstance(queries, list):
                return [str(q) for q in queries[:max_queries]]
    except Exception as e:
        reporting.log_action("LLM query generation failed", {
            "error": str(e)[:150],
        })

    return []


def _summarize_docs(docs: list[dict], max_docs: int = 50) -> str:
    """Build concise summaries of docs for LLM input."""
    summaries = []
    for i, doc in enumerate(docs[:max_docs], 1):
        title = doc.get("title", "N/A")[:80]
        snippet = doc.get("snippet", "")[:120]
        source = doc.get("source", "?")
        summaries.append(f"[{i}] ({source}) {title}: {snippet}")
    return "\n".join(summaries)


def _extract_company_claims(edinet_docs: list[dict], max_claims: int = 10) -> str:
    """Extract key claims from EDINET docs for counternarrative analysis.

    Scans EDINET document snippets for quantitative claims and strategy
    statements that should be stress-tested with external evidence.
    """
    # Collect first portion of each EDINET chunk to find key claims
    claim_texts = []
    for doc in edinet_docs[:15]:
        snippet = doc.get("snippet", "")[:500]
        if snippet:
            claim_texts.append(snippet)

    # Join and truncate to keep prompt manageable
    combined = "\n---\n".join(claim_texts)
    if len(combined) > 3000:
        combined = combined[:3000] + "..."

    return combined


def retrieval_node(state: PipelineState) -> dict:
    """Agentic multi-source retrieval with three autonomous passes.

    Pass 1: Seed — EDINET filings + DuckDuckGo from config topics
    Pass 2: Gap analysis — LLM identifies missing dimensions, generates queries
    Pass 3: Counternarrative — LLM reads company claims, seeks challenging evidence

    When called via quality gate loop-back, uses follow_up_queries from the
    quality gate instead of generating new seed queries.
    """
    cutoff = state["cutoff_date"]
    company = state["company"]
    theme = state["strategy_theme"]
    regions = state.get("regions", [])
    follow_up_queries = state.get("follow_up_queries", [])
    is_follow_up = bool(follow_up_queries)

    reporting.enter_node("retrieval", {
        "company": company,
        "theme": theme,
        "cutoff_date": cutoff,
        "regions": ", ".join(regions),
        "mode": "follow-up (quality gate)" if is_follow_up else "initial",
    })

    search_tool = _create_search_tool(max_results=8)
    seen_links: set[str] = set()

    # If this is a follow-up from the quality gate, skip EDINET and seed generation
    # — just run the targeted follow-up queries
    if is_follow_up:
        reporting.log_action("Follow-up retrieval from quality gate", {
            "queries": len(follow_up_queries),
        })
        for q in follow_up_queries:
            reporting.log_item(q, style="dim")

        raw_results, failures = _run_web_searches(follow_up_queries, search_tool)
        unique_results = _deduplicate(raw_results, seen_links)
        follow_up_docs = [_to_doc(r, source="duckduckgo_follow_up") for r in unique_results]

        reporting.exit_node("retrieval", {
            "total_docs": len(follow_up_docs),
            "mode": "follow-up",
            "failures": failures,
        }, next_node="evidence_extraction")

        return {
            "retrieved_docs": follow_up_docs,
            "follow_up_queries": [],  # clear after use
            "current_stage": "retrieval",
        }

    # ── Pass 1: Seed retrieval ──

    # Load EDINET corpus if available for this company (currently Honda only)
    edinet_docs: list[dict] = []
    if "honda" in company.lower():
        reporting.log_action("Loading EDINET corpus (Honda official filings)")
        edinet_docs = load_edinet_corpus()
        reporting.log_action("EDINET corpus loaded", {"docs": len(edinet_docs)})
    else:
        reporting.log_action("No EDINET corpus for this company — using web search only")

    # Generate seed queries autonomously from case context
    peers = state.get("peers", [])
    peer_names = ", ".join(
        p.get("company", p) if isinstance(p, dict) else str(p)
        for p in peers[:5]
    )
    seed_queries = _llm_generate_queries(
        system_msg=SEED_QUERY_SYSTEM.format(
            company=company,
            strategy_theme=theme,
            cutoff_date=cutoff,
            regions=", ".join(regions),
        ),
        user_msg=SEED_QUERY_USER.format(
            company=company,
            strategy_theme=theme,
            cutoff_date=cutoff,
            regions=", ".join(regions),
            peers=peer_names,
        ),
        max_queries=15,
    )

    # Fallback: use config topics if LLM fails, or add them as supplements
    config_topics = state.get("search_topics", [])
    search_topics = seed_queries if seed_queries else config_topics
    if not search_topics:
        search_topics = [f"{company} {theme}", f"{company} EV strategy"]

    reporting.log_action("Pass 1: Seed search (LLM-generated)", {"queries": len(search_topics)})
    for q in search_topics:
        reporting.log_item(q, style="dim")

    raw_results, failures = _run_web_searches(search_topics, search_tool)
    unique_results = _deduplicate(raw_results, seen_links)

    reporting.log_action("Pass 1 results", {
        "raw": len(raw_results),
        "unique": len(unique_results),
        "failures": failures,
    })

    seed_web_docs = [_to_doc(r) for r in unique_results]
    pass1_docs = edinet_docs + seed_web_docs

    # ── Pass 2: LLM-driven gap analysis ──

    reporting.log_action(
        "Pass 2: Gap analysis — identifying missing evidence dimensions",
    )

    gap_queries = _llm_generate_queries(
        system_msg=GAP_ANALYSIS_SYSTEM.format(
            company=company, strategy_theme=theme, cutoff_date=cutoff,
        ),
        user_msg=GAP_ANALYSIS_USER.format(
            company=company,
            strategy_theme=theme,
            cutoff_date=cutoff,
            doc_count=len(pass1_docs),
            doc_summaries=_summarize_docs(pass1_docs),
        ),
    )

    gap_web_docs: list[dict] = []
    if gap_queries:
        reporting.log_action("Gap analysis queries", {"count": len(gap_queries)})
        for q in gap_queries:
            reporting.log_item(q, style="dim")

        raw_gap, gap_failures = _run_web_searches(gap_queries, search_tool)
        unique_gap = _deduplicate(raw_gap, seen_links)

        reporting.log_action("Pass 2 results", {
            "raw": len(raw_gap),
            "new_unique": len(unique_gap),
            "failures": gap_failures,
        })
        gap_web_docs = [_to_doc(r, source="duckduckgo_gap_fill") for r in unique_gap]

    # ── Pass 3: Counternarrative search ──
    # The agent reads the company's claims and seeks external evidence
    # that challenges them. This prevents confirmation bias.

    reporting.log_action(
        "Pass 3: Counternarrative — stress-testing company claims",
    )

    # Use EDINET docs for claims if available, otherwise use seed web results
    claims_source = edinet_docs if edinet_docs else seed_web_docs
    company_claims = _extract_company_claims(claims_source)
    counter_queries = _llm_generate_queries(
        system_msg=COUNTERNARRATIVE_SYSTEM.format(cutoff_date=cutoff),
        user_msg=COUNTERNARRATIVE_USER.format(
            company=company,
            strategy_theme=theme,
            cutoff_date=cutoff,
            company_claims=company_claims,
        ),
    )

    counter_web_docs: list[dict] = []
    if counter_queries:
        reporting.log_action("Counternarrative queries", {
            "count": len(counter_queries),
        })
        for q in counter_queries:
            reporting.log_item(q, style="dim")

        raw_counter, counter_failures = _run_web_searches(
            counter_queries, search_tool,
        )
        unique_counter = _deduplicate(raw_counter, seen_links)

        reporting.log_action("Pass 3 results", {
            "raw": len(raw_counter),
            "new_unique": len(unique_counter),
            "failures": counter_failures,
        })
        counter_web_docs = [
            _to_doc(r, source="duckduckgo_counter") for r in unique_counter
        ]

    # ── Merge all sources ──
    # Order: EDINET → seed web → gap-fill → counternarrative
    retrieved_docs = edinet_docs + seed_web_docs + gap_web_docs + counter_web_docs

    total_web = len(seed_web_docs) + len(gap_web_docs) + len(counter_web_docs)

    reporting.exit_node("retrieval", {
        "total_docs": len(retrieved_docs),
        "edinet": len(edinet_docs),
        "web_seed": len(seed_web_docs),
        "web_gap_fill": len(gap_web_docs),
        "web_counter": len(counter_web_docs),
        "total_web": total_web,
    }, next_node="evidence_extraction")

    return {
        "retrieved_docs": retrieved_docs,
        "current_stage": "retrieval",
    }
