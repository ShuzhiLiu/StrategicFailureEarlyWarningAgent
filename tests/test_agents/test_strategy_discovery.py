"""Tests for the L2.4 strategy_discovery agent.

Covers the pure helpers — output parsing, fallback behavior, schema
validation. The integration path (build_initial_state_from_case calling
discover_strategies on a real case) is exercised by a separate test
that mocks the inner LLM call so no network / LLM are touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sfewa.agents.strategy_discovery import (
    _fallback_payload,
    _parse_discovery_output,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


# ── _parse_discovery_output ──


def test_parse_clean_json():
    payload = json.dumps({
        "candidates": [
            {
                "name": "EV electrification strategy",
                "description": "...",
                "type": "declared_strategy",
                "evidence_text": "We will invest 10T yen by 2030.",
                "confidence": 0.9,
            },
            {
                "name": "Software-defined vehicle pivot",
                "description": "...",
                "type": "declared_strategy",
                "evidence_text": "...",
                "confidence": 0.7,
            },
        ],
        "primary": "EV electrification strategy",
        "rationale": "Specific multi-year capital commitment with named target.",
    })
    out = _parse_discovery_output(payload)
    assert out["primary"] == "EV electrification strategy"
    assert len(out["candidates"]) == 2
    assert out["candidates"][0]["confidence"] == 0.9
    assert "fallback" not in out["rationale"].lower()


def test_parse_strips_markdown_fences():
    payload = (
        "Here is the JSON:\n"
        "```json\n"
        '{"candidates": [{"name": "X strategy", "description": "...", '
        '"type": "declared_strategy", "evidence_text": "...", "confidence": 0.5}], '
        '"primary": "X strategy", "rationale": "..."}\n'
        "```"
    )
    out = _parse_discovery_output(payload)
    assert out["primary"] == "X strategy"
    assert len(out["candidates"]) == 1


def test_parse_strips_thinking_tags():
    payload = (
        "<think>I should pick the EV strategy because...</think>\n"
        '{"candidates": [{"name": "EV", "description": "d", "type": "declared_strategy",'
        ' "evidence_text": "ev", "confidence": 0.8}],'
        ' "primary": "EV", "rationale": "r"}'
    )
    out = _parse_discovery_output(payload)
    assert out["primary"] == "EV"


def test_parse_falls_back_on_empty_content():
    out = _parse_discovery_output("")
    assert out["primary"] == "primary corporate strategy"
    assert "Fallback" in out["rationale"]


def test_parse_falls_back_on_unparseable_json():
    out = _parse_discovery_output("This is not JSON at all.")
    assert out["primary"] == "primary corporate strategy"


def test_parse_falls_back_when_candidates_missing():
    out = _parse_discovery_output('{"primary": "x", "rationale": "y"}')
    assert out["primary"] == "primary corporate strategy"


def test_parse_picks_first_candidate_when_primary_missing():
    payload = json.dumps({
        "candidates": [
            {"name": "First Strategy", "description": "d", "type": "declared_strategy",
             "evidence_text": "e", "confidence": 0.5},
            {"name": "Second Strategy", "description": "d", "type": "declared_strategy",
             "evidence_text": "e", "confidence": 0.4},
        ],
        # primary missing
        "rationale": "r",
    })
    out = _parse_discovery_output(payload)
    assert out["primary"] == "First Strategy"


def test_parse_repairs_primary_when_doesnt_match():
    """When 'primary' names a string that isn't in candidates, fall back to the
    top-1 candidate. Avoids hallucinated primary names."""
    payload = json.dumps({
        "candidates": [
            {"name": "Real Strategy", "description": "d", "type": "declared_strategy",
             "evidence_text": "e", "confidence": 0.5},
        ],
        "primary": "Hallucinated Strategy That Does Not Exist",
        "rationale": "r",
    })
    out = _parse_discovery_output(payload)
    assert out["primary"] == "Real Strategy"


def test_parse_drops_invalid_candidates():
    payload = json.dumps({
        "candidates": [
            {"name": "", "description": "d"},  # empty name → drop
            "not a dict",                       # not a dict → drop
            {"name": "Valid Strategy", "description": "d", "type": "declared_strategy",
             "evidence_text": "e", "confidence": 0.7},
        ],
        "primary": "Valid Strategy",
        "rationale": "r",
    })
    out = _parse_discovery_output(payload)
    assert len(out["candidates"]) == 1
    assert out["candidates"][0]["name"] == "Valid Strategy"


def test_parse_truncates_overly_long_evidence_text():
    payload = json.dumps({
        "candidates": [{
            "name": "X",
            "description": "d",
            "type": "declared_strategy",
            "evidence_text": "Y" * 1000,  # 1000 chars
            "confidence": 0.5,
        }],
        "primary": "X",
        "rationale": "r",
    })
    out = _parse_discovery_output(payload)
    assert len(out["candidates"][0]["evidence_text"]) <= 500


def test_parse_clamps_confidence_to_float():
    """Confidence as a string number must coerce; missing must default to 0.5."""
    payload = json.dumps({
        "candidates": [
            {"name": "A", "description": "d", "type": "declared_strategy",
             "evidence_text": "e", "confidence": "0.85"},
            {"name": "B", "description": "d", "type": "declared_strategy",
             "evidence_text": "e"},  # missing confidence
        ],
        "primary": "A",
        "rationale": "r",
    })
    out = _parse_discovery_output(payload)
    assert out["candidates"][0]["confidence"] == 0.85
    assert out["candidates"][1]["confidence"] == 0.5


# ── _fallback_payload ──


def test_fallback_payload_shape():
    p = _fallback_payload(reason="parse error")
    assert p["primary"] == "primary corporate strategy"
    assert len(p["candidates"]) == 1
    assert p["candidates"][0]["confidence"] < 0.5  # low confidence
    assert "parse error" in p["rationale"]


# ── Integration: build_initial_state_from_case calls discovery when needed ──


def test_build_state_does_not_call_discovery_when_theme_set(tmp_path):
    """Honda case has strategy_theme set; discovery must NOT run."""
    from sfewa.main import build_initial_state_from_case

    case_path = REPO_ROOT / "configs" / "cases" / "honda_ev_pre_reset.yaml"
    with patch("sfewa.agents.strategy_discovery.discover_strategies") as mock_disc:
        state = build_initial_state_from_case(case_path)
    assert state["strategy_theme"] == "EV electrification strategy"
    assert "discovered_strategies" not in state
    mock_disc.assert_not_called()


def test_build_state_calls_discovery_when_theme_missing(tmp_path):
    """Synthetic case YAML with no strategy_theme triggers discovery."""
    from sfewa.main import build_initial_state_from_case

    # Create a minimal case YAML + truth pair in tmp
    case_dir = tmp_path / "configs" / "cases"
    truth_dir = tmp_path / "configs" / "truth"
    case_dir.mkdir(parents=True)
    truth_dir.mkdir(parents=True)

    case_yaml = case_dir / "test_case.yaml"
    case_yaml.write_text(
        "case_id: test_case\n"
        "case_type: forward\n"
        "company: Some Corp\n"
        "cutoff_date: '2024-12-31'\n"
        # NO strategy_theme
    )

    fake_payload = {
        "candidates": [
            {"name": "Cloud transition strategy", "description": "d",
             "type": "declared_strategy", "evidence_text": "e", "confidence": 0.8},
        ],
        "primary": "Cloud transition strategy",
        "rationale": "Top declared strategic priority.",
    }

    with patch(
        "sfewa.agents.strategy_discovery.discover_strategies",
        return_value=fake_payload,
    ) as mock_disc:
        state = build_initial_state_from_case(case_yaml)

    mock_disc.assert_called_once()
    assert state["strategy_theme"] == "Cloud transition strategy"
    assert state["discovered_strategies"] == fake_payload


def test_build_state_force_rediscovery_keeps_authored_theme(tmp_path):
    """With discover_strategies=True, the case's authored theme stays primary
    BUT the discovered candidates are still recorded for audit."""
    from sfewa.main import build_initial_state_from_case

    case_path = REPO_ROOT / "configs" / "cases" / "honda_ev_pre_reset.yaml"

    fake_payload = {
        "candidates": [
            {"name": "Software-defined vehicle pivot", "description": "d",
             "type": "declared_strategy", "evidence_text": "e", "confidence": 0.7},
        ],
        "primary": "Software-defined vehicle pivot",
        "rationale": "...",
    }

    with patch(
        "sfewa.agents.strategy_discovery.discover_strategies",
        return_value=fake_payload,
    ) as mock_disc:
        state = build_initial_state_from_case(
            case_path, discover_strategies=True,
        )

    mock_disc.assert_called_once()
    # Authored theme is preserved as the working theme
    assert state["strategy_theme"] == "EV electrification strategy"
    # But the discovered candidates ARE recorded for audit
    assert "discovered_strategies" in state
    assert state["discovered_strategies"] == fake_payload
