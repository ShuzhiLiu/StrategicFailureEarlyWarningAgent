"""Tests for the L1.5 verifier_corpus default."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sfewa.schemas.config import (
    CaseConfig,
    apply_verifier_corpus_default,
    load_case,
)


def _write_case(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / f"{name}.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_retrospective_default_is_allowed_sources_only(tmp_path):
    p = _write_case(tmp_path, "x", """
        case_id: x
        case_type: retrospective
        company: X
        strategy_theme: y
        cutoff_date: "2024-01-01"
    """)
    case = apply_verifier_corpus_default(load_case(p))
    assert case.verifier_corpus == "allowed_sources_only"


def test_forward_default_is_open_web(tmp_path):
    p = _write_case(tmp_path, "x", """
        case_id: x
        case_type: forward
        company: X
        strategy_theme: y
        cutoff_date: "2026-04-01"
    """)
    case = apply_verifier_corpus_default(load_case(p))
    assert case.verifier_corpus == "open_web"


def test_explicit_value_is_preserved(tmp_path):
    """Iter-41 baseline configs explicitly pin open_web; default must not override."""
    p = _write_case(tmp_path, "x", """
        case_id: x
        case_type: retrospective
        company: X
        strategy_theme: y
        cutoff_date: "2024-01-01"
        verifier_corpus: open_web
    """)
    case = apply_verifier_corpus_default(load_case(p))
    assert case.verifier_corpus == "open_web"


def test_existing_honda_toyota_byd_pinned_to_open_web():
    """Iter-41 baseline preserved: existing 3 cases keep open_web."""
    repo = Path(__file__).resolve().parents[2]
    cases = repo / "configs" / "cases"
    for name in ("honda_ev_pre_reset", "toyota_ev_strategy", "byd_ev_strategy"):
        case = apply_verifier_corpus_default(load_case(cases / f"{name}.yaml"))
        assert case.verifier_corpus == "open_web", f"{name} drifted"
