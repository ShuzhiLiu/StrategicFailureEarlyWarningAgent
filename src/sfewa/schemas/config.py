"""Configuration Pydantic models for case and model configs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PeerConfig(BaseModel):
    company: str
    ticker: str
    relevance: str


class GroundTruthFigure(BaseModel):
    metric: str
    value: str | None = None
    old_value: str | None = None
    new_value: str | None = None


class GroundTruthEvent(BaseModel):
    event_id: str
    event_date: str
    description: str
    event_type: str
    source_url: str | None = None
    key_figures: list[GroundTruthFigure] = Field(default_factory=list)


class CostLimits(BaseModel):
    max_total_usd: float = 15.0
    max_calls_per_agent: int = 25


class CaseConfig(BaseModel):
    """Configuration for a single analysis case."""

    case_id: str
    company: str
    ticker: str
    strategy_theme: str
    description: str
    cutoff_date: str
    regions: list[str]
    peers: list[PeerConfig]
    allowed_source_types: list[str]
    search_topics: list[str]
    ground_truth_events: list[GroundTruthEvent]
    ontology_version: str = "v1"
    max_risk_factors: int = 15
    min_evidence_per_factor: int = 2
    thinking_mode_overrides: dict[str, bool] = Field(default_factory=dict)
    cost_limits: CostLimits = Field(default_factory=CostLimits)
