"""Tests for Pydantic evidence models."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from sfewa.schemas.evidence import EvidenceItem, RiskFactor


def test_evidence_item_valid():
    item = EvidenceItem(
        evidence_id="ev_001",
        claim_text="Honda targets 30% EV/FCEV sales by 2030",
        claim_type="target_statement",
        entity="Honda Motor Co., Ltd.",
        metric_name="EV sales ratio 2030",
        metric_value="30%",
        region="global",
        published_at=date(2024, 5, 16),
        source_url="https://global.honda/en/newsroom/news/2024/c240516eng.html",
        source_title="Honda Business Briefing 2024",
        source_type="company_presentation",
        span_text="Targeting approximately 30% of total automobile sales from EVs and FCEVs by 2030",
        stance="supports_risk",
        relevance_score=0.9,
        credibility_tier="tier1_primary",
    )
    assert item.evidence_id == "ev_001"
    assert item.stance == "supports_risk"


def test_evidence_item_invalid_score():
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="ev_bad",
            claim_text="test",
            claim_type="target_statement",
            entity="Honda",
            published_at=date(2024, 1, 1),
            source_url="http://example.com",
            source_title="test",
            source_type="company_filing",
            span_text="test",
            stance="neutral",
            relevance_score=1.5,  # out of range
            credibility_tier="tier1_primary",
        )


def test_risk_factor_valid():
    factor = RiskFactor(
        factor_id="rf_001",
        dimension="market_timing",
        title="EV adoption slower than Honda's forecast",
        description="North American EV adoption rate trails Honda's planning assumptions",
        severity="high",
        confidence=0.75,
        supporting_evidence=["ev_001", "ev_002"],
        causal_chain=[
            "NA EV adoption rate 8% vs Honda's implied 15%+ assumption",
            "Volume shortfall undermines factory utilization",
            "Unit economics worsen, triggering capex review",
        ],
    )
    assert factor.severity == "high"
    assert len(factor.supporting_evidence) == 2
