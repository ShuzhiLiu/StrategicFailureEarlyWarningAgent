"""Tests for source manifest emission and the production invariant (L1.4)."""

from __future__ import annotations

import pytest

from sfewa.tools.manifest import (
    ManifestInvariantError,
    assert_manifest_clean,
    build_manifest_from_docs,
    manifest_summary,
    save_manifest,
)


# ── Build ──


def _doc(**kwargs):
    base = {
        "title": "doc",
        "snippet": "...",
        "link": "https://example.com/x",
        "source": "duckduckgo",
    }
    base.update(kwargs)
    return base


def test_build_manifest_keeps_docs_with_no_published_at():
    """Docs without a publication date are kept (extraction does per-evidence reject)."""
    docs = [_doc(link="https://a.com/1"), _doc(link="https://b.com/2")]
    m = build_manifest_from_docs(docs, cutoff_date="2025-05-19")
    assert len(m) == 2
    assert all(e["cutoff_decision"] == "kept" for e in m)


def test_build_manifest_rejects_post_cutoff_doc():
    docs = [
        _doc(link="https://a.com/1", published_at="2024-12-01"),  # kept
        _doc(link="https://b.com/2", published_at="2025-08-01"),  # rejected (post-cutoff)
    ]
    m = build_manifest_from_docs(docs, cutoff_date="2025-05-19")
    assert len(m) == 2
    assert m[0]["cutoff_decision"] == "kept"
    assert m[1]["cutoff_decision"] == "rejected_post_cutoff"


def test_build_manifest_keeps_doc_dated_on_cutoff():
    """Cutoff is inclusive."""
    docs = [_doc(link="https://a.com/1", published_at="2025-05-19")]
    m = build_manifest_from_docs(docs, cutoff_date="2025-05-19")
    assert m[0]["cutoff_decision"] == "kept"


def test_build_manifest_dedups_by_link():
    """Multiple chunks of the same EDINET filing yield one manifest row."""
    docs = [
        _doc(link="edinet:S100ABC", source="edinet", title="Filing (Section 1/3)"),
        _doc(link="edinet:S100ABC", source="edinet", title="Filing (Section 2/3)"),
        _doc(link="edinet:S100ABC", source="edinet", title="Filing (Section 3/3)"),
    ]
    m = build_manifest_from_docs(docs, cutoff_date="2025-05-19")
    assert len(m) == 1
    assert m[0]["title"].endswith("(Section 1/3)")  # first occurrence wins


def test_build_manifest_dedups_with_empty_link_using_title():
    docs = [
        _doc(link="", title="A"),
        _doc(link="", title="A"),
        _doc(link="", title="B"),
    ]
    m = build_manifest_from_docs(docs, cutoff_date="2025-05-19")
    assert len(m) == 2  # A, B


def test_build_manifest_records_source_and_inferred_doc_type():
    docs = [
        _doc(link="edinet:1", source="edinet"),
        _doc(link="cninfo:1", source="cninfo"),
        _doc(link="https://news/1", source="news"),
        _doc(link="https://web/1", source="duckduckgo"),
    ]
    m = build_manifest_from_docs(docs, cutoff_date="2025-05-19")
    sources = {e["source"] for e in m}
    assert sources == {"edinet", "cninfo", "news", "duckduckgo"}
    by_source = {e["source"]: e for e in m}
    assert by_source["edinet"]["doc_type"] == "filing"
    assert by_source["cninfo"]["doc_type"] == "filing"
    assert by_source["news"]["doc_type"] == "news_article"
    assert by_source["duckduckgo"]["doc_type"] == "web_page"
    assert by_source["edinet"]["language"] == "ja"
    assert by_source["cninfo"]["language"] == "zh"


# ── Production invariant ──


def test_assert_manifest_clean_passes_on_clean_manifest():
    docs = [_doc(link="x", published_at="2024-12-01")]
    m = build_manifest_from_docs(docs, cutoff_date="2025-05-19")
    assert_manifest_clean(m, cutoff_date="2025-05-19")  # must not raise


def test_assert_manifest_clean_passes_when_post_cutoff_was_rejected():
    """A post-cutoff doc with cutoff_decision=rejected_post_cutoff is fine."""
    docs = [
        _doc(link="a", published_at="2024-01-01"),
        _doc(link="b", published_at="2025-12-31"),
    ]
    m = build_manifest_from_docs(docs, cutoff_date="2025-05-19")
    assert_manifest_clean(m, cutoff_date="2025-05-19")  # must not raise


def test_assert_manifest_clean_fails_on_kept_post_cutoff():
    """A doc the builder would have rejected, but that was forced kept,
    is the audit-fail signal — assert must raise."""
    m = [{
        "title": "Bad",
        "release_time": "2025-12-31",
        "cutoff_decision": "kept",
        "source": "edinet",
    }]
    with pytest.raises(ManifestInvariantError):
        assert_manifest_clean(m, cutoff_date="2025-05-19")


def test_assert_manifest_clean_ignores_kept_with_no_release_time():
    """Manifest entries without release_time can't be rejected — they pass."""
    m = [{
        "title": "?", "release_time": "", "cutoff_decision": "kept", "source": "x",
    }]
    assert_manifest_clean(m, cutoff_date="2025-05-19")


# ── Summary ──


def test_manifest_summary_aggregates_correctly():
    m = [
        {"cutoff_decision": "kept", "source": "edinet"},
        {"cutoff_decision": "kept", "source": "duckduckgo"},
        {"cutoff_decision": "kept", "source": "duckduckgo"},
        {"cutoff_decision": "rejected_post_cutoff", "source": "duckduckgo"},
    ]
    s = manifest_summary(m)
    assert s["total"] == 4
    assert s["kept"] == 3
    assert s["rejected_post_cutoff"] == 1
    assert s["by_source"] == {"edinet": 1, "duckduckgo": 3}


# ── Persistence ──


def test_save_manifest_writes_json(tmp_path):
    m = [{"title": "A", "cutoff_decision": "kept", "source": "edinet",
          "release_time": "2024-06-15", "url": None, "ticker": None,
          "issuer_name": "X", "doc_type": "filing", "language": "ja",
          "content_sha256": None}]
    p = save_manifest(m, tmp_path / "source_manifest.json")
    assert p.exists()
    import json
    loaded = json.loads(p.read_text())
    assert loaded == m
