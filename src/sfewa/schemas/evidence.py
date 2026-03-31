"""Pydantic models for evidence, risk factors, and evaluation objects."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """A single piece of structured evidence extracted from a source document."""

    evidence_id: str
    claim_text: str
    claim_type: Literal[
        "target_statement",
        "investment_commitment",
        "product_launch_plan",
        "market_outlook",
        "risk_disclosure",
        "competitive_positioning",
        "strategic_revision",
        "policy_change",
        "financial_metric",
    ]
    entity: str
    metric_name: str | None = None
    metric_value: str | None = None
    unit: str | None = None
    region: str | None = None
    event_date: date | None = None
    published_at: date
    source_url: str
    source_title: str
    source_type: Literal[
        "company_filing",
        "company_presentation",
        "industry_report",
        "government_policy",
        "peer_filing",
        "news_article",
    ]
    span_text: str  # exact quote from source
    stance: Literal["supports_risk", "contradicts_risk", "neutral"]
    relevance_score: float = Field(ge=0.0, le=1.0)
    credibility_tier: Literal[
        "tier1_primary", "tier2_official", "tier3_reputable", "tier4_secondary"
    ]


class RiskFactor(BaseModel):
    """A risk factor identified by an analyst agent."""

    factor_id: str
    dimension: Literal[
        "market_timing",
        "regional_mismatch",
        "product_portfolio",
        "technology_capability",
        "capital_allocation",
        "execution",
        "narrative_consistency",
        "policy_dependency",
        "competitive_pressure",
    ]
    title: str
    description: str
    severity: Literal["critical", "high", "medium", "low"]
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str]  # evidence_ids
    contradicting_evidence: list[str] = Field(default_factory=list)
    causal_chain: list[str]  # ordered causal reasoning steps
    unresolved_gaps: list[str] = Field(default_factory=list)


class AdversarialChallenge(BaseModel):
    """A challenge raised by the adversarial reviewer against a risk factor."""

    challenge_id: str
    target_factor_id: str
    challenge_text: str
    counter_evidence: list[str]  # evidence_ids
    severity: Literal["strong", "moderate", "weak"]
    resolution: str | None = None


class BacktestEvent(BaseModel):
    """A ground truth event matched against predicted risk factors."""

    event_id: str
    event_date: date
    description: str
    event_type: Literal[
        "target_revision",
        "capex_reset",
        "project_cancellation",
        "asset_writedown",
        "narrative_shift",
    ]
    matched_factors: list[str]  # factor_ids
    match_quality: Literal["strong", "partial", "weak", "miss"]
