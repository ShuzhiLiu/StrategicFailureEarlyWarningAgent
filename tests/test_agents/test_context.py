"""Tests for pipeline context injection.

Validates that build_pipeline_context produces correct summaries
from various pipeline states, enabling downstream nodes to be context-aware.
"""

from __future__ import annotations

from sfewa.context import build_pipeline_context


def test_empty_state_returns_empty():
    state = {}
    assert build_pipeline_context(state) == ""


def test_retrieval_summary():
    state = {
        "retrieved_docs": [
            {"source": "edinet"},
            {"source": "edinet"},
            {"source": "duckduckgo"},
        ],
    }
    ctx = build_pipeline_context(state)
    assert "Retrieved 3 documents" in ctx
    assert "2 edinet" in ctx
    assert "1 duckduckgo" in ctx


def test_evidence_stance_summary():
    state = {
        "evidence": [
            {"stance": "supports_risk"},
            {"stance": "supports_risk"},
            {"stance": "contradicts_risk"},
            {"stance": "neutral"},
            {"stance": "neutral"},
        ],
    }
    ctx = build_pipeline_context(state)
    assert "5 evidence items" in ctx
    assert "2 supports" in ctx
    assert "1 contradicts" in ctx
    assert "2 neutral" in ctx


def test_quality_gate_sufficient():
    state = {"evidence_sufficient": True}
    ctx = build_pipeline_context(state)
    assert "Quality gate: evidence sufficient" in ctx


def test_quality_gate_insufficient():
    state = {
        "evidence_sufficient": False,
        "follow_up_queries": ["query1", "query2"],
    }
    ctx = build_pipeline_context(state)
    assert "evidence insufficient" in ctx
    assert "2 follow-up queries" in ctx


def test_quality_gate_none_not_shown():
    """evidence_sufficient=None means quality gate hasn't run yet."""
    state = {"evidence_sufficient": None}
    ctx = build_pipeline_context(state)
    assert "Quality gate" not in ctx


def test_iteration_count_shown_when_above_1():
    state = {"iteration_count": 3, "evidence": [{"stance": "neutral"}]}
    ctx = build_pipeline_context(state)
    assert "Retrieval iterations: 3" in ctx


def test_iteration_count_hidden_when_1():
    state = {"iteration_count": 1, "evidence": [{"stance": "neutral"}]}
    ctx = build_pipeline_context(state)
    assert "Retrieval iterations" not in ctx


def test_risk_factors_deduped_in_summary():
    """Risk factor summary should deduplicate by dimension."""
    state = {
        "risk_factors": [
            {"dimension": "market_timing", "severity": "high"},
            {"dimension": "market_timing", "severity": "critical"},  # later = wins
            {"dimension": "execution", "severity": "medium"},
        ],
    }
    ctx = build_pipeline_context(state)
    # Should show 2 factors (deduped), not 3
    assert "Risk factors: 2" in ctx
    # Should include the latest severity for market_timing
    assert "critical" in ctx.lower()


def test_adversarial_challenges_summary():
    state = {
        "adversarial_challenges": [
            {"severity": "strong"},
            {"severity": "moderate"},
            {"severity": "moderate"},
            {"severity": "weak"},
        ],
    }
    ctx = build_pipeline_context(state)
    assert "4" in ctx
    assert "1 strong" in ctx
    assert "2 moderate" in ctx
    assert "1 weak" in ctx


def test_adversarial_passes_shown_when_above_1():
    state = {
        "adversarial_pass_count": 2,
        "adversarial_challenges": [{"severity": "moderate"}],
    }
    ctx = build_pipeline_context(state)
    assert "Adversarial passes: 2" in ctx


def test_adversarial_recommendation_shown():
    state = {"adversarial_recommendation": "proceed"}
    ctx = build_pipeline_context(state)
    assert "Adversarial recommendation: proceed" in ctx


def test_full_pipeline_context():
    """Test with a realistic full-pipeline state."""
    state = {
        "retrieved_docs": [
            {"source": "edinet"},
            {"source": "duckduckgo"},
            {"source": "duckduckgo"},
        ],
        "evidence": [
            {"stance": "supports_risk"},
            {"stance": "contradicts_risk"},
            {"stance": "neutral"},
        ],
        "evidence_sufficient": True,
        "iteration_count": 2,
        "risk_factors": [
            {"dimension": "market_timing", "severity": "high"},
            {"dimension": "execution", "severity": "medium"},
        ],
        "adversarial_challenges": [
            {"severity": "moderate"},
            {"severity": "weak"},
        ],
        "adversarial_pass_count": 1,
        "adversarial_recommendation": "proceed",
    }
    ctx = build_pipeline_context(state)
    assert "PIPELINE CONTEXT" in ctx
    assert "Retrieved 3 documents" in ctx
    assert "3 evidence items" in ctx
    assert "Quality gate: evidence sufficient" in ctx
    assert "Retrieval iterations: 2" in ctx
    assert "Risk factors: 2" in ctx
    assert "2 moderate" not in ctx  # 1 moderate + 1 weak
    assert "Adversarial recommendation: proceed" in ctx
