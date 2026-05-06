"""Pipeline state definition."""

from __future__ import annotations

from typing import Any, Literal

from typing_extensions import TypedDict


class PipelineState(TypedDict):
    """Central state flowing through the pipeline.

    Accumulating fields (evidence, risk_factors, adversarial_challenges,
    backtest_events) are extended via merge_state() in the pipeline executor.
    Other fields are overwritten by the last writer.
    """

    # ── Case config (set once at init) ──
    case_id: str
    company: str
    strategy_theme: str
    cutoff_date: str  # ISO format YYYY-MM-DD
    regions: list[str]
    # Either ["Toyota Motor", "BYD", ...] or [{"name": "Toyota Motor", ...}, ...]
    peers: list[str | dict[str, Any]]
    ground_truth_events: list[dict[str, Any]]
    # L1.3 audit envelope (added 2026-05-05). case_type drives loader and
    # verifier behavior; audit_meta carries jurisdiction / ticker /
    # allowed_sources / doc_types / verifier_corpus from CaseConfig.
    case_type: Literal["retrospective", "forward"]
    audit_meta: dict[str, Any]
    # LLM-generated per-analyst dimensions, e.g.
    # {"industry": [{"name": "...", "description": "...", ...}], "company": [...], "peer": [...]}
    analysis_dimensions: dict[str, list[dict[str, str]]]

    # ── Accumulating fields (extended by merge_state in pipeline executor) ──
    evidence: list[dict[str, Any]]
    risk_factors: list[dict[str, Any]]
    adversarial_challenges: list[dict[str, Any]]
    backtest_events: list[dict[str, Any]]

    # ── Overwriting fields ──
    retrieved_docs: list[dict[str, Any]]
    # Doc-level audit log (L1.4). Populated by retrieval; saved as
    # source_manifest.json. The production invariant is enforced at
    # artifact-save time (zero kept docs with release_time > cutoff_date).
    source_manifest: list[dict[str, Any]]
    risk_score: int | None  # 0-100 continuous risk score
    overall_risk_level: Literal["critical", "high", "medium", "low"] | None
    overall_confidence: float | None
    risk_memo: str | None
    backtest_summary: str | None

    # ── Control flow ──
    current_stage: str
    iteration_count: int
    adversarial_pass_count: int
    error: str | None

    # ── Agentic routing ──
    # LLM-driven decisions stored here so routing functions can read them
    evidence_sufficient: bool | None  # quality gate decision
    follow_up_queries: list[str]  # targeted queries from quality gate → retrieval
    adversarial_recommendation: str | None  # "proceed" or "reanalyze"
