"""Tests for the peer-filings node (closes L2.2 acceptance gap)."""

from __future__ import annotations

from unittest.mock import patch

from sfewa.agents.peer_filings import (
    MAX_CHUNKS_PER_PEER,
    MAX_PEERS,
    _peer_name_and_meta,
    _resolve,
    peer_filings_node,
)


# ── _peer_name_and_meta ──


def test_peer_name_and_meta_handles_string_peer():
    assert _peer_name_and_meta("Tesla, Inc.") == ("Tesla, Inc.", None, None)


def test_peer_name_and_meta_handles_dict_with_company_field():
    p = {"company": "Tesla", "ticker": "TSLA", "jurisdiction": "US"}
    assert _peer_name_and_meta(p) == ("Tesla", "TSLA", "US")


def test_peer_name_and_meta_falls_back_to_name_field():
    p = {"name": "Tesla"}
    n, t, j = _peer_name_and_meta(p)
    assert n == "Tesla"
    assert t is None
    assert j is None


def test_peer_name_and_meta_handles_empty_dict():
    n, t, j = _peer_name_and_meta({})
    assert n == ""


# ── _resolve ──


def test_resolve_uses_existing_fields_when_present():
    t, j = _resolve("Anything Inc", "ABC", "US", case_peer_tickers={})
    assert (t, j) == ("ABC", "US")


def test_resolve_uses_case_peer_tickers_dict_form():
    case_tickers = {"Random Peer": {"ticker": "RP", "jurisdiction": "JP"}}
    t, j = _resolve("Random Peer", None, None, case_peer_tickers=case_tickers)
    assert (t, j) == ("RP", "JP")


def test_resolve_uses_case_peer_tickers_string_form():
    case_tickers = {"Apple Computer": "AAPL"}
    t, j = _resolve(
        "Apple Computer", None, None, case_peer_tickers=case_tickers,
    )
    assert t == "AAPL"
    # jurisdiction is unset by string form — would have to come from
    # the built-in map. "Apple Computer" doesn't match "apple" exactly
    # but the substring match in _PEER_TICKER_MAP catches it.
    assert j == "US"


def test_resolve_falls_back_to_builtin_map():
    t, j = _resolve("Tesla, Inc.", None, None, case_peer_tickers={})
    assert (t, j) == ("TSLA", "US")


def test_resolve_prefers_longest_matching_key():
    """'Ford Motor Company' must resolve to ford-motor (US ticker F),
    not just 'ford' alone — both are in the map."""
    t, j = _resolve("Ford Motor Company", None, None, case_peer_tickers={})
    assert t == "F"
    assert j == "US"


def test_resolve_returns_none_for_unknown_peer():
    t, j = _resolve(
        "Some Unknown Startup XYZ", None, None, case_peer_tickers={},
    )
    assert t is None
    assert j is None


def test_resolve_jp_peer_uses_no_ticker():
    """EDINET name-matching doesn't need a ticker; jurisdiction alone
    drives discovery."""
    t, j = _resolve("Toyota Motor", None, None, case_peer_tickers={})
    assert t is None
    assert j == "JP"


def test_resolve_cn_peer_uses_no_ticker():
    t, j = _resolve("BYD Company Limited", None, None, case_peer_tickers={})
    assert t is None
    assert j == "CN"


def test_resolve_hk_peer_returns_ticker():
    t, j = _resolve("Tencent Holdings", None, None, case_peer_tickers={})
    assert t == "0700"
    assert j == "HK"


# ── peer_filings_node ──


def test_node_no_op_when_flag_off():
    """Default opt-out behavior: no audit_meta.fetch_peer_filings → empty result."""
    state = {
        "peers": ["Tesla", "Ford"],
        "cutoff_date": "2025-05-19",
        "audit_meta": {},
    }
    out = peer_filings_node(state)  # type: ignore[arg-type]
    assert out == {"peer_filings": []}


def test_node_no_op_when_no_peers():
    state = {
        "peers": [],
        "cutoff_date": "2025-05-19",
        "audit_meta": {"fetch_peer_filings": True},
    }
    out = peer_filings_node(state)  # type: ignore[arg-type]
    assert out == {"peer_filings": []}


def test_node_skips_peer_with_no_jurisdiction():
    """A peer whose name doesn't match the built-in map AND has no
    case-supplied ticker is silently skipped."""
    state = {
        "peers": ["Some Unknown Startup Z"],
        "cutoff_date": "2025-05-19",
        "audit_meta": {"fetch_peer_filings": True},
    }
    with patch("sfewa.agents.peer_filings.discover_and_load_filings") as mock:
        out = peer_filings_node(state)  # type: ignore[arg-type]
    assert out == {"peer_filings": []}
    mock.assert_not_called()


def test_node_loads_peer_when_flag_on_and_resolution_succeeds():
    """Happy path: peer resolves to (ticker, jurisdiction); discovery
    is called with the right args; chunks come back tagged."""
    state = {
        "peers": ["Tesla"],
        "cutoff_date": "2025-05-19",
        "audit_meta": {"fetch_peer_filings": True},
    }
    fake_chunks = [
        {
            "title": "Annual Report",
            "snippet": "Tesla's FY24 vehicle deliveries...",
            "link": "https://example.com/tsla-10k",
            "source": "sec_edgar",
            "source_type": "company_filing",
            "credibility_tier": "tier1_primary",
            "published_at": "2025-01-30",
        },
        {
            "title": "Quarterly",
            "snippet": "Q3 cashflow...",
            "link": "https://example.com/tsla-10q",
            "source": "sec_edgar",
            "source_type": "company_filing",
            "credibility_tier": "tier1_primary",
            "published_at": "2024-10-23",
        },
    ]
    with patch(
        "sfewa.agents.peer_filings.discover_and_load_filings",
        return_value=fake_chunks,
    ) as mock:
        out = peer_filings_node(state)  # type: ignore[arg-type]
    assert mock.call_count == 1
    args, kwargs = mock.call_args
    assert args[0] == "Tesla"
    assert kwargs.get("ticker") == "TSLA"

    docs = out["peer_filings"]
    assert len(docs) == 2
    assert all(d["peer_company"] == "Tesla" for d in docs)
    assert all(d["title"].startswith("[Peer: Tesla]") for d in docs)


def test_node_caps_peers_at_max():
    """At most MAX_PEERS peers get processed regardless of input length."""
    state = {
        "peers": [f"Peer{i}" for i in range(MAX_PEERS + 5)],  # > MAX_PEERS
        "cutoff_date": "2025-05-19",
        "audit_meta": {
            "fetch_peer_filings": True,
            "peer_tickers": {
                f"Peer{i}": {"ticker": f"P{i}", "jurisdiction": "US"}
                for i in range(MAX_PEERS + 5)
            },
        },
    }
    fake_chunks = [{
        "title": "x", "snippet": "y", "link": "z",
        "source": "sec_edgar", "source_type": "company_filing",
        "credibility_tier": "tier1_primary", "published_at": "2024-01-01",
    }]
    with patch(
        "sfewa.agents.peer_filings.discover_and_load_filings",
        return_value=fake_chunks,
    ) as mock:
        out = peer_filings_node(state)  # type: ignore[arg-type]
    assert mock.call_count == MAX_PEERS
    assert len(out["peer_filings"]) == MAX_PEERS  # 1 chunk per peer


def test_node_caps_chunks_per_peer():
    """When discover_and_load_filings returns more than
    MAX_CHUNKS_PER_PEER, only the first N are kept."""
    state = {
        "peers": ["Tesla"],
        "cutoff_date": "2025-05-19",
        "audit_meta": {"fetch_peer_filings": True},
    }
    fake_chunks = [
        {
            "title": f"Chunk {i}", "snippet": f"text {i}",
            "link": f"https://example.com/{i}",
            "source": "sec_edgar", "source_type": "company_filing",
            "credibility_tier": "tier1_primary", "published_at": "2024-01-01",
        }
        for i in range(MAX_CHUNKS_PER_PEER + 10)
    ]
    with patch(
        "sfewa.agents.peer_filings.discover_and_load_filings",
        return_value=fake_chunks,
    ):
        out = peer_filings_node(state)  # type: ignore[arg-type]
    assert len(out["peer_filings"]) == MAX_CHUNKS_PER_PEER


def test_node_handles_discovery_exception_gracefully():
    """A peer whose discovery raises must NOT crash the node — only
    that peer is skipped, others continue."""
    state = {
        "peers": ["Tesla", "Ford"],
        "cutoff_date": "2025-05-19",
        "audit_meta": {"fetch_peer_filings": True},
    }
    fake_chunks = [{
        "title": "Annual", "snippet": "",
        "link": "https://example.com/x",
        "source": "sec_edgar", "source_type": "company_filing",
        "credibility_tier": "tier1_primary", "published_at": "2024-01-01",
    }]

    call_count = [0]

    def mock_disco(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Tesla disco blew up")
        return fake_chunks

    with patch(
        "sfewa.agents.peer_filings.discover_and_load_filings",
        side_effect=mock_disco,
    ):
        out = peer_filings_node(state)  # type: ignore[arg-type]
    # Tesla failed, Ford succeeded — 1 chunk total.
    assert len(out["peer_filings"]) == 1
    assert out["peer_filings"][0]["peer_company"] == "Ford"


def test_node_accepts_dict_peer_entries():
    """Peer entries can be dicts when init_case generates structured peers."""
    state = {
        "peers": [{"company": "Tesla", "ticker": "TSLA", "jurisdiction": "US"}],
        "cutoff_date": "2025-05-19",
        "audit_meta": {"fetch_peer_filings": True},
    }
    fake_chunks = [{
        "title": "Annual", "snippet": "",
        "link": "https://example.com/x",
        "source": "sec_edgar", "source_type": "company_filing",
        "credibility_tier": "tier1_primary", "published_at": "2024-01-01",
    }]
    with patch(
        "sfewa.agents.peer_filings.discover_and_load_filings",
        return_value=fake_chunks,
    ) as mock:
        out = peer_filings_node(state)  # type: ignore[arg-type]
    args, kwargs = mock.call_args
    assert kwargs.get("ticker") == "TSLA"
    assert len(out["peer_filings"]) == 1
