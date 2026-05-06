"""Tests for filing_discovery jurisdiction routing.

L2.2 adds the United States to the jurisdiction set, so the routing
table now spans JP / CN / HK / US. These tests cover:

* Pattern-based detection for each jurisdiction
* Region-hint fallback when name patterns don't match
* Explicit `case.jurisdiction` (CaseConfig field) wins over inference
* Unknown company + unknown region → None
"""

from __future__ import annotations

from sfewa.tools.filing_discovery import identify_jurisdiction


# ── Pattern-based detection ──


def test_japan_pattern_match():
    assert identify_jurisdiction("Honda Motor Co., Ltd.") == "japan"
    assert identify_jurisdiction("Toyota") == "japan"


def test_china_pattern_match():
    assert identify_jurisdiction("BYD Company Ltd.") == "china"
    assert identify_jurisdiction("Xpeng Inc.") == "china"


def test_hong_kong_pattern_match():
    assert identify_jurisdiction("Ping An Insurance") == "hong_kong"
    assert identify_jurisdiction("HSBC Holdings") == "hong_kong"


def test_us_pattern_match():
    assert identify_jurisdiction("Tesla, Inc.") == "united_states"
    assert identify_jurisdiction("Ford Motor Co.") == "united_states"
    assert identify_jurisdiction("General Motors") == "united_states"


# ── Explicit jurisdiction wins over inference ──


def test_explicit_jurisdiction_overrides_pattern():
    # Tencent matches both China (pattern) and Hong Kong (pattern).
    # Explicit HK from CaseConfig must win.
    assert identify_jurisdiction("Tencent Holdings", explicit="HK") == "hong_kong"
    # Same company, explicit CN — inference would say HK first, but explicit wins.
    assert identify_jurisdiction("Tencent Holdings", explicit="CN") == "china"


def test_explicit_us_jurisdiction():
    assert identify_jurisdiction("Apple Inc.", explicit="US") == "united_states"


def test_explicit_jurisdiction_unknown_code_falls_to_none():
    # Unknown 2-letter code: returns None (the explicit-override path
    # short-circuits before inference, and unknown codes map to None).
    assert identify_jurisdiction("Tesla, Inc.", explicit="XX") is None


# ── Region fallback ──


def test_region_fallback_for_us():
    # Company name matches no pattern; region hint says US.
    assert identify_jurisdiction("Acme Holdings", regions=["united_states"]) == "united_states"
    assert identify_jurisdiction("Acme Holdings", regions=["USA"]) == "united_states"
    assert identify_jurisdiction("Acme Holdings", regions=["North America"]) == "united_states"


def test_region_fallback_for_japan():
    assert identify_jurisdiction("Acme Corp", regions=["Japan"]) == "japan"


def test_region_fallback_for_china():
    assert identify_jurisdiction("Acme Inc", regions=["China"]) == "china"


def test_region_fallback_for_hong_kong():
    assert identify_jurisdiction("Acme Inc", regions=["Hong Kong"]) == "hong_kong"


# ── Unknown ──


def test_unknown_company_no_region_returns_none():
    assert identify_jurisdiction("Unknown Company XYZ") is None


def test_pattern_takes_precedence_over_us_region_hint():
    # Honda is Japanese even if the case YAML lists "north america" as a region.
    assert identify_jurisdiction("Honda Motor Co.", regions=["north america"]) == "japan"
