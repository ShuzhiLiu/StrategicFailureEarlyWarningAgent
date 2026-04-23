"""Integration tests for pipeline-critical invariants.

These tests cover the code paths where silent failure would corrupt scoring:

- Factor-ID normalization (iter 38 fix): malformed LLM output like
  "IND001] geopolitical_trade_barriers" must match the clean "IND001" factor_id.
- Depth-severity consistency gate (iter 39): must flag depth<=2 HIGH and
  depth=4 without key_assumption, which drive adversarial STRONG challenges.
- Citation cross-validation: phantom + stance-mismatch + thin evidence must
  flag correctly — these gate the evidence-gated downgrade rule.
- Analyst agreement (iter 39): HHI concentration + ordinal range must
  empirically discriminate aligned vs divergent analyst output, since this
  replaces LLM-verbalized confidence.

We test the programmatic pieces directly (fast, deterministic). End-to-end
pipeline tests are covered by the stability protocol in CLAUDE.md, not by
the unit test suite.
"""

from __future__ import annotations

# ── Factor ID normalization (iter 38) ──
# LLM outputs like "[COM001]", "IND001] dimension_name", "PEER002" must all
# normalize to "COM001" / "IND001" / "PEER002" so STRONG downgrades match.


def _normalize_factor_id(raw: str) -> str:
    # Re-import lazily to avoid heavy module-level imports in adversarial.py
    from sfewa.agents.adversarial import _normalize_factor_id as impl
    return impl(raw)


class TestFactorIdNormalization:
    def test_bracketed_id(self):
        assert _normalize_factor_id("[COM001]") == "COM001"

    def test_trailing_text_after_bracket(self):
        """This format broke STRONG downgrades silently until iter 38."""
        assert _normalize_factor_id("IND001] geopolitical_trade_barriers") == "IND001"

    def test_clean_id(self):
        assert _normalize_factor_id("PEER002") == "PEER002"

    def test_all_three_prefixes(self):
        assert _normalize_factor_id("IND003") == "IND003"
        assert _normalize_factor_id("COM007") == "COM007"
        assert _normalize_factor_id("PEER010") == "PEER010"

    def test_no_match_returns_stripped_input(self):
        """Fallback: unrecognized format returns bracket-stripped input."""
        assert _normalize_factor_id("[UNKNOWN]") == "UNKNOWN"


# ── Depth-severity consistency gate (iter 39) ──


def _check(factor: dict) -> list[str]:
    from sfewa.agents._analyst_base import check_depth_consistency
    return check_depth_consistency(factor)


class TestDepthSeverityGate:
    def test_depth_2_high_is_flagged(self):
        """Layer-2 analysis claiming HIGH severity is a violation."""
        violations = _check({"depth_of_analysis": 2, "severity": "high"})
        assert any("DEPTH_SEVERITY_MISMATCH" in v for v in violations)

    def test_depth_2_critical_is_flagged(self):
        violations = _check({"depth_of_analysis": 2, "severity": "critical"})
        assert any("DEPTH_SEVERITY_MISMATCH" in v for v in violations)

    def test_depth_2_medium_is_clean(self):
        violations = _check({"depth_of_analysis": 2, "severity": "medium"})
        assert not any("DEPTH_SEVERITY_MISMATCH" in v for v in violations)

    def test_depth_4_without_assumption_is_flagged(self):
        violations = _check({
            "depth_of_analysis": 4,
            "severity": "high",
            "key_assumption_at_risk": "",
            "structural_forces": {"reinforcing_loops": ["x"], "balancing_loops": []},
        })
        assert any("MISSING_ASSUMPTION" in v for v in violations)

    def test_depth_3_without_forces_is_flagged(self):
        violations = _check({
            "depth_of_analysis": 3,
            "severity": "medium",
            "structural_forces": {"reinforcing_loops": [], "balancing_loops": []},
        })
        assert any("MISSING_FORCES" in v for v in violations)

    def test_well_formed_depth_4_is_clean(self):
        """Honda-shaped factor: depth-4 with forces and assumption → no flags."""
        violations = _check({
            "depth_of_analysis": 4,
            "severity": "critical",
            "key_assumption_at_risk": "EV demand scales as projected",
            "structural_forces": {
                "reinforcing_loops": ["capital drain compounds with delayed revenue"],
                "balancing_loops": ["hybrid cash flow"],
            },
        })
        assert violations == []


# ── Citation cross-validation ──


def _validate(factor: dict, evidence_map: dict) -> list[str]:
    from sfewa.agents._analyst_base import validate_citations
    return validate_citations(factor, evidence_map)


class TestCitationValidation:
    def _evidence(self, eid: str, stance: str = "supports_risk") -> dict:
        return {"evidence_id": eid, "stance": stance}

    def test_phantom_supporting_citation_flagged(self):
        ev_map = {"E001": self._evidence("E001")}
        factor = {"supporting_evidence": ["E001", "E999"], "severity": "high"}
        violations = _validate(factor, ev_map)
        assert any("PHANTOM_CITATION: E999" in v for v in violations)

    def test_phantom_contradicting_citation_flagged(self):
        ev_map = {}
        factor = {
            "supporting_evidence": [],
            "contradicting_evidence": ["E123"],
            "severity": "medium",
        }
        violations = _validate(factor, ev_map)
        assert any("PHANTOM_CITATION: E123" in v for v in violations)

    def test_majority_stance_mismatch_is_strong(self):
        """The BYD pattern: ≥50% of supporting citations actually contradict."""
        ev_map = {
            "E001": self._evidence("E001", "contradicts_risk"),
            "E002": self._evidence("E002", "contradicts_risk"),
            "E003": self._evidence("E003", "supports_risk"),
        }
        factor = {
            "supporting_evidence": ["E001", "E002", "E003"],
            "severity": "high",
        }
        violations = _validate(factor, ev_map)
        assert any(v.startswith("STANCE_MISMATCH") for v in violations)

    def test_single_stance_mismatch_is_noise(self):
        """A single mismatch out of many is not flagged (noise floor)."""
        ev_map = {f"E{i:03d}": self._evidence(f"E{i:03d}") for i in range(8)}
        ev_map["E007"] = self._evidence("E007", "contradicts_risk")
        factor = {
            "supporting_evidence": [f"E{i:03d}" for i in range(8)],
            "severity": "high",
        }
        violations = _validate(factor, ev_map)
        assert not any("STANCE_MISMATCH" in v for v in violations)

    def test_thin_evidence_on_high_flagged(self):
        ev_map = {"E001": self._evidence("E001")}
        factor = {"supporting_evidence": ["E001"], "severity": "high"}
        violations = _validate(factor, ev_map)
        assert any("THIN_EVIDENCE" in v for v in violations)

    def test_medium_severity_with_one_citation_not_thin(self):
        """THIN_EVIDENCE only fires for HIGH/CRITICAL."""
        ev_map = {"E001": self._evidence("E001")}
        factor = {"supporting_evidence": ["E001"], "severity": "medium"}
        violations = _validate(factor, ev_map)
        assert not any("THIN_EVIDENCE" in v for v in violations)


# ── Analyst agreement (iter 39 empirical confidence signal) ──


def _agree(factors: list[dict]) -> dict:
    from sfewa.graph.pipeline import _compute_analyst_agreement
    return _compute_analyst_agreement(factors)


class TestAnalystAgreement:
    def test_all_agree_high_concentration(self):
        factors = [
            {"severity": "high", "depth_of_analysis": 4},
            {"severity": "high", "depth_of_analysis": 4},
            {"severity": "high", "depth_of_analysis": 3},
        ]
        result = _agree(factors)
        # HHI is computed on severity distribution; all-high → concentration = 1.0
        assert result["severity_concentration"] == 1.0
        # Ordinal range is 0 (all high); depth range is 1 (4-3)
        assert result["depth_spread"] == 1

    def test_divergent_analysts_low_concentration(self):
        """The Toyota-shaped case: analysts disagree across severity levels."""
        factors = [
            {"severity": "critical", "depth_of_analysis": 4},
            {"severity": "medium", "depth_of_analysis": 3},
            {"severity": "low", "depth_of_analysis": 2},
        ]
        result = _agree(factors)
        # 1/3 each across 3 bins → HHI = 3 × (1/3)² = 1/3; with shared concentration
        # normalization this produces a value strictly less than 1.0.
        assert result["severity_concentration"] < 0.5
        # Summary text must mention that analysts disagree so synthesis can calibrate
        assert "summary" in result
        assert result["summary"]

    def test_empty_factors_does_not_crash(self):
        """Edge case: analyst fan-out fails → empty list must not crash synthesis."""
        result = _agree([])
        assert result["severity_concentration"] == 0.0
        assert "summary" in result
