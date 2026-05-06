"""SecEdgarProvider — thin FilingProvider adapter for the US SEC EDGAR (L2.2).

Same shape as EdinetProvider / CninfoProvider: search() returns FilingRefs,
download() caches the artifact, extract() produces page-anchored
EvidenceChunks (single "page" since SEC HTML has no PDF page structure),
and emit_manifest_entry() produces a ManifestEntry for source_manifest.json.

EDGAR is the easiest of the four providers to wire because the data is
served as a clean JSON API — no scraping. Live search() will succeed
without API keys; only a `User-Agent` is required.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sfewa.tools.filing_discovery import CORPUS_BASE
from sfewa.tools.filing_provider import (
    ExtractedDocument,
    FilingRef,
    ManifestEntry,
    chunk_with_offsets,
)
from sfewa.tools.sec_edgar import (
    classify_filing,
    download_primary_document,
    extract_text_from_html,
    find_filings,
    lookup_cik,
    primary_document_url,
    sleep_for_rate_limit,
)


class SecEdgarProvider:
    """FilingProvider for the US SEC EDGAR system.

    Uses ticker (preferred) or issuer_name to resolve a CIK, then walks
    the submissions feed for filings up to `to_date`. SEC filings are
    HTML, not PDF — extract() returns the document as a single "page"
    chunk set with global char offsets (page metadata is None).
    """

    source = "sec_edgar"

    def __init__(
        self,
        *,
        company_key: str | None = None,
        cache_dir: Path | None = None,
        live: bool = True,
    ):
        """Args:
        company_key: Key under data/corpus/ for caching (e.g., "tesla").
            Defaults to a sanitized form of issuer_name passed to search().
        cache_dir: Directory for cached HTML. Defaults to
            data/corpus/{company_key}/sec_edgar/.
        live: When False, search() returns []; download() raises if no
            cache hit; extract() and emit_manifest_entry() still work.
        """
        self._company_key = company_key
        self._cache_dir_override = cache_dir
        self._live = live
        # Map doc_id (== accession_number) → original metadata dict so
        # download() can find the primary_document filename.
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
        """Resolve CIK and walk recent filings up to `to_date`.

        `language` is ignored — SEC filings are English-only.
        `doc_types` filters using the project-wide vocabulary
        (annual_report, interim_report, inside_information, circulars).
        """
        if not self._live:
            return []

        lookup_key = ticker or issuer_name or ""
        if not lookup_key:
            return []

        cik = lookup_cik(lookup_key)
        if cik is None:
            # Try once more with the issuer_name when we tried ticker first
            if ticker and issuer_name and ticker != issuer_name:
                cik = lookup_cik(issuer_name)
            if cik is None:
                return []

        filings = find_filings(cik, cutoff_date=to_date, from_date=from_date)
        if not filings:
            return []

        refs: list[FilingRef] = []
        for f in filings:
            our_doc_type = classify_filing(f["form"])
            # Apply caller-side doc_type filter
            if doc_types and our_doc_type not in doc_types:
                continue

            doc_id = f["accession_number"]
            self._meta[doc_id] = f
            url = primary_document_url(
                f["cik"], f["accession_number"], f["primary_document"]
            )
            refs.append(
                FilingRef(
                    source=self.source,
                    doc_id=doc_id,
                    ticker=ticker,
                    issuer_id=f["cik"],
                    issuer_name=issuer_name or "",
                    title=f.get("primary_doc_description") or f["form"],
                    doc_type=our_doc_type,
                    language="en",
                    release_time=f["filing_date"],
                    url=url,
                )
            )
        return refs

    # ── Download ──

    def _cache_dir_for(self, ref: FilingRef) -> Path:
        if self._cache_dir_override is not None:
            return self._cache_dir_override
        key = self._company_key or _slugify(ref.issuer_name) or "unknown"
        return CORPUS_BASE / key / "sec_edgar"

    def _cache_path_for(self, ref: FilingRef) -> Path:
        cache_dir = self._cache_dir_for(ref)
        # Accession numbers contain dashes; safe for filesystem on Linux
        # but slugify-with-extension keeps things tidy across platforms.
        filename = f"{ref.doc_id}_{ref.doc_type}_{ref.release_time}.htm"
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

        # Look up the primary_document filename from the meta we cached at search() time.
        meta = self._meta.get(ref.doc_id)
        if meta is None:
            raise ValueError(
                f"FilingRef {ref.doc_id} not found in provider meta — "
                f"call search() before download()."
            )
        primary_doc = meta["primary_document"]
        cik = meta["cik"]

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        download_primary_document(cik, ref.doc_id, primary_doc, cache_path)
        sleep_for_rate_limit()
        return cache_path

    # ── Extract ──

    def extract(
        self,
        artifact: Path,
        ref: FilingRef,
        *,
        chunk_size: int = 4000,
        max_chars: int = 1_000_000,
    ) -> ExtractedDocument:
        """Extract HTML to text and chunk with global offsets.

        SEC HTML has no PDF page structure — we feed the full text as a
        single "page" to `chunk_with_offsets`, so EvidenceChunk.page
        comes back as 1 (positional) and page_char_* mirror global_char_*.
        Reviewer-facing tooling treats SEC chunks as full-text-only.
        """
        text = extract_text_from_html(artifact, max_chars=max_chars)
        if not text:
            return ExtractedDocument(ref=ref, text="", chunks=[])

        full_text, chunks = chunk_with_offsets(
            [text],
            doc_id=ref.doc_id,
            chunk_size=chunk_size,
            evidence_id_prefix=f"sec_edgar:{ref.doc_id}",
        )
        return ExtractedDocument(ref=ref, text=full_text, chunks=chunks)

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


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


__all__ = ["SecEdgarProvider", "sha256_of_file"]
