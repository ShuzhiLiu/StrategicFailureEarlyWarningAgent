"""Tests for temporal filter utility."""

from __future__ import annotations

from datetime import date

from sfewa.tools.temporal_filter import filter_documents_by_cutoff, is_before_cutoff


def test_is_before_cutoff_string_dates():
    assert is_before_cutoff("2025-05-18", "2025-05-19") is True
    assert is_before_cutoff("2025-05-19", "2025-05-19") is True
    assert is_before_cutoff("2025-05-20", "2025-05-19") is False


def test_is_before_cutoff_date_objects():
    assert is_before_cutoff(date(2025, 1, 1), date(2025, 5, 19)) is True
    assert is_before_cutoff(date(2026, 3, 12), date(2025, 5, 19)) is False


def test_filter_documents_by_cutoff():
    docs = [
        {"doc_id": "a", "published_at": "2024-06-01"},
        {"doc_id": "b", "published_at": "2025-05-20"},
        {"doc_id": "c", "published_at": "2025-05-19"},
    ]
    accepted, rejected = filter_documents_by_cutoff(docs, "2025-05-19")
    assert len(accepted) == 2
    assert len(rejected) == 1
    assert rejected[0]["doc_id"] == "b"
    assert rejected[0]["rejection_reason"] == "published_after_cutoff"
