"""Shared test fixtures for SFEWA tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_cutoff_date() -> str:
    return "2025-05-19"


@pytest.fixture
def sample_case_config() -> dict:
    return {
        "case_id": "honda_ev_pre_reset_2025",
        "company": "Honda Motor Co., Ltd.",
        "ticker": "7267.T",
        "strategy_theme": "EV electrification strategy",
        "description": "Test case",
        "cutoff_date": "2025-05-19",
        "regions": ["north_america", "china", "global"],
        "peers": [
            {
                "company": "Toyota Motor Corporation",
                "ticker": "7203.T",
                "relevance": "Traditional OEM peer",
            }
        ],
        "allowed_source_types": ["company_filing", "company_presentation"],
        "search_topics": ["Honda EV strategy"],
        "ground_truth_events": [],
    }
