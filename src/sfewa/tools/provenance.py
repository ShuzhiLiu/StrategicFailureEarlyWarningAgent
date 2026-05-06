"""Run provenance header (L1.4).

Records everything a reviewer needs to reproduce or audit a run:

    - model id and provider (DEFAULT_LLM_MODEL, DEFAULT_LLM_PROVIDER)
    - sampling temperature(s) seen during the run
    - git commit hash (HEAD), branch, dirty flag
    - case config sha256 + truth file sha256 (if present)
    - cutoff date, case_type
    - source_manifest path + summary counts
    - total LLM tokens (prompt + completion)
    - wall-clock duration

Saved as `outputs/{run_id}/provenance.json`. Surfaced inline in
run_summary.json so a single artifact carries the headline answer
(score, level) and the full audit trail.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


# ── Git ──


def _git_output(*args: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def git_commit(cwd: Path | None = None) -> str:
    """Return short HEAD commit (or empty string if not a git repo)."""
    return _git_output("rev-parse", "--short=12", "HEAD", cwd=cwd)


def git_branch(cwd: Path | None = None) -> str:
    return _git_output("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)


def git_is_dirty(cwd: Path | None = None) -> bool:
    """True if the working tree has uncommitted changes."""
    out = _git_output("status", "--porcelain", cwd=cwd)
    return bool(out)


# ── Hashing ──


def sha256_of_file(path: str | Path) -> str | None:
    """sha256 of a file. None if the file doesn't exist."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ── Builder ──


def build_provenance(
    state: dict,
    *,
    case_path: str | Path | None = None,
    truth_path: str | Path | None = None,
    started_at: float | None = None,
    elapsed_seconds: float | None = None,
    repo_root: Path | None = None,
) -> dict:
    """Build the provenance dict from pipeline state and run metadata.

    Args:
        state: pipeline state at end-of-run.
        case_path: path to the case YAML used for this run.
        truth_path: path to the truth YAML, if applicable.
        started_at: UNIX epoch seconds when the run began.
        elapsed_seconds: wall-clock duration.
        repo_root: repository root (for git introspection). Defaults to the
            cwd at call time.
    """
    case_sha = sha256_of_file(case_path) if case_path else None
    truth_sha = sha256_of_file(truth_path) if truth_path else None

    # Token totals from CallLog (best-effort — log may not exist in tests)
    total_prompt_tokens = 0
    total_completion_tokens = 0
    try:
        from sfewa.tools.chat_log import get_log
        for entry in get_log() or []:
            usage = entry.get("usage") or {}
            total_prompt_tokens += int(usage.get("prompt_tokens") or 0)
            total_completion_tokens += int(usage.get("completion_tokens") or 0)
    except Exception:
        pass

    # Manifest counts
    manifest = state.get("source_manifest") or []
    manifest_kept = sum(1 for e in manifest if e.get("cutoff_decision") == "kept")
    manifest_rejected = sum(
        1 for e in manifest if e.get("cutoff_decision") == "rejected_post_cutoff"
    )

    return {
        "case_id": state.get("case_id"),
        "case_type": state.get("case_type", "retrospective"),
        "company": state.get("company"),
        "strategy_theme": state.get("strategy_theme"),
        "cutoff_date": state.get("cutoff_date"),
        "started_at_utc": (
            datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat()
            if started_at is not None
            else None
        ),
        "elapsed_seconds": (
            round(elapsed_seconds, 2) if elapsed_seconds is not None else None
        ),
        "model": {
            "provider": os.environ.get("DEFAULT_LLM_PROVIDER", "unknown"),
            "model_id": os.environ.get("DEFAULT_LLM_MODEL", "unknown"),
            "base_url": os.environ.get("DEFAULT_BASE_URL"),
        },
        "git": {
            "commit": git_commit(repo_root),
            "branch": git_branch(repo_root),
            "dirty": git_is_dirty(repo_root),
        },
        "case_config": {
            "path": str(case_path) if case_path else None,
            "sha256": case_sha,
        },
        "truth_config": {
            "path": str(truth_path) if truth_path else None,
            "sha256": truth_sha,
        },
        "audit_meta": state.get("audit_meta") or {},
        "manifest": {
            "total_entries": len(manifest),
            "kept": manifest_kept,
            "rejected_post_cutoff": manifest_rejected,
        },
        "tokens": {
            "prompt": total_prompt_tokens,
            "completion": total_completion_tokens,
            "total": total_prompt_tokens + total_completion_tokens,
        },
    }
