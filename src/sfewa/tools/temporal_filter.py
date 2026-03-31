"""Temporal integrity filter — enforces cutoff date on all evidence."""

from __future__ import annotations

from datetime import date


def is_before_cutoff(published_at: str | date, cutoff_date: str | date) -> bool:
    """Check if a document's publication date is before the cutoff.

    Args:
        published_at: Document publication date (ISO format or date object).
        cutoff_date: Analysis cutoff date (ISO format or date object).

    Returns:
        True if published_at <= cutoff_date.
    """
    if isinstance(published_at, str):
        published_at = date.fromisoformat(published_at)
    if isinstance(cutoff_date, str):
        cutoff_date = date.fromisoformat(cutoff_date)
    return published_at <= cutoff_date


def filter_documents_by_cutoff(
    documents: list[dict], cutoff_date: str
) -> tuple[list[dict], list[dict]]:
    """Split documents into accepted and rejected based on cutoff date.

    Returns:
        Tuple of (accepted_docs, rejected_docs).
    """
    accepted = []
    rejected = []
    for doc in documents:
        pub_date = doc.get("published_at")
        if pub_date and is_before_cutoff(pub_date, cutoff_date):
            accepted.append(doc)
        else:
            rejected.append({**doc, "rejection_reason": "published_after_cutoff"})
    return accepted, rejected
