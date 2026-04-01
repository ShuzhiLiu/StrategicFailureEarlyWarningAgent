"""Tests for LLM-driven routing functions.

These are the core agentic routing decisions — the LLM sets state fields
and routing functions read them to determine next node.
"""

from __future__ import annotations

import pytest

from sfewa.graph.routing import (
    MAX_ADVERSARIAL_PASSES,
    MAX_ITERATIONS,
    after_adversarial_review,
    route_after_quality_gate,
)


# ── Quality Gate Routing ──


class TestRouteAfterQualityGate:
    """Test quality gate routing: sufficient → fan_out, insufficient → retrieval."""

    def test_sufficient_routes_to_fan_out(self):
        state = {"evidence_sufficient": True, "iteration_count": 1}
        assert route_after_quality_gate(state) == "fan_out"

    def test_insufficient_routes_to_retrieval(self):
        state = {"evidence_sufficient": False, "iteration_count": 1}
        assert route_after_quality_gate(state) == "retrieval"

    def test_max_iterations_forces_fan_out(self):
        """Dead-loop protection: even if LLM says insufficient, proceed after max iterations."""
        state = {"evidence_sufficient": False, "iteration_count": MAX_ITERATIONS}
        assert route_after_quality_gate(state) == "fan_out"

    def test_max_iterations_boundary(self):
        """One below max should still respect LLM decision."""
        state = {"evidence_sufficient": False, "iteration_count": MAX_ITERATIONS - 1}
        assert route_after_quality_gate(state) == "retrieval"

    def test_missing_evidence_sufficient_defaults_to_fan_out(self):
        """If quality gate didn't set the field, default to proceeding."""
        state = {"iteration_count": 1}
        assert route_after_quality_gate(state) == "fan_out"

    def test_none_evidence_sufficient_routes_to_retrieval(self):
        """None means quality gate hasn't decided — treated as insufficient (falsy)."""
        state = {"evidence_sufficient": None, "iteration_count": 1}
        assert route_after_quality_gate(state) == "retrieval"

    def test_zero_iterations_sufficient(self):
        state = {"evidence_sufficient": True, "iteration_count": 0}
        assert route_after_quality_gate(state) == "fan_out"

    def test_zero_iterations_insufficient(self):
        state = {"evidence_sufficient": False, "iteration_count": 0}
        assert route_after_quality_gate(state) == "retrieval"


# ── Adversarial Review Routing ──


class TestAfterAdversarialReview:
    """Test adversarial routing: proceed → synthesis, reanalyze → extraction."""

    def test_proceed_routes_to_synthesis(self):
        state = {"adversarial_recommendation": "proceed", "adversarial_pass_count": 1}
        assert after_adversarial_review(state) == "risk_synthesis"

    def test_reanalyze_routes_to_extraction(self):
        state = {"adversarial_recommendation": "reanalyze", "adversarial_pass_count": 1}
        assert after_adversarial_review(state) == "evidence_extraction"

    def test_max_passes_forces_synthesis(self):
        """Dead-loop protection: proceed after max adversarial passes."""
        state = {
            "adversarial_recommendation": "reanalyze",
            "adversarial_pass_count": MAX_ADVERSARIAL_PASSES,
        }
        assert after_adversarial_review(state) == "risk_synthesis"

    def test_max_passes_boundary(self):
        state = {
            "adversarial_recommendation": "reanalyze",
            "adversarial_pass_count": MAX_ADVERSARIAL_PASSES - 1,
        }
        assert after_adversarial_review(state) == "evidence_extraction"

    def test_missing_recommendation_defaults_to_proceed(self):
        state = {"adversarial_pass_count": 1}
        assert after_adversarial_review(state) == "risk_synthesis"

    def test_unknown_recommendation_defaults_to_proceed(self):
        """Any value other than 'reanalyze' should proceed."""
        state = {"adversarial_recommendation": "unknown_value", "adversarial_pass_count": 1}
        assert after_adversarial_review(state) == "risk_synthesis"

    def test_missing_pass_count_defaults_to_zero(self):
        state = {"adversarial_recommendation": "reanalyze"}
        assert after_adversarial_review(state) == "evidence_extraction"
