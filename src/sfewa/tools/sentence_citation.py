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

This is *post-hoc validation*: the analyst LLM doesn't currently emit
sentence→span mappings, so the validator does fuzzy matching against
cited evidence text. The threshold is intentionally lenient (the goal
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

# How much of the sentence's normalized text must match the evidence text
# (longest contiguous block / sentence length) before we declare the
# sentence "resolved". 0.25 is a deliberately lenient threshold:
#   - High enough to reject completely unrelated evidence
#   - Low enough that paraphrases and partial quotes still resolve
LONGEST_BLOCK_MIN_RATIO = 0.25

# Absolute floor — even short sentences require some real matching content,
# not a single-word coincidence ("the" matches anywhere).
LONGEST_BLOCK_MIN_CHARS = 12

# Sentences this short are skipped — they're typically headers or fragments
# that don't carry an independently citable factual claim.
MIN_SENTENCE_CHARS = 20


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


# ── Fuzzy span match ──


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace + strip non-alphanumeric padding."""
    return re.sub(r"\s+", " ", text).strip().lower()


def find_span_in_text(
    sentence: str,
    evidence_text: str,
) -> tuple[int, int] | None:
    """Locate the most plausible character span of `sentence` inside `evidence_text`.

    Returns (start, end) char offsets in `evidence_text` when matched,
    or None when the longest matching block is too small to count as
    citation evidence. Offsets are local to `evidence_text`.

    The L2.3 invariant target is `(doc_id, global_char_start, global_char_end)`.
    Local offsets are sufficient when the evidence is a single quote;
    callers that have access to global EvidenceChunk offsets can add
    `chunk.global_char_start` to make the offset global.
    """
    if not sentence or not evidence_text:
        return None

    # Normalize both sides; difflib matches on the normalized strings, then
    # we map the normalized match back to a position in the original
    # `evidence_text` by searching for the leading 24 chars (case-insensitive).
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
    # Take the first 32 chars of the matched normalized block as the
    # search needle (long enough to be specific, short enough that
    # whitespace differences don't break the lookup).
    needle = matched_norm[: min(32, len(matched_norm))]
    pos = evidence_text.lower().find(needle)
    if pos < 0:
        # Fallback: return the normalized offset directly (not always
        # accurate vs. the un-normalized text, but no worse than nothing).
        return (block.a, block.a + block.size)
    end = min(pos + block.size + 16, len(evidence_text))
    return (pos, end)


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
]
