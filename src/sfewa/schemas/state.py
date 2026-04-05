"""Pipeline state definition."""

from __future__ import annotations

from typing import Literal

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
    peers: list  # list[str] or list[dict] — both supported
    ground_truth_events: list[dict]
    analysis_dimensions: dict  # LLM-generated per-analyst dimensions (optional)

    # ── Accumulating fields (extended by merge_state in pipeline executor) ──
    evidence: list[dict]
    risk_factors: list[dict]
    adversarial_challenges: list[dict]
    backtest_events: list[dict]

    # ── Overwriting fields ──
    retrieved_docs: list[dict]
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
