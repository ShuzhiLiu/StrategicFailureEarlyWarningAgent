"""HKEXnews client (Hong Kong Stock Exchange disclosures, L1.2).

Surfaces:
    IssuerRef               — issuer identity record (issuer_id, stock_id,
                              display_name, alt_names)
    resolve_issuer()        — resolve a ticker against a cached stock list
    classify_doc_type()     — apply the L1 taxonomy filter (annual/interim/
                              results/inside info/circulars vs noise)
    parse_title_search()    — lift a structured search response into FilingRefs
    parse_stocklist_html()  — lift the HKEX stock list HTML
    parse_titlesearch_html()— lift the HKEX title-search HTML
    HK_TZ                   — Asia/Hong_Kong zoneinfo
    normalize_release_time()— produce TZ-aware ISO-8601 string

Cache layout (per roadmap rev 4):
    data/cache/hkex/
        metadata/{url_hash}.json
        artifacts/{content_sha256}.pdf
        manifest.jsonl

Live network calls live behind explicit functions guarded by a `live`
flag in the provider. Tests use structured fixtures and HTML fixtures
under tests/fixtures/hkex/ with zero network access.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


# ── Time ──

HK_TZ = ZoneInfo("Asia/Hong_Kong")


def normalize_release_time(s: str) -> str:
    """Return a TZ-aware ISO-8601 string in Asia/Hong_Kong.

    Accepted inputs:
        "HH:MM DD/MM/YYYY" (HKEXnews canonical)
        "DD/MM/YYYY HH:MM"
        "YYYY-MM-DD HH:MM"
        "YYYY-MM-DDTHH:MM:SS[+TZ]"
        "YYYY-MM-DD"  (date-only → 23:59:59 local end-of-day)
    """
    s = s.strip()

    # Date-only YYYY-MM-DD → end-of-day local. Check this BEFORE
    # datetime.fromisoformat, because fromisoformat would parse it as
    # midnight and shadow the end-of-day intent.
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        y, mo, d = map(int, m.groups())
        dt = datetime(y, mo, d, 23, 59, 59, tzinfo=HK_TZ)
        return dt.isoformat()

    # ISO-8601 (date+time, with or without TZ)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HK_TZ)
        return dt.astimezone(HK_TZ).isoformat()
    except ValueError:
        pass

    # HH:MM DD/MM/YYYY (HKEXnews canonical)
    m = re.match(r"(\d{2}):(\d{2})\s+(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        h, mi, d, mo, y = map(int, m.groups())
        dt = datetime(y, mo, d, h, mi, tzinfo=HK_TZ)
        return dt.isoformat()

    # DD/MM/YYYY HH:MM (alternate ordering some pages use)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})", s)
    if m:
        d, mo, y, h, mi = map(int, m.groups())
        dt = datetime(y, mo, d, h, mi, tzinfo=HK_TZ)
        return dt.isoformat()

    # YYYY-MM-DD HH:MM
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", s)
    if m:
        y, mo, d, h, mi = map(int, m.groups())
        dt = datetime(y, mo, d, h, mi, tzinfo=HK_TZ)
        return dt.isoformat()

    raise ValueError(f"Could not parse release_time: {s!r}")


def cutoff_date_to_endofday_hk(cutoff: str) -> str:
    """Parse a YYYY-MM-DD cutoff to end-of-day Asia/Hong_Kong, ISO-8601."""
    d = date.fromisoformat(cutoff)
    return datetime.combine(d, time(23, 59, 59), tzinfo=HK_TZ).isoformat()


# ── Issuer resolver ──


@dataclass(frozen=True)
class IssuerRef:
    """Stable issuer identity for HKEXnews lookup.

    Per roadmap rev 4 — raw ticker search isn't stable; the resolver
    normalizes once and the result is recorded in the manifest so the
    resolution itself is auditable.
    """

    issuer_id: str   # HKEX issuer code (varies; e.g., short numeric or stock-id-based)
    stock_id: str    # Zero-padded 5-digit stock code, e.g., "02318" for Ping An
    display_name: str
    alt_names: tuple[str, ...] = field(default_factory=tuple)


def _normalize_ticker(ticker: str) -> str:
    """Map any reasonable ticker form to the 5-digit padded HKEX stock_id.

    Accepts: "2318", "02318", "0002318", "2318.HK", "HKEX:2318"
    """
    t = ticker.strip().upper()
    t = t.removeprefix("HKEX:").removeprefix("HK:").removesuffix(".HK")
    digits = "".join(c for c in t if c.isdigit())
    if not digits:
        raise ValueError(f"No digits in ticker: {ticker!r}")
    # Strip leading zeros, then pad to 5. Handles "0002318" → "2318" → "02318".
    return digits.lstrip("0").zfill(5) or "00000"


def resolve_issuer(
    ticker: str,
    *,
    stock_list_html: str | None = None,
    stock_list: list[dict] | None = None,
) -> IssuerRef | None:
    """Resolve a ticker to an IssuerRef.

    Resolution sources (one of):
        - stock_list_html: HTML from the HKEX stock list page
        - stock_list: pre-parsed list of {stock_id, display_name, alt_names?}

    Returns None if the ticker is not present in the resolved stock list.
    Raises ValueError if neither source is provided.
    """
    if stock_list_html is None and stock_list is None:
        raise ValueError("Must provide stock_list_html or stock_list")

    target = _normalize_ticker(ticker)

    rows: list[dict]
    if stock_list is not None:
        rows = stock_list
    else:
        rows = parse_stocklist_html(stock_list_html or "")

    for r in rows:
        sid = _normalize_ticker(r.get("stock_id") or "")
        if sid == target:
            return IssuerRef(
                issuer_id=r.get("issuer_id") or sid,
                stock_id=sid,
                display_name=r.get("display_name") or "",
                alt_names=tuple(r.get("alt_names") or ()),
            )
    return None


# ── HTML parsing ──


def parse_stocklist_html(html: str) -> list[dict]:
    """Extract stock-list rows from HKEX stock_list_active_main.htm-style HTML.

    Looks for table rows with a stock code cell + name cell. Tolerant of
    missing fields. Returns dicts with stock_id, display_name, alt_names.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("beautifulsoup4 required for HKEX HTML parsing") from e

    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        # Heuristic: first cell that's all-digits (5 chars usually) is the code
        code = None
        name_cells: list[str] = []
        for c in cells:
            digits = "".join(ch for ch in c if ch.isdigit())
            if code is None and digits and len(digits) <= 5 and digits == c.replace(" ", "").lstrip("0").rjust(len(digits), "0").lstrip(" "):
                # accept "02318" style
                code = digits.zfill(5)
            elif code is not None:
                name_cells.append(c)
            else:
                name_cells.append(c)
        if code is None:
            continue
        display = name_cells[0] if name_cells else ""
        alt = name_cells[1:] if len(name_cells) > 1 else []
        rows.append({
            "stock_id": code,
            "issuer_id": code,
            "display_name": display,
            "alt_names": alt,
        })
    return rows


@dataclass(frozen=True)
class TitleSearchRow:
    """Structured shape produced by parse_titlesearch_html().

    The parser converts the HTML response into these rows; the provider
    converts rows → FilingRef. Splitting these layers keeps tests stable
    if HKEX's HTML structure changes.
    """
    title: str
    url: str
    release_time_raw: str  # e.g., "14:30 31/03/2025"
    release_time_iso: str  # TZ-aware Asia/Hong_Kong ISO-8601
    stock_id: str
    issuer_name: str
    language: str  # "en" | "zh"


def parse_titlesearch_html(html: str, *, language: str = "en") -> list[TitleSearchRow]:
    """Extract HKEXnews title-search result rows.

    HKEXnews title-search returns an HTML table; this parser walks the
    rows and pulls out the four cells of interest: release time, stock
    code, title (with PDF URL), and document type label. The structure
    has been stable since HKEXnews's last UI refresh, but tightening
    this against the live response is a follow-up.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("beautifulsoup4 required for HKEX HTML parsing") from e

    soup = BeautifulSoup(html, "html.parser")
    rows: list[TitleSearchRow] = []
    for tr in soup.find_all("tr"):
        # Each result row has these columns
        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        cell_texts = [c.get_text(" ", strip=True) for c in cells]

        # Find release time cell ("HH:MM DD/MM/YYYY")
        rt_raw = ""
        for txt in cell_texts:
            if re.search(r"\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4}", txt):
                rt_raw = re.search(r"\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4}", txt).group(0)
                break
        if not rt_raw:
            continue

        # Stock code: 5-digit number, possibly with prefix label
        stock_id = ""
        issuer_name = ""
        for txt in cell_texts:
            m = re.search(r"(?:Stock\s+Code:?\s*)?(\d{5})", txt)
            if m:
                stock_id = m.group(1)
                # Issuer name is often after a "Stock Short Name:" or "|"
                rest = txt.split(stock_id, 1)[-1].lstrip(" |:")
                if "Stock Short Name" in rest:
                    rest = rest.split("Stock Short Name", 1)[-1].lstrip(" |:")
                issuer_name = rest.strip()
                break
        if not stock_id:
            continue

        # Title + URL: anchor inside a cell
        a = tr.find("a")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        url = a.get("href") or ""
        if not url:
            continue

        rows.append(TitleSearchRow(
            title=title,
            url=url,
            release_time_raw=rt_raw,
            release_time_iso=normalize_release_time(rt_raw),
            stock_id=stock_id,
            issuer_name=issuer_name,
            language=language,
        ))
    return rows


# ── Doc taxonomy ──


# INCLUDE-by-default doc-type labels per roadmap rev 4
_INCLUDE_PATTERNS = [
    (re.compile(r"\bannual\s+report\b", re.I), "annual_report"),
    (re.compile(r"\binterim\s+report\b", re.I), "interim_report"),
    (re.compile(r"\b(annual|interim|first[\s-]quarter|third[\s-]quarter)\s+results?\b", re.I), "results_announcement"),
    (re.compile(r"\bfinal\s+results?\b", re.I), "results_announcement"),
    (re.compile(r"\bquarterly\s+results?\b", re.I), "results_announcement"),
    (re.compile(r"\binside\s+information\b", re.I), "inside_information"),
    (re.compile(r"\bcircular\b", re.I), "circular"),
    (re.compile(r"\bvery\s+substantial\b", re.I), "circular"),
    (re.compile(r"\bdiscloseable\s+transaction\b", re.I), "circular"),
    (re.compile(r"\bconnected\s+transaction\b", re.I), "circular"),
]

# EXCLUDE-by-default doc-type labels (administrative noise)
_EXCLUDE_PATTERNS = [
    (re.compile(r"\bmonthly\s+return\b", re.I), "monthly_return"),
    (re.compile(r"\bnext\s+day\s+disclosure\b", re.I), "next_day_disclosure"),
    (re.compile(r"\bchange\s+of\s+(?:director|company\s+secretary|registered)", re.I), "officer_change"),
    (re.compile(r"\bappointment\s+of\b", re.I), "officer_change"),
    (re.compile(r"\bresignation\b", re.I), "officer_change"),
    (re.compile(r"\bresult\s+of\s+poll\b", re.I), "poll_result"),
    (re.compile(r"\bnotification\s+of\s+(?:agm|egm)\b", re.I), "meeting_notice"),
]


def classify_doc_type(title: str) -> str:
    """Return the L1 taxonomy label for a HKEXnews title.

    Precedence: include > exclude (a circular about an officer change is
    still a circular). Returns "other" when nothing matches.
    """
    for pat, label in _INCLUDE_PATTERNS:
        if pat.search(title):
            return label
    for pat, label in _EXCLUDE_PATTERNS:
        if pat.search(title):
            return label
    return "other"


def is_excluded_doc_type(doc_type: str) -> bool:
    """True if the doc_type is in the EXCLUDE-by-default set."""
    return doc_type in (
        "monthly_return", "next_day_disclosure", "officer_change",
        "poll_result", "meeting_notice",
    )


# ── Cache layout helpers ──


def url_hash(url: str) -> str:
    """sha256-12 of a URL — used as the metadata cache key."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def hkex_cache_paths(base_dir: Path) -> dict[str, Path]:
    """Return the standard HKEX cache subpaths under a base directory."""
    return {
        "metadata": base_dir / "metadata",
        "artifacts": base_dir / "artifacts",
        "manifest": base_dir / "manifest.jsonl",
    }


def append_cache_manifest(
    base_dir: Path, *, url: str, content_sha256: str, doc_id: str
) -> None:
    """Append a URL → content_sha256 mapping to manifest.jsonl."""
    paths = hkex_cache_paths(base_dir)
    paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "url": url,
        "url_hash": url_hash(url),
        "content_sha256": content_sha256,
        "doc_id": doc_id,
    })
    with open(paths["manifest"], "a") as f:
        f.write(line + "\n")
