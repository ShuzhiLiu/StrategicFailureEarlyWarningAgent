"""EdinetProvider — thin FilingProvider adapter for Japan's EDINET.

Wraps the legacy `sfewa.tools.edinet` and `sfewa.tools.filing_discovery`
modules. Per roadmap rev 4, this is an *adapter*, not a refactor — the
behavior of the underlying discovery / download functions is unchanged.
The new value-add is:
    1. Uniform Protocol surface so HKEX (L1.2) drops in cleanly.
    2. Page-anchored EvidenceChunk extraction (preserves source page
       numbers when relevance-filtering annual reports).
    3. ManifestEntry emission for the source_manifest.json (L1.4).

Live network calls are gated behind a constructor flag (`live=False` for
tests). Tests use cached PDFs from data/corpus/{honda,toyota}/edinet/.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sfewa.tools.edinet import download_pdf
from sfewa.tools.filing_discovery import (
    CORPUS_BASE,
    _discover_edinet_code,
    _find_key_filings_edinet,
    _page_relevance,
)
from sfewa.tools.filing_provider import (
    ExtractedDocument,
    FilingRef,
    ManifestEntry,
    chunk_with_offsets,
    decide_cutoff,
)


class EdinetProvider:
    """FilingProvider for Japan's EDINET (FSA Electronic Disclosure)."""

    source = "edinet"

    def __init__(
        self,
        *,
        company_key: str | None = None,
        cache_dir: Path | None = None,
        live: bool = True,
    ):
        """Args:
        company_key: Key under data/corpus/ for caching (e.g., "honda").
            Defaults to a sanitized form of the issuer_name passed to search().
        cache_dir: Directory for cached PDFs. Defaults to
            data/corpus/{company_key}/edinet/.
        live: When False, search() returns no refs and download() raises;
            extract() and emit_manifest_entry() still work on cached files.
            Tests should use live=False.
        """
        self._company_key = company_key
        self._cache_dir_override = cache_dir
        self._live = live
        # Map filing dict (from legacy discovery) → FilingRef cache so callers
        # can pass a FilingRef back without losing the legacy metadata.
        self._ref_meta: dict[str, dict] = {}

    # ── Search ──

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
        """Discover filings for an issuer up to `to_date`.

        Wraps `_discover_edinet_code()` + `_find_key_filings_edinet()`. Returns
        FilingRefs for each discovered filing. `from_date` is currently
        ignored (legacy discovery hard-codes a 2-year backward window).
        """
        if not self._live:
            return []
        if not issuer_name:
            return []

        codes = _discover_edinet_code(issuer_name)
        if codes is None:
            return []
        edinet_code, sec_code = codes

        filings = _find_key_filings_edinet(edinet_code, sec_code, to_date)
        if not filings:
            return []

        # Optional doc_type filter (post-discovery)
        if doc_types:
            filings = [f for f in filings if f["doc_type"] in doc_types]

        refs: list[FilingRef] = []
        for f in filings:
            doc_id = f["doc_id"]
            self._ref_meta[doc_id] = f
            refs.append(
                FilingRef(
                    source=self.source,
                    doc_id=doc_id,
                    ticker=sec_code or None,
                    issuer_id=edinet_code,
                    issuer_name=f.get("filer_name", "") or issuer_name,
                    title=f.get("title", ""),
                    doc_type=f.get("doc_type", "other"),
                    language="ja",
                    release_time=f.get("filed_date", ""),
                    url=None,  # EDINET doesn't expose stable doc URLs
                )
            )
        return refs

    # ── Download ──

    def _cache_dir_for(self, ref: FilingRef) -> Path:
        if self._cache_dir_override is not None:
            return self._cache_dir_override
        key = self._company_key or _slugify(ref.issuer_name)
        return CORPUS_BASE / key / "edinet"

    def _cache_path_for(self, ref: FilingRef) -> Path:
        cache_dir = self._cache_dir_for(ref)
        filename = f"{ref.doc_id}_{ref.doc_type}_{ref.release_time}.pdf"
        return cache_dir / filename

    def download(self, ref: FilingRef) -> Path:
        """Download the filing PDF (or return the cached path)."""
        cache_path = self._cache_path_for(ref)
        if cache_path.exists():
            return cache_path
        if not self._live:
            raise FileNotFoundError(
                f"No cached artifact for {ref.doc_id} at {cache_path}; "
                f"live downloads disabled (live=False)."
            )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        return download_pdf(ref.doc_id, cache_path)

    # ── Extract ──

    def extract(
        self,
        artifact: Path,
        ref: FilingRef,
        *,
        max_pages: int = 80,
        chunk_size: int = 4000,
        min_relevance: int = 2,
    ) -> ExtractedDocument:
        """Parse a PDF into page-anchored EvidenceChunks.

        Annual reports are large (200+ pages); we apply the same
        keyword-relevance filter as the legacy code, but record the
        SOURCE page numbers in each EvidenceChunk so a reviewer can click
        back to the right PDF page. Other doc types use all pages.
        """
        try:
            import pdfplumber
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pdfplumber required for EDINET extraction") from e

        pages: list[str] = []
        page_numbers: list[int] = []
        with pdfplumber.open(artifact) as pdf:
            page_iter = pdf.pages[:max_pages]
            for i, page in enumerate(page_iter):
                text = page.extract_text() or ""
                if not text.strip():
                    continue
                if ref.doc_type == "annual_report":
                    if _page_relevance(text) < min_relevance:
                        continue
                pages.append(text)
                page_numbers.append(i + 1)  # PDF pages are 1-indexed for humans

        text, chunks = chunk_with_offsets(
            pages,
            doc_id=ref.doc_id,
            chunk_size=chunk_size,
            page_numbers=page_numbers,
            evidence_id_prefix=f"edinet:{ref.doc_id}",
        )
        return ExtractedDocument(ref=ref, text=text, chunks=chunks)

    # ── Manifest ──

    def emit_manifest_entry(
        self,
        ref: FilingRef,
        decision,
        *,
        content_sha256: str | None = None,
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


# ── Module helpers ──


def _slugify(s: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(c if c.lower() in keep else "_" for c in s.lower()).strip("_") or "unknown"


def sha256_of_file(path: Path) -> str:
    """Compute the sha256 of a file, used for manifest content_sha256."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# Re-export for callers that need a one-shot decision wrapper.
__all__ = ["EdinetProvider", "decide_cutoff", "sha256_of_file"]
