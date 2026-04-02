"""LangGraph pipeline state definition."""

from __future__ import annotations

import operator
from typing import Annotated, Literal

from typing_extensions import TypedDict


class PipelineState(TypedDict):
    """Central state flowing through the LangGraph pipeline.

    Fields with Annotated[list, operator.add] accumulate across nodes.
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

    # ── Accumulating fields ──
    evidence: Annotated[list[dict], operator.add]
    risk_factors: Annotated[list[dict], operator.add]
    adversarial_challenges: Annotated[list[dict], operator.add]
    backtest_events: Annotated[list[dict], operator.add]

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
