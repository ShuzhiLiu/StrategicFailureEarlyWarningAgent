"""Regulatory filing discovery and loading.

Determines a company's jurisdiction from its name and regions, then
discovers and loads official filings from the appropriate regulatory
system. Currently supports:

- Japan → EDINET (FSA Electronic Disclosure)
- China → CNINFO (巨潮资讯网, Shenzhen Securities Information)
- (Future) US → SEC EDGAR

The discovery process:
1. Identify jurisdiction from company name + case regions
2. Search the filing system for the company's identifier
3. Find key filings (annual report, semi-annual) before cutoff
4. Download PDFs to local cache (data/corpus/{company}/edinet/)
5. Extract text, filter for strategy-relevant pages, chunk

Cached files are reused across runs — download only happens once.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path

from sfewa import reporting
from sfewa.tools.edinet import (
    EDINET_BASE,
    search_filings_by_date,
    download_pdf,
    extract_text_from_pdf,
)

CORPUS_BASE = Path(__file__).resolve().parents[3] / "data" / "corpus"

# Patterns for identifying Japanese companies
_JAPAN_PATTERNS = [
    "honda", "toyota", "nissan", "mazda", "subaru", "suzuki",
    "mitsubishi motors", "daihatsu", "isuzu", "hino",
    "sony", "panasonic", "hitachi", "toshiba", "fujitsu",
    "softbank", "rakuten", "nomura", "daiwa", "mizuho",
    "sumitomo", "mitsui", "marubeni", "itochu",
]

# Patterns for identifying Chinese companies
_CHINA_PATTERNS = [
    "byd", "nio", "xpeng", "li auto", "geely", "changan",
    "saic", "great wall", "chery", "dongfeng",
    "alibaba", "tencent", "baidu", "xiaomi", "huawei",
    "catl", "sinopec", "petrochina", "icbc", "ping an",
]

# Keywords for filtering EV-relevant pages from large filings
# Bilingual: English + Japanese + Chinese
_STRATEGY_KEYWORDS = [
    # English
    "EV", "BEV", "FCEV", "HEV", "battery", "electrification",
    "electric vehicle", "zero emission", "charging",
    "investment", "risk", "strategy", "R&D",
    "software defined", "ADAS", "autonomous",
    # Japanese
    "電動", "電気自動車", "バッテリー", "充電", "リスク",
    "投資", "戦略", "計画", "研究開発",
    # Chinese
    "电动", "电池", "新能源", "充电", "投资",
    "风险", "战略", "研发",
]


def _page_relevance(text: str) -> int:
    """Count strategy-related keyword hits in a page of text."""
    text_lower = text.lower()
    return sum(1 for kw in _STRATEGY_KEYWORDS if kw.lower() in text_lower)


# ── Jurisdiction identification ──


def identify_jurisdiction(company: str, regions: list[str] | None = None) -> str | None:
    """Determine a company's primary filing jurisdiction.

    Uses company name patterns and case regions to infer where the company
    files regulatory disclosures.

    Returns:
        "japan", "china", or None (unknown/unsupported).
    """
    name_lower = company.lower()
    regions_lower = [r.lower() for r in (regions or [])]

    # Check company name patterns first (most reliable)
    for pattern in _JAPAN_PATTERNS:
        if pattern in name_lower:
            return "japan"
    for pattern in _CHINA_PATTERNS:
        if pattern in name_lower:
            return "china"

    # Fall back to region hints
    if "japan" in regions_lower or "tokyo" in regions_lower:
        return "japan"
    if "china" in regions_lower or "shenzhen" in regions_lower or "shanghai" in regions_lower:
        return "china"

    return None


# ── EDINET discovery (Japan) ──


def _discover_edinet_code(
    company: str,
    scan_months: list[tuple[int, int]] | None = None,
) -> tuple[str, str] | None:
    """Discover a company's EDINET code by scanning filing dates.

    Japanese companies file annual reports around June and semi-annual
    reports around November. We scan these windows and match by filer name.

    Args:
        company: Company name (used for matching in Japanese filer names).
        scan_months: List of (year, month) to scan. Defaults to recent filing windows.

    Returns:
        (edinet_code, sec_code) tuple, or None if not found.
    """
    # Build search terms from company name
    name_lower = company.lower()
    # Extract the core company name for matching
    search_terms = []
    for pattern in _JAPAN_PATTERNS:
        if pattern in name_lower:
            search_terms.append(pattern)
            break

    # Japanese name patterns for common companies
    _jp_names: dict[str, list[str]] = {
        "honda": ["本田技研工業", "ホンダ"],
        "toyota": ["トヨタ自動車", "トヨタ"],
        "nissan": ["日産自動車", "ニッサン"],
        "mazda": ["マツダ"],
        "subaru": ["SUBARU", "スバル"],
        "suzuki": ["スズキ"],
        "sony": ["ソニーグループ", "ソニー"],
        "panasonic": ["パナソニック"],
    }

    jp_search = []
    for key, names in _jp_names.items():
        if key in name_lower:
            jp_search.extend(names)
            break

    if not jp_search and not search_terms:
        return None

    # Default scan windows: recent June (annual) and November (semi-annual)
    if scan_months is None:
        scan_months = [(2024, 6), (2024, 11)]

    for year, month in scan_months:
        # Scan ~15 days in each window
        start = date(year, month, 15)
        end = date(year, month, 28) if month != 11 else date(year, month, 15)

        d = start
        while d <= end:
            try:
                resp_data = _edinet_documents_for_date(d)
                for r in resp_data:
                    filer = r.get("filerName", "") or ""
                    # Match against Japanese names
                    for jp_name in jp_search:
                        if jp_name in filer:
                            code = r.get("edinetCode", "")
                            sec = r.get("secCode", "")
                            if code:
                                return (code, sec or "")
                    # Match against English name fragments
                    filer_lower = filer.lower()
                    for term in search_terms:
                        if term in filer_lower:
                            code = r.get("edinetCode", "")
                            sec = r.get("secCode", "")
                            if code:
                                return (code, sec or "")
            except Exception:
                pass
            d += timedelta(days=1)
            time.sleep(0.3)

    return None


def _edinet_documents_for_date(target_date: date) -> list[dict]:
    """Fetch all EDINET filings for a specific date (raw results)."""
    import httpx
    import os

    key = os.environ.get("EDINET_API_KEY", "")
    if not key:
        return []

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
    if data.get("metadata", {}).get("status") != "200":
        return []
    return data.get("results", [])


def _find_key_filings_edinet(
    edinet_code: str,
    sec_code: str,
    cutoff: str,
) -> list[dict]:
    """Find key filings for a company on EDINET before the cutoff date.

    Scans filing windows (June for annual, November for semi-annual)
    in the year before and year of the cutoff.

    Returns filing metadata dicts with doc_id, title, filed_date, doc_type.
    """
    cutoff_date = date.fromisoformat(cutoff)
    cutoff_year = cutoff_date.year

    # Scan windows: annual (June), semi-annual (November), plus Q1 extraordinary
    scan_ranges = []
    for year in [cutoff_year - 1, cutoff_year]:
        # June: annual reports + extraordinary (AGM)
        scan_ranges.append((date(year, 6, 1), date(year, 6, 30)))
        # November: semi-annual reports
        scan_ranges.append((date(year, 11, 1), date(year, 11, 30)))
        # May: extraordinary reports (earnings, etc.)
        scan_ranges.append((date(year, 5, 1), date(year, 5, 19)))

    edinet_codes = [edinet_code]
    filings: list[dict] = []
    seen_docs: set[str] = set()

    for start, end in scan_ranges:
        if start > cutoff_date:
            continue
        end = min(end, cutoff_date)

        d = start
        while d <= end:
            try:
                results = search_filings_by_date(
                    d, edinet_codes=edinet_codes, sec_code=sec_code,
                )
                for r in results:
                    doc_id = r.get("docID", "")
                    if not doc_id or doc_id in seen_docs:
                        continue
                    seen_docs.add(doc_id)

                    title = r.get("docDescription", "") or ""
                    doc_type = _classify_filing_type(title)

                    # Only keep substantive filings
                    if doc_type in ("annual_report", "semiannual_report", "extraordinary_report"):
                        filings.append({
                            "doc_id": doc_id,
                            "title": title,
                            "filed_date": d.isoformat(),
                            "doc_type": doc_type,
                            "filer_name": r.get("filerName", ""),
                        })
            except Exception:
                pass
            d += timedelta(days=1)
            time.sleep(0.3)

    # Deduplicate: keep the most recent annual + semi-annual + up to 2 extraordinary
    annual = [f for f in filings if f["doc_type"] == "annual_report"]
    semi = [f for f in filings if f["doc_type"] == "semiannual_report"]
    extra = [f for f in filings if f["doc_type"] == "extraordinary_report"]

    # Keep most recent of each type
    key_filings = []
    if annual:
        key_filings.append(annual[-1])  # most recent annual
    if semi:
        key_filings.append(semi[-1])  # most recent semi-annual
    key_filings.extend(extra[-2:])  # up to 2 most recent extraordinary

    return key_filings


def _classify_filing_type(title: str) -> str:
    """Classify a Japanese filing by its title."""
    if "有価証券報告書" in title:
        return "annual_report"
    if "半期報告書" in title:
        return "semiannual_report"
    if "臨時報告書" in title:
        return "extraordinary_report"
    if "四半期報告書" in title:
        return "quarterly_report"
    # Skip administrative filings
    if any(skip in title for skip in ["確認書", "内部統制", "訂正", "変更報告", "自己株券"]):
        return "administrative"
    return "other"


# ── Download and extraction ──


def _download_filing(doc_id: str, cache_dir: Path, filename: str) -> Path | None:
    """Download a filing PDF to cache, or return cached path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = cache_dir / filename

    if pdf_path.exists():
        reporting.log_action(f"Using cached: {filename}")
        return pdf_path

    try:
        reporting.log_action(f"Downloading EDINET filing: {doc_id}")
        return download_pdf(doc_id, pdf_path)
    except Exception as e:
        reporting.log_action(f"Download failed: {doc_id}", {"error": str(e)[:100]})
        return None


def _extract_and_chunk(
    pdf_path: Path,
    doc_type: str,
    max_pages: int = 80,
    min_relevance: int = 2,
    chunk_size: int = 4000,
) -> list[str]:
    """Extract text from a filing PDF and chunk it.

    Annual reports: filter for strategy-relevant pages only.
    Smaller reports: extract full text.
    """
    import pdfplumber

    if doc_type == "annual_report":
        # Large document — filter for relevant pages
        relevant = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                text = page.extract_text()
                if text and _page_relevance(text) >= min_relevance:
                    relevant.append(f"[Page {i + 1}]\n{text}")
        text = "\n\n".join(relevant)
    else:
        text = extract_text_from_pdf(pdf_path, max_pages=50)

    if not text.strip():
        return []

    # Chunk into manageable pieces
    chunks: list[str] = []
    if len(text) > chunk_size + 500:
        for start in range(0, len(text), chunk_size):
            chunk = text[start : start + chunk_size]
            if chunk.strip():
                chunks.append(chunk)
    else:
        chunks = [text]

    return chunks


# ── Main discovery + loading function ──


def discover_and_load_filings(
    company: str,
    cutoff_date: str,
    regions: list[str] | None = None,
) -> list[dict]:
    """Discover and load regulatory filings for a company.

    1. Identifies the company's jurisdiction from name + regions
    2. Searches the appropriate filing system for company filings
    3. Downloads PDFs to local cache
    4. Extracts text, filters for relevant content, chunks

    Returns:
        List of document dicts compatible with retrieved_docs format.
    """
    jurisdiction = identify_jurisdiction(company, regions)

    if jurisdiction is None:
        reporting.log_action("Filing discovery: unknown jurisdiction", {
            "company": company,
            "regions": regions or [],
        })
        return []

    if jurisdiction == "japan":
        return _discover_and_load_edinet(company, cutoff_date)

    if jurisdiction == "china":
        return _discover_and_load_cninfo(company, cutoff_date)

    return []


def _discover_and_load_edinet(company: str, cutoff_date: str) -> list[dict]:
    """Full EDINET discovery pipeline for a Japanese company.

    Steps:
    1. Check if filings are already cached locally
    2. If not, discover EDINET code by scanning filing dates
    3. Find key filings (annual, semi-annual, extraordinary)
    4. Download PDFs to cache
    5. Extract text, chunk, return as docs
    """
    # Determine cache directory from company name
    name_lower = company.lower()
    company_key = "unknown"
    for pattern in _JAPAN_PATTERNS:
        if pattern in name_lower:
            company_key = pattern
            break

    cache_dir = CORPUS_BASE / company_key / "edinet"

    # Check for existing cached PDFs
    cached_pdfs = list(cache_dir.glob("*.pdf")) if cache_dir.exists() else []
    if cached_pdfs:
        reporting.log_action(f"Found {len(cached_pdfs)} cached EDINET PDFs", {
            "company": company_key,
            "dir": str(cache_dir),
        })
        return _load_cached_filings(cache_dir, cached_pdfs, company_key)

    # No cache — discover EDINET code
    reporting.log_action(f"Discovering EDINET code for {company}")
    result = _discover_edinet_code(company)
    if result is None:
        reporting.log_action("EDINET code not found — skipping regulatory filings")
        return []

    edinet_code, sec_code = result
    reporting.log_action(f"Found EDINET code: {edinet_code}", {
        "sec_code": sec_code,
    })

    # Find key filings
    reporting.log_action("Scanning EDINET for key filings")
    filings = _find_key_filings_edinet(edinet_code, sec_code, cutoff_date)
    if not filings:
        reporting.log_action("No key filings found before cutoff")
        return []

    reporting.log_action(f"Found {len(filings)} key filings", {
        "types": [f["doc_type"] for f in filings],
    })

    # Download and extract
    docs: list[dict] = []
    for filing in filings:
        doc_type = filing["doc_type"]
        filename = f"{company_key}_{doc_type}_{filing['filed_date']}.pdf"
        pdf_path = _download_filing(filing["doc_id"], cache_dir, filename)
        if pdf_path is None:
            continue

        chunks = _extract_and_chunk(pdf_path, doc_type)
        if not chunks:
            reporting.log_action(f"No text extracted: {filename}")
            continue

        for i, chunk in enumerate(chunks):
            suffix = f" (Section {i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            docs.append({
                "title": f"[EDINET] {filing['title']}{suffix}",
                "snippet": chunk,
                "link": f"edinet:{filing['doc_id']}",
                "source": "edinet",
                "source_type": "company_filing",
                "credibility_tier": "tier1_primary",
                "published_at": filing["filed_date"],
            })

        reporting.log_action("Loaded EDINET filing", {
            "file": filename,
            "type": doc_type,
            "chunks": len(chunks),
            "filed_date": filing["filed_date"],
        })

    return docs


def _discover_and_load_cninfo(company: str, cutoff_date: str) -> list[dict]:
    """Full CNINFO discovery pipeline for a Chinese company.

    Steps:
    1. Check if filings are already cached locally
    2. If not, discover stock code + orgId from CNINFO stock list
    3. Search for annual + semi-annual reports before cutoff
    4. Download PDFs to cache
    5. Extract text, chunk, return as docs
    """
    from sfewa.tools.cninfo import discover_org_id, search_filings, download_filing

    # Determine cache directory from company name
    name_lower = company.lower()
    company_key = "unknown"
    for pattern in _CHINA_PATTERNS:
        if pattern in name_lower:
            company_key = pattern
            break

    cache_dir = CORPUS_BASE / company_key / "cninfo"

    # Check for existing cached PDFs
    cached_pdfs = list(cache_dir.glob("*.pdf")) if cache_dir.exists() else []
    if cached_pdfs:
        reporting.log_action(f"Found {len(cached_pdfs)} cached CNINFO PDFs", {
            "company": company_key,
            "dir": str(cache_dir),
        })
        return _load_cached_filings(cache_dir, cached_pdfs, company_key, source="cninfo")

    # Discover stock code + orgId from company name
    reporting.log_action(f"Discovering CNINFO stock code for {company}")
    result = discover_org_id(company)
    if result is None:
        reporting.log_action("CNINFO stock code not found — skipping regulatory filings")
        return []

    stock_code, org_id = result
    reporting.log_action(f"Found CNINFO: stock={stock_code}, orgId={org_id}")

    # Search for key filings before cutoff
    date_range = f"2023-01-01~{cutoff_date}"
    all_filings: list[dict] = []

    for category, label in [
        ("category_ndbg_szsh", "annual"),
        ("category_bndbg_szsh", "semi-annual"),
    ]:
        filings = search_filings(
            stock_code, org_id,
            category=category,
            date_range=date_range,
            max_results=5,
        )
        # Filter: keep full reports, skip summaries
        for f in filings:
            if f["doc_type"] in ("annual_report", "semiannual_report"):
                all_filings.append(f)

        reporting.log_action(f"CNINFO {label} search", {
            "found": len(filings),
            "kept": sum(1 for f in filings if f["doc_type"] in ("annual_report", "semiannual_report")),
        })

    if not all_filings:
        reporting.log_action("No key filings found before cutoff on CNINFO")
        return []

    # Keep most recent annual + most recent semi-annual
    annual = [f for f in all_filings if f["doc_type"] == "annual_report"]
    semi = [f for f in all_filings if f["doc_type"] == "semiannual_report"]
    key_filings = []
    if annual:
        key_filings.append(annual[0])  # most recent (sorted by date desc from API)
    if semi:
        key_filings.append(semi[0])

    reporting.log_action(f"Downloading {len(key_filings)} CNINFO filings")

    # Download and extract
    docs: list[dict] = []
    cache_dir.mkdir(parents=True, exist_ok=True)

    for filing in key_filings:
        doc_type = filing["doc_type"]
        filename = f"{company_key}_{doc_type}_{filing['filed_date']}.pdf"
        pdf_path = cache_dir / filename

        if not pdf_path.exists():
            reporting.log_action(f"Downloading CNINFO filing: {filing['title']}")
            if not download_filing(filing["pdf_url"], str(pdf_path)):
                reporting.log_action(f"Download failed: {filing['title']}")
                continue
            time.sleep(1)  # polite delay between downloads
        else:
            reporting.log_action(f"Using cached: {filename}")

        chunks = _extract_and_chunk(pdf_path, doc_type)
        if not chunks:
            reporting.log_action(f"No text extracted: {filename}")
            continue

        for i, chunk in enumerate(chunks):
            suffix = f" (Section {i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            docs.append({
                "title": f"[CNINFO] {filing['title']}{suffix}",
                "snippet": chunk,
                "link": filing["pdf_url"],
                "source": "cninfo",
                "source_type": "company_filing",
                "credibility_tier": "tier1_primary",
                "published_at": filing["filed_date"],
            })

        reporting.log_action("Loaded CNINFO filing", {
            "file": filename,
            "type": doc_type,
            "chunks": len(chunks),
            "filed_date": filing["filed_date"],
        })

    return docs


def _load_cached_filings(
    cache_dir: Path,
    pdf_files: list[Path],
    company_key: str,
    source: str = "edinet",
) -> list[dict]:
    """Load previously cached filing PDFs.

    Infers doc_type and filed_date from filename patterns.

    Args:
        source: Filing system identifier ("edinet" or "cninfo").
    """
    docs: list[dict] = []
    source_label = source.upper()

    for pdf_path in sorted(pdf_files):
        filename = pdf_path.name
        # Infer doc type from filename
        if "semiannual" in filename or "semi_annual" in filename:
            doc_type = "semiannual_report"
        elif "annual" in filename:
            doc_type = "annual_report"
        elif "extraordinary" in filename:
            doc_type = "extraordinary_report"
        else:
            doc_type = "other"

        # Infer filed date from filename (pattern: *_YYYYMMDD.pdf or *_fyYYYY.pdf)
        filed_date = _infer_date_from_filename(filename)

        chunks = _extract_and_chunk(pdf_path, doc_type)
        if not chunks:
            continue

        title = f"{company_key.title()} {doc_type.replace('_', ' ').title()}"
        link = f"{source}:{pdf_path.stem}"

        for i, chunk in enumerate(chunks):
            suffix = f" (Section {i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            docs.append({
                "title": f"[{source_label}] {title}{suffix}",
                "snippet": chunk,
                "link": link,
                "source": source,
                "source_type": "company_filing",
                "credibility_tier": "tier1_primary",
                "published_at": filed_date,
            })

        reporting.log_action(f"Loaded cached {source_label} filing", {
            "file": filename,
            "type": doc_type,
            "chunks": len(chunks),
        })

    return docs


def _infer_date_from_filename(filename: str) -> str:
    """Best-effort date extraction from filing filename."""
    import re
    # Pattern: YYYYMMDD or YYYY-MM-DD
    m = re.search(r"(\d{4})(\d{2})(\d{2})", filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # Pattern: fy2023 → approximate as mid-year filing
    m = re.search(r"fy(\d{4})", filename)
    if m:
        return f"{int(m.group(1)) + 1}-06-15"  # annual reports filed ~June next year
    return "2024-06-01"  # fallback
