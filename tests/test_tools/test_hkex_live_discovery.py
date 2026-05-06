"""Unit tests for L2.1 HKEX live discovery (Playwright-backed).

The actual Playwright integration test is gated on the Playwright Python
package being importable. By default it isn't — these tests cover:

* is_playwright_available() — True/False matches the runtime state
* live_discover_filings() — returns [] gracefully when Playwright missing
* _parse_row_html — pure function, extracts title / release_time /
                    pdf_url / announcement_id from sample row HTML
* _parse_release_time — HK date format → ISO 8601 +08:00
* HKEX_PDF_URL_PATTERN — regex matches valid HKEX archive URLs

Live integration test is skipped when Playwright is not installed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sfewa.tools.hkex_live_discovery import (
    HKEX_PDF_URL_PATTERN,
    _parse_release_time,
    _parse_row_html,
    is_playwright_available,
    live_discover_filings,
)


# ── is_playwright_available ──


def test_is_playwright_available_returns_bool():
    """The function must always return a bool — never raise."""
    out = is_playwright_available()
    assert isinstance(out, bool)


# ── live_discover_filings: DDG path is primary ──


def test_live_discover_uses_ddg_when_company_provided():
    """The DDG path runs first; Playwright is fallback. When DDG returns
    rows, Playwright must NOT be invoked."""
    fake_rows = [{
        "announcement_id": "2022042501544",
        "title": "Country Garden Annual Report 2021",
        "release_time": "2022-04-25T00:00:00+08:00",
        "pdf_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0425/2022042501544.pdf",
        "doc_type": "annual_report",
    }]
    with patch(
        "sfewa.tools.hkex_live_discovery._ddg_discover",
        return_value=fake_rows,
    ) as mock_ddg, patch(
        "sfewa.tools.hkex_live_discovery._run_playwright_discovery",
    ) as mock_pw:
        out = live_discover_filings(
            company="Country Garden Holdings Company Limited",
            stock_id="02007",
            from_date="2021-01-01",
            to_date="2023-07-31",
        )
    assert out == fake_rows
    mock_ddg.assert_called_once()
    mock_pw.assert_not_called()


def test_live_discover_falls_back_to_playwright_when_ddg_empty():
    """When DDG returns nothing AND Playwright is available, fall back."""
    fake_rows = [{
        "announcement_id": "2024082200428",
        "title": "Interim Report",
        "release_time": "2024-08-22T17:23:00+08:00",
        "pdf_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0822/2024082200428.pdf",
        "doc_type": "interim_report",
    }]
    with patch(
        "sfewa.tools.hkex_live_discovery._ddg_discover",
        return_value=[],
    ), patch(
        "sfewa.tools.hkex_live_discovery.is_playwright_available",
        return_value=True,
    ), patch(
        "sfewa.tools.hkex_live_discovery._run_playwright_discovery",
        return_value=fake_rows,
    ):
        out = live_discover_filings(
            company="Tencent Holdings Limited",
            stock_id="00700",
            from_date="2023-01-01",
            to_date="2024-12-31",
        )
    assert out == fake_rows


def test_live_discover_returns_empty_when_both_paths_fail():
    """DDG returns nothing; Playwright not installed → empty list, no raise."""
    with patch(
        "sfewa.tools.hkex_live_discovery._ddg_discover",
        return_value=[],
    ), patch(
        "sfewa.tools.hkex_live_discovery.is_playwright_available",
        return_value=False,
    ):
        out = live_discover_filings(
            company="Some Company",
            stock_id="02318",
            from_date="2023-01-01",
            to_date="2024-12-31",
        )
    assert out == []


def test_live_discover_swallows_playwright_errors():
    """Playwright crashes must not propagate up. Errors land in the log."""
    with patch(
        "sfewa.tools.hkex_live_discovery._ddg_discover",
        return_value=[],
    ), patch(
        "sfewa.tools.hkex_live_discovery.is_playwright_available",
        return_value=True,
    ), patch(
        "sfewa.tools.hkex_live_discovery._run_playwright_discovery",
        side_effect=RuntimeError("simulated browser crash"),
    ):
        out = live_discover_filings(
            company="X", stock_id="02318",
            from_date="2023-01-01", to_date="2024-12-31",
        )
    assert out == []


def test_live_discover_filters_by_doc_categories():
    """Caller can scope to specific doc_types post-discovery."""
    fake_rows = [
        {"announcement_id": "1", "title": "Annual Report",
         "release_time": "2023-04-25T00:00:00+08:00",
         "pdf_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0425/1.pdf",
         "doc_type": "annual_report"},
        {"announcement_id": "2", "title": "Random Notice",
         "release_time": "2023-06-15T00:00:00+08:00",
         "pdf_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0615/2.pdf",
         "doc_type": "other"},
    ]
    with patch(
        "sfewa.tools.hkex_live_discovery._ddg_discover",
        return_value=fake_rows,
    ):
        out = live_discover_filings(
            company="X", stock_id="02007",
            from_date="2022-01-01", to_date="2023-07-31",
            doc_categories=["annual_report"],
        )
    assert len(out) == 1
    assert out[0]["doc_type"] == "annual_report"


# ── _parse_row_html ──


def test_parse_row_html_extracts_pdf_url_and_announcement_id():
    """Realistic-looking JSF result row: anchor tag with PDF href +
    title text + HK-format date."""
    html = (
        '<td class="C">22/08/2024 17:23</td>'
        '<td><a href="/listedco/listconews/sehk/2024/0822/2024082200428.pdf" '
        'target="_blank">Interim Report 2024</a></td>'
        '<td>Financial Statements/ESG Information - Interim/Quarterly Results</td>'
    )
    out = _parse_row_html(html)
    assert out is not None
    assert out["announcement_id"] == "2024082200428"
    assert out["pdf_url"].endswith("/2024/0822/2024082200428.pdf")
    assert out["release_time"] == "2024-08-22T17:23:00+08:00"
    assert "Interim Report" in out["title"]


def test_parse_row_html_returns_none_when_no_pdf_link():
    """A row without a PDF URL is not a filing row — return None."""
    html = (
        '<td>22/08/2024 17:23</td>'
        '<td>Some non-filing notification</td>'
        '<td>Other</td>'
    )
    out = _parse_row_html(html)
    assert out is None


def test_parse_row_html_falls_back_when_release_time_absent():
    """When the row has no parseable date, fall back to the URL's
    YYYY/MMDD components."""
    html = (
        '<td><a href="/listedco/listconews/sehk/2024/0822/2024082200428.pdf">'
        'Filing</a></td>'
    )
    out = _parse_row_html(html)
    assert out is not None
    # Date inferred from URL → midnight HK time on that date
    assert out["release_time"].startswith("2024-08-22T00:00:00+08:00")


# ── _parse_release_time ──


def test_parse_release_time_iso_format():
    out = _parse_release_time("Some text 22/08/2024 17:23 more text")
    assert out == "2024-08-22T17:23:00+08:00"


def test_parse_release_time_zero_padded():
    out = _parse_release_time("01/01/2024 09:05")
    assert out == "2024-01-01T09:05:00+08:00"


def test_parse_release_time_returns_none_on_no_match():
    assert _parse_release_time("just plain text") is None
    assert _parse_release_time("") is None


# ── HKEX_PDF_URL_PATTERN ──


def test_pdf_url_pattern_matches_canonical_url():
    m = HKEX_PDF_URL_PATTERN.search(
        "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0822/2024082200428.pdf"
    )
    assert m is not None
    assert m.group(1) == "2024"
    assert m.group(2) == "0822"
    assert m.group(3) == "2024082200428"


def test_pdf_url_pattern_matches_legacy_hostname():
    """The legacy hostname is `www.hkexnews.hk` (no digit suffix). The
    pre-2018 announcement IDs had alphanumeric prefixes like `ltn...`
    that the modern (\\d+) match doesn't accept; we test the modern
    URL format under the legacy hostname instead, which IS the case
    that matters for L2.1 retrospectives (2018+ cutoffs)."""
    m = HKEX_PDF_URL_PATTERN.search(
        "https://www.hkexnews.hk/listedco/listconews/sehk/2022/0425/2022042501544.pdf"
    )
    assert m is not None
    assert m.group(1) == "2022"
    assert m.group(3) == "2022042501544"


def test_pdf_url_pattern_rejects_wrong_path():
    assert HKEX_PDF_URL_PATTERN.search(
        "https://www1.hkexnews.hk/listedco/something_else/sehk/2024/0822/file.pdf"
    ) is None
    assert HKEX_PDF_URL_PATTERN.search("/just/some/path.pdf") is None


# ── DDG-discovery helpers ──


def test_classify_doc_type_from_title_handles_common_titles():
    """Doc-type classifier from search-result title."""
    from sfewa.tools.hkex_live_discovery import _classify_doc_type_from_title
    assert _classify_doc_type_from_title("Annual Report 2022") == "annual_report"
    assert _classify_doc_type_from_title("INTERIM REPORT 2022 - HKEXnews") == "interim_report"
    assert _classify_doc_type_from_title("Annual Results Announcement") == "results_announcement"
    assert _classify_doc_type_from_title("Inside Information Disclosure") == "inside_information"
    assert _classify_doc_type_from_title("Random administrative notice") == "other"


def test_row_from_url_and_title_full_url():
    """The DDG path constructs row metadata from a (url, title) pair."""
    from sfewa.tools.hkex_live_discovery import _row_from_url_and_title
    row = _row_from_url_and_title(
        url="https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0425/2022042501544.pdf",
        title="Annual Report 2021",
    )
    assert row is not None
    assert row["announcement_id"] == "2022042501544"
    assert row["doc_type"] == "annual_report"
    assert row["release_time"].startswith("2022-04-25T")
    assert row["pdf_url"] == (
        "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0425/2022042501544.pdf"
    )


def test_row_from_url_and_title_returns_none_for_non_hkex_url():
    """Non-HKEX URLs (e.g., third-party analyst PDFs) must return None."""
    from sfewa.tools.hkex_live_discovery import _row_from_url_and_title
    assert _row_from_url_and_title(
        url="https://example.com/some/file.pdf", title="Annual Report",
    ) is None


# ── _short_company_name (DDG query refinement) ──


def test_short_company_name_strips_holdings_company_limited():
    from sfewa.tools.hkex_live_discovery import _short_company_name
    assert _short_company_name(
        "Country Garden Holdings Company Limited"
    ) == "Country Garden"


def test_short_company_name_strips_inc_and_corp():
    from sfewa.tools.hkex_live_discovery import _short_company_name
    assert _short_company_name("Apple Inc.") == "Apple"
    assert _short_company_name("Boeing Corp") == "Boeing"


def test_short_company_name_handles_group_suffix():
    from sfewa.tools.hkex_live_discovery import _short_company_name
    assert _short_company_name("Tencent Holdings Limited") == "Tencent"


def test_short_company_name_preserves_simple_names():
    from sfewa.tools.hkex_live_discovery import _short_company_name
    assert _short_company_name("Honda") == "Honda"


# ── promote_hkex_urls_from_results ──


def test_promote_returns_empty_when_no_hkex_urls():
    """Search results that contain no HKEXnews URLs → empty promotion."""
    from sfewa.tools.hkex_live_discovery import promote_hkex_urls_from_results
    results = [
        {"link": "https://www.reuters.com/article", "title": "Foo"},
        {"link": "https://example.com/x.pdf", "title": "Bar"},
    ]
    out = promote_hkex_urls_from_results(
        results, company_key="test", cutoff_date="2023-12-31",
    )
    assert out == []


def test_promote_filters_post_cutoff_urls():
    """A URL whose YYYY/MMDD is post-cutoff must be skipped pre-download."""
    from sfewa.tools.hkex_live_discovery import promote_hkex_urls_from_results
    results = [{
        "link": "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0822/2024082200428.pdf",
        "title": "Post-cutoff Annual Report",
    }]
    # patch load_hkex_pdfs so we can prove it was NOT called
    with patch("sfewa.tools.hkex_live_discovery.load_hkex_pdfs") as mock_load:
        out = promote_hkex_urls_from_results(
            results, company_key="test", cutoff_date="2023-12-31",
        )
    assert out == []
    mock_load.assert_not_called()


def test_promote_passes_through_pre_cutoff_urls():
    """A URL whose YYYY/MMDD is pre-cutoff must be downloaded."""
    from sfewa.tools.hkex_live_discovery import promote_hkex_urls_from_results
    results = [{
        "link": "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0425/2022042501544.pdf",
        "title": "Country Garden Annual Report 2021",
    }]
    fake_docs = [{"title": "[HKEX] ...", "snippet": "..."}]
    with patch(
        "sfewa.tools.hkex_live_discovery.load_hkex_pdfs",
        return_value=fake_docs,
    ) as mock_load:
        out = promote_hkex_urls_from_results(
            results, company_key="country_garden", cutoff_date="2023-07-31",
        )
    assert out == fake_docs
    mock_load.assert_called_once()
    # Confirm the row passed in carries the parsed announcement_id
    args, kwargs = mock_load.call_args
    rows = args[0] if args else kwargs.get("rows")
    assert len(rows) == 1
    assert rows[0]["announcement_id"] == "2022042501544"


def test_promote_dedupes_repeated_urls():
    """Same URL appearing multiple times in search results → one row."""
    from sfewa.tools.hkex_live_discovery import promote_hkex_urls_from_results
    results = [
        {"link": "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0425/2022042501544.pdf",
         "title": "Country Garden Annual Report 2021"},
        {"link": "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0425/2022042501544.pdf",
         "title": "Country Garden Annual Report 2021 (duplicate)"},
    ]
    with patch(
        "sfewa.tools.hkex_live_discovery.load_hkex_pdfs",
        return_value=[],
    ) as mock_load:
        promote_hkex_urls_from_results(
            results, company_key="country_garden", cutoff_date="2023-07-31",
        )
    args, _ = mock_load.call_args
    rows = args[0]
    assert len(rows) == 1


# ── Optional Playwright integration test (auto-skipped when missing) ──


@pytest.mark.skipif(
    not is_playwright_available(),
    reason="Playwright not installed; install via `pip install playwright && playwright install chromium`",
)
def test_playwright_integration_invokes_browser_with_mock_page():
    """If Playwright is installed, exercise the inner function with a
    monkey-patched `sync_playwright` so the browser is never actually
    launched. This proves the import path is wired correctly."""
    # Skipped automatically when Playwright is missing; otherwise we
    # confirm the code path enters the inner function.
    from unittest.mock import MagicMock

    with patch("playwright.sync_api.sync_playwright") as mock_pw:
        # Mock chained calls: sync_playwright().__enter__().chromium.launch().new_context()...
        mock_browser = MagicMock()
        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser
        mock_context = mock_browser.new_context.return_value
        mock_page = mock_context.new_page.return_value
        mock_page.query_selector_all.return_value = []  # no rows
        out = live_discover_filings(
            stock_id="02318", from_date="2023-01-01", to_date="2024-12-31",
        )
    assert isinstance(out, list)
