"""Sentence-level claim citation enforcement (L2.3).

L1.4-C requires every top-level claim (i.e., each entry in
risk_factors.json) to reference at least one supporting_evidence id that
resolves to evidence with a real document reference. That's the
"top-level" floor — a factor with three claim sentences and one
cited evidence id passes L1 even if only one of the three sentences
actually appears in the evidence.

L2.3 tightens the invariant by walking each *sentence* of the factor's
claim + description and asking: does any cited evidence's text contain
this sentence (or its load-bearing content)? When the answer is yes, we
record a `(doc_id, char_start, char_end)` span pointing into the cited
evidence's `span_text`. When the answer is no, we record an
`unresolved` violation.

Two complementary matchers run in series:
    1. Token overlap (primary, catches paraphrases). Compares content
       words (stopword-filtered) between sentence and evidence; when
       coverage exceeds threshold, finds the tightest evidence window
       containing the matched tokens.
    2. difflib longest-block (fallback, catches verbatim quotes and
       CJK text where token-splitting is too coarse).

Why two paths? Analysts paraphrase synthesized claims rather than
quote verbatim. Pure-difflib resolution rates were 1-10% across cases
even when the underlying claim was clearly traceable. Token overlap
lifts paraphrase recall while difflib remains the safety net for the
exact-quote and CJK cases.

This is *post-hoc validation*: the analyst LLM doesn't currently emit
sentence→span mappings, so the validator does fuzzy matching against
cited evidence text. The thresholds are deliberately lenient (the goal
is honest audit signal, not gatekeeping a brittle matcher). Like
L1.4-C, violations are recorded as data in
`run_summary.json["audit_violations"]["sentence_citations_unresolved"]`,
not raised — saving artifacts must always complete.

Why audit-level instead of pipeline-level?
    Pipeline-level enforcement (i.e., refuse to ship a memo with
    unresolved sentences) would require the LLM to author claims that
    fit the matcher's grammar, which would distort the analytical
    output. Recording the gap as data lets the audit story be honest
    while keeping the analytical layer free.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

# ── difflib path thresholds (verbatim/near-verbatim quotes) ──

# How much of the sentence's normalized text must match the evidence text
# (longest contiguous block / sentence length) before we declare the
# sentence "resolved" via the difflib path. 0.25 is a deliberately
# lenient threshold — high enough to reject completely unrelated
# evidence, low enough that partial verbatim quotes still resolve.
LONGEST_BLOCK_MIN_RATIO = 0.25

# Absolute floor — even short sentences require some real matching content,
# not a single-word coincidence ("the" matches anywhere).
LONGEST_BLOCK_MIN_CHARS = 12

# Sentences this short are skipped — they're typically headers or fragments
# that don't carry an independently citable factual claim.
MIN_SENTENCE_CHARS = 20

# ── Token-overlap path thresholds (paraphrases, reordered prose) ──

# Sentences with fewer content tokens than this skip the token path
# entirely — too few signals to distinguish a real match from chance.
TOKEN_OVERLAP_MIN_TOKENS = 4

# Distinct content tokens that must appear in BOTH sentence and evidence
# for a token-overlap match to count. Floor of 3 prevents 1-2 word
# coincidences from resolving.
TOKEN_OVERLAP_MIN_HITS = 3

# Fraction of the sentence's content tokens that must be present in the
# evidence. 0.55 catches typical paraphrases (which preserve most
# content words while reordering connectives) without admitting
# loosely-related evidence.
TOKEN_OVERLAP_MIN_RATIO = 0.55


# ── Sentence splitting ──


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z一-鿿])")


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentence-like chunks.

    Conservative regex-based splitter (no NLP dep). Sentence boundary =
    `.!?` followed by whitespace and a capital ASCII letter or a CJK
    ideograph. Empty / very-short fragments (< MIN_SENTENCE_CHARS) are
    dropped — they're typically section headers, list bullets, or
    figures that don't carry an independent factual claim.
    """
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = _SENTENCE_BOUNDARY.split(normalized)
    out: list[str] = []
    for p in parts:
        s = p.strip()
        if len(s) >= MIN_SENTENCE_CHARS:
            out.append(s)
    return out


# ── Content tokenization ──

# Common English stopwords that carry little citation signal. Kept
# small on purpose — over-aggressive filtering eats meaningful tokens
# (e.g. "not", "no" can flip a claim's polarity but rarely change
# whether evidence supports it). Years like "2024" are NOT filtered;
# they're high-signal anchors.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his",
    "how", "man", "new", "now", "old", "see", "two", "way", "who", "boy",
    "did", "its", "let", "put", "say", "she", "too", "use", "with", "this",
    "that", "from", "they", "have", "been", "were", "said", "what", "your",
    "when", "make", "than", "them", "then", "into", "more", "some", "such",
    "very", "just", "also", "only", "over", "those", "these", "their",
    "would", "could", "should", "after", "before", "during", "while",
    "within", "without", "among", "between", "through", "across", "above",
    "below", "under", "upon", "against", "because", "since", "though",
    "although", "however", "therefore", "thus", "hence", "indeed", "still",
    "even", "ever", "yet", "any", "many", "much", "each", "every", "either",
    "neither", "both", "other", "another", "where", "which", "whose",
})


def _content_tokens(text: str) -> list[str]:
    """Lowercase content tokens carrying citation signal.

    Rules:
        - words: length >= 3 and not in _STOPWORDS
        - numbers: length >= 2 (drops "1", "4" but keeps "24", "2024")

    Numbers are preserved deliberately — years and dollar magnitudes
    are high-signal anchors for retrospective claims.
    """
    raw = re.findall(r"[A-Za-z0-9]+", text.lower())
    out: list[str] = []
    for t in raw:
        if t.isdigit():
            if len(t) >= 2:
                out.append(t)
        elif len(t) >= 3 and t not in _STOPWORDS:
            out.append(t)
    return out


def _find_word_boundary_positions(text_lower: str, token: str) -> list[int]:
    """All word-boundary positions of `token` in `text_lower`."""
    out: list[int] = []
    idx = 0
    n = len(text_lower)
    while True:
        j = text_lower.find(token, idx)
        if j < 0:
            return out
        left_ok = j == 0 or not text_lower[j - 1].isalnum()
        right_end = j + len(token)
        right_ok = right_end >= n or not text_lower[right_end].isalnum()
        if left_ok and right_ok:
            out.append(j)
        idx = j + 1


# ── Fuzzy span match ──


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace + strip non-alphanumeric padding."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _token_overlap_match(
    sentence: str, evidence_text: str,
) -> tuple[int, int] | None:
    """Locate `sentence` inside `evidence_text` via content-token overlap.

    Returns (start, end) char offsets in `evidence_text` when the
    sentence's content-token coverage in evidence is above threshold,
    else None.

    The span is the tightest window in the evidence containing the
    matched tokens — gives the reviewer something to highlight, even
    when the prose was paraphrased rather than quoted.
    """
    sent_tokens = _content_tokens(sentence)
    if len(sent_tokens) < TOKEN_OVERLAP_MIN_TOKENS:
        return None
    sent_set = set(sent_tokens)
    if not sent_set:
        return None

    ev_tokens = _content_tokens(evidence_text)
    if not ev_tokens:
        return None
    ev_set = set(ev_tokens)

    hits = sent_set & ev_set
    if len(hits) < TOKEN_OVERLAP_MIN_HITS:
        return None
    ratio = len(hits) / len(sent_set)
    if ratio < TOKEN_OVERLAP_MIN_RATIO:
        return None

    # Locate the tightest window in evidence_text containing the hit tokens.
    text_lower = evidence_text.lower()
    positions: list[int] = []
    for tok in hits:
        positions.extend(_find_word_boundary_positions(text_lower, tok))
    if not positions:
        return None
    positions.sort()

    # Window heuristic: smallest range covering ~60% of hit positions
    # (or all of them when only a handful).
    target = max(2, int(round(len(positions) * 0.6)))
    target = min(target, len(positions))
    best_span: tuple[int, int] | None = None
    best_width = 10**9
    for i in range(len(positions) - target + 1):
        start = positions[i]
        end = positions[i + target - 1]
        width = end - start
        if width < best_width:
            best_width = width
            best_span = (start, min(end + 30, len(evidence_text)))
    if best_span is None:
        first = positions[0]
        return (first, min(first + 80, len(evidence_text)))
    return best_span


def _longest_block_match(
    sentence: str, evidence_text: str,
) -> tuple[int, int] | None:
    """difflib longest-contiguous-block match. Catches verbatim quotes
    and CJK prose where token-splitting is too coarse."""
    sent_norm = _normalize(sentence)
    text_norm = _normalize(evidence_text)
    if len(sent_norm) < LONGEST_BLOCK_MIN_CHARS:
        return None
    if not text_norm:
        return None

    matcher = SequenceMatcher(None, text_norm, sent_norm, autojunk=False)
    block = matcher.find_longest_match(0, len(text_norm), 0, len(sent_norm))
    if block.size < max(LONGEST_BLOCK_MIN_CHARS, int(len(sent_norm) * LONGEST_BLOCK_MIN_RATIO)):
        return None

    matched_norm = text_norm[block.a : block.a + block.size]
    needle = matched_norm[: min(32, len(matched_norm))]
    pos = evidence_text.lower().find(needle)
    if pos < 0:
        return (block.a, block.a + block.size)
    end = min(pos + block.size + 16, len(evidence_text))
    return (pos, end)


def find_span_in_text(
    sentence: str,
    evidence_text: str,
) -> tuple[int, int] | None:
    """Locate the most plausible character span of `sentence` inside `evidence_text`.

    Returns (start, end) char offsets in `evidence_text` when matched,
    or None when no path produces a confident match. Offsets are local
    to `evidence_text`; callers with global EvidenceChunk offsets add
    `chunk.global_char_start` to globalize.

    Path order:
        1. Token-overlap (primary) — robust to paraphrase.
        2. difflib longest-block (fallback) — catches verbatim quotes
           and CJK prose.
    """
    if not sentence or not evidence_text:
        return None

    span = _token_overlap_match(sentence, evidence_text)
    if span is not None:
        return span
    return _longest_block_match(sentence, evidence_text)


# ── Validator ──


def _evidence_index(evidence: list[dict]) -> dict[str, dict]:
    return {e.get("evidence_id"): e for e in evidence if e.get("evidence_id")}


def _evidence_match_text(e: dict) -> str:
    """The text body to match a sentence against.

    Prefer `span_text` (the verbatim quote from the source) since that's
    the field the L2.3 invariant most cleanly resolves against. Fall
    back to `claim_text`/`snippet` for evidence loaded from web-search
    or filings without explicit span quotes.
    """
    for key in ("span_text", "claim_text", "snippet", "text"):
        v = e.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _factor_claim_text(f: dict) -> str:
    """Combine the factor's load-bearing prose into a single block.

    Toulmin output (iter 39+) puts the central factual assertion in
    `claim`; older runs use `description`. We concatenate so sentence
    splitting catches both. `warrant` and `strongest_counter` are
    intentionally excluded — they're argumentation, not factual
    claims that need verbatim source citation.
    """
    parts = []
    for key in ("claim", "description"):
        v = f.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return "\n".join(parts)


def validate_sentence_citations(
    risk_factors: list[dict],
    evidence: list[dict],
) -> list[dict]:
    """Per-sentence audit of every risk factor's claim text.

    Returns a flat list of result dicts; one entry per (factor, sentence):
        {
            "factor_id":   str,
            "sentence":    str (truncated to 180 chars for log readability),
            "status":      "resolved" | "unresolved" | "no_citations",
            "matched_evidence_id":   str | None,
            "doc_id":      str | None,
            "char_start":  int | None,
            "char_end":    int | None,
        }

    Callers usually filter by `status != "resolved"` to extract the
    audit_violations payload.
    """
    if not risk_factors:
        return []
    ev_index = _evidence_index(evidence)

    out: list[dict] = []
    for f in risk_factors:
        fid = f.get("factor_id") or f.get("dimension") or "<unnamed>"
        claim_block = _factor_claim_text(f)
        sentences = split_into_sentences(claim_block)
        if not sentences:
            continue

        cited = list(f.get("supporting_evidence") or [])

        for sent in sentences:
            sent_truncated = sent[:180] + ("…" if len(sent) > 180 else "")
            if not cited:
                out.append({
                    "factor_id": fid,
                    "sentence": sent_truncated,
                    "status": "no_citations",
                    "matched_evidence_id": None,
                    "doc_id": None,
                    "char_start": None,
                    "char_end": None,
                })
                continue

            best_match: dict | None = None
            for ev_id in cited:
                ev = ev_index.get(ev_id)
                if ev is None:
                    continue
                ev_text = _evidence_match_text(ev)
                if not ev_text:
                    continue
                span = find_span_in_text(sent, ev_text)
                if span is None:
                    continue
                start, end = span
                # Add chunk's global offset when present so the recorded
                # span is global, not just local to the cited evidence.
                offset = int(ev.get("global_char_start") or 0)
                best_match = {
                    "matched_evidence_id": ev_id,
                    "doc_id": ev.get("doc_id") or ev.get("source_url") or ev.get("link"),
                    "char_start": offset + start,
                    "char_end": offset + end,
                }
                break  # first cited evidence that matches wins

            if best_match is not None:
                out.append({
                    "factor_id": fid,
                    "sentence": sent_truncated,
                    "status": "resolved",
                    **best_match,
                })
            else:
                out.append({
                    "factor_id": fid,
                    "sentence": sent_truncated,
                    "status": "unresolved",
                    "matched_evidence_id": None,
                    "doc_id": None,
                    "char_start": None,
                    "char_end": None,
                })

    return out


def sentence_citation_summary(results: list[dict]) -> dict[str, Any]:
    """Aggregate counts for run_summary.json."""
    total = len(results)
    if total == 0:
        return {
            "total_sentences": 0,
            "resolved": 0,
            "unresolved": 0,
            "no_citations": 0,
            "resolution_rate": 1.0,
        }
    resolved = sum(1 for r in results if r["status"] == "resolved")
    unresolved = sum(1 for r in results if r["status"] == "unresolved")
    no_citations = sum(1 for r in results if r["status"] == "no_citations")
    return {
        "total_sentences": total,
        "resolved": resolved,
        "unresolved": unresolved,
        "no_citations": no_citations,
        "resolution_rate": round(resolved / total, 3),
    }


def unresolved_violations(results: list[dict]) -> list[dict]:
    """Return only the entries whose status is not 'resolved'.

    Saved into `audit_violations.sentence_citations_unresolved`.
    """
    return [r for r in results if r["status"] != "resolved"]


__all__ = [
    "split_into_sentences",
    "find_span_in_text",
    "validate_sentence_citations",
    "sentence_citation_summary",
    "unresolved_violations",
    "LONGEST_BLOCK_MIN_RATIO",
    "LONGEST_BLOCK_MIN_CHARS",
    "MIN_SENTENCE_CHARS",
    "TOKEN_OVERLAP_MIN_TOKENS",
    "TOKEN_OVERLAP_MIN_HITS",
    "TOKEN_OVERLAP_MIN_RATIO",
]
