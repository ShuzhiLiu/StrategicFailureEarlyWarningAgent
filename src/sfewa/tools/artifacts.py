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


def get_run_dir(run_id: str, base_dir: str = "outputs") -> Path:
    """Get or create the output directory for a pipeline run."""
    run_dir = Path(base_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def save_artifact(run_id: str, name: str, data: list | dict | str) -> Path:
    """Save a pipeline artifact to the run directory.

    Args:
        run_id: Unique identifier for this pipeline run.
        name: Artifact name (e.g., "evidence.json", "risk_memo.md").
        data: Data to save. Dicts/lists are saved as JSON, strings as text.

    Returns:
        Path to the saved artifact.
    """
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


def save_run_artifacts(state: dict) -> Path:
    """Save all pipeline outputs from a completed run.

    Creates a timestamped directory with:
      evidence.json        — accepted evidence items with traceability
      risk_factors.json    — risk factors with causal chains
      challenges.json      — adversarial challenges
      backtest.json        — backtest matches and summary
      risk_memo.md         — full risk assessment memo
      run_summary.json     — high-level metrics for quick review

    Returns:
        Path to the run directory.
    """
    case_id = state.get("case_id", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{case_id}_{timestamp}"

    save_artifact(run_id, "evidence.json", state.get("evidence", []))

    # Deduplicate risk factors: keep latest per dimension (handles multi-pass)
    raw_factors = state.get("risk_factors", [])
    seen_dims: dict[str, dict] = {}
    for rf in raw_factors:
        seen_dims[rf.get("dimension", "unknown")] = rf
    deduped_factors = list(seen_dims.values())
    save_artifact(run_id, "risk_factors.json", deduped_factors)
    save_artifact(run_id, "challenges.json", state.get("adversarial_challenges", []))

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
        "risk_score": state.get("risk_score"),
        "overall_risk_level": state.get("overall_risk_level"),
        "overall_confidence": state.get("overall_confidence"),
        "evidence_count": len(state.get("evidence", [])),
        "risk_factor_count": len(deduped_factors),
        "challenge_count": len(state.get("adversarial_challenges", [])),
        "backtest_events": len(state.get("backtest_events", [])),
        "adversarial_pass_count": state.get("adversarial_pass_count", 0),
        "iteration_count": state.get("iteration_count", 0),
    }
    save_artifact(run_id, "run_summary.json", summary)

    save_run_metadata(run_id, case_id)

    return get_run_dir(run_id)
