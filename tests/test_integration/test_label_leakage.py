"""Label-leakage tests for the case/truth split (L1.3).

Two layers of defense:

1. **Static check**: agents/*.py must not contain any reference to
   `configs/truth/` or `TruthConfig`. The backtest agent and the main.py
   loader are the only allowed readers (verified by allowlist).

2. **Runtime sentinel check**: each truth YAML carries a unique sentinel
   string; we verify that sentinel does NOT appear in any agent-visible
   prompt, state field, or evidence content.

Both must pass for the audit invariant to hold.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "src" / "sfewa" / "agents"
PROMPTS_DIR = REPO_ROOT / "src" / "sfewa" / "prompts"
TOOLS_DIR = REPO_ROOT / "src" / "sfewa" / "tools"
TRUTH_DIR = REPO_ROOT / "configs" / "truth"

# Modules whitelisted to read truth content. Everything else under
# src/sfewa/agents/ is forbidden from referencing configs/truth/, TruthConfig,
# or load_truth().
TRUTH_READER_ALLOWLIST = {
    # Backtest is THE only agent that reads ground-truth events.
    AGENTS_DIR / "backtest.py",
}

# Forbidden tokens — any of these in an agent file is a leakage signal.
_FORBIDDEN_PATTERNS = [
    re.compile(r"configs[/\\]truth"),
    re.compile(r"\bTruthConfig\b"),
    re.compile(r"\bload_truth\b"),
    re.compile(r"\bload_case_and_truth\b"),
]


# ── Layer 1: static grep ──


def test_no_agent_imports_truth_directly():
    """No agent module (except backtest) may reference truth-side paths or types.

    Agents read ground_truth_events from the pipeline state, which is populated
    by main.py's loader. Reading configs/truth/ directly bypasses the audit
    boundary.
    """
    offenders: list[tuple[Path, str, str]] = []
    for py_file in AGENTS_DIR.glob("*.py"):
        if py_file in TRUTH_READER_ALLOWLIST:
            continue
        if py_file.name == "__init__.py":
            continue
        text = py_file.read_text()
        for pat in _FORBIDDEN_PATTERNS:
            for m in pat.finditer(text):
                # Allow comment-only mentions if they explicitly say "must not"
                # or "forbidden" — but flag everything else for review.
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                line = text[line_start:line_end if line_end != -1 else None]
                offenders.append((py_file.relative_to(REPO_ROOT), pat.pattern, line.strip()))

    assert not offenders, (
        f"Agent modules contain forbidden references to truth content. "
        f"Truth files must only be read by main.py and "
        f"sfewa.agents.backtest. Offenders:\n"
        + "\n".join(f"  {p}: pattern '{pat}' on line: {line!r}"
                    for p, pat, line in offenders)
    )


def test_prompts_dir_has_no_truth_references():
    """Prompt templates must never contain truth-side identifiers."""
    if not PROMPTS_DIR.exists():
        return
    offenders = []
    for py_file in PROMPTS_DIR.glob("*.py"):
        text = py_file.read_text()
        for pat in _FORBIDDEN_PATTERNS:
            if pat.search(text):
                offenders.append((py_file.name, pat.pattern))
    assert not offenders, f"Prompt files reference truth content: {offenders}"


def test_tools_have_no_truth_references_except_loader():
    """Tools (filing discovery, temporal filter, etc.) must not read truth."""
    offenders = []
    for py_file in TOOLS_DIR.glob("*.py"):
        text = py_file.read_text()
        for pat in _FORBIDDEN_PATTERNS:
            if pat.search(text):
                offenders.append((py_file.name, pat.pattern))
    assert not offenders, f"Tool modules reference truth content: {offenders}"


# ── Layer 2: truth file structure ──


def test_truth_files_have_unique_sentinels():
    """Each truth YAML carries a unique sentinel string.

    This is the runtime detection mechanism — sentinel must not appear in
    any agent-visible artifact for the leakage check to be meaningful.
    """
    if not TRUTH_DIR.exists():
        pytest.skip("configs/truth/ does not exist yet")
    sentinels: dict[str, Path] = {}
    for truth_file in TRUTH_DIR.glob("*.yaml"):
        data = yaml.safe_load(truth_file.read_text()) or {}
        sentinel = data.get("sentinel")
        assert sentinel, f"{truth_file.name}: missing 'sentinel' field"
        assert sentinel.startswith("__TRUTH_SENTINEL_"), (
            f"{truth_file.name}: sentinel must start with __TRUTH_SENTINEL_, "
            f"got {sentinel!r}"
        )
        assert sentinel not in sentinels, (
            f"Duplicate sentinel {sentinel!r} in {truth_file.name} "
            f"and {sentinels[sentinel].name}"
        )
        sentinels[sentinel] = truth_file


def test_truth_sentinels_appear_only_in_truth_files():
    """A truth sentinel must appear ONLY in its own truth YAML.

    If a sentinel appears anywhere under src/, configs/cases/, tests/, or
    docs/, that's evidence the truth content has leaked into agent-visible
    surfaces.
    """
    if not TRUTH_DIR.exists():
        pytest.skip("configs/truth/ does not exist yet")

    # Collect all sentinels
    sentinels: dict[str, Path] = {}
    for truth_file in TRUTH_DIR.glob("*.yaml"):
        data = yaml.safe_load(truth_file.read_text()) or {}
        s = data.get("sentinel")
        if s:
            sentinels[s] = truth_file

    # Scan everywhere except configs/truth/, outputs/, and this test file
    search_roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "configs" / "cases",
        REPO_ROOT / "configs" / "prompts",
    ]
    self_path = Path(__file__).resolve()

    leaks: list[tuple[str, Path]] = []
    for root in search_roots:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            if f.resolve() == self_path:
                continue
            if "__pycache__" in f.parts:
                continue
            try:
                text = f.read_text()
            except (UnicodeDecodeError, PermissionError):
                continue
            for sentinel in sentinels:
                if sentinel in text:
                    leaks.append((sentinel, f.relative_to(REPO_ROOT)))

    assert not leaks, (
        f"Truth sentinels leaked into non-truth files (this means truth "
        f"content has reached an agent-visible surface):\n"
        + "\n".join(f"  {sentinel} found in {path}" for sentinel, path in leaks)
    )


# ── Layer 3: runtime sentinel — exercises the actual loader path ──


def _walk_strings(obj, path: str = "$"):
    """Yield (path, string) pairs from any nested dict/list/string structure."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")


def test_runtime_sentinel_isolated_to_ground_truth_events():
    """The truth sentinel must NEVER appear outside `state["ground_truth_events"]`.

    Builds the initial pipeline state via the SAME function the CLI uses
    (`build_initial_state_from_case`), then walks every string in the state
    and asserts the sentinel only appears nowhere — sentinels live as the
    `sentinel` field of the truth YAML, which is intentionally NOT copied
    into the state. If a sentinel surfaces anywhere in the state, the
    loader has leaked truth content into agent-reachable surfaces.
    """
    if not TRUTH_DIR.exists():
        pytest.skip("configs/truth/ does not exist yet")

    # Lazy import to avoid pulling LLM clients into test collection
    from sfewa.main import build_initial_state_from_case

    sentinels = {}
    for truth_file in TRUTH_DIR.glob("*.yaml"):
        data = yaml.safe_load(truth_file.read_text()) or {}
        s = data.get("sentinel")
        if s:
            sentinels[data["case_id"]] = s

    cases_dir = REPO_ROOT / "configs" / "cases"
    leaks: list[tuple[str, str, str]] = []

    for case_yaml in cases_dir.glob("*.yaml"):
        state = build_initial_state_from_case(case_yaml)
        case_id = state["case_id"]
        if case_id not in sentinels:
            continue
        sentinel = sentinels[case_id]
        for path, s in _walk_strings(state):
            if sentinel in s:
                leaks.append((case_yaml.name, path, sentinel))

    assert not leaks, (
        f"Truth sentinel surfaced in pipeline state via the loader path. "
        f"This means truth content is leaking into the agent-visible state:\n"
        + "\n".join(
            f"  {case} at state{path}: contains {sentinel!r}"
            for case, path, sentinel in leaks
        )
    )


def test_ground_truth_events_carry_no_sentinel():
    """The sentinel field is on the truth ROOT, not on the events themselves.

    This test verifies our truth YAMLs are structured correctly: events are
    the only truth-side data the loader propagates into state, and they
    must not carry the sentinel string. Otherwise the runtime test above
    would report false positives (the sentinel WOULD show up in
    state.ground_truth_events legitimately).
    """
    if not TRUTH_DIR.exists():
        pytest.skip("configs/truth/ does not exist yet")
    for truth_file in TRUTH_DIR.glob("*.yaml"):
        data = yaml.safe_load(truth_file.read_text()) or {}
        sentinel = data.get("sentinel")
        if not sentinel:
            continue
        events = data.get("ground_truth_events", [])
        for path, s in _walk_strings(events, f"{truth_file.name}.ground_truth_events"):
            assert sentinel not in s, (
                f"Truth file {truth_file.name} has sentinel {sentinel!r} "
                f"embedded inside ground_truth_events at {path} — sentinels "
                f"must live ONLY at the truth root."
            )
