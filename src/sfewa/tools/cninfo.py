"""CNINFO API client for fetching Chinese company filings.

CNINFO (巨潮资讯网, cninfo.com.cn) is operated by Shenzhen Securities
Information Co. It hosts all A-share company filings for both SZSE and SSE.

Uses the undocumented but stable hisAnnouncement/query endpoint.
No authentication required.

Key concepts:
- orgId: Internal company identifier (e.g., "gshk0001211" for BYD)
- Stock codes need orgId suffix: "002594,gshk0001211"
- Filing categories: category_ndbg_szsh (annual), category_bndbg_szsh (semi-annual)
- PDF URLs: prepend "http://static.cninfo.com.cn/" to adjunctUrl
"""

from __future__ import annotations

import time
from datetime import datetime

import httpx

CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_LIST_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_PDF_BASE = "http://static.cninfo.com.cn/"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

# Cache for stock list (loaded once)
_stock_list_cache: list[dict] | None = None


def _load_stock_list() -> list[dict]:
    """Load CNINFO stock list to discover orgIds."""
    global _stock_list_cache
    if _stock_list_cache is not None:
        return _stock_list_cache

    resp = httpx.get(
        CNINFO_STOCK_LIST_URL,
        headers={"User-Agent": _HEADERS["User-Agent"]},
        timeout=30,
    )
    data = resp.json()
    # Response is {"stockList": [{"code": "002594", "orgId": "gshk0001211", "zwjc": "比亚迪", ...}]}
    _stock_list_cache = data.get("stockList", [])
    return _stock_list_cache


def discover_org_id(company_name: str) -> tuple[str, str] | None:
    """Find a company's CNINFO stock code and orgId from its name.

    Searches the CNINFO stock list by:
    1. Chinese short name (zwjc) — exact substring match
    2. Pinyin abbreviation — for English company names (e.g., "BYD" → "byd")

    Args:
        company_name: Company name in any language.

    Returns:
        (stock_code, orgId) tuple, or None if not found.
    """
    stocks = _load_stock_list()
    name_lower = company_name.lower()

    # Build search terms from the company name
    # Extract core name parts for matching
    search_terms: list[str] = []
    for part in name_lower.replace(",", " ").replace(".", " ").split():
        if len(part) >= 2 and part not in ("co", "ltd", "inc", "company", "limited", "corporation"):
            search_terms.append(part)

    for s in stocks:
        code = s.get("code", "")
        zwjc = s.get("zwjc", "")  # Chinese short name
        pinyin = s.get("pinyin", "").lower()  # Pinyin abbreviation
        org_id = s.get("orgId", "")

        if not org_id:
            continue

        # Match by Chinese name
        if zwjc and zwjc in company_name:
            return (code, org_id)

        # Match by pinyin against English name parts
        if pinyin:
            for term in search_terms:
                if term == pinyin or pinyin == term:
                    return (code, org_id)

    return None


def search_filings(
    stock_code: str,
    org_id: str,
    category: str = "",
    date_range: str = "",
    max_results: int = 10,
) -> list[dict]:
    """Search CNINFO for company filings.

    Args:
        stock_code: A-share stock code (e.g., "002594").
        org_id: CNINFO orgId (e.g., "gshk0001211").
        category: Filing category filter. Common values:
            "category_ndbg_szsh" — annual reports (年度报告)
            "category_bndbg_szsh" — semi-annual reports (半年度报告)
            "" — all filings
        date_range: Date filter as "YYYY-MM-DD~YYYY-MM-DD" or empty.
        max_results: Maximum results to return.

    Returns:
        List of filing dicts with: title, filed_date, pdf_url, doc_type.
    """
    data = {
        "stock": f"{stock_code},{org_id}",
        "tabName": "fulltext",
        "column": "szse",
        "category": category,
        "pageNum": "1",
        "pageSize": str(max_results),
        "sortName": "",
        "sortType": "",
        "limit": "",
        "seDate": date_range,
    }

    resp = httpx.post(
        CNINFO_QUERY_URL,
        headers=_HEADERS,
        data=data,
        timeout=30,
    )
    result = resp.json()
    announcements = result.get("announcements") or []

    filings = []
    for ann in announcements:
        title = ann.get("announcementTitle", "")
        date_ms = ann.get("announcementTime", 0)
        adjunct_url = ann.get("adjunctUrl", "")

        if not adjunct_url:
            continue

        # Convert timestamp to date string
        if isinstance(date_ms, (int, float)) and date_ms > 0:
            filed_date = datetime.fromtimestamp(date_ms / 1000).strftime("%Y-%m-%d")
        else:
            filed_date = ""

        # Classify filing type from title
        doc_type = _classify_cn_filing(title)

        filings.append({
            "title": title,
            "filed_date": filed_date,
            "pdf_url": f"{CNINFO_PDF_BASE}{adjunct_url}",
            "doc_type": doc_type,
        })

    return filings


def download_filing(pdf_url: str, output_path: str) -> bool:
    """Download a filing PDF from CNINFO.

    Args:
        pdf_url: Full PDF URL (including static.cninfo.com.cn prefix).
        output_path: Local path to save the PDF.

    Returns:
        True if download succeeded.
    """
    from pathlib import Path

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    resp = httpx.get(
        pdf_url,
        headers={"User-Agent": _HEADERS["User-Agent"]},
        timeout=120,
        follow_redirects=True,
    )
    if resp.status_code == 200 and len(resp.content) > 1000:
        path.write_bytes(resp.content)
        return True
    return False


def _classify_cn_filing(title: str) -> str:
    """Classify a Chinese filing by its title.

    Check order matters: 半年度 (semi-annual) must precede 年度 (annual)
    because 半年度报告 contains 年度报告 as a substring.
    """
    if "半年度报告摘要" in title:
        return "semiannual_summary"
    if "半年度报告" in title:
        return "semiannual_report"
    if "年度报告摘要" in title:
        return "annual_summary"
    if "年度报告" in title:
        return "annual_report"
    if "季度报告" in title:
        return "quarterly_report"
    return "other"
