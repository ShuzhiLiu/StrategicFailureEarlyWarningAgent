"""CninfoProvider — thin FilingProvider adapter for China's CNINFO.

Wraps `sfewa.tools.cninfo` (巨潮资讯网, Shenzhen Securities Information).
Same shape as EdinetProvider: search() returns FilingRefs, download()
caches PDFs, extract() produces page-anchored EvidenceChunks, and
emit_manifest_entry() produces a ManifestEntry for source_manifest.json.
"""

from __future__ import annotations

from pathlib import Path

from sfewa.tools.cninfo import (
    discover_org_id,
    download_filing,
    search_filings,
)
from sfewa.tools.filing_discovery import CORPUS_BASE, _page_relevance
from sfewa.tools.filing_provider import (
    ExtractedDocument,
    FilingRef,
    ManifestEntry,
    chunk_with_offsets,
)


class CninfoProvider:
    """FilingProvider for China's CNINFO."""

    source = "cninfo"

    def __init__(
        self,
        *,
        company_key: str | None = None,
        cache_dir: Path | None = None,
        live: bool = True,
    ):
        self._company_key = company_key
        self._cache_dir_override = cache_dir
        self._live = live
        # Per-doc metadata captured during search() for use in download/extract
        self._meta: dict[str, dict] = {}

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
        if not self._live:
            return []
        if not issuer_name:
            return []
        result = discover_org_id(issuer_name)
        if result is None:
            return []
        stock_code, org_id = result

        from_str = from_date or "2023-01-01"
        date_range = f"{from_str}~{to_date}"

        kept_filings: list[dict] = []
        for category in ("category_ndbg_szsh", "category_bndbg_szsh"):
            filings = search_filings(
                stock_code, org_id,
                category=category,
                date_range=date_range,
                max_results=5,
            )
            for f in filings:
                if f["doc_type"] in ("annual_report", "semiannual_report"):
                    kept_filings.append(f)

        # Optional doc_type filter (from caller)
        if doc_types:
            kept_filings = [f for f in kept_filings if f["doc_type"] in doc_types]

        refs: list[FilingRef] = []
        for f in kept_filings:
            doc_id = f.get("announcement_id") or f.get("doc_id") or f["pdf_url"]
            self._meta[doc_id] = f
            refs.append(
                FilingRef(
                    source=self.source,
                    doc_id=doc_id,
                    ticker=stock_code,
                    issuer_id=org_id,
                    issuer_name=f.get("issuer_name", "") or issuer_name,
                    title=f.get("title", ""),
                    doc_type=f.get("doc_type", "other"),
                    language="zh",
                    release_time=f.get("filed_date", ""),
                    url=f.get("pdf_url"),
                )
            )
        return refs

    # ── Download ──

    def _cache_dir_for(self, ref: FilingRef) -> Path:
        if self._cache_dir_override is not None:
            return self._cache_dir_override
        key = self._company_key or _slugify(ref.issuer_name)
        return CORPUS_BASE / key / "cninfo"

    def _cache_path_for(self, ref: FilingRef) -> Path:
        cache_dir = self._cache_dir_for(ref)
        filename = f"{_safe_doc_id(ref.doc_id)}_{ref.doc_type}_{ref.release_time}.pdf"
        return cache_dir / filename

    def download(self, ref: FilingRef) -> Path:
        cache_path = self._cache_path_for(ref)
        if cache_path.exists():
            return cache_path
        if not self._live:
            raise FileNotFoundError(
                f"No cached artifact for {ref.doc_id} at {cache_path}; "
                f"live downloads disabled (live=False)."
            )
        if not ref.url:
            raise ValueError(f"FilingRef {ref.doc_id} has no URL; cannot download")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        ok = download_filing(ref.url, str(cache_path))
        if not ok:
            raise RuntimeError(f"CNINFO download failed for {ref.doc_id}")
        return cache_path

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
        try:
            import pdfplumber
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pdfplumber required for CNINFO extraction") from e

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
                page_numbers.append(i + 1)

        text, chunks = chunk_with_offsets(
            pages,
            doc_id=ref.doc_id,
            chunk_size=chunk_size,
            page_numbers=page_numbers,
            evidence_id_prefix=f"cninfo:{_safe_doc_id(ref.doc_id)}",
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


# ── Helpers ──


def _slugify(s: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(c if c.lower() in keep else "_" for c in s.lower()).strip("_") or "unknown"


def _safe_doc_id(doc_id: str) -> str:
    """Make a CNINFO doc_id (which may be a URL) filesystem-safe."""
    return _slugify(doc_id)[:64]


__all__ = ["CninfoProvider"]
