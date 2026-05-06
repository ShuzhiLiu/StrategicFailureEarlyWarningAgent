"""Source manifest emission and validation (L1.4).

The source manifest is the audit log of every document that the
retrieval layer touched, with one row per filing/article and the
cutoff_decision recorded for each. It is the artifact that proves the
temporal gate fired correctly.

Production-level invariant (enforced by `assert_manifest_clean`):

    For all entries in source_manifest.json:
        if release_time > cutoff_date AND cutoff_decision == "kept": FAIL.

Fixture-level invariant (enforced by per-provider tests):

    Each provider's test fixture set MUST include at least one entry
    with cutoff_decision == "rejected_post_cutoff", proving the gate
    exists rather than just being absent.

The manifest is doc-level, not evidence-level. A retrieved doc may yield
multiple evidence items, each with its own published_at; per-evidence
rejection happens in evidence_extraction. The manifest captures what
RETRIEVAL saw and what it decided.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from datetime import date

from sfewa.tools.filing_provider import CutoffDecision  # noqa: F401  (re-exported)
from sfewa.tools.temporal_filter import is_before_cutoff


def _iso_date_part(s: str) -> date:
    """Extract the date portion of an ISO string (YYYY-MM-DD or fuller)."""
    return date.fromisoformat(s[:10])


# ── Builder ──


def build_manifest_from_docs(
    docs: Iterable[dict],
    *,
    cutoff_date: str,
) -> list[dict]:
    """Build a doc-level manifest from a list of retrieved docs.

    Deduplicates by `link`. Each output row has the L1.4 schema:
        ticker, issuer_name, title, doc_type, language, release_time,
        url, content_sha256, cutoff_decision, source.

    cutoff_decision is "kept" when:
        - the doc has no published_at (we cannot reject without a date —
          downstream extraction handles per-evidence rejection), OR
        - the doc has published_at <= cutoff_date.

    cutoff_decision is "rejected_post_cutoff" when:
        - the doc has a published_at strictly after cutoff_date.

    Args:
        docs: iterable of retrieved-doc dicts (the existing pipeline's
            retrieved_docs format: {title, snippet, link, source,
            source_type, credibility_tier, published_at, ...}).
        cutoff_date: ISO YYYY-MM-DD analysis cutoff.

    Returns:
        list of manifest entry dicts. Order is the deduplicated input
        order (first occurrence per link).
    """
    seen: set[str] = set()
    entries: list[dict] = []
    for doc in docs:
        link = doc.get("link") or ""
        # Use title fallback when link is empty (e.g., cached EDINET filings)
        key = link or f"::{doc.get('title', '')[:80]}"
        if key in seen:
            continue
        seen.add(key)

        pub_at = doc.get("published_at") or ""
        decision = _decide_for_doc(pub_at=pub_at, cutoff_date=cutoff_date)
        source = doc.get("source") or "unknown"
        entries.append({
            "ticker": doc.get("ticker"),
            "issuer_name": doc.get("issuer_name") or doc.get("filer_name"),
            "title": doc.get("title", "")[:400],
            "doc_type": doc.get("doc_type") or _infer_doc_type(source),
            "language": doc.get("language") or _infer_language(source),
            "release_time": pub_at,
            "url": link or None,
            "content_sha256": doc.get("content_sha256"),
            "cutoff_decision": decision,
            "source": source,
        })
    return entries


def _decide_for_doc(*, pub_at: str, cutoff_date: str) -> CutoffDecision:
    """Apply the cutoff gate to a doc-level manifest row.

    No published_at → "kept" (cannot reject without a date; per-evidence
    rejection at extraction handles content-level temporal leakage).
    """
    if not pub_at:
        return "kept"
    try:
        if is_before_cutoff(pub_at, cutoff_date):
            return "kept"
    except Exception:
        # Malformed published_at → keep, but the assertion below will catch
        # it if a downstream layer rewrote it as post-cutoff.
        return "kept"
    return "rejected_post_cutoff"


def _infer_doc_type(source: str) -> str:
    if source in ("edinet", "cninfo", "hkexnews"):
        return "filing"
    if source == "news":
        return "news_article"
    return "web_page"


def _infer_language(source: str) -> str:
    return {
        "edinet": "ja",
        "cninfo": "zh",
        "hkexnews": "en",
    }.get(source, "en")


# ── Validation ──


class ManifestInvariantError(AssertionError):
    """Raised when source_manifest.json violates L1.4 production invariants."""


def assert_manifest_clean(manifest: list[dict], *, cutoff_date: str) -> None:
    """Production-level invariant: zero entries with kept post-cutoff.

    Run this at the end of every pipeline run. If it raises, the temporal
    gate failed and the audit story is broken — fail loudly, do not save
    artifacts.

    Args:
        manifest: list of manifest entry dicts (output of
            build_manifest_from_docs).
        cutoff_date: ISO YYYY-MM-DD.

    Raises:
        ManifestInvariantError if any entry has cutoff_decision == "kept"
        AND release_time > cutoff_date.
    """
    cutoff = _iso_date_part(cutoff_date)
    offenders: list[dict] = []
    for e in manifest:
        if e.get("cutoff_decision") != "kept":
            continue
        rt = e.get("release_time") or ""
        if not rt:
            continue
        try:
            rt_date = _iso_date_part(rt)
        except ValueError:
            continue
        if rt_date > cutoff:
            offenders.append(e)
    if offenders:
        raise ManifestInvariantError(
            f"source_manifest contains {len(offenders)} kept doc(s) with "
            f"release_time > cutoff_date {cutoff_date}. The temporal gate "
            f"failed. Examples:\n"
            + "\n".join(
                f"  - {e.get('source')}/{e.get('title','')[:60]} "
                f"published {e.get('release_time')!r}, decision=kept"
                for e in offenders[:5]
            )
        )


def manifest_summary(manifest: list[dict]) -> dict[str, Any]:
    """Aggregate counts for display + provenance header."""
    by_decision: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for e in manifest:
        d = e.get("cutoff_decision", "unknown")
        by_decision[d] = by_decision.get(d, 0) + 1
        s = e.get("source", "unknown")
        by_source[s] = by_source.get(s, 0) + 1
    return {
        "total": len(manifest),
        "kept": by_decision.get("kept", 0),
        "rejected_post_cutoff": by_decision.get("rejected_post_cutoff", 0),
        "rejected_doc_type": by_decision.get("rejected_doc_type", 0),
        "rejected_language": by_decision.get("rejected_language", 0),
        "by_source": by_source,
    }


# ── Persistence ──


def save_manifest(manifest: list[dict], path: str | Path) -> Path:
    """Save the manifest as JSON to `path`. Returns the absolute path."""
    import json

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return p
