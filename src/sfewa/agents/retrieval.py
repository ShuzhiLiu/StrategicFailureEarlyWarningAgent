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

from liteagent import extract_json, strip_thinking

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS  # type: ignore[no-redef]

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
from sfewa.tools.chat_log import log_llm_call, log_tool_call
from sfewa.tools.filing_discovery import discover_and_load_filings


def _is_english(text: str, threshold: float = 0.6) -> bool:
    """Check if text is predominantly English (Latin script + ASCII)."""
    if not text:
        return False
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return ascii_count / len(text) >= threshold


def _search_web(query: str, max_results: int = 12, ddgs_instance=None) -> list[dict]:
    """Run a single DuckDuckGo text search. Returns list of {title, link, snippet}.

    Filters out non-English results to prevent irrelevant Japanese/Chinese
    pages from polluting the evidence pipeline.
    """
    import time as _time
    for attempt in range(2):
        try:
            ddgs = ddgs_instance or DDGS()
            raw = list(ddgs.text(query, region="us-en", max_results=max_results))
            results = []
            for r in raw:
                snippet = r.get("body", "")
                title = r.get("title", "")
                if not _is_english(f"{title} {snippet}"):
                    continue
                results.append({
                    "title": title,
                    "link": r.get("href", ""),
                    "snippet": snippet,
                })
            return results
        except Exception as e:
            if "Ratelimit" in str(e) and attempt == 0:
                _time.sleep(10)
                continue
            return []
    return []


def _search_news(query: str, max_results: int = 10, ddgs_instance=None) -> list[dict]:
    """Run a DuckDuckGo NEWS search. Returns list of {title, link, snippet}.

    News search returns timestamped articles from news sources — much better
    for finding pre-cutoff business/financial content than general web search.
    """
    import time as _time
    for attempt in range(2):
        try:
            ddgs = ddgs_instance or DDGS()
            raw = list(ddgs.news(query, region="us-en", max_results=max_results))
            results = []
            for r in raw:
                body = r.get("body", "")
                title = r.get("title", "")
                if not _is_english(f"{title} {body}"):
                    continue
                # News results have 'date' and 'url' instead of 'href'
                snippet = body
                date_str = r.get("date", "")
                if date_str:
                    snippet = f"[{date_str[:10]}] {body}"
                results.append({
                    "title": title,
                    "link": r.get("url", ""),
                    "snippet": snippet,
                })
            return results
        except Exception as e:
            if "Ratelimit" in str(e) and attempt == 0:
                _time.sleep(10)
                continue
            return []
    return []


def _augment_queries_with_years(
    queries: list[str],
    cutoff_date: str,
) -> list[str]:
    """Add year-augmented variants for queries missing explicit year hints.

    DuckDuckGo biases toward recent content. Adding "2024" or "FY2024" to
    queries biases results toward pre-cutoff content, which is critical when
    the cutoff date is many months in the past.
    """
    import re as _re

    # Extract cutoff year and prior year
    cutoff_year = int(cutoff_date[:4])
    prior_year = cutoff_year - 1
    year_pattern = _re.compile(r"\b20[12]\d\b")

    augmented = list(queries)  # keep originals
    for query in queries:
        if not year_pattern.search(query):
            # Query has no year hint — add one variant with prior year
            augmented.append(f"{query} {prior_year}")
    return augmented


# Reputable English-language financial/business sources with good archives
_ARCHIVAL_SOURCES = [
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "cnbc.com",
    "asia.nikkei.com",
    "wsj.com",
]


def _generate_archival_queries(
    company: str,
    theme: str,
    cutoff_date: str,
    peers: list[str],
) -> list[str]:
    """Generate site-specific queries for archival English-language sources.

    DuckDuckGo often returns irrelevant results for non-US companies
    (Japanese dealer pages, Chinese Q&A sites). Site-specific searches
    target reputable financial journalism with good historical archives.
    """
    cutoff_year = int(cutoff_date[:4])
    prior_year = cutoff_year - 1
    # Short company name for queries (e.g., "Toyota Motor Corporation" → "Toyota")
    short_name = company.split()[0]

    queries = []
    for site in _ARCHIVAL_SOURCES[:3]:  # top 3 sources to limit API calls
        queries.append(f"site:{site} {short_name} EV strategy {prior_year}")
        queries.append(f"site:{site} {short_name} electric vehicle {cutoff_year}")
    # Competitor comparison queries on one archival source
    if peers:
        first_peer = peers[0]
        peer_name = first_peer.get("name", "") if isinstance(first_peer, dict) else str(first_peer)
        top_peer = peer_name.split()[0] if peer_name else ""
        if top_peer:
            queries.append(f"site:reuters.com {short_name} vs {top_peer} EV {prior_year}")
    return queries


def _run_web_searches(
    queries: list[str],
    max_results: int = 10,
    search_label: str = "",
    use_news: bool = True,
) -> tuple[list[dict], int]:
    """Run a batch of search queries using text + news search.

    Uses both DDGS.text() and DDGS.news() to maximize coverage.
    News search returns timestamped articles from reputable sources.
    Rate limit mitigation: 2s delays between calls, early stop on
    consecutive empty results.
    """
    import time as _time

    all_results: list[dict] = []
    failures = 0
    consecutive_empty = 0
    max_consecutive_empty = 6  # Stop if 6 straight empties (likely rate limited)
    ddgs = DDGS()

    for i, query in enumerate(queries):
        if consecutive_empty >= max_consecutive_empty:
            reporting.log_action("Rate limit detected — stopping early", {
                "completed_queries": i,
                "total_queries": len(queries),
                "results_so_far": len(all_results),
            })
            break

        # Rate limit compliance: ~20 requests/min safe threshold.
        # Each query = 2 API calls (text + news).
        # 3s between queries ≈ 6s per 2 calls ≈ 20 calls/min.
        # The DDGS library adds its own 0.75s floor between calls.
        if i > 0:
            _time.sleep(3)

        got_results = False
        try:
            # Text search
            results = _search_web(query, max_results=max_results, ddgs_instance=ddgs)
            if results:
                log_tool_call(
                    "retrieval", "duckduckgo_search",
                    {"query": query},
                    results,
                    label=search_label,
                )
                all_results.extend(results)
                got_results = True

            # News search — catches timestamped articles text search misses
            if use_news:
                _time.sleep(2)
                news_results = _search_news(
                    query, max_results=max_results, ddgs_instance=ddgs,
                )
                if news_results:
                    log_tool_call(
                        "retrieval", "duckduckgo_news",
                        {"query": query},
                        news_results,
                        label=f"{search_label}_news",
                    )
                    all_results.extend(news_results)
                    got_results = True
        except Exception:
            failures += 1

        if got_results:
            consecutive_empty = 0
        else:
            consecutive_empty += 1

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
    label: str = "",
) -> list[str]:
    """Call LLM and parse a JSON array of search query strings."""
    llm = get_llm_for_role("retrieval")

    try:
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        response = llm.invoke(messages)
        log_llm_call("retrieval", messages, response, label=label)
        raw = strip_thinking(response.content)

        try:
            queries = extract_json(raw)
            if isinstance(queries, list):
                return [str(q) for q in queries[:max_queries]]
        except json.JSONDecodeError:
            pass
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

    seen_links: set[str] = set()

    # If this is a follow-up from the quality gate, skip EDINET and seed generation
    # — just run the targeted follow-up queries
    if is_follow_up:
        reporting.log_action("Follow-up retrieval from quality gate", {
            "queries": len(follow_up_queries),
        })
        for q in follow_up_queries:
            reporting.log_item(q, style="dim")

        raw_results, failures = _run_web_searches(follow_up_queries, search_label="follow_up")
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

    # Discover and load regulatory filings for this company
    regions = state.get("regions", [])
    edinet_docs = discover_and_load_filings(company, cutoff, regions)
    if edinet_docs:
        reporting.log_action("Regulatory filings loaded", {"docs": len(edinet_docs)})
    else:
        reporting.log_action("No regulatory filings available — using web search only")

    # Generate seed queries autonomously from case context
    peers = state.get("peers", [])
    peer_names = ", ".join(
        p.get("company", str(p)) if isinstance(p, dict) else str(p)
        for p in peers[:7]
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
        label="seed_queries",
    )

    # Fallback: use config topics if LLM fails, or add them as supplements
    config_topics = state.get("search_topics", [])
    search_topics = seed_queries if seed_queries else config_topics
    if not search_topics:
        search_topics = [f"{company} {theme}", f"{company} EV strategy"]

    # Add archival source queries (site-specific for reputable English sources)
    peer_list = [
        p.get("company", str(p)) if isinstance(p, dict) else str(p)
        for p in state.get("peers", [])[:5]
    ]
    archival_queries = _generate_archival_queries(company, theme, cutoff, peer_list)
    search_topics.extend(archival_queries)

    reporting.log_action("Pass 1: Seed search (LLM-generated + archival)", {
        "queries": len(search_topics),
        "archival": len(archival_queries),
    })
    for q in search_topics:
        reporting.log_item(q, style="dim")

    raw_results, failures = _run_web_searches(search_topics, search_label="seed")
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
        label="gap_analysis",
    )

    gap_web_docs: list[dict] = []
    if gap_queries:
        reporting.log_action("Gap analysis queries", {
            "count": len(gap_queries),
        })
        for q in gap_queries:
            reporting.log_item(q, style="dim")

        raw_gap, gap_failures = _run_web_searches(gap_queries, search_label="gap_fill")
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
        label="counternarrative",
    )

    counter_web_docs: list[dict] = []
    if counter_queries:
        reporting.log_action("Counternarrative queries", {
            "count": len(counter_queries),
        })
        for q in counter_queries:
            reporting.log_item(q, style="dim")

        raw_counter, counter_failures = _run_web_searches(
            counter_queries, search_label="counternarrative",
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
