"""Tests for top-level claim-citation enforcement (L1.4-C)."""

from __future__ import annotations

import pytest

from sfewa.tools.citation_check import (
    ClaimCitationError,
    assert_claim_citations,
    citation_summary,
    validate_top_level_claims,
)


def _evidence_item(eid: str, **kw) -> dict:
    base = {
        "evidence_id": eid,
        "claim_text": "...",
        "claim_type": "financial_metric",
        "source_url": f"https://example.com/{eid}",
        "source_title": f"Article {eid}",
        "published_at": "2024-06-01",
        "stance": "supports_risk",
    }
    base.update(kw)
    return base


def _factor(fid: str, *, supporting: list[str]) -> dict:
    return {
        "factor_id": fid,
        "dimension": fid.lower(),
        "severity": "medium",
        "supporting_evidence": supporting,
    }


# ── Happy path ──


def test_clean_factors_pass():
    evidence = [_evidence_item("E001"), _evidence_item("E002")]
    factors = [
        _factor("IND001", supporting=["E001"]),
        _factor("COM001", supporting=["E001", "E002"]),
    ]
    assert validate_top_level_claims(factors, evidence) == []
    assert_claim_citations(factors, evidence)  # must not raise


def test_no_factors_no_violations():
    """Empty risk_factors is not a citation violation (separate concern)."""
    assert validate_top_level_claims([], []) == []
    assert_claim_citations([], [])


# ── Failure modes ──


def test_phantom_citation_raises():
    """Cited evidence_id not in evidence base."""
    evidence = [_evidence_item("E001")]
    factors = [_factor("IND001", supporting=["E999"])]  # phantom
    violations = validate_top_level_claims(factors, evidence)
    assert len(violations) == 1
    assert "phantom" in violations[0]
    with pytest.raises(ClaimCitationError):
        assert_claim_citations(factors, evidence)


def test_empty_supporting_evidence_raises():
    evidence = [_evidence_item("E001")]
    factors = [_factor("IND001", supporting=[])]
    violations = validate_top_level_claims(factors, evidence)
    assert len(violations) == 1
    assert "empty" in violations[0]
    with pytest.raises(ClaimCitationError):
        assert_claim_citations(factors, evidence)


def test_evidence_with_no_doc_reference_fails():
    """An evidence item with no source_url/doc_id/title-and-date is unusable."""
    bad = {
        "evidence_id": "E001",
        "claim_text": "x",
        "claim_type": "financial_metric",
        # no source_url, no doc_id, no source_title
    }
    factors = [_factor("IND001", supporting=["E001"])]
    violations = validate_top_level_claims(factors, [bad])
    assert len(violations) == 1
    assert "no_doc_ref" in violations[0]
    with pytest.raises(ClaimCitationError):
        assert_claim_citations(factors, [bad])


def test_evidence_with_doc_id_passes():
    """FilingProvider-native EvidenceChunk style citation works."""
    e = {
        "evidence_id": "E001",
        "doc_id": "edinet:S100UOAW",
        "claim_text": "x",
        "claim_type": "financial_metric",
    }
    factors = [_factor("IND001", supporting=["E001"])]
    assert validate_top_level_claims(factors, [e]) == []


def test_evidence_with_title_and_date_passes():
    """Filing-style citation (title + published_at) is acceptable."""
    e = {
        "evidence_id": "E001",
        "claim_text": "x",
        "claim_type": "financial_metric",
        "source_title": "Honda 有価証券報告書 第100期",
        "published_at": "2024-06-19",
    }
    factors = [_factor("IND001", supporting=["E001"])]
    assert validate_top_level_claims(factors, [e]) == []


def test_partial_resolve_is_acceptable():
    """If at least one cited id resolves, the factor passes."""
    evidence = [_evidence_item("E001")]
    factors = [_factor("IND001", supporting=["E999", "E001", "E998"])]
    # 2 phantom, 1 valid → passes
    assert validate_top_level_claims(factors, evidence) == []


def test_multi_factor_violations_all_reported():
    evidence = [_evidence_item("E001")]
    factors = [
        _factor("IND001", supporting=["E001"]),     # OK
        _factor("COM001", supporting=["E999"]),     # phantom
        _factor("PEER001", supporting=[]),          # empty
    ]
    violations = validate_top_level_claims(factors, evidence)
    assert len(violations) == 2


# ── Summary ──


def test_citation_summary_counts():
    evidence = [_evidence_item("E001"), _evidence_item("E002")]
    factors = [
        _factor("IND001", supporting=["E001"]),
        _factor("COM001", supporting=["E001", "E002"]),
        _factor("PEER001", supporting=["E999"]),  # phantom — won't count toward resolved
    ]
    s = citation_summary(factors, evidence)
    assert s["total_factors"] == 3
    assert s["factors_with_resolved_citation"] == 2  # IND001 + COM001
    assert s["total_citations_made"] == 4
    assert s["total_citations_resolved"] == 3  # E001, E001, E002 (the phantom doesn't count)
