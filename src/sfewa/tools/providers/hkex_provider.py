"""HkexProvider — FilingProvider implementation for HKEXnews (L1.2).

Wraps the structured-data layer in `sfewa.tools.hkex`. Live HTTP calls
are gated behind a `live` flag; tests use HTML fixtures and pre-built
TitleSearchRow lists.

Cache layout (per roadmap rev 4):
    {cache_dir}/metadata/{url_hash}.json   — request metadata cache
    {cache_dir}/artifacts/{content_sha256}.pdf  — de-duplicated by content
    {cache_dir}/manifest.jsonl             — append-only URL → sha map
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sfewa.tools.filing_provider import (
    ExtractedDocument,
    FilingRef,
    ManifestEntry,
    chunk_with_offsets,
)
from sfewa.tools.hkex import (
    TitleSearchRow,
    append_cache_manifest,
    classify_doc_type,
    cutoff_date_to_endofday_hk,
    hkex_cache_paths,
    is_excluded_doc_type,
    parse_titlesearch_html,
    resolve_issuer,
    url_hash,
)


class HkexProvider:
    """FilingProvider for Hong Kong Stock Exchange disclosures."""

    source = "hkexnews"

    def __init__(
        self,
        *,
        cache_dir: Path,
        stock_list_html: str | None = None,
        stock_list: list[dict] | None = None,
        live: bool = True,
    ):
        """Args:
        cache_dir: base path for {metadata, artifacts, manifest}.
        stock_list_html / stock_list: source for issuer resolution.
        live: when False, search() returns no rows unless preloaded; download()
            raises if the artifact isn't already cached.
        """
        self._cache_dir = Path(cache_dir)
        self._stock_list_html = stock_list_html
        self._stock_list = stock_list
        self._live = live
        # Preload mechanism: tests can inject pre-parsed search rows
        self._preloaded_rows: list[TitleSearchRow] = []

    # ── Test/offline preload ──

    def preload_rows(self, rows: list[TitleSearchRow]) -> None:
        """Inject TitleSearchRow records (used by tests with HTML fixtures)."""
        self._preloaded_rows.extend(rows)

    def preload_titlesearch_html(self, html: str, *, language: str = "en") -> None:
        """Parse a HKEXnews title-search HTML fixture and queue rows."""
        self._preloaded_rows.extend(parse_titlesearch_html(html, language=language))

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
        """Resolve issuer, then filter the available search rows by criteria.

        - Issuer resolution via the stock list (no network: uses
          self._stock_list_html / self._stock_list).
        - Search rows come from self._preloaded_rows (tests) or, in live
          mode, from a network call (not implemented in this iteration —
          falls through to preloaded rows for now).
        - Cutoff applied immediately: rows with release_time strictly after
          to_date end-of-day Asia/Hong_Kong are dropped here.
        - Doc-type filter:
            - When doc_types is given, restrict to those.
            - When doc_types is None, drop is_excluded_doc_type() classes
              (the HKEX administrative noise list).
        """
        if not ticker:
            return []
        issuer = resolve_issuer(
            ticker,
            stock_list_html=self._stock_list_html,
            stock_list=self._stock_list,
        )
        if issuer is None:
            return []

        # Cutoff: end-of-day Asia/Hong_Kong inclusive
        cutoff_iso = cutoff_date_to_endofday_hk(to_date)

        rows = [r for r in self._preloaded_rows if r.stock_id == issuer.stock_id]
        # Optional language filter
        if language:
            rows = [r for r in rows if r.language == language]

        refs: list[FilingRef] = []
        for r in rows:
            doc_type = classify_doc_type(r.title)
            # Doc-type filter: caller-supplied takes precedence over the
            # default exclusion list.
            if doc_types:
                if doc_type not in doc_types:
                    continue
            else:
                if is_excluded_doc_type(doc_type):
                    continue
            # Temporal pre-filter: skip strictly-post-cutoff rows so they
            # don't appear in the kept set. (The provider still records
            # rejected entries via emit_manifest_entry when the caller
            # explicitly tracks them — this is the search-time gate.)
            if r.release_time_iso > cutoff_iso:
                continue
            refs.append(FilingRef(
                source=self.source,
                doc_id=url_hash(r.url),
                ticker=issuer.stock_id,
                issuer_id=issuer.issuer_id,
                issuer_name=issuer.display_name or r.issuer_name,
                title=r.title,
                doc_type=doc_type,
                language=r.language,
                release_time=r.release_time_iso,
                url=r.url,
            ))
        return refs

    # ── Download ──

    def download(self, ref: FilingRef) -> Path:
        if not ref.url:
            raise ValueError(f"FilingRef {ref.doc_id} has no URL")
        paths = hkex_cache_paths(self._cache_dir)
        meta_path = paths["metadata"] / f"{url_hash(ref.url)}.json"

        # If we have cached metadata, return the cached artifact
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            sha = meta.get("content_sha256")
            if sha:
                artifact_path = paths["artifacts"] / f"{sha}.pdf"
                if artifact_path.exists():
                    return artifact_path

        if not self._live:
            raise FileNotFoundError(
                f"No cached HKEX artifact for {ref.url} (live=False)."
            )

        import httpx
        resp = httpx.get(ref.url, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        content = resp.content
        sha = hashlib.sha256(content).hexdigest()
        paths["artifacts"].mkdir(parents=True, exist_ok=True)
        paths["metadata"].mkdir(parents=True, exist_ok=True)
        artifact_path = paths["artifacts"] / f"{sha}.pdf"
        artifact_path.write_bytes(content)
        meta_path.write_text(json.dumps({
            "url": ref.url,
            "content_sha256": sha,
            "release_time": ref.release_time,
            "doc_type": ref.doc_type,
            "language": ref.language,
        }))
        append_cache_manifest(
            self._cache_dir,
            url=ref.url,
            content_sha256=sha,
            doc_id=ref.doc_id,
        )
        return artifact_path

    # ── Extract ──

    def extract(
        self,
        artifact: Path,
        ref: FilingRef,
        *,
        max_pages: int = 80,
        chunk_size: int = 4000,
    ) -> ExtractedDocument:
        try:
            import pdfplumber
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pdfplumber required for HKEX extraction") from e

        pages: list[str] = []
        page_numbers: list[int] = []
        with pdfplumber.open(artifact) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                text = page.extract_text() or ""
                if not text.strip():
                    continue
                pages.append(text)
                page_numbers.append(i + 1)

        text, chunks = chunk_with_offsets(
            pages,
            doc_id=ref.doc_id,
            chunk_size=chunk_size,
            page_numbers=page_numbers,
            evidence_id_prefix=f"hkexnews:{ref.doc_id}",
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


__all__ = ["HkexProvider"]
