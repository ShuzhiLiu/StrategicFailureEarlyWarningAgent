"""File-based artifact handoffs between agents.

Inspired by Anthropic's harness design pattern: agents communicate via
structured files, making outputs auditable, persistent across context
resets, and easy to inspect.

Each pipeline run produces a directory of artifacts:
  outputs/{run_id}/
    evidence.json       - extracted evidence items
    risk_factors.json   - identified risk factors
    challenges.json     - adversarial challenges
    risk_memo.md        - final risk memo (markdown)
    backtest.json       - backtest results
    run_metadata.json   - config hash, model versions, timestamps
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from liteagent import dedup_by_key
from sfewa.tools.chat_log import get_log
from sfewa.tools.citation_check import (
    citation_summary,
    validate_top_level_claims,
)
from sfewa.tools.manifest import (
    build_manifest_from_docs,
    manifest_summary,
)
from sfewa.tools.provenance import build_provenance
from sfewa.tools.sentence_citation import (
    sentence_citation_summary,
    unresolved_violations,
    validate_sentence_citations,
)


def get_run_dir(run_id: str, base_dir: str = "outputs") -> Path:
    """Get or create the output directory for a pipeline run."""
    run_dir = Path(base_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def save_artifact(run_id: str, name: str, data: list | dict | str) -> Path:
    """Save a pipeline artifact to the run directory."""
    run_dir = get_run_dir(run_id)
    path = run_dir / name

    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    return path


def load_artifact(run_id: str, name: str) -> list | dict | str | None:
    """Load a pipeline artifact from a previous run."""
    path = get_run_dir(run_id) / name
    if not path.exists():
        return None

    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8")


def save_run_metadata(
    run_id: str,
    case_id: str,
    config_hash: str = "",
    model_info: dict | None = None,
) -> Path:
    """Save run metadata for reproducibility and audit trail."""
    metadata = {
        "run_id": run_id,
        "case_id": case_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "config_hash": config_hash,
        "model_info": model_info or {},
    }
    return save_artifact(run_id, "run_metadata.json", metadata)


def save_run_artifacts(
    state: dict,
    *,
    case_path: str | Path | None = None,
    truth_path: str | Path | None = None,
    started_at: float | None = None,
    elapsed_seconds: float | None = None,
) -> Path:
    """Save all pipeline outputs from a completed run.

    Computes the L1.4 audit invariants but RECORDS violations as data in
    run_summary.json rather than raising — saving artifacts is more
    important than punishing the run. The CI gate (a separate test that
    reads run_summary.json) is the place where violations fail the build.

    Args:
        state: completed pipeline state.
        case_path: path to the case YAML used for the run (for provenance sha).
        truth_path: path to the truth YAML, if any (for provenance sha).
        started_at: UNIX epoch seconds when the run began.
        elapsed_seconds: wall-clock duration.
    """
    case_id = state.get("case_id", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{case_id}_{timestamp}"

    # ── Source manifest (L1.4-A) ──
    # Prefer the manifest accumulated in state by retrieval; fall back to
    # building it from retrieved_docs.
    cutoff_date = state.get("cutoff_date") or ""
    manifest = state.get("source_manifest") or build_manifest_from_docs(
        state.get("retrieved_docs", []),
        cutoff_date=cutoff_date,
    )
    save_artifact(run_id, "source_manifest.json", manifest)

    # Compute manifest violations as data (kept docs with release_time > cutoff).
    manifest_violations: list[dict] = []
    if cutoff_date:
        from sfewa.tools.manifest import _iso_date_part
        try:
            cutoff_d = _iso_date_part(cutoff_date)
            for e in manifest:
                if e.get("cutoff_decision") != "kept":
                    continue
                rt = e.get("release_time") or ""
                if not rt:
                    continue
                try:
                    if _iso_date_part(rt) > cutoff_d:
                        manifest_violations.append({
                            "title": e.get("title"),
                            "source": e.get("source"),
                            "release_time": rt,
                        })
                except ValueError:
                    pass
        except ValueError:
            pass

    save_artifact(run_id, "evidence.json", state.get("evidence", []))

    # ── Strategy discovery audit (L2.4) ──
    # When strategy_discovery ran (case YAML had no strategy_theme, or
    # --discover-strategies was passed), record the full candidate list
    # so a reviewer can see what alternatives existed and why the chosen
    # primary was used.
    discovered = state.get("discovered_strategies")
    if discovered:
        save_artifact(run_id, "discovered_strategies.json", discovered)

    # ── Claim-citation check (L1.4-C) ──
    # Records violations as data; never raises (artifact saving must
    # always complete so the user has the full audit trail).
    deduped_factors = dedup_by_key(state.get("risk_factors", []), "dimension")
    citation_violations = validate_top_level_claims(
        deduped_factors, state.get("evidence", []) or []
    )
    # ── Sentence-level citation check (L2.3) ──
    # Soft validator: per-sentence walk of each factor's claim+description,
    # fuzzy-matching against cited evidence text. Records violations as data;
    # the `sentence_citations.json` artifact is the full per-sentence audit.
    sentence_results = validate_sentence_citations(
        deduped_factors, state.get("evidence", []) or []
    )
    save_artifact(run_id, "sentence_citations.json", sentence_results)
    sentence_violations = unresolved_violations(sentence_results)
    save_artifact(run_id, "risk_factors.json", deduped_factors)
    # Deduplicate challenges: cross-pass accumulation creates duplicates
    deduped_challenges = dedup_by_key(
        state.get("adversarial_challenges", []), "target_factor_id"
    )
    save_artifact(run_id, "challenges.json", deduped_challenges)

    backtest_data = {
        "events": state.get("backtest_events", []),
        "summary": state.get("backtest_summary"),
    }
    save_artifact(run_id, "backtest.json", backtest_data)

    memo = state.get("risk_memo")
    if memo:
        save_artifact(run_id, "risk_memo.md", memo)

    summary = {
        "case_id": case_id,
        "company": state.get("company"),
        "strategy_theme": state.get("strategy_theme"),
        "cutoff_date": state.get("cutoff_date"),
        "case_type": state.get("case_type", "retrospective"),
        "risk_score": state.get("risk_score"),
        "overall_risk_level": state.get("overall_risk_level"),
        "overall_confidence": state.get("overall_confidence"),
        "evidence_count": len(state.get("evidence", [])),
        "risk_factor_count": len(deduped_factors),
        "challenge_count": len(state.get("adversarial_challenges", [])),
        "backtest_events": len(state.get("backtest_events", [])),
        "adversarial_pass_count": state.get("adversarial_pass_count", 0),
        "iteration_count": state.get("iteration_count", 0),
        "manifest": manifest_summary(manifest),
        "citations": citation_summary(deduped_factors, state.get("evidence", [])),
        "sentence_citations": sentence_citation_summary(sentence_results),
        # L1.4 + L2.3 audit violations recorded as data. CI gate fails when
        # these are non-empty; pipeline runs always complete so the audit
        # trail is available for inspection.
        "audit_violations": {
            "manifest_kept_post_cutoff": manifest_violations,
            "citations_unresolved": citation_violations,
            "sentence_citations_unresolved": sentence_violations,
        },
    }
    save_artifact(run_id, "run_summary.json", summary)

    save_run_metadata(run_id, case_id)

    # Save raw LLM chat history (JSONL: one JSON object per line)
    chat_log = get_log()
    if chat_log:
        lines = [json.dumps(entry, ensure_ascii=False, default=str) for entry in chat_log]
        save_artifact(run_id, "llm_history.jsonl", "\n".join(lines))

    # ── Provenance header (L1.4) ──
    provenance = build_provenance(
        state,
        case_path=case_path,
        truth_path=truth_path,
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
    )
    save_artifact(run_id, "provenance.json", provenance)

    # ── Static HTML report (L1.7) ──
    # Generated last so it can read every other artifact off disk. Failures
    # in the report generator are non-fatal — the JSON artifacts remain
    # the authoritative output.
    try:
        from sfewa.tools.html_report import generate_report
        generate_report(get_run_dir(run_id))
    except Exception as e:  # noqa: BLE001
        # Don't break artifact saving if templating throws; log via reporting.
        try:
            from sfewa import reporting
            reporting.log_action("HTML report generation failed", {"error": str(e)[:200]})
        except Exception:
            pass

    return get_run_dir(run_id)
