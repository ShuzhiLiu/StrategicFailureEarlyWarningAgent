"""Tests for the quality gate agent node.

Uses mocked LLM to test decision logic without real API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sfewa.agents.quality_gate import quality_gate_node


def _make_state(
    evidence: list[dict] | None = None,
    iteration_count: int = 0,
) -> dict:
    """Build a minimal PipelineState dict for quality gate testing."""
    return {
        "company": "Honda Motor Co., Ltd.",
        "strategy_theme": "EV electrification strategy",
        "cutoff_date": "2025-05-19",
        "evidence": evidence or [],
        "iteration_count": iteration_count,
        "evidence_sufficient": None,
        "follow_up_queries": [],
    }


def _make_evidence(n: int, stance: str = "supports_risk") -> list[dict]:
    """Generate n dummy evidence items."""
    return [
        {
            "evidence_id": f"E{i:03d}",
            "claim_text": f"Test claim {i}",
            "claim_type": "target_statement",
            "entity": "Honda",
            "published_at": "2025-01-01",
            "source_url": "http://example.com",
            "source_title": "Test source",
            "source_type": "news_article",
            "span_text": f"Test span {i}",
            "stance": stance,
            "relevance_score": 0.8,
        }
        for i in range(1, n + 1)
    ]


def _mock_llm_response(json_str: str) -> MagicMock:
    """Create a mock LLM response with given content."""
    response = MagicMock()
    response.content = json_str
    return response


class TestQualityGateNode:
    """Test quality gate LLM-driven routing decisions."""

    @patch("sfewa.agents.quality_gate.get_llm_for_role")
    def test_sufficient_decision(self, mock_get_llm):
        """LLM says sufficient → evidence_sufficient=True, no follow-up queries."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _mock_llm_response(
            '{"decision": "sufficient", "reasoning": "Evidence covers all dimensions", "gaps": [], "follow_up_queries": []}'
        )
        mock_get_llm.return_value = mock_llm

        state = _make_state(evidence=_make_evidence(10))
        result = quality_gate_node(state)

        assert result["evidence_sufficient"] is True
        assert result["follow_up_queries"] == []
        assert result["current_stage"] == "quality_gate"

    @patch("sfewa.agents.quality_gate.get_llm_for_role")
    def test_insufficient_decision(self, mock_get_llm):
        """LLM says insufficient → evidence_sufficient=False, follow-up queries provided."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _mock_llm_response(
            '{"decision": "insufficient", "reasoning": "Missing competitor data", '
            '"gaps": ["No BYD comparison"], '
            '"follow_up_queries": ["BYD vs Honda EV sales 2024", "China NEV market share 2024"]}'
        )
        mock_get_llm.return_value = mock_llm

        state = _make_state(evidence=_make_evidence(3))
        result = quality_gate_node(state)

        assert result["evidence_sufficient"] is False
        assert len(result["follow_up_queries"]) == 2
        assert "BYD vs Honda EV sales 2024" in result["follow_up_queries"]

    @patch("sfewa.agents.quality_gate.get_llm_for_role")
    def test_max_iterations_bypasses_llm(self, mock_get_llm):
        """At max iterations, quality gate should force-proceed without calling LLM."""
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        state = _make_state(evidence=_make_evidence(5), iteration_count=3)
        result = quality_gate_node(state)

        assert result["evidence_sufficient"] is True
        assert result["follow_up_queries"] == []
        # LLM should NOT be called
        mock_llm.invoke.assert_not_called()

    @patch("sfewa.agents.quality_gate.get_llm_for_role")
    def test_llm_failure_defaults_to_proceed(self, mock_get_llm):
        """If LLM call fails, quality gate should default to proceeding."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Connection refused")
        mock_get_llm.return_value = mock_llm

        state = _make_state(evidence=_make_evidence(10))
        result = quality_gate_node(state)

        assert result["evidence_sufficient"] is True
        assert result["follow_up_queries"] == []

    @patch("sfewa.agents.quality_gate.get_llm_for_role")
    def test_malformed_json_defaults_to_proceed(self, mock_get_llm):
        """If LLM returns unparseable JSON, quality gate should default to proceeding."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _mock_llm_response("This is not JSON at all")
        mock_get_llm.return_value = mock_llm

        state = _make_state(evidence=_make_evidence(10))
        result = quality_gate_node(state)

        assert result["evidence_sufficient"] is True
        assert result["follow_up_queries"] == []

    @patch("sfewa.agents.quality_gate.get_llm_for_role")
    def test_follow_up_queries_capped_at_5(self, mock_get_llm):
        """Follow-up queries should be capped at 5."""
        mock_llm = MagicMock()
        queries = [f"query {i}" for i in range(10)]
        mock_llm.invoke.return_value = _mock_llm_response(
            '{"decision": "insufficient", "reasoning": "test", "gaps": [], '
            f'"follow_up_queries": {queries!r}}}'.replace("'", '"')
        )
        mock_get_llm.return_value = mock_llm

        state = _make_state(evidence=_make_evidence(3))
        result = quality_gate_node(state)

        assert len(result["follow_up_queries"]) <= 5

    @patch("sfewa.agents.quality_gate.get_llm_for_role")
    def test_think_tags_stripped(self, mock_get_llm):
        """LLM response with <think> tags should still parse correctly."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _mock_llm_response(
            '<think>Let me evaluate...</think>\n'
            '{"decision": "sufficient", "reasoning": "OK", "gaps": [], "follow_up_queries": []}'
        )
        mock_get_llm.return_value = mock_llm

        state = _make_state(evidence=_make_evidence(10))
        result = quality_gate_node(state)

        assert result["evidence_sufficient"] is True

    @patch("sfewa.agents.quality_gate.get_llm_for_role")
    def test_evidence_statistics_passed_to_llm(self, mock_get_llm):
        """Verify the LLM receives correct evidence statistics in the prompt."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _mock_llm_response(
            '{"decision": "sufficient", "reasoning": "OK", "gaps": [], "follow_up_queries": []}'
        )
        mock_get_llm.return_value = mock_llm

        evidence = _make_evidence(5, stance="supports_risk") + _make_evidence(3, stance="contradicts_risk")
        # Fix IDs to avoid collision
        for i, e in enumerate(evidence):
            e["evidence_id"] = f"E{i:03d}"

        state = _make_state(evidence=evidence)
        quality_gate_node(state)

        # Check the user message passed to LLM contains correct counts
        call_args = mock_llm.invoke.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "8 items" in user_msg
        assert "5 supports_risk" in user_msg
        assert "3 contradicts_risk" in user_msg
