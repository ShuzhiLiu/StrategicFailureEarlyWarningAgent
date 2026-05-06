"""HKEX provider tests (L1.2).

No live network. All tests use HTML fixtures under tests/fixtures/hkex/
and pre-built TitleSearchRow records.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sfewa.tools.filing_provider import (
    FilingProvider,
    FilingRef,
    decide_cutoff,
)
from sfewa.tools.hkex import (
    HK_TZ,
    IssuerRef,
    TitleSearchRow,
    classify_doc_type,
    cutoff_date_to_endofday_hk,
    is_excluded_doc_type,
    normalize_release_time,
    parse_stocklist_html,
    parse_titlesearch_html,
    resolve_issuer,
    url_hash,
)
from sfewa.tools.providers import HkexProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "hkex"


# ── Time normalization ──


def test_normalize_hh_mm_dd_mm_yyyy_canonical():
    """HKEXnews canonical format: HH:MM DD/MM/YYYY."""
    s = normalize_release_time("14:30 31/03/2025")
    dt = datetime.fromisoformat(s)
    assert dt.year == 2025 and dt.month == 3 and dt.day == 31
    assert dt.hour == 14 and dt.minute == 30
    assert dt.utcoffset().total_seconds() == 8 * 3600
    assert dt.utcoffset().total_seconds() == 8 * 3600


def test_normalize_dd_mm_yyyy_hh_mm_alternate():
    """Alternate ordering: DD/MM/YYYY HH:MM."""
    s = normalize_release_time("31/03/2025 14:30")
    dt = datetime.fromisoformat(s)
    assert dt.year == 2025 and dt.month == 3 and dt.day == 31
    assert dt.hour == 14 and dt.minute == 30


def test_normalize_iso_with_tz_passes_through():
    s = normalize_release_time("2025-03-31T14:30:00+08:00")
    dt = datetime.fromisoformat(s)
    assert dt.utcoffset().total_seconds() == 8 * 3600


def test_normalize_naive_iso_assumed_hk():
    s = normalize_release_time("2025-03-31 14:30")
    dt = datetime.fromisoformat(s)
    assert dt.utcoffset().total_seconds() == 8 * 3600


def test_normalize_date_only_to_end_of_day_hk():
    s = normalize_release_time("2025-03-31")
    dt = datetime.fromisoformat(s)
    assert dt.hour == 23 and dt.minute == 59 and dt.second == 59
    assert dt.utcoffset().total_seconds() == 8 * 3600


def test_cutoff_date_endofday_is_233959_hk():
    s = cutoff_date_to_endofday_hk("2024-12-31")
    dt = datetime.fromisoformat(s)
    assert dt.hour == 23 and dt.minute == 59
    assert dt.utcoffset().total_seconds() == 8 * 3600


# ── Stock list parsing & issuer resolution ──


def test_parse_stocklist_html_finds_known_issuers():
    html = (FIXTURES / "stocklist_sample.html").read_text()
    rows = parse_stocklist_html(html)
    codes = {r["stock_id"] for r in rows}
    for code in ("00005", "00700", "01299", "02318", "02378"):
        assert code in codes, f"missing {code}: {codes}"


def test_resolve_issuer_handles_ticker_variants():
    html = (FIXTURES / "stocklist_sample.html").read_text()
    for variant in ("2318", "02318", "0002318", "2318.HK", "HKEX:2318"):
        ref = resolve_issuer(variant, stock_list_html=html)
        assert ref is not None, f"failed to resolve {variant!r}"
        assert ref.stock_id == "02318"


def test_resolve_issuer_returns_none_for_unknown():
    html = (FIXTURES / "stocklist_sample.html").read_text()
    assert resolve_issuer("99999", stock_list_html=html) is None


def test_resolve_issuer_requires_a_source():
    with pytest.raises(ValueError):
        resolve_issuer("2318")


# ── Title-search parsing ──


def test_parse_titlesearch_html_extracts_5_rows():
    html = (FIXTURES / "titlesearch_pingan.html").read_text()
    rows = parse_titlesearch_html(html)
    assert len(rows) == 5
    titles = [r.title for r in rows]
    assert "2023 ANNUAL REPORT" in titles
    assert "ANNOUNCEMENT - 2025 INTERIM RESULTS" in titles


def test_parse_titlesearch_release_times_are_tz_aware():
    html = (FIXTURES / "titlesearch_pingan.html").read_text()
    rows = parse_titlesearch_html(html)
    for r in rows:
        dt = datetime.fromisoformat(r.release_time_iso)
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 8 * 3600


# ── Doc-type taxonomy ──


@pytest.mark.parametrize("title,expected", [
    ("2023 ANNUAL REPORT", "annual_report"),
    ("INTERIM REPORT 2024", "interim_report"),
    ("ANNOUNCEMENT - 2024 INTERIM RESULTS", "results_announcement"),
    ("2024 ANNUAL RESULTS", "results_announcement"),
    ("INSIDE INFORMATION - PROFIT WARNING", "inside_information"),
    ("Circular - Major Transaction", "circular"),
    ("VERY SUBSTANTIAL ACQUISITION", "circular"),
    ("CONNECTED TRANSACTION", "circular"),
    # EXCLUDE-by-default
    ("MONTHLY RETURN OF EQUITY ISSUER", "monthly_return"),
    ("Next Day Disclosure Return", "next_day_disclosure"),
    ("CHANGE OF DIRECTOR", "officer_change"),
    ("APPOINTMENT OF NON-EXECUTIVE DIRECTOR", "officer_change"),
    ("RESIGNATION OF COMPANY SECRETARY", "officer_change"),
    ("RESULT OF POLL AT THE 2024 AGM", "poll_result"),
    ("NOTIFICATION OF AGM", "meeting_notice"),
])
def test_classify_doc_type(title, expected):
    assert classify_doc_type(title) == expected


def test_is_excluded_doc_type_classifies_admin_correctly():
    assert is_excluded_doc_type("monthly_return")
    assert is_excluded_doc_type("officer_change")
    assert not is_excluded_doc_type("annual_report")
    assert not is_excluded_doc_type("inside_information")


# ── Provider Protocol ──


def test_hkex_provider_satisfies_protocol(tmp_path):
    p = HkexProvider(cache_dir=tmp_path / "hkex", live=False)
    assert isinstance(p, FilingProvider)
    assert p.source == "hkexnews"


def test_hkex_search_with_no_issuer_returns_empty(tmp_path):
    p = HkexProvider(cache_dir=tmp_path / "hkex", live=False)
    refs = p.search(
        ticker=None, issuer_name=None, from_date=None,
        to_date="2025-05-19", doc_types=None, language=None,
    )
    assert refs == []


def test_hkex_search_unknown_ticker_returns_empty(tmp_path):
    html = (FIXTURES / "stocklist_sample.html").read_text()
    p = HkexProvider(
        cache_dir=tmp_path / "hkex",
        stock_list_html=html,
        live=False,
    )
    refs = p.search(
        ticker="99999", issuer_name=None, from_date=None,
        to_date="2025-05-19", doc_types=None, language=None,
    )
    assert refs == []


# ── End-to-end fixture flow ──


def test_hkex_provider_search_with_pingan_fixtures_filters_correctly(tmp_path):
    """Round-trip: stocklist + titlesearch fixtures → search() → FilingRefs.

    Cutoff 2024-12-31. Expected behavior:
        - 2023 ANNUAL REPORT (2024-03-28) → kept (annual_report)
        - 2024 INTERIM RESULTS (2024-08-22) → kept (results_announcement)
        - PROFIT WARNING (2024-12-15) → kept (inside_information)
        - MONTHLY RETURN (2025-01-05) → dropped (excluded doc type)
                                        AND post-cutoff
        - 2025 INTERIM RESULTS (2025-08-22) → dropped (post-cutoff)
    """
    stock_html = (FIXTURES / "stocklist_sample.html").read_text()
    titlesearch_html = (FIXTURES / "titlesearch_pingan.html").read_text()

    p = HkexProvider(
        cache_dir=tmp_path / "hkex",
        stock_list_html=stock_html,
        live=False,
    )
    p.preload_titlesearch_html(titlesearch_html)

    refs = p.search(
        ticker="2318", issuer_name=None, from_date=None,
        to_date="2024-12-31", doc_types=None, language=None,
    )
    assert len(refs) == 3, f"expected 3 kept refs, got {[r.title for r in refs]}"
    titles = {r.title for r in refs}
    assert "2023 ANNUAL REPORT" in titles
    assert "ANNOUNCEMENT - 2024 INTERIM RESULTS" in titles
    assert "INSIDE INFORMATION - PROFIT WARNING" in titles
    # Post-cutoff and excluded doc types are NOT in the kept set
    assert "MONTHLY RETURN OF EQUITY ISSUER" not in titles
    assert "ANNOUNCEMENT - 2025 INTERIM RESULTS" not in titles


def test_hkex_post_cutoff_doc_rejected_via_decide_cutoff(tmp_path):
    """L1 fixture-level invariant: a post-cutoff doc must classify as
    rejected_post_cutoff. Required for every provider."""
    p = HkexProvider(cache_dir=tmp_path / "hkex", live=False)
    ref = FilingRef(
        source="hkexnews",
        doc_id="POSTCUTOFF",
        ticker="02318",
        issuer_id="02318",
        issuer_name="PING AN INSURANCE",
        title="ANNOUNCEMENT - 2025 INTERIM RESULTS",
        doc_type="results_announcement",
        language="en",
        release_time="2025-08-22T17:00:00+08:00",
    )
    decision = decide_cutoff(ref, cutoff_date="2024-12-31")
    assert decision == "rejected_post_cutoff"
    entry = p.emit_manifest_entry(ref, decision)
    assert entry.cutoff_decision == "rejected_post_cutoff"
    assert entry.source == "hkexnews"


def test_hkex_doc_type_filter_overrides_default_exclusion(tmp_path):
    """Caller-supplied doc_types replaces the default exclusion list.

    Asking for monthly_return explicitly should return it (audit reviewers
    may want to inspect filing cadence).
    """
    stock_html = (FIXTURES / "stocklist_sample.html").read_text()
    titlesearch_html = (FIXTURES / "titlesearch_pingan.html").read_text()
    p = HkexProvider(
        cache_dir=tmp_path / "hkex",
        stock_list_html=stock_html,
        live=False,
    )
    p.preload_titlesearch_html(titlesearch_html)

    # Move cutoff out so MONTHLY RETURN (2025-01-05) is in window
    refs = p.search(
        ticker="2318", issuer_name=None, from_date=None,
        to_date="2025-06-30", doc_types=["monthly_return"], language=None,
    )
    titles = {r.title for r in refs}
    assert "MONTHLY RETURN OF EQUITY ISSUER" in titles


def test_hkex_offline_download_raises_when_no_cache(tmp_path):
    p = HkexProvider(cache_dir=tmp_path / "hkex", live=False)
    ref = FilingRef(
        source="hkexnews", doc_id="x",
        ticker="02318", issuer_id="02318",
        issuer_name="PING AN", title="t",
        doc_type="annual_report", language="en",
        release_time="2024-03-28T14:30:00+08:00",
        url="https://www1.hkexnews.hk/test.pdf",
    )
    with pytest.raises(FileNotFoundError):
        p.download(ref)


def test_url_hash_is_stable_and_short():
    a = url_hash("https://example.com/a")
    b = url_hash("https://example.com/a")
    c = url_hash("https://example.com/b")
    assert a == b
    assert a != c
    assert len(a) == 12
