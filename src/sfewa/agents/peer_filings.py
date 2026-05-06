"""Peer-side filing discovery (closes L2.2 acceptance gap).

The pipeline's primary filing pass fetches the *target* company's
disclosures only. Peer companies (named in `state["peers"]`) appear in
analyst prompts but their evidence comes from web search alone — never
Tier-1 primary sources. This node closes that gap.

Why a separate node, not folded into agentic_retrieval:
    Peer filing discovery is an O(N×download) operation per peer,
    each invocation hits a different filing system, and the total
    chunks added needs caps to avoid drowning the primary signal.
    Keeping it as a separate node makes the budget + opt-in flag
    explicit.

Opt-in by default: the existing 9-run stability gate (3×3 H/T/B) was
established without peer filings. Enabling them by default could
change the score distribution, breaking the gate. Cases that want
peer filings set `audit_meta.fetch_peer_filings: true` in their YAML,
or pass `--enable-peer-filings` on the CLI.

Caps (defensive):
    - MAX_PEERS: at most 3 peers processed per run
    - MAX_CHUNKS_PER_PEER: at most 6 chunks emitted per peer
    - peers without resolvable jurisdiction are skipped silently

Output: state["peer_filings"] is a list of doc dicts in the same
shape as `retrieved_docs` entries. The agentic_retrieval node reads
this list at start-up and prepends it to its own search results, so
peer filings flow into the manifest, evidence extraction, and
analyst prompts unchanged.
"""

from __future__ import annotations

from typing import Any

from sfewa import reporting
from sfewa.schemas.state import PipelineState
from sfewa.tools.filing_discovery import discover_and_load_filings


# Caps to keep peer filings from dominating the corpus.
MAX_PEERS = 3
MAX_CHUNKS_PER_PEER = 6


# Hardcoded peer → (ticker, jurisdiction) map. Used as a fallback when
# the case YAML doesn't supply peer_tickers and the peer name doesn't
# carry a ticker. Jurisdictions are ISO-style codes consumed by
# filing_discovery.identify_jurisdiction(explicit=...).
#
# Tickers are required for SEC EDGAR (CIK lookup is far more stable
# via ticker than corporate-name fuzzy matching) and HKEX (DDG site
# search needs the stock id implicitly via short company name).
# EDINET / CNINFO discovery uses Japanese / Chinese filer-name
# matching; their `ticker` field is None.
_PEER_TICKER_MAP: dict[str, tuple[str | None, str]] = {
    # US — SEC EDGAR
    "tesla": ("TSLA", "US"),
    "ford motor": ("F", "US"),
    "ford": ("F", "US"),
    "general motors": ("GM", "US"),
    "stellantis": ("STLA", "US"),
    "rivian": ("RIVN", "US"),
    "lucid": ("LCID", "US"),
    "boeing": ("BA", "US"),
    "apple": ("AAPL", "US"),
    "microsoft": ("MSFT", "US"),
    "alphabet": ("GOOGL", "US"),
    "amazon": ("AMZN", "US"),
    "meta platforms": ("META", "US"),
    "nvidia": ("NVDA", "US"),
    # JP — EDINET (filer-name match; ticker not used)
    "toyota motor": (None, "JP"),
    "toyota": (None, "JP"),
    "honda motor": (None, "JP"),
    "honda": (None, "JP"),
    "nissan": (None, "JP"),
    "mazda": (None, "JP"),
    "subaru": (None, "JP"),
    "suzuki": (None, "JP"),
    "sony": (None, "JP"),
    "panasonic": (None, "JP"),
    # CN — CNINFO (Chinese filer-name match; ticker not used)
    "byd": (None, "CN"),
    "nio": (None, "CN"),
    "xpeng": (None, "CN"),
    "li auto": (None, "CN"),
    "geely": (None, "CN"),
    # HK — HKEX
    "tencent holdings": ("0700", "HK"),
    "tencent": ("0700", "HK"),
    "alibaba group": ("9988", "HK"),
    "ping an": ("2318", "HK"),
    "hsbc": ("0005", "HK"),
    "aia": ("1299", "HK"),
    "country garden": ("2007", "HK"),
}


def _peer_name_and_meta(p: Any) -> tuple[str, str | None, str | None]:
    """Extract (name, ticker, jurisdiction) from a peer entry.

    Peer entries can be either bare strings or dicts (the LLM's
    init_case prompt sometimes returns structured peers). We accept
    both shapes and pull the first available field.
    """
    if isinstance(p, dict):
        name = (
            p.get("company")
            or p.get("name")
            or ""
        )
        return name, p.get("ticker"), p.get("jurisdiction")
    return str(p), None, None


def _resolve(
    name: str,
    ticker: str | None,
    jurisdiction: str | None,
    *,
    case_peer_tickers: dict[str, str | dict[str, str]],
) -> tuple[str | None, str | None]:
    """Resolve missing ticker/jurisdiction.

    Priority order:
        1. Already-known fields on the peer entry win.
        2. Case YAML `audit_meta.peer_tickers` map.
        3. Built-in `_PEER_TICKER_MAP` (longest-prefix match wins to
           prefer "ford motor" over "ford" when both exist).
    """
    if jurisdiction and ticker is not None:
        return ticker, jurisdiction

    case_entry = case_peer_tickers.get(name)
    if case_entry is None:
        # Try case-insensitive lookup
        for k, v in case_peer_tickers.items():
            if k.lower() == name.lower():
                case_entry = v
                break
    if case_entry is not None:
        if isinstance(case_entry, dict):
            ticker = ticker or case_entry.get("ticker")
            jurisdiction = jurisdiction or case_entry.get("jurisdiction")
        else:
            # bare-string case map: assume ticker
            ticker = ticker or str(case_entry)

    if jurisdiction is None or ticker is None:
        name_lower = name.lower()
        # Prefer the longest matching key so "ford motor" beats "ford".
        best_key: str | None = None
        for key in _PEER_TICKER_MAP:
            if key in name_lower and (best_key is None or len(key) > len(best_key)):
                best_key = key
        if best_key is not None:
            t, j = _PEER_TICKER_MAP[best_key]
            ticker = ticker or t
            jurisdiction = jurisdiction or j
    return ticker, jurisdiction


def peer_filings_node(state: PipelineState) -> dict:
    """Discover and load regulatory filings for case peers.

    Gated by `state["audit_meta"]["fetch_peer_filings"]` (default
    False). Returns `{"peer_filings": [...]}` — a list of doc dicts
    in the same shape as `retrieved_docs` entries. The agentic
    retrieval node prepends them to its all_docs list so they enter
    the manifest, evidence extraction, and analyst prompts as a
    single coherent corpus.
    """
    audit_meta = state.get("audit_meta") or {}
    if not audit_meta.get("fetch_peer_filings"):
        # Opt-in path: silent no-op when not enabled.
        return {"peer_filings": []}

    peers = state.get("peers") or []
    cutoff = state.get("cutoff_date") or ""
    if not peers or not cutoff:
        return {"peer_filings": []}

    case_peer_tickers = audit_meta.get("peer_tickers") or {}

    reporting.enter_node("peer_filings", {
        "peers": len(peers),
        "cutoff_date": cutoff,
        "max_peers": MAX_PEERS,
        "max_chunks_per_peer": MAX_CHUNKS_PER_PEER,
    })

    docs: list[dict] = []
    processed = 0
    for p in peers:
        if processed >= MAX_PEERS:
            break

        name, ticker, jurisdiction = _peer_name_and_meta(p)
        if not name:
            continue

        ticker, jurisdiction = _resolve(
            name, ticker, jurisdiction,
            case_peer_tickers=case_peer_tickers,
        )
        if jurisdiction is None:
            reporting.log_action("Skipping peer (no jurisdiction)", {"peer": name})
            continue

        try:
            peer_docs = discover_and_load_filings(
                name,
                cutoff,
                regions=[jurisdiction.lower()],
                ticker=ticker,
            )
        except Exception as e:  # noqa: BLE001
            reporting.log_action("Peer filing discovery failed", {
                "peer": name,
                "error": str(e)[:120],
            })
            continue

        if not peer_docs:
            reporting.log_action("No filings found for peer", {"peer": name})
            continue

        capped = peer_docs[:MAX_CHUNKS_PER_PEER]
        for d in capped:
            # Tag every chunk with the peer name so analysts can
            # distinguish target-company filings from peer filings.
            d["peer_company"] = name
            base_title = d.get("title", "")
            d["title"] = f"[Peer: {name}] {base_title}"
        docs.extend(capped)
        processed += 1

        reporting.log_action("Loaded peer filing chunks", {
            "peer": name,
            "ticker": ticker or "—",
            "jurisdiction": jurisdiction,
            "chunks": len(capped),
        })

    reporting.exit_node("peer_filings", {
        "peers_processed": processed,
        "chunks": len(docs),
    })

    return {"peer_filings": docs}
