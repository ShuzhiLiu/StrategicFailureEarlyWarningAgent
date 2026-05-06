"""Tests for the FilingProvider Protocol and supporting helpers (L1.1).

No live network. The Protocol's behavior is exercised through a
synthetic FakeProvider; chunking and cutoff helpers are tested with
hand-constructed inputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sfewa.tools.filing_provider import (
    EvidenceChunk,
    ExtractedDocument,
    FilingProvider,
    FilingRef,
    ManifestEntry,
    chunk_with_offsets,
    decide_cutoff,
)


# ── Helpers / fixtures ──


def _make_ref(
    *,
    release_time: str = "2024-06-15",
    doc_type: str = "annual_report",
    language: str = "ja",
    source: str = "fake",
    doc_id: str = "doc1",
) -> FilingRef:
    return FilingRef(
        source=source,
        doc_id=doc_id,
        ticker="0000",
        issuer_id="ISSUER0",
        issuer_name="Fake Issuer Co.",
        title="Annual Report",
        doc_type=doc_type,
        language=language,
        release_time=release_time,
        url=None,
    )


# ── decide_cutoff ──


def test_decide_cutoff_kept_when_before_cutoff():
    ref = _make_ref(release_time="2024-12-30")
    assert decide_cutoff(ref, cutoff_date="2024-12-31") == "kept"


def test_decide_cutoff_kept_when_equals_cutoff():
    """Cutoff is inclusive — release on the cutoff date is kept."""
    ref = _make_ref(release_time="2024-12-31")
    assert decide_cutoff(ref, cutoff_date="2024-12-31") == "kept"


def test_decide_cutoff_rejected_post_cutoff():
    ref = _make_ref(release_time="2025-01-01")
    assert decide_cutoff(ref, cutoff_date="2024-12-31") == "rejected_post_cutoff"


def test_decide_cutoff_rejected_post_cutoff_with_datetime():
    ref = _make_ref(release_time="2025-01-01T08:30:00+08:00")
    assert decide_cutoff(ref, cutoff_date="2024-12-31") == "rejected_post_cutoff"


def test_decide_cutoff_rejected_doc_type():
    ref = _make_ref(doc_type="quarterly_report")
    assert (
        decide_cutoff(
            ref,
            cutoff_date="2025-01-01",
            allowed_doc_types=["annual_report", "interim_report"],
        )
        == "rejected_doc_type"
    )


def test_decide_cutoff_rejected_language():
    ref = _make_ref(language="ko")
    assert (
        decide_cutoff(
            ref,
            cutoff_date="2025-01-01",
            allowed_languages=["en", "ja", "zh"],
        )
        == "rejected_language"
    )


def test_decide_cutoff_precedence_post_cutoff_beats_doc_type():
    """A post-cutoff doc with disallowed type is still rejected_post_cutoff
    (post-cutoff is the most important audit signal)."""
    ref = _make_ref(release_time="2025-02-01", doc_type="quarterly_report")
    assert (
        decide_cutoff(
            ref,
            cutoff_date="2025-01-01",
            allowed_doc_types=["annual_report"],
        )
        == "rejected_post_cutoff"
    )


def test_decide_cutoff_no_filters():
    """Without doc_type/language filters, anything pre-cutoff is kept."""
    ref = _make_ref()
    assert decide_cutoff(ref, cutoff_date="2025-12-31") == "kept"


# ── chunk_with_offsets ──


def test_chunk_empty_input():
    text, chunks = chunk_with_offsets([], doc_id="d")
    assert text == ""
    assert chunks == []


def test_chunk_single_page_single_chunk():
    pages = ["hello world"]
    text, chunks = chunk_with_offsets(pages, doc_id="d", chunk_size=100)
    assert text == "hello world"
    assert len(chunks) == 1
    c = chunks[0]
    assert c.text == "hello world"
    assert c.global_char_start == 0
    assert c.global_char_end == 11
    assert c.page == 1
    assert c.page_char_start == 0
    assert c.page_char_end == 11
    assert c.doc_id == "d"
    assert c.evidence_id == "d#c000"


def test_chunk_single_page_multiple_chunks():
    pages = ["a" * 250]
    text, chunks = chunk_with_offsets(pages, doc_id="d", chunk_size=100)
    assert len(text) == 250
    assert len(chunks) == 3
    # Chunk 0: 0..100
    assert chunks[0].global_char_start == 0
    assert chunks[0].global_char_end == 100
    assert chunks[0].page == 1
    assert chunks[0].page_char_start == 0
    assert chunks[0].page_char_end == 100
    # Chunk 1: 100..200
    assert chunks[1].global_char_start == 100
    assert chunks[1].global_char_end == 200
    # Chunk 2: 200..250
    assert chunks[2].global_char_start == 200
    assert chunks[2].global_char_end == 250
    # All chunks reconstruct the text when concatenated
    assert "".join(c.text for c in chunks) == text


def test_chunk_multiple_pages_offsets_match_full_text():
    pages = ["first page", "second page longer", "third"]
    text, chunks = chunk_with_offsets(pages, doc_id="d", chunk_size=100)
    # full text is pages joined by "\n"
    assert text == "first page\nsecond page longer\nthird"
    # Single chunk because total < 100
    assert len(chunks) == 1
    c = chunks[0]
    assert c.global_char_start == 0
    assert c.global_char_end == len(text)
    # Round-trip: text[global_start:global_end] == chunk.text
    assert text[c.global_char_start : c.global_char_end] == c.text


def test_chunk_global_offsets_round_trip_through_full_text():
    pages = ["page one content " * 20, "page two content " * 20, "page three " * 20]
    text, chunks = chunk_with_offsets(pages, doc_id="d", chunk_size=80)
    # Every chunk's text must equal the slice of the full text at its
    # global offsets — this is the L1.4 invariant.
    for c in chunks:
        assert text[c.global_char_start : c.global_char_end] == c.text


def test_chunk_page_attribution_for_chunk_starting_in_each_page():
    pages = ["A" * 50, "B" * 50, "C" * 50]
    # Chunks of size 30 → boundaries at 0, 30, 60(spans p1->p2), 90(p2),
    # 120(spans p2->p3), 150(p3).
    text, chunks = chunk_with_offsets(pages, doc_id="d", chunk_size=30)
    # The full text length is 50 + 1 + 50 + 1 + 50 = 152
    assert len(text) == 152
    # First chunk starts on page 1
    assert chunks[0].page == 1
    assert chunks[0].page_char_start == 0
    # Some later chunk starts on page 2 — find it
    p2_chunk = next(c for c in chunks if 51 <= c.global_char_start < 102)
    assert p2_chunk.page == 2
    # p2's global start is 51 (50 chars + 1 newline). Chunk at global 60
    # has page_char_start = 60 - 51 = 9.
    if p2_chunk.global_char_start == 60:
        assert p2_chunk.page_char_start == 9


def test_chunk_overlap_works():
    pages = ["a" * 200]
    text, chunks = chunk_with_offsets(
        pages, doc_id="d", chunk_size=100, overlap=20
    )
    # step = 80, so chunk starts at 0, 80, 160
    assert [c.global_char_start for c in chunks] == [0, 80, 160]
    assert [c.global_char_end for c in chunks] == [100, 180, 200]


def test_chunk_preserves_source_page_numbers_when_pages_were_filtered():
    """When relevance-filtering a PDF, source page numbers are non-contiguous.

    chunk_with_offsets must use the provided page_numbers list so chunks
    point back to the original PDF page, not the filtered position.
    """
    pages = ["page 5 content " * 10, "page 17 content " * 10]
    page_numbers = [5, 17]
    text, chunks = chunk_with_offsets(
        pages, doc_id="d", chunk_size=80, page_numbers=page_numbers
    )
    # First chunk(s) should report page=5; later chunks page=17
    seen_pages = {c.page for c in chunks}
    assert seen_pages.issubset({5, 17})
    assert 5 in seen_pages
    assert 17 in seen_pages
    # Page-local offsets stay correct within their source page.
    for c in chunks:
        if c.page == 5:
            assert (c.page_char_start or 0) < len(pages[0])
        if c.page == 17:
            assert (c.page_char_start or 0) < len(pages[1])


def test_chunk_page_numbers_length_mismatch_raises():
    with pytest.raises(ValueError):
        chunk_with_offsets(["a", "b"], doc_id="d", page_numbers=[1])


def test_chunk_invalid_overlap_raises():
    with pytest.raises(ValueError):
        chunk_with_offsets(["abc"], doc_id="d", chunk_size=10, overlap=10)
    with pytest.raises(ValueError):
        chunk_with_offsets(["abc"], doc_id="d", chunk_size=0)


# ── ManifestEntry ──


def test_manifest_entry_to_dict_round_trips_decision():
    entry = ManifestEntry(
        ticker="0000",
        issuer_name="Fake Co.",
        title="Annual Report",
        doc_type="annual_report",
        language="ja",
        release_time="2024-06-15",
        url="https://example.com/doc.pdf",
        content_sha256="0" * 64,
        cutoff_decision="kept",
        source="fake",
    )
    d = entry.to_dict()
    assert d["cutoff_decision"] == "kept"
    assert d["source"] == "fake"
    assert d["ticker"] == "0000"


def test_manifest_entry_supports_all_decision_values():
    """Each decision string is accepted by the ManifestEntry constructor."""
    for decision in (
        "kept",
        "rejected_post_cutoff",
        "rejected_doc_type",
        "rejected_language",
    ):
        entry = ManifestEntry(
            ticker=None,
            issuer_name="X",
            title="Y",
            doc_type="annual_report",
            language="en",
            release_time="2024-01-01",
            url=None,
            content_sha256=None,
            cutoff_decision=decision,  # type: ignore[arg-type]
            source="fake",
        )
        assert entry.cutoff_decision == decision


# ── Protocol shape ──


class _FakeProvider:
    """Minimum FilingProvider implementation for Protocol shape testing."""

    source = "fake"

    def search(
        self,
        *,
        ticker,
        issuer_name,
        from_date,
        to_date,
        doc_types,
        language,
    ):
        return [_make_ref()]

    def download(self, ref: FilingRef) -> Path:
        return Path("/tmp/fake.pdf")

    def extract(self, artifact: Path, ref: FilingRef) -> ExtractedDocument:
        text, chunks = chunk_with_offsets(["fake page"], doc_id=ref.doc_id)
        return ExtractedDocument(ref=ref, text=text, chunks=chunks)

    def emit_manifest_entry(
        self,
        ref: FilingRef,
        decision,
        *,
        content_sha256=None,
    ) -> ManifestEntry:
        return ManifestEntry(
            ticker=ref.ticker,
            issuer_name=ref.issuer_name,
            title=ref.title,
            doc_type=ref.doc_type,
            language=ref.language,
            release_time=ref.release_time,
            url=ref.url,
            content_sha256=content_sha256,
            cutoff_decision=decision,
            source=self.source,
        )


def test_fake_provider_satisfies_protocol():
    """runtime_checkable Protocol works as a structural type test."""
    p = _FakeProvider()
    assert isinstance(p, FilingProvider)


def test_fake_provider_round_trips_a_filing():
    """End-to-end provider lifecycle with a synthetic provider."""
    p = _FakeProvider()
    refs = p.search(
        ticker="0000",
        issuer_name=None,
        from_date=None,
        to_date="2025-01-01",
        doc_types=None,
        language=None,
    )
    assert len(refs) == 1
    ref = refs[0]
    artifact = p.download(ref)
    doc = p.extract(artifact, ref)
    assert doc.ref == ref
    assert doc.text == "fake page"
    assert len(doc.chunks) == 1
    assert doc.chunks[0].evidence_id == f"{ref.doc_id}#c000"

    entry = p.emit_manifest_entry(ref, "kept", content_sha256="x" * 64)
    assert entry.cutoff_decision == "kept"
    assert entry.source == "fake"
