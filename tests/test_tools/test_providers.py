"""Provider adapter tests (EDINET + CNINFO).

These tests use the FilingProvider Protocol's runtime check and exercise
extract() + emit_manifest_entry() against cached fixture PDFs in
data/corpus/. Live network is disabled (live=False); search()/download()
are tested separately with mocked HTTP elsewhere.

Per L1 acceptance gate, each provider's fixture set must include at
least one post-cutoff doc and prove it lands as `rejected_post_cutoff`.
That assertion lives in `test_post_cutoff_doc_is_rejected_for_*` below
and uses synthetic FilingRefs (no PDF needed for cutoff decision).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sfewa.tools.filing_provider import (
    FilingProvider,
    FilingRef,
    decide_cutoff,
)
from sfewa.tools.providers import CninfoProvider, EdinetProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "data" / "corpus"


# ── Protocol satisfaction ──


def test_edinet_provider_satisfies_protocol():
    assert isinstance(EdinetProvider(live=False), FilingProvider)


def test_cninfo_provider_satisfies_protocol():
    assert isinstance(CninfoProvider(live=False), FilingProvider)


def test_provider_source_identifiers():
    assert EdinetProvider(live=False).source == "edinet"
    assert CninfoProvider(live=False).source == "cninfo"


# ── search() with live=False is empty (no network) ──


def test_edinet_search_returns_empty_when_offline():
    p = EdinetProvider(live=False)
    refs = p.search(
        ticker=None, issuer_name="Honda", from_date=None,
        to_date="2025-05-19", doc_types=None, language=None,
    )
    assert refs == []


def test_cninfo_search_returns_empty_when_offline():
    p = CninfoProvider(live=False)
    refs = p.search(
        ticker=None, issuer_name="BYD", from_date=None,
        to_date="2025-05-19", doc_types=None, language=None,
    )
    assert refs == []


def test_offline_download_with_no_cache_raises():
    p = EdinetProvider(live=False, cache_dir=Path("/tmp/_nonexistent_dir"))
    ref = FilingRef(
        source="edinet", doc_id="DOES_NOT_EXIST", ticker=None, issuer_id=None,
        issuer_name="X", title="t", doc_type="annual_report",
        language="ja", release_time="2024-01-01",
    )
    with pytest.raises(FileNotFoundError):
        p.download(ref)


# ── Cutoff gate fixture-level tests (provider-level audit invariant) ──


def test_post_cutoff_doc_is_rejected_for_edinet():
    """Required fixture-level assertion: a post-cutoff EDINET filing must
    be classified as `rejected_post_cutoff`. Proves the cutoff gate exists."""
    p = EdinetProvider(live=False)
    ref = FilingRef(
        source="edinet", doc_id="POST_CUTOFF",
        ticker="72670", issuer_id="E02529",
        issuer_name="Honda Motor Co., Ltd.",
        title="有価証券報告書 (post-cutoff)",
        doc_type="annual_report",
        language="ja",
        release_time="2025-06-19",  # 1 month AFTER 2025-05-19 cutoff
    )
    decision = decide_cutoff(ref, cutoff_date="2025-05-19")
    assert decision == "rejected_post_cutoff"
    entry = p.emit_manifest_entry(ref, decision)
    assert entry.cutoff_decision == "rejected_post_cutoff"
    assert entry.source == "edinet"


def test_post_cutoff_doc_is_rejected_for_cninfo():
    """Required fixture-level assertion for CNINFO."""
    p = CninfoProvider(live=False)
    ref = FilingRef(
        source="cninfo", doc_id="POST_CUTOFF",
        ticker="002594", issuer_id="ORG1",
        issuer_name="比亚迪股份有限公司",
        title="2025 中报 (post-cutoff)",
        doc_type="semiannual_report",
        language="zh",
        release_time="2025-08-30",  # AFTER 2025-05-19 cutoff
    )
    decision = decide_cutoff(ref, cutoff_date="2025-05-19")
    assert decision == "rejected_post_cutoff"
    entry = p.emit_manifest_entry(ref, decision)
    assert entry.cutoff_decision == "rejected_post_cutoff"
    assert entry.source == "cninfo"


def test_pre_cutoff_doc_is_kept_for_edinet():
    p = EdinetProvider(live=False)
    ref = FilingRef(
        source="edinet", doc_id="OK",
        ticker="72670", issuer_id="E02529",
        issuer_name="Honda Motor Co., Ltd.",
        title="有価証券報告書 (FY2023)",
        doc_type="annual_report",
        language="ja",
        release_time="2024-06-19",
    )
    decision = decide_cutoff(ref, cutoff_date="2025-05-19")
    assert decision == "kept"
    assert p.emit_manifest_entry(ref, decision).cutoff_decision == "kept"


# ── Extract on cached fixtures (skip if not present) ──


@pytest.mark.skipif(
    not (CORPUS / "honda" / "edinet" / "honda_semiannual_report_h1_fy2024.pdf").exists(),
    reason="Honda EDINET fixtures not cached",
)
def test_edinet_extract_on_cached_honda_semiannual():
    """Round-trip a real cached Honda semi-annual through the EDINET adapter."""
    artifact = CORPUS / "honda" / "edinet" / "honda_semiannual_report_h1_fy2024.pdf"
    ref = FilingRef(
        source="edinet", doc_id="S100UOAW",
        ticker="72670", issuer_id="E02529",
        issuer_name="本田技研工業株式会社",
        title="半期報告書 第101期",
        doc_type="semiannual_report",
        language="ja",
        release_time="2024-11-08",
    )
    p = EdinetProvider(live=False, company_key="honda")
    doc = p.extract(artifact, ref)
    # Must produce some text and chunks
    assert len(doc.text) > 100
    assert len(doc.chunks) >= 1
    # Every chunk must have valid global offsets and round-trip the text
    for c in doc.chunks:
        assert c.doc_id == ref.doc_id
        assert c.global_char_start >= 0
        assert c.global_char_end > c.global_char_start
        assert doc.text[c.global_char_start : c.global_char_end] == c.text
        # page must be set (we have page metadata for PDFs)
        assert c.page is not None and c.page >= 1
        # evidence_id format
        assert c.evidence_id.startswith("edinet:S100UOAW#c")


@pytest.mark.skipif(
    not (CORPUS / "byd" / "cninfo" / "byd_semiannual_report_2024-08-29.pdf").exists(),
    reason="BYD CNINFO fixtures not cached",
)
def test_cninfo_extract_on_cached_byd_semiannual():
    """Round-trip a real cached BYD semi-annual through the CNINFO adapter."""
    artifact = CORPUS / "byd" / "cninfo" / "byd_semiannual_report_2024-08-29.pdf"
    ref = FilingRef(
        source="cninfo", doc_id="byd_h1_2024",
        ticker="002594", issuer_id="ORG1",
        issuer_name="比亚迪股份有限公司",
        title="2024 半年度报告",
        doc_type="semiannual_report",
        language="zh",
        release_time="2024-08-29",
    )
    p = CninfoProvider(live=False, company_key="byd")
    doc = p.extract(artifact, ref)
    assert len(doc.text) > 100
    assert len(doc.chunks) >= 1
    for c in doc.chunks:
        assert c.doc_id == ref.doc_id
        assert doc.text[c.global_char_start : c.global_char_end] == c.text
        assert c.page is not None
