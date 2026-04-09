"""EDINET API client for fetching Japanese financial filings.

EDINET (Electronic Disclosure for Investors' NETwork) is Japan's FSA
filing system. Provides access to official filings for Japanese companies:
- 有価証券報告書 (Annual Securities Report)
- 半期報告書 (Semi-Annual Report)
- 臨時報告書 (Extraordinary Report)

API docs: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

EDINET_BASE = "https://api.edinet-fsa.go.jp/api/v2"

# Honda's EDINET identifiers
HONDA_EDINET_CODE = "E02529"
HONDA_EDINET_CODE_ALT = "E02166"  # Some filings use this code
HONDA_SEC_CODE = "72670"  # 7267 + check digit

# Toyota's EDINET identifiers
TOYOTA_EDINET_CODE = "E02144"
TOYOTA_SEC_CODE = "72030"  # 7203 + check digit


def _get_api_key() -> str:
    key = os.environ.get("EDINET_API_KEY", "")
    if not key:
        raise ValueError("EDINET_API_KEY not set in .env")
    return key


def search_filings_by_date(
    target_date: date,
    edinet_codes: list[str] | None = None,
    sec_code: str | None = None,
) -> list[dict]:
    """Get all filings for a specific date, filtered by company.

    EDINET has no company search endpoint — must query by date and filter.

    Args:
        target_date: The filing date to query.
        edinet_codes: EDINET codes to filter for.
        sec_code: Securities code (5 digits) to filter for.

    Returns:
        List of filing metadata dicts matching the company filter.
    """
    key = _get_api_key()
    resp = httpx.get(
        f"{EDINET_BASE}/documents.json",
        params={
            "date": target_date.isoformat(),
            "type": "2",
            "Subscription-Key": key,
        },
        timeout=30,
    )
    data = resp.json()
    if data["metadata"]["status"] != "200":
        return []

    results = []
    for r in data.get("results", []):
        code = r.get("edinetCode", "")
        sec = r.get("secCode", "")
        if edinet_codes and code in edinet_codes:
            results.append(r)
        elif sec_code and sec == sec_code:
            results.append(r)
    return results


def scan_company_filings(
    start_date: date,
    end_date: date,
    edinet_codes: list[str],
    sec_code: str,
    delay: float = 0.3,
) -> list[dict]:
    """Scan a date range for a company's filings on EDINET.

    Args:
        start_date: Start of scan range (inclusive).
        end_date: End of scan range (inclusive).
        edinet_codes: EDINET codes to filter for.
        sec_code: Securities code (5 digits) to filter for.
        delay: Delay between API calls in seconds (be polite to gov API).

    Returns:
        List of filing metadata dicts.
    """
    filings = []
    d = start_date
    while d <= end_date:
        try:
            results = search_filings_by_date(
                d,
                edinet_codes=edinet_codes,
                sec_code=sec_code,
            )
            filings.extend(results)
        except Exception:
            pass
        d += timedelta(days=1)
        time.sleep(delay)
    return filings


def scan_honda_filings(
    start_date: date,
    end_date: date,
    delay: float = 0.3,
) -> list[dict]:
    """Scan a date range for Honda filings on EDINET."""
    return scan_company_filings(
        start_date, end_date,
        edinet_codes=[HONDA_EDINET_CODE, HONDA_EDINET_CODE_ALT],
        sec_code=HONDA_SEC_CODE,
        delay=delay,
    )


def download_pdf(doc_id: str, output_path: str | Path) -> Path:
    """Download a filing as PDF from EDINET.

    Args:
        doc_id: The EDINET document ID (e.g., "S100TNE0").
        output_path: Where to save the PDF.

    Returns:
        Path to the saved file.
    """
    key = _get_api_key()
    resp = httpx.get(
        f"{EDINET_BASE}/documents/{doc_id}",
        params={"type": "2", "Subscription-Key": key},
        timeout=60,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ct = resp.headers.get("content-type", "")
    if "pdf" in ct or "octet" in ct:
        output_path.write_bytes(resp.content)
        return output_path
    raise ValueError(f"Expected PDF, got {ct}: {resp.text[:200]}")


def extract_text_from_pdf(pdf_path: str | Path, max_pages: int = 50) -> str:
    """Extract text from a Japanese PDF filing using pdfplumber.

    Args:
        pdf_path: Path to the PDF file.
        max_pages: Maximum pages to extract (to limit context size).

    Returns:
        Extracted text content.
    """
    import pdfplumber

    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages[:max_pages]):
            text = page.extract_text()
            if text:
                pages_text.append(f"[Page {i + 1}]\n{text}")
    return "\n\n".join(pages_text)


# ── Pre-configured filing metadata ──

HONDA_KEY_FILINGS = [
    {
        "doc_id": "S100TNE0",
        "filename": "honda_annual_report_fy2023.pdf",
        "title": "有価証券報告書 第100期 (FY2023 Annual Report)",
        "filed_date": "2024-06-19",
        "doc_type": "annual_report",
        "source_type": "company_filing",
        "credibility_tier": "tier1_primary",
    },
    {
        "doc_id": "S100UOAW",
        "filename": "honda_semiannual_report_h1_fy2024.pdf",
        "title": "半期報告書 第101期 (H1 FY2024 Semi-Annual Report)",
        "filed_date": "2024-11-08",
        "doc_type": "semiannual_report",
        "source_type": "company_filing",
        "credibility_tier": "tier1_primary",
    },
    {
        "doc_id": "S100TQHL",
        "filename": "honda_extraordinary_20240624a.pdf",
        "title": "臨時報告書 (Extraordinary Report - AGM results)",
        "filed_date": "2024-06-24",
        "doc_type": "extraordinary_report",
        "source_type": "company_filing",
        "credibility_tier": "tier1_primary",
    },
]

TOYOTA_KEY_FILINGS = [
    {
        "doc_id": "S100TR7I",
        "filename": "toyota_annual_report_fy2023.pdf",
        "title": "有価証券報告書 第120期 (FY2023 Annual Report)",
        "filed_date": "2024-06-25",
        "doc_type": "annual_report",
        "source_type": "company_filing",
        "credibility_tier": "tier1_primary",
    },
    {
        "doc_id": "S100UP32",
        "filename": "toyota_semiannual_report_h1_fy2024.pdf",
        "title": "半期報告書 第121期 (H1 FY2024 Semi-Annual Report)",
        "filed_date": "2024-11-13",
        "doc_type": "semiannual_report",
        "source_type": "company_filing",
        "credibility_tier": "tier1_primary",
    },
    {
        "doc_id": "S100TNT2",
        "filename": "toyota_extraordinary_20240619.pdf",
        "title": "臨時報告書 (Extraordinary Report - AGM results)",
        "filed_date": "2024-06-19",
        "doc_type": "extraordinary_report",
        "source_type": "company_filing",
        "credibility_tier": "tier1_primary",
    },
    {
        "doc_id": "S100VPQE",
        "filename": "toyota_extraordinary_20250508.pdf",
        "title": "臨時報告書 (Extraordinary Report - May 2025)",
        "filed_date": "2025-05-08",
        "doc_type": "extraordinary_report",
        "source_type": "company_filing",
        "credibility_tier": "tier1_primary",
    },
]


# ── Company registry for EDINET-eligible companies ──

EDINET_REGISTRY: dict[str, dict] = {
    "honda": {
        "edinet_codes": [HONDA_EDINET_CODE, HONDA_EDINET_CODE_ALT],
        "sec_code": HONDA_SEC_CODE,
        "corpus_dir": "honda",
        "filings": HONDA_KEY_FILINGS,
    },
    "toyota": {
        "edinet_codes": [TOYOTA_EDINET_CODE],
        "sec_code": TOYOTA_SEC_CODE,
        "corpus_dir": "toyota",
        "filings": TOYOTA_KEY_FILINGS,
    },
}


def get_edinet_company(company_name: str) -> dict | None:
    """Look up a company in the EDINET registry by name.

    Returns the registry entry if the company is EDINET-eligible, else None.
    """
    name_lower = company_name.lower()
    for key, entry in EDINET_REGISTRY.items():
        if key in name_lower:
            return entry
    return None
