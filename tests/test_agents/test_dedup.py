"""Tests for risk factor deduplication and evidence ID numbering.

These are critical for multi-pass pipeline correctness:
- Risk factor dedup ensures operator.add accumulation doesn't create duplicates
- Evidence ID numbering prevents collisions when quality gate loops back
"""

from __future__ import annotations

import pytest


# ── Risk Factor Deduplication ──
# The dedup pattern (keep latest per dimension) is used in:
# adversarial.py, risk_synthesis.py, backtest.py, artifacts.py
# We test the pattern directly rather than through those nodes.


def _dedup_risk_factors(raw_factors: list[dict]) -> list[dict]:
    """Reproduce the dedup pattern used across the pipeline."""
    seen_dims: dict[str, dict] = {}
    for rf in raw_factors:
        dim = rf.get("dimension", "unknown")
        seen_dims[dim] = rf  # last writer wins per dimension
    return list(seen_dims.values())


class TestRiskFactorDedup:
    def test_no_duplicates_unchanged(self):
        factors = [
            {"factor_id": "RF001", "dimension": "market_timing", "severity": "high"},
            {"factor_id": "RF002", "dimension": "execution", "severity": "medium"},
            {"factor_id": "RF003", "dimension": "competitive_pressure", "severity": "critical"},
        ]
        result = _dedup_risk_factors(factors)
        assert len(result) == 3

    def test_duplicate_dimensions_keep_latest(self):
        """When two factors share a dimension, keep the last one (most recent pass)."""
        factors = [
            {"factor_id": "RF001", "dimension": "market_timing", "severity": "medium"},
            {"factor_id": "RF002", "dimension": "execution", "severity": "high"},
            # Second pass re-analyzed market_timing:
            {"factor_id": "RF010", "dimension": "market_timing", "severity": "critical"},
        ]
        result = _dedup_risk_factors(factors)
        assert len(result) == 2
        market_timing = [r for r in result if r["dimension"] == "market_timing"][0]
        assert market_timing["factor_id"] == "RF010"
        assert market_timing["severity"] == "critical"

    def test_all_same_dimension(self):
        """If all factors share a dimension (edge case), only keep the last."""
        factors = [
            {"factor_id": "RF001", "dimension": "execution", "severity": "low"},
            {"factor_id": "RF002", "dimension": "execution", "severity": "medium"},
            {"factor_id": "RF003", "dimension": "execution", "severity": "high"},
        ]
        result = _dedup_risk_factors(factors)
        assert len(result) == 1
        assert result[0]["factor_id"] == "RF003"

    def test_empty_list(self):
        assert _dedup_risk_factors([]) == []

    def test_missing_dimension_uses_unknown(self):
        factors = [
            {"factor_id": "RF001", "severity": "high"},
            {"factor_id": "RF002", "dimension": "execution", "severity": "medium"},
        ]
        result = _dedup_risk_factors(factors)
        assert len(result) == 2

    def test_simulates_two_pass_accumulation(self):
        """Simulate operator.add merging factors from two analyst passes."""
        # First pass: 3 analysts produce 9 factors
        pass1 = [
            {"factor_id": f"IND{i:03d}", "dimension": dim, "severity": "medium"}
            for i, dim in enumerate(["market_timing", "policy_dependency"], 1)
        ] + [
            {"factor_id": f"COM{i:03d}", "dimension": dim, "severity": "high"}
            for i, dim in enumerate(["capital_allocation", "narrative_consistency", "execution", "product_portfolio"], 1)
        ] + [
            {"factor_id": f"PEER{i:03d}", "dimension": dim, "severity": "medium"}
            for i, dim in enumerate(["competitive_pressure", "regional_mismatch", "technology_capability"], 1)
        ]

        # Second pass (after adversarial reanalyze): analysts produce another 9
        pass2 = [
            {"factor_id": f"IND{i:03d}", "dimension": dim, "severity": "high"}
            for i, dim in enumerate(["market_timing", "policy_dependency"], 10)
        ] + [
            {"factor_id": f"COM{i:03d}", "dimension": dim, "severity": "critical"}
            for i, dim in enumerate(["capital_allocation", "narrative_consistency", "execution", "product_portfolio"], 10)
        ] + [
            {"factor_id": f"PEER{i:03d}", "dimension": dim, "severity": "high"}
            for i, dim in enumerate(["competitive_pressure", "regional_mismatch", "technology_capability"], 10)
        ]

        # operator.add accumulates both passes
        accumulated = pass1 + pass2
        assert len(accumulated) == 18

        # Dedup should keep only the 9 from pass2 (latest)
        result = _dedup_risk_factors(accumulated)
        assert len(result) == 9
        # All should be from pass2 (higher severity)
        for rf in result:
            assert rf["severity"] in ("high", "critical")


# ── Evidence ID Numbering ──


class TestEvidenceIDNumbering:
    """Test that evidence IDs don't collide across quality gate loops."""

    def test_first_pass_starts_at_1(self):
        existing_evidence: list[dict] = []
        new_items = [{"claim_text": f"claim {i}"} for i in range(5)]

        existing_count = len(existing_evidence)
        for i, item in enumerate(new_items, existing_count + 1):
            item["evidence_id"] = f"E{i:03d}"

        assert new_items[0]["evidence_id"] == "E001"
        assert new_items[4]["evidence_id"] == "E005"

    def test_second_pass_continues_numbering(self):
        existing_evidence = [
            {"evidence_id": "E001"},
            {"evidence_id": "E002"},
            {"evidence_id": "E003"},
        ]
        new_items = [{"claim_text": f"claim {i}"} for i in range(4)]

        existing_count = len(existing_evidence)
        for i, item in enumerate(new_items, existing_count + 1):
            item["evidence_id"] = f"E{i:03d}"

        assert new_items[0]["evidence_id"] == "E004"
        assert new_items[3]["evidence_id"] == "E007"

    def test_no_id_collisions_across_three_passes(self):
        """Simulate 3 quality gate loops generating evidence."""
        all_ids: set[str] = set()

        # Pass 1: 10 items
        existing_count = 0
        for i in range(1, 11):
            eid = f"E{existing_count + i:03d}"
            assert eid not in all_ids, f"Collision: {eid}"
            all_ids.add(eid)

        # Pass 2: 8 items
        existing_count = 10
        for i in range(1, 9):
            eid = f"E{existing_count + i:03d}"
            assert eid not in all_ids, f"Collision: {eid}"
            all_ids.add(eid)

        # Pass 3: 5 items
        existing_count = 18
        for i in range(1, 6):
            eid = f"E{existing_count + i:03d}"
            assert eid not in all_ids, f"Collision: {eid}"
            all_ids.add(eid)

        assert len(all_ids) == 23
        assert "E001" in all_ids
        assert "E023" in all_ids
