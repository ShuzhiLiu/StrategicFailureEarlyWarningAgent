"""Evidence Extraction agent node.

Extracts structured EvidenceItem objects from retrieved documents using LLM.
Applies temporal filtering to reject post-cutoff evidence.
"""

from __future__ import annotations

import json
import re

from sfewa import reporting
from sfewa.llm import get_llm_for_role
from sfewa.prompts.extraction import (
    EXTRACTION_SYSTEM,
    EXTRACTION_USER,
    format_documents,
)
from sfewa.schemas.state import PipelineState
from sfewa.tools.temporal_filter import is_before_cutoff


def _parse_evidence_json(text: str) -> list[dict]:
    """Extract JSON array from LLM response, handling markdown fences."""
    # Strip markdown code fences if present
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()

    # Try to find a JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start : end + 1]

    return json.loads(text)


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

    # Ensure relevance_score is a float in range
    try:
        score = float(item.get("relevance_score", 0.5))
        item["relevance_score"] = max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        item["relevance_score"] = 0.5

    return item


def evidence_extraction_node(state: PipelineState) -> dict:
    """Extract structured evidence from retrieved documents.

    1. Send retrieved docs to LLM with extraction prompt
    2. Parse structured JSON response
    3. Validate each item against schema
    4. Apply temporal filter (reject post-cutoff items)
    5. Report results
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

    # Format prompt
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

    # Call LLM
    llm = get_llm_for_role("extraction")
    reporting.log_action("Calling LLM for evidence extraction")

    evidence_items: list[dict] = []
    retry_count = 0
    max_retries = 1
    last_error = None

    while retry_count <= max_retries:
        try:
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ]
            if last_error and retry_count > 0:
                messages.append({
                    "role": "user",
                    "content": f"Your previous response had an error: {last_error}. "
                               "Please return ONLY a valid JSON array.",
                })

            response = llm.invoke(messages)
            raw_text = response.content

            # Strip <think>...</think> block if present (Qwen3.5 thinking mode)
            raw_text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text).strip()

            parsed = _parse_evidence_json(raw_text)
            if not isinstance(parsed, list):
                raise ValueError(f"Expected list, got {type(parsed).__name__}")

            evidence_items = parsed
            break

        except Exception as e:
            last_error = str(e)[:200]
            retry_count += 1
            reporting.log_action(f"LLM parse error (attempt {retry_count})", {
                "error": last_error,
            })

    if not evidence_items:
        reporting.log_action("Failed to extract evidence after retries")
        reporting.exit_node("evidence_extraction", {"evidence": 0}, next_node="analysts")
        return {
            "evidence": [],
            "current_stage": "evidence_extraction",
            "iteration_count": iteration,
            "error": f"Evidence extraction failed: {last_error}",
        }

    # Validate and filter
    valid_items: list[dict] = []
    invalid_count = 0
    for item in evidence_items:
        cleaned = _validate_evidence_item(item)
        if cleaned:
            valid_items.append(cleaned)
        else:
            invalid_count += 1

    reporting.log_action("Validation", {
        "raw_items": len(evidence_items),
        "valid": len(valid_items),
        "invalid": invalid_count,
    })

    # Temporal filter
    accepted: list[dict] = []
    rejected: list[dict] = []
    for item in valid_items:
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

    # Log a few sample items
    for item in accepted[:3]:
        reporting.log_item(
            f"{item['evidence_id']} [{item['claim_type']}] {item['claim_text'][:70]}...",
            style="dim",
        )

    reporting.exit_node("evidence_extraction", {
        "evidence_items": len(accepted),
    }, next_node="fan-out [industry, company, peer]")

    return {
        "evidence": accepted,
        "current_stage": "evidence_extraction",
        "iteration_count": iteration,
    }
