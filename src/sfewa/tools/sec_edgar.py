"""SEC EDGAR client for fetching US public-company filings (L2.2).

EDGAR (Electronic Data Gathering, Analysis, and Retrieval) is the SEC's
filing system. Unlike HKEXnews (JSF UI scrape) or EDINET (date-window
scan + PDF parsing), EDGAR exposes a free, well-designed JSON API at
`data.sec.gov` — no scraping, no session state, no auth. The only
constraint is a `User-Agent` header (the SEC asks callers to identify
themselves) and a 10 req/sec rate limit.

Endpoints used:
    company_tickers.json    — ticker → CIK mapping (one file, ~10K issuers)
    submissions/CIK{...}.json — per-issuer filing feed
    Archives/edgar/data/...   — direct artifact (HTML) download

All filings on EDGAR are filed in machine-readable HTML; we extract text
via beautifulsoup4 (already a project dependency).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import httpx

EDGAR_BASE = "https://www.sec.gov"
EDGAR_DATA_BASE = "https://data.sec.gov"

# The SEC requires a descriptive User-Agent. Default falls back to the
# project name + an env-overridable contact email so single-user runs work
# without configuration.
DEFAULT_USER_AGENT = (
    "SFEWA Research "
    + os.environ.get("SFEWA_CONTACT_EMAIL", "sfewa-noreply@local.invalid")
)


def _user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }


# ── CIK lookup ──


def lookup_cik(
    ticker_or_name: str,
    *,
    tickers_payload: dict | None = None,
) -> str | None:
    """Resolve a ticker or company name to a 10-digit zero-padded CIK.

    Args:
        ticker_or_name: Stock ticker (case-insensitive) or company name fragment.
        tickers_payload: Pre-loaded company_tickers.json (for tests). When
            None, fetches live from sec.gov.

    Returns:
        Zero-padded 10-digit CIK string ("0001318605" for Tesla), or None
        when no match is found.
    """
    if tickers_payload is None:
        tickers_payload = _fetch_company_tickers()
    if not tickers_payload:
        return None

    target = (ticker_or_name or "").strip().upper()
    if not target:
        return None

    # Pass 1: exact ticker match (most reliable)
    for entry in tickers_payload.values():
        ticker = (entry.get("ticker") or "").upper()
        if ticker == target:
            return _pad_cik(entry["cik_str"])

    # Pass 2: name match on the SEC company title.
    # Only run when the input looks like a name (>5 chars, has spaces, etc.).
    if len(target) > 5 or " " in target:
        target_norm = _normalize_company_name(target)
        if not target_norm:
            return None
        for entry in tickers_payload.values():
            title = (entry.get("title") or "").upper()
            title_norm = _normalize_company_name(title)
            if not title_norm:
                continue
            # Bidirectional containment after stripping common corporate
            # suffixes — handles "The Boeing Company" vs "BOEING CO" by
            # comparing on the core token set.
            if target_norm == title_norm:
                return _pad_cik(entry["cik_str"])
            if title_norm in target_norm or target_norm in title_norm:
                return _pad_cik(entry["cik_str"])

    return None


_CORPORATE_STOPWORDS = {
    "THE", "COMPANY", "CO", "CORPORATION", "CORP", "INC", "INCORPORATED",
    "LIMITED", "LTD", "LLC", "PLC", "HOLDINGS", "GROUP", "&",
}


def _normalize_company_name(name: str) -> str:
    """Drop common corporate suffixes/prefixes for fuzzy name matching.

    "THE BOEING COMPANY" → "BOEING"
    "BOEING CO"          → "BOEING"
    "FORD MOTOR CO"      → "FORD MOTOR"
    "Apple Inc."         → "APPLE"

    Returns the normalized form (uppercase, single-spaced). Empty when
    every token was a stopword.
    """
    import re

    cleaned = re.sub(r"[.,]", " ", name.upper())
    tokens = [t for t in cleaned.split() if t and t not in _CORPORATE_STOPWORDS]
    return " ".join(tokens)


def _fetch_company_tickers() -> dict:
    """Fetch the ticker → CIK mapping from sec.gov.

    The endpoint returns ~10K rows keyed by stringified integer index;
    the structure is `{0: {"cik_str": int, "ticker": str, "title": str}, ...}`.
    """
    try:
        resp = httpx.get(
            f"{EDGAR_BASE}/files/company_tickers.json",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return {}


def _pad_cik(cik: int | str) -> str:
    """Pad a CIK to the 10-digit form required by data.sec.gov endpoints."""
    return str(cik).zfill(10)


# ── Submissions feed ──


def get_submissions(cik: str) -> dict:
    """Fetch the per-issuer submissions feed (`data.sec.gov/submissions/`).

    Returns the raw JSON. Caller is responsible for walking
    `filings.recent` and applying date/doc-type filters.
    """
    cik_padded = _pad_cik(cik)
    try:
        resp = httpx.get(
            f"{EDGAR_DATA_BASE}/submissions/CIK{cik_padded}.json",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return {}


def find_filings(
    cik: str,
    *,
    cutoff_date: str,
    forms: list[str] | None = None,
    from_date: str | None = None,
    submissions_payload: dict | None = None,
    max_per_form: int = 2,
) -> list[dict]:
    """Walk `filings.recent` and return strategy-relevant filings before cutoff.

    Args:
        cik: 10-digit padded CIK (or any form `_pad_cik` accepts).
        cutoff_date: ISO date "YYYY-MM-DD" — strict-greater rejection.
        forms: SEC form types to keep ("10-K", "10-Q", "8-K", "DEF 14A").
            Defaults to ["10-K", "10-Q", "8-K", "DEF 14A"].
        from_date: ISO date — earliest filing date to consider. Defaults to
            cutoff - ~3 years.
        submissions_payload: Pre-loaded submissions JSON (for tests).
        max_per_form: Cap kept filings per form type (avoid drowning in
            8-K filings; the most recent few per type cover the strategic surface).

    Returns:
        List of dicts with keys: accession_number, form, filing_date,
        report_date, primary_document, primary_doc_description, size, cik.
        Sorted: most recent first.
    """
    if forms is None:
        forms = ["10-K", "10-Q", "8-K", "DEF 14A"]

    if submissions_payload is None:
        submissions_payload = get_submissions(cik)
    if not submissions_payload:
        return []

    recent = submissions_payload.get("filings", {}).get("recent", {})
    if not recent:
        return []

    accessions = recent.get("accessionNumber", [])
    if not accessions:
        return []

    cik_padded = _pad_cik(submissions_payload.get("cik") or cik)

    found: list[dict] = []
    for i, acc in enumerate(accessions):
        form = recent["form"][i] if i < len(recent.get("form", [])) else ""
        if form not in forms:
            continue

        filing_date = recent["filingDate"][i] if i < len(recent.get("filingDate", [])) else ""
        if not filing_date:
            continue

        # Cutoff (strict greater-than) — we keep filings on or before cutoff.
        if filing_date > cutoff_date:
            continue

        if from_date and filing_date < from_date:
            continue

        primary_doc = (
            recent["primaryDocument"][i]
            if i < len(recent.get("primaryDocument", []))
            else ""
        )
        if not primary_doc:
            continue

        found.append({
            "accession_number": acc,
            "form": form,
            "filing_date": filing_date,
            "report_date": (
                recent["reportDate"][i] if i < len(recent.get("reportDate", [])) else ""
            ),
            "acceptance_datetime": (
                recent["acceptanceDateTime"][i]
                if i < len(recent.get("acceptanceDateTime", []))
                else ""
            ),
            "primary_document": primary_doc,
            "primary_doc_description": (
                recent["primaryDocDescription"][i]
                if i < len(recent.get("primaryDocDescription", []))
                else ""
            ),
            "size": recent["size"][i] if i < len(recent.get("size", [])) else 0,
            "cik": cik_padded,
        })

    # Cap per-form to avoid drowning in 8-K. Sort by date descending first
    # so the most recent of each type wins.
    found.sort(key=lambda f: f["filing_date"], reverse=True)
    per_form: dict[str, int] = {}
    capped: list[dict] = []
    for f in found:
        per_form.setdefault(f["form"], 0)
        if per_form[f["form"]] >= max_per_form:
            continue
        per_form[f["form"]] += 1
        capped.append(f)

    return capped


# ── Doc-type taxonomy ──


def classify_filing(form: str) -> str:
    """Map an SEC form type to the project-wide doc_type vocabulary.

    Vocabulary (shared across EDINET / CNINFO / HKEX / SEC):
        annual_report, interim_report, results_announcement,
        inside_information, circulars, other.

    Form mapping:
        10-K, 20-F, 40-F → annual_report
        10-Q, 6-K        → interim_report
        8-K              → inside_information (most analogous to HKEX category)
        DEF 14A, 14A     → circulars (proxy / governance circular)
        S-1, S-3, S-4    → other (registration; rarely strategic-signal)
    """
    f = (form or "").strip().upper()
    if f in ("10-K", "20-F", "40-F"):
        return "annual_report"
    if f in ("10-Q", "6-K"):
        return "interim_report"
    if f in ("8-K",):
        return "inside_information"
    if f in ("DEF 14A", "14A", "PRE 14A"):
        return "circulars"
    return "other"


# ── Download ──


def primary_document_url(cik: str, accession_number: str, primary_document: str) -> str:
    """Construct the direct-artifact URL for a filing's primary document.

    Format: https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_dashes}/{primaryDocument}
    Note: Archives uses the un-padded CIK as an integer (no leading zeros).
    """
    cik_int = str(int(cik))
    acc_no_dashes = accession_number.replace("-", "")
    return f"{EDGAR_BASE}/Archives/edgar/data/{cik_int}/{acc_no_dashes}/{primary_document}"


def download_primary_document(
    cik: str,
    accession_number: str,
    primary_document: str,
    dest: Path,
    *,
    timeout: float = 60.0,
) -> Path:
    """Download a filing's primary document to `dest`. Returns dest path.

    The SEC asks for a single request per second; callers in a loop should
    sleep ≥ 0.1s between calls (rate limit is 10/s).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = primary_document_url(cik, accession_number, primary_document)
    headers = {
        "User-Agent": _user_agent(),
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Encoding": "gzip, deflate",
    }
    resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


# ── Extraction ──


def extract_text_from_html(path: Path, *, max_chars: int = 1_000_000) -> str:
    """Extract visible text from an SEC EDGAR HTML filing.

    SEC filings are XBRL-tagged HTML; the boilerplate (navigation, XBRL
    overlays, footnote markers) is best stripped before chunking. We use
    BeautifulSoup to drop <script>/<style> and condense whitespace, then
    cap to `max_chars` (a 10-K can be 15MB+ — the tail is mostly XBRL
    instance data, not strategic prose).
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("beautifulsoup4 required for SEC EDGAR extraction") from e

    raw = path.read_bytes()
    soup = BeautifulSoup(raw, "html.parser")

    # Drop script/style/XBRL link refs
    for tag in soup(["script", "style", "link", "meta"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    # Collapse runs of whitespace; preserve paragraph breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def sleep_for_rate_limit() -> None:
    """SEC asks callers to stay under 10 req/sec. 0.12s between calls is safe."""
    time.sleep(0.12)


__all__ = [
    "EDGAR_BASE",
    "EDGAR_DATA_BASE",
    "lookup_cik",
    "get_submissions",
    "find_filings",
    "classify_filing",
    "primary_document_url",
    "download_primary_document",
    "extract_text_from_html",
    "sleep_for_rate_limit",
]
