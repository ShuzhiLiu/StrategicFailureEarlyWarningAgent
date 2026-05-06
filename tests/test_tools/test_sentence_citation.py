"""Tests for L2.3 sentence-level claim citation enforcement."""

from __future__ import annotations

from sfewa.tools.sentence_citation import (
    find_span_in_text,
    sentence_citation_summary,
    split_into_sentences,
    unresolved_violations,
    validate_sentence_citations,
)


# ── split_into_sentences ──


def test_split_basic_three_sentences():
    text = (
        "Tesla reported record revenues. Operating margin compressed under "
        "price reductions. The 2024 outlook remains constructive."
    )
    out = split_into_sentences(text)
    assert len(out) == 3
    assert out[0].startswith("Tesla reported")
    assert out[2].endswith("constructive.")


def test_split_drops_short_fragments():
    # "Yes." is below MIN_SENTENCE_CHARS=20 — must be discarded.
    text = "Yes. Tesla's earnings beat consensus by a significant margin."
    out = split_into_sentences(text)
    assert len(out) == 1
    assert "Tesla's earnings" in out[0]


def test_split_handles_questions_and_exclamations():
    text = (
        "Will the BEV transition succeed? Honda has not committed sufficient capital. "
        "The hybrid pivot suggests doubt."
    )
    out = split_into_sentences(text)
    assert len(out) == 3


def test_split_handles_cjk_text():
    # Boundary regex matches CJK ideographs as the start-of-next-sentence marker.
    text = "本田の電気自動車戦略は不透明です。 中国市場では競争が激化しています。"
    out = split_into_sentences(text)
    # Both sentences are >= MIN_SENTENCE_CHARS in chars
    assert len(out) >= 1


def test_split_empty_returns_empty():
    assert split_into_sentences("") == []
    assert split_into_sentences("   ") == []
    assert split_into_sentences(None) == []  # type: ignore[arg-type]


# ── find_span_in_text ──


def test_find_span_locates_verbatim_quote():
    sentence = "Tesla's operating margin compressed in fiscal year 2024."
    text = (
        "ANNUAL REPORT EXCERPT — Item 7. We disclose that Tesla's operating "
        "margin compressed in fiscal year 2024 due to price reductions."
    )
    span = find_span_in_text(sentence, text)
    assert span is not None
    start, end = span
    matched = text[start:end].lower()
    assert "tesla's operating margin compressed" in matched


def test_find_span_returns_none_for_unrelated_text():
    sentence = "Honda announced a $1B investment in solid-state batteries."
    text = "The Tokyo restaurant scene revived after pandemic restrictions lifted."
    assert find_span_in_text(sentence, text) is None


def test_find_span_handles_short_sentence_by_returning_none():
    # Below LONGEST_BLOCK_MIN_CHARS → not enough signal.
    assert find_span_in_text("Yes.", "Some long evidence text here.") is None


def test_find_span_handles_paraphrase_with_partial_match():
    # The sentence shares a long substring with the evidence — should resolve.
    sentence = "Tesla's vehicle deliveries grew strongly in 2024."
    text = (
        "We note that Tesla's vehicle deliveries grew compared to the prior period, "
        "though margin compressed."
    )
    span = find_span_in_text(sentence, text)
    assert span is not None


def test_find_span_empty_inputs_return_none():
    assert find_span_in_text("", "evidence") is None
    assert find_span_in_text("sentence", "") is None
    assert find_span_in_text(None, "x") is None  # type: ignore[arg-type]


# ── validate_sentence_citations ──


def test_validate_marks_resolved_when_evidence_contains_sentence():
    factors = [{
        "factor_id": "COM001",
        "dimension": "capital_allocation",
        "claim": "Tesla's operating margin compressed in fiscal year 2024.",
        "supporting_evidence": ["E001"],
    }]
    evidence = [{
        "evidence_id": "E001",
        "span_text": (
            "Item 7 MD&A: Tesla's operating margin compressed in fiscal year 2024 "
            "due to price reductions and increased manufacturing investment."
        ),
        "doc_id": "0001628280-25-003063",
        "global_char_start": 14000,
    }]
    results = validate_sentence_citations(factors, evidence)
    assert len(results) == 1
    r = results[0]
    assert r["status"] == "resolved"
    assert r["matched_evidence_id"] == "E001"
    assert r["doc_id"] == "0001628280-25-003063"
    # global offset is 14000 + (local match position)
    assert r["char_start"] is not None and r["char_start"] >= 14000


def test_validate_marks_unresolved_when_no_cited_evidence_matches():
    factors = [{
        "factor_id": "COM001",
        "claim": "Honda announced a $5 billion investment in solid-state batteries.",
        "supporting_evidence": ["E001"],
    }]
    evidence = [{
        "evidence_id": "E001",
        "span_text": "Tokyo's restaurant scene is recovering quickly post-pandemic.",
        "doc_id": "DOC-RANDOM",
    }]
    results = validate_sentence_citations(factors, evidence)
    assert len(results) == 1
    assert results[0]["status"] == "unresolved"
    assert results[0]["matched_evidence_id"] is None
    assert results[0]["doc_id"] is None


def test_validate_marks_no_citations_when_supporting_evidence_empty():
    factors = [{
        "factor_id": "COM001",
        "claim": "This factor has a real claim sentence with enough length to be valid.",
        "supporting_evidence": [],  # empty
    }]
    evidence = []
    results = validate_sentence_citations(factors, evidence)
    assert len(results) == 1
    assert results[0]["status"] == "no_citations"


def test_validate_walks_both_claim_and_description():
    """The validator considers `claim` AND `description` as load-bearing prose."""
    factors = [{
        "factor_id": "COM001",
        "claim": "Honda's BEV strategy lags competitors significantly.",
        "description": "The capital commitment is below industry benchmarks.",
        "supporting_evidence": ["E001"],
    }]
    evidence = [{
        "evidence_id": "E001",
        "span_text": (
            "Honda's BEV strategy lags competitors significantly in scale. "
            "The capital commitment is below industry benchmarks for tier-1 OEMs."
        ),
        "doc_id": "DOC1",
    }]
    results = validate_sentence_citations(factors, evidence)
    # Both sentences should resolve
    assert len(results) == 2
    assert all(r["status"] == "resolved" for r in results)


def test_validate_uses_first_matching_cited_evidence():
    """When multiple cited evidence ids could match, the first wins."""
    factors = [{
        "factor_id": "X",
        "claim": "Tesla's vehicle deliveries grew strongly in fiscal year 2024.",
        "supporting_evidence": ["E001", "E002"],
    }]
    evidence = [
        {
            "evidence_id": "E001",
            "span_text": "Tesla's vehicle deliveries grew strongly in fiscal year 2024.",
            "doc_id": "DOC_A",
        },
        {
            "evidence_id": "E002",
            "span_text": "Tesla's vehicle deliveries grew strongly in fiscal year 2024.",
            "doc_id": "DOC_B",
        },
    ]
    results = validate_sentence_citations(factors, evidence)
    assert len(results) == 1
    # E001 is first in supporting_evidence — must win.
    assert results[0]["matched_evidence_id"] == "E001"
    assert results[0]["doc_id"] == "DOC_A"


def test_validate_skips_factor_with_no_claim_text():
    factors = [{
        "factor_id": "X",
        # No claim, no description
        "supporting_evidence": ["E001"],
    }]
    evidence = [{"evidence_id": "E001", "span_text": "text", "doc_id": "D"}]
    results = validate_sentence_citations(factors, evidence)
    assert results == []


def test_validate_handles_phantom_citation():
    """A cited evidence_id that doesn't exist in the evidence index =
    falls through as unresolved, not crash."""
    factors = [{
        "factor_id": "X",
        "claim": "Some factual claim about strategic risk that is long enough.",
        "supporting_evidence": ["E_DOES_NOT_EXIST"],
    }]
    evidence = []
    results = validate_sentence_citations(factors, evidence)
    assert len(results) == 1
    assert results[0]["status"] == "unresolved"


# ── sentence_citation_summary ──


def test_summary_aggregate_counts():
    results = [
        {"status": "resolved", "factor_id": "A", "sentence": "x"},
        {"status": "resolved", "factor_id": "A", "sentence": "y"},
        {"status": "unresolved", "factor_id": "B", "sentence": "z"},
        {"status": "no_citations", "factor_id": "C", "sentence": "w"},
    ]
    s = sentence_citation_summary(results)
    assert s["total_sentences"] == 4
    assert s["resolved"] == 2
    assert s["unresolved"] == 1
    assert s["no_citations"] == 1
    assert s["resolution_rate"] == 0.5


def test_summary_handles_empty():
    s = sentence_citation_summary([])
    assert s["total_sentences"] == 0
    assert s["resolution_rate"] == 1.0


# ── unresolved_violations ──


def test_unresolved_filters_out_resolved():
    results = [
        {"status": "resolved", "factor_id": "A"},
        {"status": "unresolved", "factor_id": "B"},
        {"status": "no_citations", "factor_id": "C"},
    ]
    out = unresolved_violations(results)
    assert len(out) == 2
    statuses = sorted(r["status"] for r in out)
    assert statuses == ["no_citations", "unresolved"]
