"""Load pre-curated corpus documents for retrieval enrichment.

Loads EDINET filings and other pre-downloaded documents, extracts text,
filters for relevant sections, and returns them as retrieved_docs.

EDINET filings provide Tier 1 primary evidence (official disclosures)
with known, verified publication dates — solving the DuckDuckGo date
ambiguity problem for company-specific data.

Supports multiple companies via the EDINET registry in edinet.py.
"""

from __future__ import annotations

from pathlib import Path

from sfewa import reporting
from sfewa.tools.edinet import (
    HONDA_KEY_FILINGS,
    extract_text_from_pdf,
    get_edinet_company,
)

CORPUS_BASE = Path(__file__).resolve().parents[3] / "data" / "corpus"

# Keywords for filtering relevant pages from large documents
# Both Japanese and English since Honda filings are bilingual
EV_KEYWORDS = [
    # English
    "EV", "BEV", "FCEV", "HEV", "battery", "electrification",
    "electric vehicle", "zero emission", "0 Series", "charging",
    "2030", "investment", "risk", "North America", "China",
    "software defined", "ADAS", "autonomous",
    # Japanese
    "電動", "電気自動車", "バッテリー", "充電", "リスク",
    "投資", "北米", "中国", "戦略", "計画",
]


def _page_ev_relevance(text: str) -> int:
    """Count EV-related keyword hits in a page of text."""
    text_lower = text.lower()
    return sum(1 for kw in EV_KEYWORDS if kw.lower() in text_lower)


def _extract_relevant_pages(
    pdf_path: Path,
    max_pages: int = 80,
    min_relevance: int = 2,
) -> str:
    """Extract text from EV-relevant pages of a large PDF.

    Scores each page by keyword relevance and keeps only pages
    with sufficient keyword hits. This avoids flooding the context
    with irrelevant financial tables from 200+ page annual reports.
    """
    import pdfplumber

    relevant = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages[:max_pages]):
            text = page.extract_text()
            if not text:
                continue
            if _page_ev_relevance(text) >= min_relevance:
                relevant.append(f"[Page {i + 1}]\n{text}")

    return "\n\n".join(relevant)


def load_edinet_corpus(company: str = "honda") -> list[dict]:
    """Load EDINET filings as retrieved_docs for any registered company.

    For annual reports (200+ pages): extracts only EV-relevant pages.
    For smaller reports: extracts full text.
    Results are chunked into manageable pieces for the extraction LLM.

    Args:
        company: Company name (matched against EDINET registry).

    Returns:
        List of document dicts compatible with retrieved_docs format.
        Each has: title, snippet, link, source, source_type,
                  credibility_tier, published_at.
    """
    entry = get_edinet_company(company)
    if entry is None:
        # Fallback for backward compat: if called with "honda" directly
        if "honda" in company.lower():
            filings = HONDA_KEY_FILINGS
            corpus_dir = "honda"
        else:
            return []
    else:
        filings = entry["filings"]
        corpus_dir = entry["corpus_dir"]

    docs: list[dict] = []

    for filing in filings:
        pdf_path = CORPUS_BASE / corpus_dir / "edinet" / filing["filename"]
        if not pdf_path.exists():
            reporting.log_action(f"EDINET PDF missing: {filing['filename']}")
            continue

        try:
            if filing["doc_type"] == "annual_report":
                text = _extract_relevant_pages(
                    pdf_path, max_pages=80, min_relevance=2,
                )
            else:
                text = extract_text_from_pdf(pdf_path, max_pages=50)
        except Exception as e:
            reporting.log_action(
                f"PDF extraction failed: {filing['filename']}",
                {"error": str(e)[:100]},
            )
            continue

        if not text.strip():
            reporting.log_action(f"No text extracted: {filing['filename']}")
            continue

        # Chunk into ~4000 char pieces for manageable LLM input
        chunk_size = 4000
        chunks: list[str] = []
        if len(text) > chunk_size + 500:
            for start in range(0, len(text), chunk_size):
                chunk = text[start : start + chunk_size]
                if chunk.strip():
                    chunks.append(chunk)
        else:
            chunks = [text]

        for i, chunk in enumerate(chunks):
            suffix = f" (Section {i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            docs.append({
                "title": f"[EDINET] {filing['title']}{suffix}",
                "snippet": chunk,
                "link": f"edinet:{filing['doc_id']}",
                "source": "edinet",
                "source_type": filing.get("source_type", "company_filing"),
                "credibility_tier": filing.get("credibility_tier", "tier1_primary"),
                "published_at": filing["filed_date"],
            })

        reporting.log_action("Loaded EDINET filing", {
            "file": filing["filename"],
            "type": filing["doc_type"],
            "text_chars": len(text),
            "chunks": len(chunks),
            "filed_date": filing["filed_date"],
        })

    return docs
