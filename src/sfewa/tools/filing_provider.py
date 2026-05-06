"""FilingProvider Protocol and supporting types (L1.1).

A `FilingProvider` is a uniform façade over a regulatory filing source
(EDINET for Japan, CNINFO for China, HKEXnews for Hong Kong, etc.).
Providers expose four operations:

    search()      — discover filings matching ticker/date/type/language
    download()    — fetch the artifact (PDF/HTML) to local cache
    extract()     — parse the artifact into page-anchored EvidenceChunks
    emit_manifest_entry() — produce one row of source_manifest.json with the
                            cutoff decision for that filing

Per roadmap rev 4, adapters are *thin*: they wrap existing edinet.py /
cninfo.py / hkex.py modules without deep-refactoring them. The Protocol
exists so HKEX (L1.2) can be added with a uniform shape, and so the
audit manifest (L1.4) can be emitted uniformly across jurisdictions.

Two offset systems live on `EvidenceChunk`:
    page_char_start/page_char_end — offsets within the page text
                                    (None when `page` is unknown)
    global_char_start/global_char_end — offsets within the full document
                                        (always present)

PDF page-view UIs use the page-local offsets; full-text HTML highlight
uses the global offsets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

# ── Decision vocabulary ──

CutoffDecision = Literal[
    "kept",
    "rejected_post_cutoff",
    "rejected_doc_type",
    "rejected_language",
]
"""Why a filing was kept or rejected at retrieval time.

Recorded in source_manifest.json so a reviewer can audit the temporal gate.
The fixture tests for each provider must include at least one
post-cutoff doc and assert it lands as `rejected_post_cutoff` — that's
the artifact that proves the gate exists (L1.4 acceptance criterion).
"""


# ── Filing reference ──


@dataclass(frozen=True)
class FilingRef:
    """Stable identifier + metadata for a filing.

    Returned by `search()`, consumed by `download()` and `extract()`.
    Frozen so it can be used as a dict key and safely passed across
    threads in parallel retrieval.
    """

    # Source-level identifier — opaque to callers, meaningful to the provider
    source: str  # e.g. "edinet", "cninfo", "hkexnews"
    doc_id: str  # provider-native document id (EDINET docID, CNINFO announcementId, ...)

    # Issuer
    ticker: str | None
    issuer_id: str | None  # provider-native issuer id (EDINET edinetCode, etc.)
    issuer_name: str

    # Document
    title: str
    doc_type: str  # "annual_report", "interim_report", "results_announcement", ...
    language: str  # ISO 639-1: "en", "ja", "zh"

    # Time
    # `release_time` is the publication timestamp. ISO-8601, ideally
    # timezone-aware (HK uses +08:00, JST +09:00, CST +08:00). For sources
    # that publish with day granularity (EDINET filing date), midnight
    # local time is used.
    release_time: str

    # Optional: artifact URL on the original source (for the audit trail)
    url: str | None = None


# ── Evidence chunk (page-anchored) ──


@dataclass(frozen=True)
class EvidenceChunk:
    """A piece of extracted text with both page-local and global offsets.

    Both offset systems are present so that two different UI surfaces work:
        - PDF page view: uses (page, page_char_start, page_char_end)
        - Full-text HTML view: uses (global_char_start, global_char_end)

    Per L1.4 acceptance criterion, every top-level claim in
    risk_factors.json must reference an evidence_id that resolves to an
    EvidenceChunk with a valid (doc_id, global_char_start, global_char_end).
    """

    evidence_id: str
    doc_id: str
    text: str

    # Always present — offset within the full document text
    global_char_start: int
    global_char_end: int

    # Present when the source provides per-page text (PDF, etc.)
    page: int | None = None
    page_char_start: int | None = None
    page_char_end: int | None = None


@dataclass
class ExtractedDocument:
    """Result of provider.extract(): the full text plus chunked view."""

    ref: FilingRef
    text: str  # the full document text — chunk offsets refer to this string
    chunks: list[EvidenceChunk] = field(default_factory=list)


# ── Manifest entry ──


@dataclass(frozen=True)
class ManifestEntry:
    """One row of source_manifest.json — the audit log for a filing.

    The production manifest assertion is: zero entries with
    cutoff_decision == "kept" AND release_time > cutoff_date.

    Fixture-level assertion: each provider's test fixture set MUST
    include at least one entry with cutoff_decision == "rejected_post_cutoff"
    to prove the gate exists.
    """

    ticker: str | None
    issuer_name: str
    title: str
    doc_type: str
    language: str
    release_time: str
    url: str | None
    content_sha256: str | None
    cutoff_decision: CutoffDecision
    source: str  # "edinet" | "cninfo" | "hkexnews"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "issuer_name": self.issuer_name,
            "title": self.title,
            "doc_type": self.doc_type,
            "language": self.language,
            "release_time": self.release_time,
            "url": self.url,
            "content_sha256": self.content_sha256,
            "cutoff_decision": self.cutoff_decision,
            "source": self.source,
        }


# ── The Protocol ──


@runtime_checkable
class FilingProvider(Protocol):
    """Uniform façade over a regulatory filing source.

    Implementations live in src/sfewa/tools/providers/{edinet,cninfo,hkex}.py
    and wrap the legacy modules without deep-refactoring them.
    """

    # Source identifier — used to tag manifest entries.
    source: str

    def search(
        self,
        *,
        ticker: str | None,
        issuer_name: str | None,
        from_date: str | None,
        to_date: str,
        doc_types: list[str] | None,
        language: str | None,
    ) -> list[FilingRef]:
        """Find filings matching the given criteria.

        `to_date` is the cutoff (inclusive). Implementations should not
        return filings published after `to_date` — that's the first
        line of the temporal gate.
        """
        ...

    def download(self, ref: FilingRef) -> Path:
        """Fetch the artifact to local cache; return the path."""
        ...

    def extract(self, artifact: Path, ref: FilingRef) -> ExtractedDocument:
        """Parse a downloaded artifact into ExtractedDocument."""
        ...

    def emit_manifest_entry(
        self,
        ref: FilingRef,
        decision: CutoffDecision,
        *,
        content_sha256: str | None = None,
    ) -> ManifestEntry:
        """Produce a manifest row for this filing."""
        ...


# ── Helpers ──


def _to_iso_string(t: str | date | datetime) -> str:
    """Best-effort normalization to an ISO string.

    L1.4 (revision 4) tightens this to require timezone-aware datetimes
    on the cutoff path; for now, this helper accepts naive inputs and
    normalizes them so the existing edinet.py/cninfo.py call sites keep
    working. The TZ-aware enforcement lands with the HKEX provider.
    """
    if isinstance(t, datetime):
        return t.isoformat()
    if isinstance(t, date):
        return t.isoformat()
    return t


def decide_cutoff(
    ref: FilingRef,
    *,
    cutoff_date: str,
    allowed_doc_types: list[str] | None = None,
    allowed_languages: list[str] | None = None,
) -> CutoffDecision:
    """Apply the cutoff/doc-type/language gates to a single filing.

    Order matters: post-cutoff is checked first (most important audit
    invariant), then doc_type, then language. The first failing check wins.
    """
    # Temporal gate — strict greater-than (cutoff is inclusive).
    # Compare on date granularity if either side lacks a time component.
    rt = _to_iso_string(ref.release_time)
    if _is_after_cutoff(rt, cutoff_date):
        return "rejected_post_cutoff"

    if allowed_doc_types and ref.doc_type not in allowed_doc_types:
        return "rejected_doc_type"

    if allowed_languages and ref.language not in allowed_languages:
        return "rejected_language"

    return "kept"


def _is_after_cutoff(release_time: str, cutoff_date: str) -> bool:
    """True if release_time is strictly after cutoff_date.

    Both inputs may be ISO date or ISO datetime. We compare at the
    coarser of the two granularities (date) when either is date-only.
    Cutoff is interpreted as end-of-day local when given as date-only;
    full TZ-aware comparison lands with the HKEX provider.
    """
    rt_date = _date_part(release_time)
    cutoff = _date_part(cutoff_date)
    return rt_date > cutoff


def _date_part(s: str) -> date:
    """Extract the date portion of an ISO string."""
    # Strip TZ suffix if present, keep just YYYY-MM-DD
    head = s[:10]
    return date.fromisoformat(head)


def chunk_with_offsets(
    pages: list[str],
    *,
    doc_id: str,
    chunk_size: int = 4000,
    overlap: int = 0,
    evidence_id_prefix: str | None = None,
    page_numbers: list[int] | None = None,
) -> tuple[str, list[EvidenceChunk]]:
    """Chunk a list of page texts, recording both page-local and global offsets.

    Args:
        pages: list of page texts. `pages[i]` is the text of the i-th
            page in the order received. Pass a single-element list when
            the source has no page structure.
        doc_id: provider-native document id, written into each chunk.
        chunk_size: target chunk size in characters.
        overlap: characters of overlap between adjacent chunks.
        evidence_id_prefix: prefix for generated evidence_ids; defaults to
            the doc_id.
        page_numbers: optional source-side page numbers, one per element of
            `pages`. When given, EvidenceChunk.page records the source
            page number rather than the positional index. Useful when the
            extractor has filtered pages (e.g., relevance-filtered annual
            report) and the chunk should still point back to the original
            page number in the PDF.

    Returns:
        (full_text, chunks) — full_text is the concatenation of pages with
        a single newline separator. Chunk global offsets refer to this
        string. Chunks may span page boundaries; in that case `page` is
        set to the page where the chunk *starts* and `page_char_*` are
        relative to that page's text.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be in [0, chunk_size)")
    if page_numbers is not None and len(page_numbers) != len(pages):
        raise ValueError(
            f"page_numbers length {len(page_numbers)} != pages length {len(pages)}"
        )

    sep = "\n"
    full_text_parts: list[str] = []
    # page_starts[i] = global offset where pages[i] begins
    page_starts: list[int] = []
    cursor = 0
    for i, page_text in enumerate(pages):
        page_starts.append(cursor)
        full_text_parts.append(page_text)
        cursor += len(page_text)
        if i < len(pages) - 1:
            cursor += len(sep)
    full_text = sep.join(full_text_parts)

    if not full_text:
        return full_text, []

    prefix = evidence_id_prefix or doc_id
    chunks: list[EvidenceChunk] = []
    step = chunk_size - overlap
    chunk_idx = 0
    pos = 0
    n = len(full_text)
    while pos < n:
        end = min(pos + chunk_size, n)
        chunk_text = full_text[pos:end]
        page_idx_1based, page_offset = _global_to_page(pos, page_starts, sep_len=len(sep))
        # Resolve to source page number if mapping was provided
        if page_numbers is not None and 1 <= page_idx_1based <= len(page_numbers):
            page_num: int | None = page_numbers[page_idx_1based - 1]
        else:
            page_num = page_idx_1based
        page_text_len = (
            len(pages[page_idx_1based - 1])
            if 1 <= page_idx_1based <= len(pages)
            else None
        )
        if page_offset is not None and page_text_len is not None:
            page_char_start = page_offset
            page_char_end = min(page_offset + (end - pos), page_text_len)
        else:
            page_char_start = None
            page_char_end = None

        chunks.append(
            EvidenceChunk(
                evidence_id=f"{prefix}#c{chunk_idx:03d}",
                doc_id=doc_id,
                text=chunk_text,
                global_char_start=pos,
                global_char_end=end,
                page=page_num,
                page_char_start=page_char_start,
                page_char_end=page_char_end,
            )
        )
        chunk_idx += 1
        if end == n:
            break
        pos += step

    return full_text, chunks


def _global_to_page(
    global_pos: int, page_starts: list[int], *, sep_len: int = 1
) -> tuple[int, int | None]:
    """Map a global character offset to (page_number, page_local_offset).

    Returns (page_number_1_indexed, offset_within_page_or_None).
    The offset is None if the global position lands exactly on a page
    separator (rare; chunk start positions are always inside a page in
    practice).
    """
    if not page_starts:
        return 1, global_pos
    # Find the last page whose start is <= global_pos.
    page_idx = 0
    for i, start in enumerate(page_starts):
        if start <= global_pos:
            page_idx = i
        else:
            break
    page_num = page_idx + 1
    page_local = global_pos - page_starts[page_idx]
    return page_num, page_local
