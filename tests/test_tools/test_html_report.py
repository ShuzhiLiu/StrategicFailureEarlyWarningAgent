"""Tests for the L1.7 static HTML report generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sfewa.tools.html_report import generate_report, render_report


# ── Fixtures ──


def _retrospective_summary(**kw):
    base = {
        "case_id": "honda_ev_2025",
        "case_type": "retrospective",
        "company": "Honda Motor Co., Ltd.",
        "strategy_theme": "EV electrification strategy",
        "cutoff_date": "2025-05-19",
        "risk_score": 78,
        "overall_risk_level": "high",
        "overall_confidence": 0.7,
        "evidence_count": 45,
        "risk_factor_count": 10,
        "challenge_count": 8,
        "adversarial_pass_count": 1,
        "manifest": {"total": 35, "kept": 33, "rejected_post_cutoff": 2},
        "citations": {
            "total_factors": 10,
            "factors_with_resolved_citation": 10,
            "total_citations_made": 35,
            "total_citations_resolved": 33,
        },
    }
    base.update(kw)
    return base


def _factor(fid: str, **kw):
    base = {
        "factor_id": fid,
        "dimension": "capital_allocation",
        "title": "Capital strain",
        "severity": "high",
        "depth_of_analysis": 4,
        "claim": "Honda EV losses exceed 4.48B yen",
        "supporting_evidence": ["E001", "E002"],
    }
    base.update(kw)
    return base


def _evidence(eid: str, **kw):
    base = {
        "evidence_id": eid,
        "claim_text": f"Sample claim {eid}",
        "stance": "supports_risk",
        "source_url": f"https://example.com/{eid}",
        "source_title": f"Source {eid}",
        "published_at": "2024-06-15",
    }
    base.update(kw)
    return base


def _provenance(**kw):
    base = {
        "model": {"model_id": "Qwen/Qwen3.6-27B", "provider": "vllm"},
        "git": {"commit": "abc123def456", "branch": "main", "dirty": False},
        "case_config": {"path": "configs/cases/honda_ev_pre_reset.yaml",
                        "sha256": "0" * 64},
        "truth_config": {"path": None, "sha256": None},
        "audit_meta": {"verifier_corpus": "open_web", "jurisdiction": "JP"},
        "cutoff_date": "2025-05-19",
        "tokens": {"prompt": 1000, "completion": 500, "total": 1500},
    }
    base.update(kw)
    return base


def _challenge(severity="strong"):
    return {
        "challenge_id": "AC001",
        "target_factor_id": "IND001",
        "severity": severity,
        "challenge_text": "...",
    }


# ── Forward banner ──


def test_forward_case_shows_banner():
    summary = _retrospective_summary(case_type="forward")
    html_text = render_report(
        summary=summary,
        factors=[],
        evidence=[],
        challenges=[],
        manifest=[],
        provenance=_provenance(),
        memo=None,
    )
    assert "Forward surveillance case" in html_text
    assert "Not a retrospective validation" in html_text


def test_retrospective_case_has_no_forward_banner():
    summary = _retrospective_summary(case_type="retrospective")
    html_text = render_report(
        summary=summary, factors=[], evidence=[], challenges=[],
        manifest=[], provenance=_provenance(), memo=None,
    )
    assert "Forward surveillance case" not in html_text


# ── Three pillars present above the fold ──


def test_evidence_trace_pillar_present():
    summary = _retrospective_summary()
    html_text = render_report(
        summary=summary, factors=[_factor("F1")], evidence=[_evidence("E001")],
        challenges=[], manifest=[], provenance=_provenance(), memo=None,
    )
    assert "Evidence trace" in html_text
    # Citation summary numbers surfaced
    assert "10" in html_text  # total_factors / factors_with_resolved_citation
    assert "33" in html_text  # total_citations_resolved


def test_provenance_pillar_present():
    html_text = render_report(
        summary=_retrospective_summary(), factors=[], evidence=[],
        challenges=[], manifest=[], provenance=_provenance(), memo=None,
    )
    assert "Provenance" in html_text
    assert "Qwen/Qwen3.6-27B" in html_text
    assert "abc123def456" in html_text  # commit hash


def test_controls_pillar_shows_temporal_gate_counts():
    summary = _retrospective_summary()
    html_text = render_report(
        summary=summary, factors=[], evidence=[], challenges=[],
        manifest=[], provenance=_provenance(), memo=None,
    )
    assert "Controls applied" in html_text
    assert "33 kept" in html_text
    assert "2 rejected post-cutoff" in html_text


def test_controls_pillar_shows_verifier_corpus():
    html_text = render_report(
        summary=_retrospective_summary(),
        factors=[], evidence=[], challenges=[], manifest=[],
        provenance=_provenance(audit_meta={"verifier_corpus": "allowed_sources_only"}),
        memo=None,
    )
    assert "allowed_sources_only" in html_text


def test_controls_pillar_shows_strong_count():
    challenges = [_challenge("strong"), _challenge("strong"), _challenge("moderate")]
    html_text = render_report(
        summary=_retrospective_summary(),
        factors=[], evidence=[], challenges=challenges, manifest=[],
        provenance=_provenance(), memo=None,
    )
    assert "2 STRONG" in html_text
    assert "1 MODERATE" in html_text


# ── Evidence linking (claim → citation) ──


def test_factor_citations_link_to_evidence_anchors():
    factors = [_factor("F1", supporting_evidence=["E001"])]
    evidence = [_evidence("E001")]
    html_text = render_report(
        summary=_retrospective_summary(), factors=factors, evidence=evidence,
        challenges=[], manifest=[], provenance=_provenance(), memo=None,
    )
    # Claim-side anchor
    assert "<a href='#ev-E001'>E001</a>" in html_text
    # Evidence-side target
    assert "id='ev-E001'" in html_text


def test_unresolved_citations_dont_render_links():
    factors = [_factor("F1", supporting_evidence=["E999"])]  # phantom
    evidence = [_evidence("E001")]
    html_text = render_report(
        summary=_retrospective_summary(), factors=factors, evidence=evidence,
        challenges=[], manifest=[], provenance=_provenance(), memo=None,
    )
    assert "no resolved citations" in html_text
    assert "<a href='#ev-E999'>" not in html_text


# ── Verdict header ──


def test_score_and_level_in_header():
    summary = _retrospective_summary(risk_score=88, overall_risk_level="critical")
    html_text = render_report(
        summary=summary, factors=[], evidence=[], challenges=[],
        manifest=[], provenance=_provenance(), memo=None,
    )
    assert ">88<" in html_text  # score
    assert ">critical<" in html_text


# ── Manifest table ──


def test_manifest_table_renders_kept_and_rejected():
    manifest = [
        {"source": "edinet", "title": "Annual report",
         "release_time": "2024-06-19", "cutoff_decision": "kept"},
        {"source": "duckduckgo", "title": "Post-cutoff news",
         "release_time": "2025-08-01", "cutoff_decision": "rejected_post_cutoff"},
    ]
    html_text = render_report(
        summary=_retrospective_summary(), factors=[], evidence=[],
        challenges=[], manifest=manifest, provenance=_provenance(), memo=None,
    )
    assert "Annual report" in html_text
    assert "Post-cutoff news" in html_text
    assert "dec-kept" in html_text
    assert "dec-rejected" in html_text


# ── Generator wraps file I/O ──


def test_generate_report_writes_html_file(tmp_path):
    """generate_report() reads artifact files from a run dir."""
    run = tmp_path / "run1"
    run.mkdir()
    (run / "run_summary.json").write_text(json.dumps(_retrospective_summary()))
    (run / "risk_factors.json").write_text(json.dumps([_factor("F1")]))
    (run / "evidence.json").write_text(json.dumps([_evidence("E001"), _evidence("E002")]))
    (run / "challenges.json").write_text(json.dumps([_challenge()]))
    (run / "source_manifest.json").write_text(json.dumps([]))
    (run / "provenance.json").write_text(json.dumps(_provenance()))
    (run / "risk_memo.md").write_text("Honda is in trouble.")
    out = generate_report(run)
    assert out == run / "report.html"
    assert out.exists()
    text = out.read_text()
    assert "Honda Motor Co., Ltd." in text
    assert "Honda is in trouble." in text


def test_generate_report_handles_missing_optional_artifacts(tmp_path):
    """Run dirs without memo or challenges still produce a report."""
    run = tmp_path / "run_minimal"
    run.mkdir()
    (run / "run_summary.json").write_text(json.dumps(_retrospective_summary()))
    out = generate_report(run)
    assert out.exists()


def test_html_escapes_user_content():
    """No raw HTML/JS injection through company name or claim text."""
    summary = _retrospective_summary(company="<script>alert('x')</script> Co.")
    factors = [_factor("F1", claim="Claim <img onerror='x' src=y>")]
    html_text = render_report(
        summary=summary, factors=factors, evidence=[],
        challenges=[], manifest=[], provenance=_provenance(), memo=None,
    )
    assert "<script>alert" not in html_text
    assert "&lt;script&gt;" in html_text
    assert "<img onerror" not in html_text
