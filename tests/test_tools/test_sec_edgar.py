"""Unit tests for sfewa.tools.sec_edgar (low-level EDGAR client).

All tests use cached JSON / HTML fixtures from tests/fixtures/sec_edgar/.
No live network is hit. The tests cover:

* lookup_cik() — ticker exact match, case-insensitivity, name fallback,
                 unknown returns None, zero-padding.
* find_filings() — date filtering (cutoff strict-greater), form filter,
                   per-form cap, sort order.
* classify_filing() — every supported SEC form maps to the project doc_type.
* primary_document_url() — URL composition with int-form CIK + dash-stripped accession.
* extract_text_from_html() — strips script/style, returns visible text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sfewa.tools import sec_edgar

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sec_edgar"


@pytest.fixture
def tickers_payload() -> dict:
    return json.loads((FIXTURES / "company_tickers_sample.json").read_text())


@pytest.fixture
def tesla_submissions() -> dict:
    return json.loads((FIXTURES / "submissions_tesla.json").read_text())


# ── lookup_cik ──


def test_lookup_cik_exact_ticker_match(tickers_payload):
    assert sec_edgar.lookup_cik("TSLA", tickers_payload=tickers_payload) == "0001318605"
    assert sec_edgar.lookup_cik("AAPL", tickers_payload=tickers_payload) == "0000320193"


def test_lookup_cik_is_case_insensitive(tickers_payload):
    assert sec_edgar.lookup_cik("tsla", tickers_payload=tickers_payload) == "0001318605"
    assert sec_edgar.lookup_cik("Tsla", tickers_payload=tickers_payload) == "0001318605"


def test_lookup_cik_falls_back_to_name_match(tickers_payload):
    assert sec_edgar.lookup_cik("Ford Motor", tickers_payload=tickers_payload) == "0000037996"


def test_lookup_cik_handles_corporate_suffix_mismatch(tickers_payload):
    """Regression: SEC's title for Boeing is 'BOEING CO' but the case YAML
    uses 'The Boeing Company'. The matcher must normalize stopwords
    (THE, COMPANY, CO, INC, ...) to find the match. This is the bug
    that caused the first Boeing acceptance run to skip SEC EDGAR."""
    boeing_payload = {
        "0": {"cik_str": 12927, "ticker": "BA", "title": "BOEING CO"},
    }
    assert sec_edgar.lookup_cik("The Boeing Company", tickers_payload=boeing_payload) == "0000012927"
    assert sec_edgar.lookup_cik("BOEING CO", tickers_payload=boeing_payload) == "0000012927"
    # And the canonical ticker still wins via Pass 1
    assert sec_edgar.lookup_cik("BA", tickers_payload=boeing_payload) == "0000012927"


def test_lookup_cik_handles_inc_and_corp_suffixes(tickers_payload):
    """Apple Inc. ↔ Apple Incorporated; General Motors Corp. ↔ GENERAL MOTORS.

    The Pass-2 name gate requires either >5 chars or a space, so the bare
    "Apple" (5 chars, no space) intentionally won't trigger fuzzy match
    — that prevents 4-letter stock-symbol-like inputs from spuriously
    matching titles like "PINEAPPLE INC". Inputs with corporate suffixes
    or spaces work."""
    payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1467858, "ticker": "GM", "title": "GENERAL MOTORS CO"},
    }
    assert sec_edgar.lookup_cik("Apple Inc.", tickers_payload=payload) == "0000320193"
    assert sec_edgar.lookup_cik("Apple Incorporated", tickers_payload=payload) == "0000320193"
    assert sec_edgar.lookup_cik("General Motors Corporation", tickers_payload=payload) == "0001467858"


def test_lookup_cik_returns_none_for_unknown(tickers_payload):
    assert sec_edgar.lookup_cik("NOTAREALSYMBOL", tickers_payload=tickers_payload) is None
    assert sec_edgar.lookup_cik("", tickers_payload=tickers_payload) is None


def test_lookup_cik_pads_to_ten_digits(tickers_payload):
    cik = sec_edgar.lookup_cik("F", tickers_payload=tickers_payload)
    assert cik == "0000037996"
    assert len(cik) == 10


def test_lookup_cik_short_input_skips_name_search(tickers_payload):
    # 'GM' is 2 chars — must hit the ticker exact-match path, not the name fallback.
    # (Name fallback is gated on len > 5 to avoid spurious 'AAPL' in 'PINEAPPLE INC' matches.)
    assert sec_edgar.lookup_cik("GM", tickers_payload=tickers_payload) == "0001467858"


# ── classify_filing ──


def test_classify_filing_annual_forms():
    assert sec_edgar.classify_filing("10-K") == "annual_report"
    assert sec_edgar.classify_filing("20-F") == "annual_report"
    assert sec_edgar.classify_filing("40-F") == "annual_report"


def test_classify_filing_interim_forms():
    assert sec_edgar.classify_filing("10-Q") == "interim_report"
    assert sec_edgar.classify_filing("6-K") == "interim_report"


def test_classify_filing_8k_is_inside_information():
    assert sec_edgar.classify_filing("8-K") == "inside_information"


def test_classify_filing_def14a_is_circular():
    assert sec_edgar.classify_filing("DEF 14A") == "circulars"
    assert sec_edgar.classify_filing("PRE 14A") == "circulars"


def test_classify_filing_unknown_falls_through_to_other():
    assert sec_edgar.classify_filing("S-1") == "other"
    assert sec_edgar.classify_filing("") == "other"
    assert sec_edgar.classify_filing("SC 13G") == "other"


# ── find_filings ──


def test_find_filings_respects_strict_cutoff(tesla_submissions):
    """The L1 invariant: strict-greater rejection. A filing on cutoff IS kept.
    A filing one day after cutoff is NOT."""
    # Cutoff at 2025-01-29 — should keep the 2025-01-29 8-K but not the 2025-01-30 10-K.
    filings = sec_edgar.find_filings(
        "0001318605",
        cutoff_date="2025-01-29",
        submissions_payload=tesla_submissions,
    )
    dates = [f["filing_date"] for f in filings]
    assert "2025-01-30" not in dates
    assert "2025-01-29" in dates


def test_find_filings_filters_by_form(tesla_submissions):
    filings = sec_edgar.find_filings(
        "0001318605",
        cutoff_date="2026-12-31",
        forms=["10-K"],
        submissions_payload=tesla_submissions,
    )
    forms = sorted(set(f["form"] for f in filings))
    assert forms == ["10-K"]
    # We have two 10-Ks in the fixture (2026-01-29 and 2025-01-30); both should appear.
    assert len(filings) == 2


def test_find_filings_caps_per_form(tesla_submissions):
    # max_per_form=1 + many 8-Ks → keep only the most recent 8-K
    filings = sec_edgar.find_filings(
        "0001318605",
        cutoff_date="2026-12-31",
        forms=["8-K"],
        max_per_form=1,
        submissions_payload=tesla_submissions,
    )
    assert len(filings) == 1
    assert filings[0]["filing_date"] == "2026-04-02"  # the most recent 8-K


def test_find_filings_sorted_most_recent_first(tesla_submissions):
    filings = sec_edgar.find_filings(
        "0001318605",
        cutoff_date="2026-12-31",
        submissions_payload=tesla_submissions,
    )
    dates = [f["filing_date"] for f in filings]
    assert dates == sorted(dates, reverse=True)


def test_find_filings_respects_from_date(tesla_submissions):
    filings = sec_edgar.find_filings(
        "0001318605",
        cutoff_date="2026-12-31",
        from_date="2025-06-01",
        submissions_payload=tesla_submissions,
    )
    for f in filings:
        assert f["filing_date"] >= "2025-06-01"


def test_find_filings_returns_complete_metadata(tesla_submissions):
    filings = sec_edgar.find_filings(
        "0001318605",
        cutoff_date="2025-12-31",
        forms=["10-K"],
        submissions_payload=tesla_submissions,
    )
    assert len(filings) >= 1
    f = filings[0]
    # Every metadata field needed for the provider.download() flow
    assert f["accession_number"]
    assert f["form"] == "10-K"
    assert f["filing_date"]
    assert f["primary_document"].endswith(".htm")
    assert f["cik"] == "0001318605"


# ── primary_document_url ──


def test_primary_document_url_format():
    url = sec_edgar.primary_document_url(
        "0001318605", "0001628280-25-003063", "tsla-20241231.htm"
    )
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/1318605/"
        "000162828025003063/tsla-20241231.htm"
    )


def test_primary_document_url_strips_dashes_from_accession():
    url = sec_edgar.primary_document_url("320193", "0000320193-24-000123", "doc.htm")
    assert "/000032019324000123/" in url
    assert "0000320193-24-000123" not in url  # dashes must be gone


def test_primary_document_url_uses_int_cik_in_archives_path():
    # data.sec.gov uses the zero-padded form, but Archives uses the int form.
    url = sec_edgar.primary_document_url("0000037996", "0000037996-25-000001", "doc.htm")
    assert "/data/37996/" in url
    assert "/data/0000037996/" not in url


# ── extract_text_from_html ──


def test_extract_text_from_html_strips_script_and_style():
    html_path = FIXTURES / "tesla_10k_excerpt.htm"
    text = sec_edgar.extract_text_from_html(html_path)
    assert "var x = 1;" not in text
    assert "font-family: serif;" not in text
    # Visible body content survives
    assert "Tesla" in text
    assert "Risk Factors" in text


def test_extract_text_from_html_caps_max_chars(tmp_path):
    big = tmp_path / "big.htm"
    big.write_text("<html><body>" + ("x" * 10_000) + "</body></html>")
    text = sec_edgar.extract_text_from_html(big, max_chars=500)
    assert len(text) == 500


# ── User-Agent / privacy guard ──


def test_default_user_agent_has_no_real_email():
    """Catch accidental leakage of a developer's real email into the
    User-Agent default. The placeholder must be a fake .invalid TLD."""
    assert ".invalid" in sec_edgar.DEFAULT_USER_AGENT
    assert "@" in sec_edgar.DEFAULT_USER_AGENT
    # Anti-leak guard: no .com / .co.jp / .org / .net in the default
    for tld in (".com", ".co.jp", ".org", ".net"):
        assert tld not in sec_edgar.DEFAULT_USER_AGENT, (
            f"Default User-Agent leaks a real-looking TLD: {tld}. "
            f"Must use a *.invalid placeholder."
        )
