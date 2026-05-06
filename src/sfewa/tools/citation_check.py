"""Claim-citation enforcement (L1.4-C).

Production-level invariant enforced at artifact-save time:

    Every entry in risk_factors.json (top-level claim) MUST reference at
    least one supporting_evidence id that resolves to an existing
    evidence item with a non-empty source URL / doc reference.

If violated, save_run_artifacts raises ClaimCitationError before any
artifacts are written. The audit story breaks if we can't trace claims
back to source documents.

L1 scope is top-level claims only (the 10 risk factors). Layer 2 will
tighten this to sentence-level citations against EvidenceChunk
(global_char_start, global_char_end) offsets.
"""

from __future__ import annotations

from typing import Any


class ClaimCitationError(AssertionError):
    """A top-level claim has no resolvable supporting evidence (L1.4-C)."""


def _evidence_index(evidence: list[dict]) -> dict[str, dict]:
    return {e.get("evidence_id"): e for e in evidence if e.get("evidence_id")}


def _evidence_has_doc_reference(e: dict) -> bool:
    """Does this evidence item carry a verifiable pointer back to a source?

    Accepted forms (any one is sufficient):
        - source_url (legacy evidence pipeline)
        - doc_id     (FilingProvider-native EvidenceChunk)
        - source_title + published_at (filing-style citation, useful for
          EDINET/CNINFO chunks loaded from cache where source_url may be
          opaque like "edinet:S100UOAW")
    """
    if e.get("source_url"):
        return True
    if e.get("doc_id"):
        return True
    if e.get("source_title") and e.get("published_at"):
        return True
    return False


def validate_top_level_claims(
    risk_factors: list[dict],
    evidence: list[dict],
) -> list[str]:
    """Return a list of human-readable violations. Empty list = clean.

    Used by both the runtime assert_claim_citations() and the per-test
    inspection helper.
    """
    violations: list[str] = []
    if not risk_factors:
        # No factors → nothing to validate. The pipeline-level decision
        # whether 0 factors is a failure lives elsewhere.
        return violations

    ev_index = _evidence_index(evidence)

    for f in risk_factors:
        fid = f.get("factor_id") or f.get("dimension") or "<unnamed>"
        cited = list(f.get("supporting_evidence") or [])
        if not cited:
            violations.append(f"{fid}: supporting_evidence is empty")
            continue
        valid = [
            ev_id for ev_id in cited
            if ev_id in ev_index and _evidence_has_doc_reference(ev_index[ev_id])
        ]
        if not valid:
            phantom = [eid for eid in cited if eid not in ev_index]
            no_ref = [
                eid for eid in cited
                if eid in ev_index and not _evidence_has_doc_reference(ev_index[eid])
            ]
            reason_parts = []
            if phantom:
                reason_parts.append(f"phantom={phantom[:3]}")
            if no_ref:
                reason_parts.append(f"no_doc_ref={no_ref[:3]}")
            violations.append(
                f"{fid}: no resolvable supporting_evidence "
                f"(cited {len(cited)}, "
                f"{', '.join(reason_parts) or 'all unresolvable'})"
            )
    return violations


def assert_claim_citations(
    risk_factors: list[dict],
    evidence: list[dict],
) -> None:
    """Raise ClaimCitationError if any top-level claim is uncited.

    Called by save_run_artifacts() as part of the L1.4 audit gate.
    """
    violations = validate_top_level_claims(risk_factors, evidence)
    if violations:
        raise ClaimCitationError(
            f"{len(violations)} top-level claim(s) have no resolvable "
            f"supporting evidence (L1.4 audit invariant failed):\n"
            + "\n".join(f"  - {v}" for v in violations[:10])
        )


def citation_summary(
    risk_factors: list[dict],
    evidence: list[dict],
) -> dict[str, Any]:
    """Aggregate citation health for the run summary."""
    ev_index = _evidence_index(evidence)
    total = len(risk_factors)
    fully_cited = 0
    total_cited = 0
    total_resolved = 0
    for f in risk_factors:
        cited = list(f.get("supporting_evidence") or [])
        total_cited += len(cited)
        resolved = [
            eid for eid in cited
            if eid in ev_index and _evidence_has_doc_reference(ev_index[eid])
        ]
        total_resolved += len(resolved)
        if resolved:
            fully_cited += 1
    return {
        "total_factors": total,
        "factors_with_resolved_citation": fully_cited,
        "total_citations_made": total_cited,
        "total_citations_resolved": total_resolved,
    }
