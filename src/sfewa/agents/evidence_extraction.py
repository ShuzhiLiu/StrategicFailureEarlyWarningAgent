"""Evidence Extraction agent node.

Extracts structured EvidenceItem objects from retrieved documents using LLM.
Applies temporal filtering to reject post-cutoff evidence.

Agentic behavior: processes documents in batches by source type to maximize
extraction quality. EDINET filings (company disclosures) are processed
separately from web search results (external signals) so the LLM gives
each source type appropriate attention.
"""

from __future__ import annotations

import json

from liteagent import extract_json, strip_thinking

from sfewa import reporting
from sfewa.llm import get_llm_for_role
from sfewa.tools.chat_log import log_llm_call
from sfewa.prompts.extraction import (
    EXTRACTION_SYSTEM,
    EXTRACTION_USER,
    format_documents,
)
from sfewa.schemas.state import PipelineState
from sfewa.tools.temporal_filter import is_before_cutoff


def _parse_evidence_json(text: str) -> list[dict]:
    """Extract JSON array from LLM response, handling markdown fences."""
    text = strip_thinking(text)
    parsed = extract_json(text)
    if isinstance(parsed, list):
        return parsed
    # LLM may wrap array in a dict like {"evidence_items": [...]}
    if isinstance(parsed, dict):
        for key in ("evidence_items", "items", "evidence"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
        # Fallback: any key with a list value
        for value in parsed.values():
            if isinstance(value, list):
                return value
    raise json.JSONDecodeError("Expected JSON array", text, 0)


def _validate_evidence_item(item: dict) -> dict | None:
    """Validate and clean an evidence item dict. Returns None if invalid."""
    required_fields = [
        "evidence_id", "claim_text", "claim_type", "entity",
        "published_at", "source_url", "source_title", "source_type",
        "span_text", "stance",
    ]
    for field in required_fields:
        if field not in item or not item[field]:
            return None

    try:
        score = float(item.get("relevance_score", 0.5))
        item["relevance_score"] = max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        item["relevance_score"] = 0.5

    return item


def _extract_batch(
    docs: list[dict],
    batch_label: str,
    company: str,
    theme: str,
    cutoff: str,
    start_id: int,
    llm,
) -> list[dict]:
    """Run extraction on a single batch of documents.

    Returns validated evidence items (before temporal filtering).
    """
    if not docs:
        return []

    documents_text = format_documents(docs)
    system_msg = EXTRACTION_SYSTEM.format(
        company=company,
        strategy_theme=theme,
        cutoff_date=cutoff,
    )
    user_msg = EXTRACTION_USER.format(
        doc_count=len(docs),
        company=company,
        strategy_theme=theme,
        cutoff_date=cutoff,
        documents_text=documents_text,
    )
    # Tell the LLM to start IDs from the correct offset
    if start_id > 1:
        user_msg += f"\n\nStart evidence_id numbering from E{start_id:03d}."

    reporting.log_action(f"Extracting from batch: {batch_label}", {
        "docs": len(docs),
    })

    retry_count = 0
    max_retries = 1
    last_error = None
    evidence_items: list[dict] = []

    while retry_count <= max_retries:
        try:
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ]
            if last_error and retry_count > 0:
                messages.append({
                    "role": "user",
                    "content": f"Previous error: {last_error}. Return ONLY a valid JSON array.",
                })

            response = llm.invoke(messages)
            log_llm_call("evidence_extraction", messages, response, label=batch_label)
            raw_text = response.content
            parsed = _parse_evidence_json(raw_text)
            if not isinstance(parsed, list):
                raise ValueError(f"Expected list, got {type(parsed).__name__}")

            evidence_items = parsed
            break

        except Exception as e:
            last_error = str(e)[:200]
            retry_count += 1
            reporting.log_action(f"Parse error in {batch_label} (attempt {retry_count})", {
                "error": last_error,
            })

    # Validate
    valid: list[dict] = []
    for item in evidence_items:
        cleaned = _validate_evidence_item(item)
        if cleaned:
            valid.append(cleaned)

    reporting.log_action(f"Batch '{batch_label}' extraction", {
        "raw": len(evidence_items),
        "valid": len(valid),
    })

    return valid


def evidence_extraction_node(state: PipelineState) -> dict:
    """Extract structured evidence from retrieved documents.

    Agentic batched extraction:
    1. Split documents by source type (EDINET filings vs web search)
    2. Extract from each batch separately for focused attention
    3. Merge, deduplicate, validate
    4. Apply temporal filter (reject post-cutoff items)

    Processing EDINET and web docs separately ensures the LLM gives
    full attention to each source type rather than skimming 100+ docs.
    """
    docs = state.get("retrieved_docs", [])
    cutoff = state["cutoff_date"]
    company = state["company"]
    theme = state["strategy_theme"]
    iteration = state.get("iteration_count", 0) + 1

    reporting.enter_node("evidence_extraction", {
        "input_docs": len(docs),
        "cutoff_date": cutoff,
        "iteration": f"{iteration}/3",
    })

    if not docs:
        reporting.log_action("No documents to extract from")
        reporting.exit_node("evidence_extraction", {"evidence": 0})
        return {
            "evidence": [],
            "current_stage": "evidence_extraction",
            "iteration_count": iteration,
        }

    # ── Split documents by source type ──
    edinet_docs = [d for d in docs if d.get("source") == "edinet"]
    web_docs = [d for d in docs if d.get("source") != "edinet"]

    reporting.log_action("Batched extraction strategy", {
        "edinet_batch": len(edinet_docs),
        "web_batch": len(web_docs),
    })

    llm = get_llm_for_role("extraction")

    # ── Batch 1: EDINET filings (company disclosures) ──
    edinet_evidence = _extract_batch(
        edinet_docs,
        batch_label="EDINET filings",
        company=company,
        theme=theme,
        cutoff=cutoff,
        start_id=1,
        llm=llm,
    )

    # ── Batch 2+: Web search results (external signals) ──
    # Split large web doc sets into chunks to stay within LLM context window.
    # 50 docs ≈ 15K chars prompt — fits comfortably in 32K token context.
    WEB_BATCH_SIZE = 50
    web_evidence: list[dict] = []
    for chunk_idx in range(0, max(1, len(web_docs)), WEB_BATCH_SIZE):
        chunk = web_docs[chunk_idx : chunk_idx + WEB_BATCH_SIZE]
        if not chunk:
            break
        chunk_label = (
            f"Web search results"
            if len(web_docs) <= WEB_BATCH_SIZE
            else f"Web search results (batch {chunk_idx // WEB_BATCH_SIZE + 1})"
        )
        chunk_evidence = _extract_batch(
            chunk,
            batch_label=chunk_label,
            company=company,
            theme=theme,
            cutoff=cutoff,
            start_id=len(edinet_evidence) + len(web_evidence) + 1,
            llm=llm,
        )
        web_evidence.extend(chunk_evidence)

    # ── Merge batches ──
    all_evidence = edinet_evidence + web_evidence

    # Re-number evidence IDs starting from existing evidence count
    # This prevents ID collisions when quality gate loops back
    existing_count = len(state.get("evidence", []))
    for i, item in enumerate(all_evidence, existing_count + 1):
        item["evidence_id"] = f"E{i:03d}"

    reporting.log_action("Merged evidence", {"total": len(all_evidence)})

    # ── Temporal filter ──
    accepted: list[dict] = []
    rejected: list[dict] = []
    for item in all_evidence:
        pub_date = item.get("published_at", "")
        if is_before_cutoff(pub_date, cutoff):
            accepted.append(item)
        else:
            rejected.append(item)
            reporting.log_rejection(
                item.get("source_title", "?")[:60],
                f"published {pub_date} > cutoff {cutoff}",
            )

    # Stance summary
    stance_counts = {"supports_risk": 0, "contradicts_risk": 0, "neutral": 0}
    for item in accepted:
        stance = item.get("stance", "neutral")
        if stance in stance_counts:
            stance_counts[stance] += 1

    reporting.log_action("Temporal filter", {
        "accepted": len(accepted),
        "rejected": len(rejected),
    })
    reporting.log_action("Stance distribution", stance_counts)

    for item in accepted[:3]:
        reporting.log_item(
            f"{item['evidence_id']} [{item['claim_type']}] {item['claim_text'][:70]}...",
            style="dim",
        )

    reporting.exit_node("evidence_extraction", {
        "evidence_items": len(accepted),
        "from_edinet": sum(
            1 for e in accepted
            if "edinet" in e.get("source_url", "").lower()
            or "EDINET" in e.get("source_title", "")
        ),
        "from_web": sum(
            1 for e in accepted
            if "edinet" not in e.get("source_url", "").lower()
            and "EDINET" not in e.get("source_title", "")
        ),
    }, next_node="fan-out [industry, company, peer]")

    return {
        "evidence": accepted,
        "current_stage": "evidence_extraction",
        "iteration_count": iteration,
    }
