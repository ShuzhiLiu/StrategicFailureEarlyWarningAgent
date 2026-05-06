"""Tests for the provenance header (L1.4)."""

from __future__ import annotations

import os
from pathlib import Path

from sfewa.tools.provenance import build_provenance, sha256_of_file


def _state(**overrides) -> dict:
    base = {
        "case_id": "honda_ev_2025",
        "case_type": "retrospective",
        "company": "Honda Motor Co., Ltd.",
        "strategy_theme": "EV electrification strategy",
        "cutoff_date": "2025-05-19",
        "audit_meta": {"jurisdiction": "JP", "ticker": None, "verifier_corpus": "open_web"},
        "source_manifest": [
            {"cutoff_decision": "kept", "release_time": "2024-06-01"},
            {"cutoff_decision": "kept", "release_time": "2024-11-08"},
            {"cutoff_decision": "rejected_post_cutoff", "release_time": "2025-08-01"},
        ],
    }
    base.update(overrides)
    return base


def test_provenance_includes_required_fields():
    p = build_provenance(_state(), elapsed_seconds=42.0)
    # Required L1.4 fields present
    for k in ("case_id", "case_type", "cutoff_date", "model", "git",
              "case_config", "truth_config", "audit_meta", "manifest", "tokens"):
        assert k in p, f"missing field: {k}"


def test_provenance_manifest_summary_counts():
    p = build_provenance(_state(), elapsed_seconds=1.0)
    assert p["manifest"]["total_entries"] == 3
    assert p["manifest"]["kept"] == 2
    assert p["manifest"]["rejected_post_cutoff"] == 1


def test_provenance_handles_no_manifest_in_state():
    p = build_provenance(_state(source_manifest=None), elapsed_seconds=1.0)
    assert p["manifest"]["total_entries"] == 0


def test_provenance_records_model_from_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "test/model-99")
    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "test_provider")
    p = build_provenance(_state(), elapsed_seconds=1.0)
    assert p["model"]["model_id"] == "test/model-99"
    assert p["model"]["provider"] == "test_provider"


def test_provenance_records_git_commit():
    """In a git repo, commit and branch are populated."""
    p = build_provenance(_state(), elapsed_seconds=1.0)
    # commit may be empty when running in a non-git context, but in this
    # repo it should be 12 hex chars.
    if p["git"]["commit"]:
        assert len(p["git"]["commit"]) == 12
        assert all(c in "0123456789abcdef" for c in p["git"]["commit"])


def test_sha256_of_file_handles_missing(tmp_path):
    assert sha256_of_file(tmp_path / "does_not_exist") is None


def test_sha256_of_file_returns_hex(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello")
    h = sha256_of_file(f)
    assert h is not None
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_provenance_records_case_config_sha(tmp_path):
    case = tmp_path / "case.yaml"
    case.write_text("company: x\n")
    p = build_provenance(_state(), case_path=case, elapsed_seconds=1.0)
    assert p["case_config"]["path"] == str(case)
    assert p["case_config"]["sha256"] is not None
    assert len(p["case_config"]["sha256"]) == 64


def test_provenance_records_truth_config_sha_only_when_present(tmp_path):
    truth = tmp_path / "truth.yaml"
    truth.write_text("case_id: x\n")
    p = build_provenance(_state(), truth_path=truth, elapsed_seconds=1.0)
    assert p["truth_config"]["sha256"] is not None
    # No truth path → None
    p2 = build_provenance(_state(), elapsed_seconds=1.0)
    assert p2["truth_config"]["path"] is None
    assert p2["truth_config"]["sha256"] is None


def test_provenance_serializable_to_json():
    """The provenance dict must round-trip through JSON cleanly."""
    import json
    p = build_provenance(_state(), elapsed_seconds=1.0)
    s = json.dumps(p)
    loaded = json.loads(s)
    assert loaded["case_id"] == "honda_ev_2025"
