"""HKEXnews live discovery (L2.1).

Two discovery paths, in priority order:

1. **DuckDuckGo `site:hkexnews.hk filetype:pdf` search** (no extra deps,
   default path). The HKEXnews PDF archive is publicly indexed; queries
   like ``Country Garden 2022 annual report site:hkexnews.hk filetype:pdf``
   return direct URLs of the form
   ``https://www1.hkexnews.hk/listedco/listconews/sehk/{YYYY}/{MMDD}/{announcementId}.pdf``
   that download without auth. When DDG surfaces the right filing, this
   path is fast, dep-free, and produces real Tier-1 audit evidence.

2. **Headless Playwright JSF scrape** (optional dep). Fallback when
   DDG coverage is thin (e.g., Tencent / Ping An 2023 filings did not
   surface in DDG during L2.1 probing). Drives titlesearch.xhtml. Adds
   ~5MB Python + ~300MB browser binaries via
   ``pip install playwright && playwright install chromium``.

Both paths return a list of filing-metadata dicts in the same shape:

    {"announcement_id": str, "title": str, "release_time": ISO 8601 +08:00,
     "pdf_url": str, "doc_type": str}

Why not manual pre-staging (the L1.2 fallback)? Because the agent
should fetch its own evidence — that's the SFEWA thesis. Manual
staging breaks the audit story for any new HK case.

Usage:

    from sfewa.tools.hkex_live_discovery import live_discover_filings
    filings = live_discover_filings(
        company="Country Garden Holdings Company Limited",
        stock_id="02007",
        from_date="2021-01-01",
        to_date="2023-07-31",
    )
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any

from sfewa import reporting

log = logging.getLogger(__name__)

HKEX_TITLESEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"

# Direct PDF URL pattern (verified alive):
# https://www1.hkexnews.hk/listedco/listconews/sehk/{YYYY}/{MMDD}/{announcementId}.pdf
HKEX_PDF_URL_PATTERN = re.compile(
    r"https?://www\d?\.hkexnews\.hk/listedco/listconews/sehk/(\d{4})/(\d{4})/(\d+)\.pdf"
)

# Filing-type keywords for doc-type classification from search-result titles.
# Each entry is `(keyword_or_tuple, classification)`. When the first
# element is a tuple, ANY of its keywords matches.
_DOC_TYPE_KEYWORDS: list[tuple[str | tuple[str, ...], str]] = [
    ("annual report",                                  "annual_report"),
    ("annual results",                                 "results_announcement"),
    ("interim report",                                 "interim_report"),
    ("interim results",                                "results_announcement"),
    ("results announcement",                           "results_announcement"),
    ("inside information",                             "inside_information"),
    ("circular",                                       "circulars"),
    (("notice of egm", "notice of agm"),               "circulars"),
]


def is_playwright_available() -> bool:
    """Probe whether the Playwright Python package is importable.

    Does NOT verify a browser binary is installed. The optional fallback
    path raises if Playwright is installed but no browser binary; that's
    a configuration error we surface rather than swallow.
    """
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


# ── Public entry point ──


def live_discover_filings(
    *,
    company: str | None = None,
    stock_id: str | None = None,
    from_date: str,
    to_date: str,
    doc_categories: list[str] | None = None,
    max_results: int = 12,
    timeout_ms: int = 30_000,
) -> list[dict[str, Any]]:
    """Discover HKEXnews filings for an issuer up to `to_date`.

    Args:
        company: Issuer's English name. Required for the DDG path.
        stock_id: HKEXnews internal stockId (5-digit padded form, e.g.
            "02318" for Ping An). Required for the Playwright fallback.
            Optional when DDG-only.
        from_date / to_date: ISO dates ("YYYY-MM-DD"). Filings outside
            this window are filtered post-discovery.
        doc_categories: Optional doc_type filter ("annual_report",
            "interim_report", "results_announcement"). When None, all
            classified types are returned.
        max_results: Cap on rows returned.
        timeout_ms: Per-action timeout for the Playwright path.

    Returns:
        List of filing-metadata dicts. Empty when neither path yields
        results (network failures + dep-missing + no DDG hits).
    """
    rows: list[dict[str, Any]] = []

    # Path 1: DDG-based discovery (default)
    if company:
        rows = _ddg_discover(
            company=company,
            stock_id=stock_id,
            from_date=from_date,
            to_date=to_date,
            max_results=max_results,
        )
        if rows:
            reporting.log_action("HKEX live discovery succeeded (DDG path)", {
                "company": company,
                "rows": len(rows),
            })

    # Path 2: Playwright fallback when DDG returned nothing
    if not rows and stock_id and is_playwright_available():
        try:
            rows = _run_playwright_discovery(
                stock_id=stock_id,
                from_date=from_date,
                to_date=to_date,
                timeout_ms=timeout_ms,
                max_results=max_results,
            )
            if rows:
                reporting.log_action("HKEX live discovery succeeded (Playwright path)", {
                    "stock_id": stock_id,
                    "rows": len(rows),
                })
        except Exception as exc:  # noqa: BLE001 — broad catch by design
            reporting.log_action("HKEX Playwright path failed", {
                "stock_id": stock_id,
                "error_type": exc.__class__.__name__,
                "error": str(exc)[:200],
            })

    if not rows:
        reporting.log_action("HKEX live discovery returned 0 rows", {
            "company": company, "stock_id": stock_id,
            "ddg_tried": bool(company),
            "playwright_tried": bool(stock_id) and is_playwright_available(),
        })

    # Post-discovery filter on doc_categories (caller can scope to e.g.
    # ["annual_report", "interim_report"])
    if doc_categories:
        rows = [r for r in rows if r.get("doc_type") in doc_categories]

    return rows[:max_results]


# ── Path 1: DDG-based discovery ──


def _build_ddg_queries(
    *, short_name: str, stock_id: str | None, cutoff_year: int, lookback_years: int,
) -> list[str]:
    """Construct the ranked DDG query list for HKEX discovery.

    DDG indexing is highly verbosity-sensitive. The L2.1 probe found
    that short company names plus a year and `site:hkexnews.hk
    filetype:pdf` surface HKEX archive URLs reliably for Country Garden
    but not for Tencent or Ping An. Broadening the query set with
    doc-type variants and a 4-digit ticker anchor materially improves
    coverage on the harder issuers without paid API access.

    Query priority order:
        1. Year + doc-type + short name + site/filetype  (most selective)
        2. Year + doc-type + short name + site (no filetype)
        3. Stock-id-anchored when ticker known
        4. Generic short-name + site/filetype (no year, no doc-type)
        5. Doc-type-only fallbacks (no year, no name precision)

    Doc-type variants cover the actual title patterns HKEX uses:
    "annual report", "interim report", "annual results", "interim
    results", "results announcement", "circular".
    """
    # Trim ticker to 4-digit form ("00700" → "700"). DDG indexes both
    # zero-padded and bare forms; bare form has higher recall.
    ticker_short: str | None = None
    if stock_id:
        ticker_short = stock_id.lstrip("0") or stock_id

    # Year range — search backward from cutoff_year. lookback_years=2 by
    # default covers the agent's standard 2-year window without
    # over-querying.
    year_window = list(range(cutoff_year, cutoff_year - lookback_years - 1, -1))

    # Doc-type variants — these are the actual title forms HKEX uses.
    # Keep order consistent with how often they appear in practice.
    doc_terms = (
        "annual report",
        "interim report",
        "annual results",
        "interim results",
        "results announcement",
    )

    queries: list[str] = []

    # Tier 1: year + doc-type + short_name + site/filetype
    for year in year_window:
        for term in doc_terms[:3]:  # core 3 only (annual/interim report + annual results)
            queries.append(
                f'{short_name} {year} {term} site:hkexnews.hk filetype:pdf'
            )

    # Tier 2: year + doc-type + short_name + site (drop filetype hint)
    for year in year_window[:2]:
        for term in doc_terms[:2]:
            queries.append(f'{short_name} {year} {term} site:hkexnews.hk')

    # Tier 3: ticker-anchored — `"700" site:hkexnews.hk filetype:pdf`
    if ticker_short:
        queries.append(
            f'{ticker_short} {short_name} site:hkexnews.hk filetype:pdf'
        )
        queries.append(
            f'"({ticker_short})" {short_name} site:hkexnews.hk filetype:pdf'
        )

    # Tier 4: generic broadening
    queries.append(f'{short_name} site:hkexnews.hk filetype:pdf')

    # Tier 5: last-resort, doc-type-only with year
    queries.append(
        f'{short_name} {cutoff_year} site:hkexnews.hk filetype:pdf'
    )

    # Dedup while preserving order (some templates may produce identical
    # strings when ticker_short is None or doc_terms overlap).
    seen: set[str] = set()
    deduped: list[str] = []
    for q in queries:
        if q in seen:
            continue
        seen.add(q)
        deduped.append(q)
    return deduped


def _ddg_discover(
    *,
    company: str,
    stock_id: str | None = None,
    from_date: str,
    to_date: str,
    max_results: int,
    lookback_years: int = 2,
) -> list[dict[str, Any]]:
    """Discover HKEXnews PDFs by querying DuckDuckGo.

    DDG is sensitive to query verbosity. The L2.1 probe found that
    short company names + year hint surface HKEX archive URLs reliably
    for Country Garden but not for Tencent / Ping An. L2.4 broadens the
    query set with doc-type variants, ticker-anchored queries, and a
    wider year window — substantially improving coverage on the harder
    issuers with no extra dependencies.

    Filters returned URLs by:
      * URL pattern match (must look like an HKEXnews archive PDF)
      * URL date (YYYY/MMDD components must be on or before to_date and
        on or after from_date)
      * Deduplication by announcement_id

    The function keeps issuing queries until either max_results is hit
    or the query list is exhausted. This replaces the earlier
    "first-query-with-rows wins" pattern, which left coverage
    incomplete on issuers whose first query missed older filings.
    """
    try:
        from ddgs import DDGS
    except ImportError:  # pragma: no cover
        from duckduckgo_search import DDGS  # type: ignore[no-redef]

    ddgs = DDGS()
    short_name = _short_company_name(company)
    cutoff_year = int(to_date[:4])

    queries = _build_ddg_queries(
        short_name=short_name,
        stock_id=stock_id,
        cutoff_year=cutoff_year,
        lookback_years=lookback_years,
    )

    seen_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    cutoff_d = date.fromisoformat(to_date)
    from_d = date.fromisoformat(from_date)
    queries_run = 0

    for q in queries:
        if len(rows) >= max_results:
            break
        queries_run += 1
        try:
            results = list(ddgs.text(q, max_results=8))
        except Exception as exc:  # noqa: BLE001
            reporting.log_action("HKEX DDG query failed", {
                "query": q[:80], "error": str(exc)[:120],
            })
            results = []

        new_in_this_query = 0
        for r in results:
            url = r.get("href") or r.get("url") or ""
            title = r.get("title") or r.get("body") or ""
            row = _row_from_url_and_title(url=url, title=title)
            if row is None:
                continue
            # Date filter
            try:
                rt = date.fromisoformat(row["release_time"][:10])
            except ValueError:
                continue
            if rt > cutoff_d or rt < from_d:
                continue
            ann_id = row["announcement_id"]
            if ann_id in seen_ids:
                continue
            seen_ids.add(ann_id)
            rows.append(row)
            new_in_this_query += 1

        # Polite delay between DDG queries (matches retrieval module)
        time.sleep(2)

    if rows:
        reporting.log_action("HKEX DDG discovery yielded rows", {
            "company_short": short_name,
            "queries_run": queries_run,
            "rows": len(rows),
        })
    return rows


# Common corporate suffixes to strip when shortening a company name for
# DDG queries. Long legal names ("Holdings Company Limited") empty DDG
# results; bare brand names work much better.
_CORPORATE_NOISE_SUFFIXES = (
    "holdings company limited",
    "holdings ltd",
    "holdings limited",
    "company limited",
    "co., ltd.",
    "co., ltd",
    "co. ltd",
    "co ltd",
    "limited",
    "incorporated",
    "corporation",
    "corp.",
    "corp",
    "inc.",
    "inc",
    "ltd.",
    "ltd",
    "plc",
    "(group)",
    "group",
)


def _short_company_name(company: str) -> str:
    """Strip common corporate suffixes for a more selective DDG query.

    "Country Garden Holdings Company Limited" → "Country Garden"
    "Tencent Holdings Limited"                → "Tencent"
    "Ping An Insurance (Group) Company..."    → "Ping An Insurance"
    "Apple Inc."                              → "Apple"
    """
    s = company.strip()
    lower = s.lower()
    for suffix in _CORPORATE_NOISE_SUFFIXES:
        if lower.endswith(" " + suffix):
            s = s[: -len(suffix) - 1]
            lower = s.lower()
    return s.strip(" ,.")


def _row_from_url_and_title(*, url: str, title: str) -> dict[str, Any] | None:
    """Build a filing-metadata dict from a single search result."""
    m = HKEX_PDF_URL_PATTERN.search(url)
    if m is None:
        return None
    year, mmdd, announcement_id = m.group(1), m.group(2), m.group(3)
    doc_type = _classify_doc_type_from_title(title)
    release_time = _release_time_from_url(year, mmdd)
    canonical = (
        f"https://www1.hkexnews.hk/listedco/listconews/sehk/{year}/{mmdd}/"
        f"{announcement_id}.pdf"
    )
    return {
        "announcement_id": announcement_id,
        "title": (title or "(no title)")[:200],
        "release_time": release_time,
        "pdf_url": canonical,
        "doc_type": doc_type,
    }


def _classify_doc_type_from_title(title: str) -> str:
    """Best-effort doc_type from search-result title.

    The downstream loader uses this hint plus first-page text inspection
    to confirm the classification. Defaults to "other" when no keyword
    matches — that's still a kept manifest entry, just typed broadly.
    """
    t = (title or "").lower()
    for keywords, classification in _DOC_TYPE_KEYWORDS:
        if isinstance(keywords, str):
            if keywords in t:
                return classification
        else:  # tuple of synonyms
            if any(k in t for k in keywords):
                return classification
    return "other"


# ── Path 2: Playwright JSF fallback (kept for L2.1 completeness) ──


def _run_playwright_discovery(
    *,
    stock_id: str,
    from_date: str,
    to_date: str,
    timeout_ms: int,
    max_results: int,
) -> list[dict[str, Any]]:
    """Drive HKEXnews titlesearch.xhtml via Playwright. Same shape as DDG path.

    Used as a fallback when DDG coverage is thin. Selectors are
    best-effort against the JSF DOM as observed during L1.2 probing;
    if HKEXnews changes the form, this raises and the outer caller
    swallows.
    """
    from playwright.sync_api import sync_playwright

    from_compact = from_date.replace("-", "")
    to_compact = to_date.replace("-", "")
    rows: list[dict[str, Any]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(HKEX_TITLESEARCH_URL, wait_until="domcontentloaded")
            page.fill("input[id$='stockId']", stock_id)
            page.fill("input[id$='from']", from_compact)
            page.fill("input[id$='to']", to_compact)
            page.click("button:has-text('Search'), input[value='Search']")
            page.wait_for_selector(
                "table.releaseDocument, .resultLine, .titleLine",
                timeout=timeout_ms,
            )
            row_handles = page.query_selector_all(
                "table.releaseDocument tbody tr, tr.resultLine, .titleLine"
            )
            for handle in row_handles[:max_results]:
                row = _parse_row_html(handle.inner_html())
                if row is not None:
                    rows.append(row)
        finally:
            browser.close()

    return rows


# ── Pure helpers (testable without network) ──


def _parse_row_html(html: str) -> dict[str, Any] | None:
    """Extract one filing row's metadata from rendered JSF row HTML."""
    pdf_match = HKEX_PDF_URL_PATTERN.search(html)
    if pdf_match is None:
        # Try the relative form `/listedco/...` too — the JSF page often
        # renders relative hrefs.
        rel_match = re.search(
            r"/listedco/listconews/sehk/(\d{4})/(\d{4})/(\d+)\.pdf", html
        )
        if rel_match is None:
            return None
        year, mmdd, announcement_id = rel_match.groups()
    else:
        year, mmdd, announcement_id = pdf_match.group(1), pdf_match.group(2), pdf_match.group(3)

    text_only = re.sub(r"<[^>]+>", " ", html)
    text_only = re.sub(r"\s+", " ", text_only).strip()

    iso_release_time = (
        _parse_release_time(text_only) or _release_time_from_url(year, mmdd)
    )
    title_text = _strip_known_dates(text_only).strip()[:200] or "(no title)"

    pdf_url = (
        f"https://www1.hkexnews.hk/listedco/listconews/sehk/{year}/{mmdd}/"
        f"{announcement_id}.pdf"
    )

    return {
        "announcement_id": announcement_id,
        "title": title_text,
        "release_time": iso_release_time,
        "pdf_url": pdf_url,
        "doc_type": _classify_doc_type_from_title(title_text),
    }


_DATE_HK_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})")


def _parse_release_time(s: str) -> str | None:
    """HK-format '22/08/2024 17:23' → ISO 8601 +08:00."""
    m = _DATE_HK_PATTERN.search(s)
    if not m:
        return None
    d, mo, y, h, mn = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}T{int(h):02d}:{int(mn):02d}:00+08:00"


def _release_time_from_url(year: str, mmdd: str) -> str:
    mo, d = mmdd[:2], mmdd[2:]
    return f"{int(year):04d}-{int(mo):02d}-{int(d):02d}T00:00:00+08:00"


def _strip_known_dates(s: str) -> str:
    return _DATE_HK_PATTERN.sub("", s)


# ── PDF loading + auto-promotion (shared between discovery and search) ──


def load_hkex_pdfs(
    rows: list[dict[str, Any]],
    *,
    company_key: str,
    cutoff_date: str,
) -> list[dict[str, Any]]:
    """Download + chunk HKEXnews PDFs into pipeline-doc format.

    Used by:
      * `_discover_and_load_hkex` (after `live_discover_filings` returns rows)
      * `promote_hkex_urls_from_results` (auto-promotion during search)

    Each row must carry `pdf_url`, `announcement_id`, optional `title` and
    `release_time`. PDFs are cached at
    `data/corpus/{company_key}/hkex/{company_key}_{announcement_id}.pdf`
    so the same URL isn't re-downloaded across runs.

    Returns docs in the agentic_retrieval format (one per chunk):
      {title, snippet, link, source: "hkexnews", source_type: "company_filing",
       credibility_tier: "tier1_primary", published_at}
    """
    import httpx
    from sfewa.tools.filing_discovery import CORPUS_BASE, _extract_and_chunk
    try:
        from sfewa.tools.hkex import classify_doc_type
    except ImportError:  # pragma: no cover
        classify_doc_type = None  # type: ignore[assignment]

    cache_dir = CORPUS_BASE / company_key / "hkex"
    cache_dir.mkdir(parents=True, exist_ok=True)
    docs: list[dict[str, Any]] = []
    cutoff_d = date.fromisoformat(cutoff_date) if cutoff_date else None

    for row in rows:
        pdf_url = row.get("pdf_url")
        announcement_id = row.get("announcement_id")
        if not pdf_url or not announcement_id:
            continue

        # Cutoff filter (defensive — discovery already filters, but
        # promotion may pass through unfiltered URLs).
        rt = row.get("release_time") or ""
        if cutoff_d is not None and rt:
            try:
                if date.fromisoformat(rt[:10]) > cutoff_d:
                    continue
            except ValueError:
                pass

        pdf_path = cache_dir / f"{company_key}_{announcement_id}.pdf"
        if not pdf_path.exists():
            try:
                resp = httpx.get(pdf_url, timeout=60, follow_redirects=True)
                resp.raise_for_status()
                pdf_path.write_bytes(resp.content)
            except (httpx.HTTPError, OSError) as e:
                reporting.log_action("HKEX PDF download failed", {
                    "url": pdf_url, "error": str(e)[:100],
                })
                continue
            time.sleep(0.5)  # polite

        # Doc-type: prefer the row's hint, fall back to title-based classifier
        doc_type = row.get("doc_type")
        if (not doc_type or doc_type == "other") and classify_doc_type is not None:
            try:
                doc_type = classify_doc_type(row.get("title") or "")
            except Exception:  # noqa: BLE001
                pass
        doc_type = doc_type or "other"

        chunks = _extract_and_chunk(pdf_path, doc_type)
        if not chunks:
            continue

        filed_date = rt[:10] if rt else cutoff_date or ""
        title = row.get("title") or (
            f"{company_key.replace('_', ' ').title()} {doc_type.replace('_', ' ').title()}"
        )

        for i, chunk in enumerate(chunks):
            suffix = f" (Section {i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            docs.append({
                "title": f"[HKEX] {title}{suffix}",
                "snippet": chunk,
                "link": pdf_url,
                "source": "hkexnews",
                "source_type": "company_filing",
                "credibility_tier": "tier1_primary",
                "published_at": filed_date,
            })

        reporting.log_action("Loaded HKEX filing", {
            "announcement_id": announcement_id,
            "type": doc_type,
            "filed": filed_date,
            "chunks": len(chunks),
        })

    return docs


def promote_hkex_urls_from_results(
    search_results: list[dict[str, Any]],
    *,
    company_key: str,
    cutoff_date: str,
) -> list[dict[str, Any]]:
    """Scan generic search-result dicts for HKEXnews PDF URLs and Tier-1-promote.

    Args:
        search_results: list of dicts from `_search_web` / `_search_news`.
            Expected keys: title (or body), link / href / url.
        company_key: slugified company key for cache dir layout.
        cutoff_date: ISO date — URLs whose YYYY/MMDD encoding is post-cutoff
            are dropped here, before download.

    Returns:
        List of Tier-1 filing docs (one per chunk), or [] when no HKEX
        URL surfaces in the search results.
    """
    if not search_results:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in search_results:
        url = r.get("link") or r.get("href") or r.get("url") or ""
        title = r.get("title") or r.get("body") or ""
        row = _row_from_url_and_title(url=url, title=title)
        if row is None:
            continue
        if row["announcement_id"] in seen:
            continue
        # URL-encoded date pre-filter (cheap; skips download for post-cutoff)
        try:
            if date.fromisoformat(row["release_time"][:10]) > date.fromisoformat(cutoff_date):
                continue
        except ValueError:
            pass
        seen.add(row["announcement_id"])
        rows.append(row)

    if not rows:
        return []
    return load_hkex_pdfs(rows, company_key=company_key, cutoff_date=cutoff_date)


__all__ = [
    "is_playwright_available",
    "live_discover_filings",
    "load_hkex_pdfs",
    "promote_hkex_urls_from_results",
    "HKEX_PDF_URL_PATTERN",
    "HKEX_TITLESEARCH_URL",
]
